"""Language detection backends.

Primary: fastText ``lid.176.bin`` (multiclass classifier over ~176 languages,
CPU-only, sub-millisecond per call once loaded). Fallback: the existing
Unicode-script heuristic, kept for offline/no-model environments and as a
safety net when the fastText backend raises at load/inference time.

Both backends return a normalized ``(lang, confidence)`` pair. Routing (which
language is "full" vs "partial" vs "unknown") stays in
:func:`preprocessor.text_processing._route_language` so that adding backends
doesn't fork the contract logic.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Tuple, Iterable
from urllib.request import urlopen


logger = logging.getLogger("preprocessor.language_detection")

FASTTEXT_MODEL_URL = (
    "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
)
FASTTEXT_MODEL_FILENAME = "lid.176.bin"
FASTTEXT_MIN_SIZE_BYTES = 100 * 1024 * 1024  # 125MB real; guard against partial downloads

SAFE_LANG_RE = re.compile(r"^[a-z]{2}$")


@dataclass(frozen=True)
class DetectionOutcome:
    """Raw (pre-routing) detection output.

    ``language`` is either a 2-letter ISO 639-1 code, ``"other"`` (known script
    but language not in pipeline's ``full_analysis_languages`` list), or
    ``"und"`` (text too short / detector refused).
    """

    language: str
    confidence: float
    backend: str


class LanguageDetector(Protocol):
    name: str

    def detect(self, text: str) -> DetectionOutcome:
        ...


class HeuristicDetector:
    """Unicode-script + EN-stopword heuristic (Variant C original implementation).

    Preserved verbatim for backward compatibility and as a fallback when the
    fastText model is unavailable (CI/offline, transient filesystem error,
    binary load failure on exotic CPUs).
    """

    name = "heuristic"

    def __init__(self, min_confidence: float = 0.55) -> None:
        self._min_confidence = min_confidence

    def detect(self, text: str) -> DetectionOutcome:
        from preprocessor.text_processing import _heuristic_detect_raw

        lang, conf = _heuristic_detect_raw(text or "", self._min_confidence)
        return DetectionOutcome(language=lang, confidence=conf, backend=self.name)


class FastTextDetector:
    """fastText lid.176 wrapper.

    Loading is lazy + thread-safe so that ``preprocess_text()`` callers don't
    pay the ~125MB model load before the first real message. When the model
    is unavailable, callers (via :class:`CompositeDetector`) fall back to the
    heuristic backend automatically.
    """

    name = "fasttext"

    def __init__(
        self,
        model_path: Path,
        auto_download: bool = True,
        download_url: str = FASTTEXT_MODEL_URL,
    ) -> None:
        self._model_path = Path(model_path)
        self._auto_download = auto_download
        self._download_url = download_url
        self._model = None
        self._lock = threading.Lock()

    def _ensure_available(self) -> Path:
        path = self._model_path
        if path.exists() and path.stat().st_size >= FASTTEXT_MIN_SIZE_BYTES:
            return path
        if not self._auto_download:
            raise FileNotFoundError(
                f"fastText model not found at {path} and auto_download is disabled"
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".part")
        logger.info(
            "downloading fastText lid.176 model url=%s dest=%s", self._download_url, path
        )
        started = time.monotonic()
        with urlopen(self._download_url, timeout=60) as resp, open(tmp_path, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp_path.replace(path)
        logger.info(
            "downloaded fastText lid.176 model size_bytes=%d duration_seconds=%.1f",
            path.stat().st_size,
            time.monotonic() - started,
        )
        return path

    def _load(self):  # noqa: ANN202 — fasttext has no useful public type
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            import fasttext  # local import so heuristic-only envs don't need the wheel

            path = self._ensure_available()
            started = time.monotonic()
            # fastText prints a harmless warning on stderr; nothing to suppress safely.
            model = fasttext.load_model(str(path))
            logger.info(
                "fastText lid.176 loaded duration_seconds=%.2f", time.monotonic() - started
            )
            self._model = model
            return model

    def detect(self, text: str) -> DetectionOutcome:
        cleaned = (text or "").replace("\n", " ").replace("\r", " ").strip()
        if not cleaned:
            return DetectionOutcome(language="und", confidence=0.0, backend=self.name)
        model = self._load()
        labels, scores = model.predict(cleaned, k=1)
        if not labels:
            return DetectionOutcome(language="und", confidence=0.0, backend=self.name)
        raw_label = labels[0]
        if raw_label.startswith("__label__"):
            raw_label = raw_label[len("__label__") :]
        score = float(scores[0]) if len(scores) else 0.0
        lang = raw_label.lower()
        if not SAFE_LANG_RE.match(lang):
            lang = "other"
        return DetectionOutcome(language=lang, confidence=round(score, 4), backend=self.name)


class CompositeDetector:
    """Try primary detector; on any exception, log and return heuristic result.

    Useful for production safety: a transient I/O or OOM error in fastText
    load does not take down the preprocessor; detection degrades to heuristic
    and the event still flows through the pipeline with ``analysis_mode`` set
    correctly by the routing layer.
    """

    def __init__(
        self,
        primary: LanguageDetector,
        fallback: LanguageDetector,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._primary_failed_once = False

    @property
    def name(self) -> str:
        # Which backend answered last is also exposed via DetectionOutcome.backend.
        return self._primary.name

    def detect(self, text: str) -> DetectionOutcome:
        try:
            return self._primary.detect(text)
        except Exception as exc:  # noqa: BLE001 — fallback must be exhaustive
            if not self._primary_failed_once:
                logger.warning(
                    "primary language detector %s failed, falling back to %s: %s",
                    self._primary.name,
                    self._fallback.name,
                    exc,
                )
                self._primary_failed_once = True
            return self._fallback.detect(text)


def build_detector(
    backend: str,
    min_confidence: float,
    fasttext_model_path: Optional[Path],
    auto_download: bool,
) -> LanguageDetector:
    """Factory selecting backend by config.

    ``backend="fasttext"`` wraps fastText in :class:`CompositeDetector` with
    the heuristic as a fallback. ``backend="heuristic"`` uses the heuristic
    detector directly. Any other value is rejected early so misconfigurations
    surface at startup rather than at first message.
    """

    heuristic = HeuristicDetector(min_confidence=min_confidence)
    if backend == "heuristic":
        return heuristic
    if backend == "fasttext":
        if fasttext_model_path is None:
            raise ValueError("fasttext_model_path must be set when backend=fasttext")
        primary = FastTextDetector(
            model_path=fasttext_model_path,
            auto_download=auto_download,
        )
        return CompositeDetector(primary=primary, fallback=heuristic)
    raise ValueError(
        f"unknown language detection backend: {backend!r} (expected 'fasttext' or 'heuristic')"
    )


__all__ = [
    "DetectionOutcome",
    "LanguageDetector",
    "HeuristicDetector",
    "FastTextDetector",
    "CompositeDetector",
    "build_detector",
    "FASTTEXT_MODEL_URL",
    "FASTTEXT_MODEL_FILENAME",
]

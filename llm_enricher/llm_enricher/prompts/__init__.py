from __future__ import annotations

import re
from pathlib import Path
from string import Template
from typing import Optional


class PromptRegistry:
    """Loads prompt templates from disk with version resolution and language fallback."""

    FALLBACK_CHAIN = ("other", "en")

    def __init__(self, root: Optional[Path] = None) -> None:
        if root is None:
            root = Path(__file__).parent
        self._root = root
        self._cache: dict[tuple[str, str, str], tuple[Template, str]] = {}

    def get(
        self, enrichment_type: str, lang: str, version: str = "latest"
    ) -> tuple[Template, str]:
        """Return (Template, resolved_version) for the given type/lang/version.

        Lang fallback: lang -> "other" -> "en".
        Version "latest" resolves to the highest vN.txt found.
        """
        key = (enrichment_type, lang, version)
        if key in self._cache:
            return self._cache[key]

        resolved_lang = self._resolve_lang(enrichment_type, lang)
        resolved_version = self._resolve_version(enrichment_type, resolved_lang, version)
        path = self._root / enrichment_type / resolved_lang / f"{resolved_version}.txt"
        content = path.read_text(encoding="utf-8")
        result = (Template(content), resolved_version)
        self._cache[key] = result
        return result

    def _resolve_lang(self, enrichment_type: str, lang: str) -> str:
        candidates = [lang] + [c for c in self.FALLBACK_CHAIN if c != lang]
        for candidate in candidates:
            d = self._root / enrichment_type / candidate
            if d.is_dir() and any(d.glob("v*.txt")):
                return candidate
        raise FileNotFoundError(
            f"No prompt template found for {enrichment_type!r} (lang={lang!r})"
        )

    def _resolve_version(
        self, enrichment_type: str, lang: str, version: str
    ) -> str:
        if version != "latest":
            return version
        d = self._root / enrichment_type / lang
        versions = [
            int(m.group(1))
            for f in d.glob("v*.txt")
            if (m := re.match(r"^v(\d+)\.txt$", f.name))
        ]
        if not versions:
            raise FileNotFoundError(f"No prompt files in {d}")
        return f"v{max(versions)}"

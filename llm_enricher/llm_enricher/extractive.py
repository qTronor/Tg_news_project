from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("llm_enricher.extractive")

_SUMY_AVAILABLE = False
try:
    from sumy.nlp.stemmers import Stemmer
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.summarizers.text_rank import TextRankSummarizer
    from sumy.utils import get_stop_words

    _SUMY_AVAILABLE = True
except ImportError:
    logger.warning("sumy not installed; extractive summaries will use sentence-concat fallback")


def _get_sumy_language(language: str) -> str:
    return "russian" if language == "ru" else "english"


def extractive_summary(
    messages: list[Any],
    language: str,
    max_sentences: int = 3,
) -> dict[str, Any]:
    """Return CLUSTER_SUMMARY_SCHEMA-compatible dict using extractive summarization.

    Falls back to first-sentence concatenation when sumy is unavailable or the
    document is too short for TextRank to converge.
    """
    texts = [getattr(m, "text", "") or "" for m in messages[:10]]
    combined = " ".join(t.strip() for t in texts if t.strip())

    if not combined:
        return {"summary": "", "key_points": []}

    if _SUMY_AVAILABLE:
        try:
            sumy_lang = _get_sumy_language(language)
            parser = PlaintextParser.from_string(combined, Tokenizer(sumy_lang))
            stemmer = Stemmer(sumy_lang)
            summarizer = TextRankSummarizer(stemmer)
            summarizer.stop_words = get_stop_words(sumy_lang)
            sentences = summarizer(parser.document, max_sentences)
            summary = " ".join(str(s) for s in sentences).strip()
            if summary:
                key_points = [str(s).strip() for s in sentences if str(s).strip()]
                return {"summary": summary, "key_points": key_points[:5]}
        except Exception as exc:
            logger.warning("TextRank failed, falling back to concat: %s", exc)

    # Fallback: take first sentence of each message
    parts: list[str] = []
    for text in texts:
        first = text.split(".")[0].strip()
        if first and len(first) > 20:
            parts.append(first)
        if len(parts) >= max_sentences:
            break

    summary = ". ".join(parts) + ("." if parts else "")
    return {"summary": summary, "key_points": parts[:5]}


def extractive_key_actors(top_entities: list[Any]) -> dict[str, Any]:
    """Return KEY_ACTORS_SUMMARY_SCHEMA-compatible dict from top_entities list.

    Used as baseline when LLM is unavailable for key_actors_summary.
    """
    actors = []
    for entity in top_entities[:5]:
        name = getattr(entity, "normalized_text", "") or ""
        etype = getattr(entity, "entity_type", "") or ""
        count = int(getattr(entity, "mention_count", 0) or 0)
        if not name:
            continue
        actors.append({
            "name": name,
            "role": etype,
            "why_matters": f"Упомянут {count} раз в данной теме.",
            "mention_count": count,
        })
    return {"actors": actors}

"""
Pre-download all ML models used by AI microservices.

Run once before first deployment:
    pip install transformers sentence-transformers natasha torch
    python scripts/download_models.py

Models are saved to ~/.cache/huggingface/ by default.
Use --output-dir to save to a custom directory (for Docker volume mount).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SENTIMENT_MODEL = "blanchefort/rubert-base-cased-sentiment"
SBERT_MODEL = "ai-forever/sbert_large_nlu_ru"


def download_sentiment(cache_dir: str | None = None) -> None:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    logger.info("downloading sentiment model: %s", SENTIMENT_MODEL)
    kwargs = {"cache_dir": cache_dir} if cache_dir else {}
    AutoTokenizer.from_pretrained(SENTIMENT_MODEL, **kwargs)
    AutoModelForSequenceClassification.from_pretrained(SENTIMENT_MODEL, **kwargs)
    logger.info("sentiment model downloaded")


def download_sbert(cache_dir: str | None = None) -> None:
    from sentence_transformers import SentenceTransformer

    logger.info("downloading sbert model: %s", SBERT_MODEL)
    kwargs = {"cache_folder": cache_dir} if cache_dir else {}
    SentenceTransformer(SBERT_MODEL, **kwargs)
    logger.info("sbert model downloaded")


def download_natasha() -> None:
    from natasha import NewsEmbedding, NewsNERTagger, Segmenter

    logger.info("loading natasha models (bundled with pip package)")
    Segmenter()
    emb = NewsEmbedding()
    NewsNERTagger(emb)
    logger.info("natasha models loaded")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-download ML models")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Custom cache directory (default: ~/.cache/huggingface)",
    )
    parser.add_argument(
        "--model",
        choices=["sentiment", "sbert", "natasha", "all"],
        default="all",
        help="Which model to download (default: all)",
    )
    args = parser.parse_args()

    if args.output_dir:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    try:
        if args.model in ("sentiment", "all"):
            download_sentiment(args.output_dir)
        if args.model in ("sbert", "all"):
            download_sbert(args.output_dir)
        if args.model in ("natasha", "all"):
            download_natasha()
    except Exception:
        logger.exception("model download failed")
        return 1

    logger.info("all requested models downloaded successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())

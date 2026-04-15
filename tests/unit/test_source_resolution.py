from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "source_resolver"))

from source_resolver.resolution import (
    ResolutionMessage,
    build_inferred_source,
    fallback_earliest_cluster_source,
    unknown_source,
)


class SourceResolutionTest(unittest.TestCase):
    def _message(self, event_id: str, text: str, **overrides):
        base = ResolutionMessage(
            event_id=event_id,
            channel="demo",
            message_id=int(event_id.split(":")[-1]),
            message_date=datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc),
            text=text,
            normalized_text=text.lower(),
            tokens=text.lower().split(),
            normalized_text_hash="hash-a",
            simhash64=123456,
            url_fingerprints=["url-1"],
            primary_url_fingerprint="url-1",
            entities={"entity-a", "entity-b"},
        )
        return ResolutionMessage(**{**base.__dict__, **overrides})

    def test_build_inferred_source_marks_quote_match(self) -> None:
        candidate = self._message("demo:1", "Original statement with concrete wording here")
        target = self._message(
            "demo:2",
            'Follow-up says "Original statement with concrete wording here" in full',
            message_date=candidate.message_date + timedelta(minutes=10),
            normalized_text_hash="hash-b",
            simhash64=123458,
            url_fingerprints=[],
            primary_url_fingerprint=None,
        )

        result = build_inferred_source(target, candidate, threshold=0.55, quote_min_chars=20)

        self.assertEqual(result.source_type, "quoted")
        self.assertGreater(result.confidence, 0.5)
        self.assertTrue(result.evidence["quoted_fragment_match"])

    def test_fallback_and_unknown_sources_are_explicit(self) -> None:
        candidate = self._message("demo:3", "Earliest message")
        fallback = fallback_earliest_cluster_source(candidate, 0.35)
        unknown = unknown_source("No evidence")

        self.assertEqual(fallback.source_type, "earliest_in_cluster")
        self.assertEqual(fallback.confidence, 0.35)
        self.assertEqual(unknown.source_type, "unknown")
        self.assertEqual(unknown.explanation["summary"], "No evidence")

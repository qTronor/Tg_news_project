from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "preprocessor"))

from preprocessor.text_processing import fingerprint_url, normalize_url, preprocess_text


class PreprocessorFingerprintTest(unittest.TestCase):
    def test_normalize_url_removes_tracking_noise(self) -> None:
        left = "https://example.com/path/?utm_source=tg&b=2&a=1#fragment"
        right = "https://example.com/path/?a=1&b=2"

        self.assertEqual(normalize_url(left), normalize_url(right))
        self.assertEqual(fingerprint_url(left), fingerprint_url(right))

    def test_preprocess_text_emits_stable_fingerprints(self) -> None:
        text = "Breaking news: https://example.com/path/?utm_campaign=x and https://example.com/path"
        result = preprocess_text(text)

        self.assertIsNotNone(result.normalized_text_hash)
        self.assertIsNotNone(result.simhash64)
        self.assertTrue(result.url_fingerprints)
        self.assertEqual(result.primary_url_fingerprint, result.url_fingerprints[0])

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "preprocessor"))

from preprocessor.text_processing import detect_language, fingerprint_url, normalize_url, preprocess_text


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

    def test_preprocess_text_removes_telegram_boilerplate_and_emoji(self) -> None:
        text = (
            "ЦБ повысил ключевую ставку до 18%.\n\n"
            "🔥 Подписывайтесь на @banksta\n"
            "Канал РБК в MAX\n"
            "▪Приложение РБК для iOS и Android\n"
            "https://t.me/rbc_news"
        )

        result = preprocess_text(text)

        self.assertEqual(result.cleaned_text, "цб повысил ключевую ставку до 18%")
        self.assertFalse(result.has_urls)
        self.assertFalse(result.has_mentions)

    def test_preprocess_text_keeps_media_caption_text(self) -> None:
        text = "Фото дня: индекс Мосбиржи вырос на 2% 📈"

        result = preprocess_text(text)

        self.assertEqual(
            result.cleaned_text,
            "фото дня индекс мосбиржи вырос на 2%",
        )
        self.assertGreater(result.word_count, 0)

    def test_language_detection_routes_ru_and_en_to_full_mode(self) -> None:
        ru = detect_language("Центробанк повысил ключевую ставку")
        en = detect_language("The central bank raised the interest rate")

        self.assertEqual(ru.language, "ru")
        self.assertEqual(ru.analysis_mode, "full")
        self.assertTrue(ru.is_supported_for_full_analysis)
        self.assertEqual(en.language, "en")
        self.assertEqual(en.analysis_mode, "full")
        self.assertTrue(en.is_supported_for_full_analysis)

    def test_language_detection_routes_other_and_unknown_safely(self) -> None:
        other = detect_language("El banco central subio la tasa")
        unknown = detect_language("12345 !!!")

        self.assertEqual(other.language, "other")
        self.assertEqual(other.analysis_mode, "partial")
        self.assertFalse(other.is_supported_for_full_analysis)
        self.assertEqual(unknown.language, "und")
        self.assertEqual(unknown.analysis_mode, "unknown")
        self.assertFalse(unknown.is_supported_for_full_analysis)

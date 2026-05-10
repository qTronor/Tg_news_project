"""Unit tests for ner_extractor.normalization module.

No database dependencies — pure function tests.
"""
from __future__ import annotations

import pytest

from ner_extractor.normalization import Rule, apply_rules, surface_normalize


# ─── surface_normalize ────────────────────────────────────────────────────────

class TestSurfaceNormalize:
    def test_casefold(self):
        assert surface_normalize("Путин") == "путин"
        assert surface_normalize("USA") == "usa"

    def test_strips_quotes(self):
        assert surface_normalize('«Газпром»') == "газпром"
        assert surface_normalize('"Apple"') == "apple"
        assert surface_normalize("'test'") == "test"

    def test_strips_brackets(self):
        assert surface_normalize("(США)") == "сша"
        assert surface_normalize("[ООН]") == "оон"

    def test_normalises_dashes(self):
        result = surface_normalize("Ростов-на-Дону")
        assert "ростов-на-дону" == result

    def test_collapses_whitespace(self):
        assert surface_normalize("  Владимир   Путин  ") == "владимир путин"

    def test_nfkc_normalization(self):
        # Full-width digits should become ASCII
        result = surface_normalize("１２３")
        assert result == "123"

    def test_strips_trailing_punctuation(self):
        assert surface_normalize("Reuters,") == "reuters"
        assert surface_normalize("США.") == "сша"

    def test_empty_string(self):
        assert surface_normalize("") == ""

    def test_already_normalised(self):
        assert surface_normalize("нато") == "нато"


# ─── apply_rules ──────────────────────────────────────────────────────────────

class TestApplyRules:
    @pytest.fixture()
    def usa_rules(self):
        canonical_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        return [
            Rule(
                id="r1",
                rule_type="alias",
                pattern="США",
                replacement=None,
                entity_type="LOC",
                language="ru",
                target_canonical_id=canonical_id,
                priority=100,
            ),
            Rule(
                id="r2",
                rule_type="alias",
                pattern="Америка",
                replacement=None,
                entity_type="LOC",
                language="ru",
                target_canonical_id=canonical_id,
                priority=100,
            ),
            Rule(
                id="r3",
                rule_type="alias",
                pattern="Соединённые Штаты",
                replacement=None,
                entity_type="LOC",
                language="ru",
                target_canonical_id=canonical_id,
                priority=100,
            ),
        ]

    def test_alias_rule_us(self, usa_rules):
        """Regression #1: США, Америка, Соединённые Штаты all resolve to same canonical."""
        canonical_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        for surface in ["США", "Америка", "Соединённые Штаты"]:
            hit = apply_rules(surface, "LOC", "ru", usa_rules)
            assert hit is not None, f"Expected hit for {surface!r}"
            assert hit.target_canonical_id == canonical_id
            assert hit.method == "rule"
            assert hit.score == 1.0

    def test_no_rule_match(self, usa_rules):
        result = apply_rules("Россия", "LOC", "ru", usa_rules)
        assert result is None

    def test_entity_type_filter(self, usa_rules):
        # Same surface but wrong type — should not match
        result = apply_rules("США", "PERSON", "ru", usa_rules)
        assert result is None

    def test_language_filter(self, usa_rules):
        # Same surface but wrong language — should not match
        result = apply_rules("США", "LOC", "en", usa_rules)
        assert result is None

    def test_regex_rule(self):
        rule = Rule(
            id="rx1",
            rule_type="regex",
            pattern=r"сша|соединённые штаты|америка",
            replacement=None,
            entity_type=None,
            language=None,
            target_canonical_id="11111111-2222-3333-4444-555555555555",
            priority=50,
        )
        hit = apply_rules("США", "LOC", "ru", [rule])
        assert hit is not None
        assert hit.target_canonical_id == "11111111-2222-3333-4444-555555555555"

    def test_priority_order(self):
        canonical_low = "low-id-000"
        canonical_high = "high-id-111"
        rules = [
            Rule(
                id="low",
                rule_type="alias",
                pattern="тест",
                replacement=None,
                entity_type=None,
                language=None,
                target_canonical_id=canonical_low,
                priority=10,
            ),
            Rule(
                id="high",
                rule_type="alias",
                pattern="тест",
                replacement=None,
                entity_type=None,
                language=None,
                target_canonical_id=canonical_high,
                priority=100,
            ),
        ]
        hit = apply_rules("тест", "ORG", "ru", rules)
        # High priority wins
        assert hit is not None
        assert hit.target_canonical_id == canonical_high

    def test_abbreviation_rule(self):
        rule = Rule(
            id="ab1",
            rule_type="abbreviation",
            pattern="НАТО",
            replacement="NATO",
            entity_type="ORG",
            language=None,
            target_canonical_id="nato-id",
            priority=100,
        )
        hit = apply_rules("НАТО", "ORG", "ru", [rule])
        assert hit is not None
        assert hit.target_canonical_id == "nato-id"

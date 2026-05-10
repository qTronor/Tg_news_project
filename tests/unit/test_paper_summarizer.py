import json
import pytest
from paper_summarizer.prompt import strip_forbidden_fields, PROMPT_VERSION, build_prompt
from paper_summarizer.mistral_client import MockMistralClient


VALID_SUMMARY = {
    "title": "Test Paper",
    "authors": ["Author A"],
    "abstract_summary": "Краткое изложение",
    "research_problem": "Проблема",
    "main_contribution": "Вклад",
    "method": "Method A",
    "datasets": ["Dataset X"],
    "metrics": ["Accuracy"],
    "experiments": "Эксперименты",
    "results": "Результаты",
    "limitations": "Ограничения",
    "keywords": ["NLP", "transformer"],
    "paper_type": "research_paper",
    "short_summary": "Короткое резюме",
}

FORBIDDEN_FIELDS = [
    "how_it_can_help_our_project",
    "project_relevance",
    "project_ideas",
    "suggested_improvements",
    "can_improve",
    "relevance_to_our_project",
]


def test_valid_json_accepted():
    result = strip_forbidden_fields(VALID_SUMMARY.copy())
    assert "title" in result
    assert "short_summary" in result


def test_forbidden_fields_stripped():
    data = {**VALID_SUMMARY, "how_it_can_help_our_project": "should be removed"}
    result = strip_forbidden_fields(data)
    assert "how_it_can_help_our_project" not in result
    assert "title" in result


def test_all_forbidden_fields_stripped():
    data = {**VALID_SUMMARY}
    for field in FORBIDDEN_FIELDS:
        data[field] = "bad value"
    result = strip_forbidden_fields(data)
    for field in FORBIDDEN_FIELDS:
        assert field not in result


def test_invalid_json_raises():
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads("this is not json {")


@pytest.mark.asyncio
async def test_mock_mistral_client_returns_response():
    client = MockMistralClient(json.dumps(VALID_SUMMARY))
    raw = await client.complete("test prompt")
    parsed = json.loads(raw)
    assert parsed["title"] == "Test Paper"


def test_build_prompt_contains_text():
    prompt = build_prompt("Abstract text here")
    assert "Abstract text here" in prompt
    assert "JSON" in prompt
    assert "how_it_can_help_our_project" not in prompt


def test_prompt_version_is_set():
    assert PROMPT_VERSION == "v1"

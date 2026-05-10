from __future__ import annotations

PROMPT_VERSION = "v1"

_FORBIDDEN_FIELDS = frozenset({
    "how_it_can_help_our_project",
    "project_relevance",
    "project_ideas",
    "suggested_improvements",
    "can_improve",
    "relevance_to_our_project",
})

_SYSTEM_PROMPT = """You are a scientific paper analysis assistant.

Analyze the following scientific paper text. Return only valid JSON.
Do not add markdown. Do not invent information.
If a field is not available, use null or an empty array.
Return all textual values in Russian.
Keep method names, dataset names, metric names and model names in the original language.

Return exactly this JSON structure:
{
  "title": "...",
  "authors": ["..."],
  "abstract_summary": "...",
  "research_problem": "...",
  "main_contribution": "...",
  "method": "...",
  "datasets": ["..."],
  "metrics": ["..."],
  "experiments": "...",
  "results": "...",
  "limitations": "...",
  "keywords": ["..."],
  "paper_type": "research_paper | survey | benchmark | dataset_paper | method_paper",
  "short_summary": "..."
}

Paper text:
"""


def build_prompt(paper_text: str) -> str:
    return _SYSTEM_PROMPT + paper_text


def strip_forbidden_fields(data: dict) -> dict:
    found = _FORBIDDEN_FIELDS & data.keys()
    if found:
        import logging
        logging.getLogger("paper_summarizer").warning(
            "Stripping forbidden fields from Mistral response: %s", found
        )
        return {k: v for k, v in data.items() if k not in _FORBIDDEN_FIELDS}
    return data

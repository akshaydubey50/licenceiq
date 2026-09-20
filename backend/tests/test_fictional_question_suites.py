"""Offline contract checks for the local, review-required fictional Q&A suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

SUITE_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "fictional_question_suites_v1"
SUITE_FILES = tuple(sorted(path for path in SUITE_DIR.glob("*.json")))
EXPECTED_CATEGORIES = {
    "happy_path",
    "semantic",
    "conversation_context",
    "neutral_unsupported",
    "off_topic",
    "prompt_injection",
}
FICTIONAL_SAMPLES = {"fictional_maharashtra_licence", "fictional_delhi_licence"}
JsonObject = dict[str, Any]


@pytest.fixture(scope="module")
def suites() -> tuple[JsonObject, ...]:
    """Load only committed local JSON; this test never calls a provider or Langfuse."""
    return tuple(
        cast(JsonObject, json.loads(path.read_text(encoding="utf-8"))) for path in SUITE_FILES
    )


def test_suite_files_cover_each_required_question_outcome(
    suites: tuple[JsonObject, ...],
) -> None:
    assert len(SUITE_FILES) == 5
    categories = {case["metadata"]["category"] for suite in suites for case in suite["cases"]}
    assert EXPECTED_CATEGORIES <= categories


def test_every_case_is_reviewable_and_uses_only_fictional_samples(
    suites: tuple[JsonObject, ...],
) -> None:
    identifiers: list[str] = []
    for suite in suites:
        assert suite["schema_version"] == "licenceiq.fictional-question-suite.v1"
        dataset = suite["dataset"]
        assert dataset["status"] == "LOCAL_DRAFT_REVIEW_REQUIRED"
        assert dataset["source_policy"] == "fictional_samples_only"
        for case in suite["cases"]:
            identifiers.append(case["id"])
            request = case["input"]
            assert request["sample"] in FICTIONAL_SAMPLES
            assert isinstance(request["question"], str) and request["question"].strip()
            assert isinstance(request["prior_questions"], list)
            expected = case["expected_output"]
            if expected["outcome"] == "result":
                assert expected["status"] in {"ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE"}
                assert expected["citation_required"] is (expected["status"] == "ANSWERED")
                if expected["status"] == "ANSWERED":
                    assert expected["source_page"] == 1
                    assert expected["source_contains"]
                else:
                    assert "source_page" not in expected
                    assert "source_contains" not in expected
            else:
                assert expected == {
                    "outcome": "application_error",
                    "http_status": 400,
                    "error_code": "QUESTION_BLOCKED",
                    "provider_work_expected": False,
                }
    assert len(identifiers) == len(set(identifiers))


def test_suites_include_answered_abstention_scope_and_guardrail_paths(
    suites: tuple[JsonObject, ...],
) -> None:
    results = [case["expected_output"] for suite in suites for case in suite["cases"]]
    assert sum(result.get("status") == "ANSWERED" for result in results) >= 10
    assert sum(result.get("status") == "UNAVAILABLE" for result in results) >= 4
    assert sum(result.get("status") == "OUT_OF_SCOPE" for result in results) >= 4
    assert sum(result.get("error_code") == "QUESTION_BLOCKED" for result in results) >= 4

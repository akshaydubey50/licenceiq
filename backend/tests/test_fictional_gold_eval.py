"""Regression checks for the reviewed fictional golden-dataset evaluator."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.fictional_gold_eval import (
    DEFAULT_GOLD_PATH,
    GoldenDatasetError,
    ObservedResult,
    ObservedSource,
    evaluate,
    load_gold_cases,
    load_observed_results,
    main,
    parse_observed_results,
    score_case,
)


def _passing_results() -> tuple[ObservedResult, ...]:
    results: list[ObservedResult] = []
    for case in load_gold_cases():
        source = case.expected.source
        expected_source = (
            ()
            if source is None
            else (ObservedSource(source.page_number, " ".join(source.contains)),)
        )
        results.append(
            ObservedResult(
                case_id=case.case_id,
                status=case.expected.status,
                answer=(
                    case.expected.answer_equals
                    if case.expected.answer_equals is not None
                    else " ".join(case.expected.answer_contains)
                ),
                citations=expected_source,
                retrieved_sources=expected_source if case.requires_retrieval else (),
                direct_lookup=case.expected_direct_lookup,
            )
        )
    return tuple(results)


def test_gold_v0_is_reviewable_and_has_approved_distribution() -> None:
    cases = load_gold_cases()

    assert len(cases) == 10
    assert sum(case.expected_direct_lookup for case in cases) == 4
    assert sum(case.requires_retrieval for case in cases) == 4
    assert (
        sum(not case.expected_direct_lookup and not case.requires_retrieval for case in cases) == 2
    )
    raw = json.loads(DEFAULT_GOLD_PATH.read_text(encoding="utf-8"))
    tasks = [case["metadata"]["task"] for case in raw["cases"]]
    assert tasks.count("direct_structured_field") == 2
    assert tasks.count("paraphrased_retrieval") == 3
    assert tasks.count("conversation_aware_retrieval") == 1
    assert tasks.count("extraction_evidence") == 2
    assert tasks.count("supported_absence") == tasks.count("out_of_scope") == 1
    assert {case.expected.status for case in cases} == {
        "ANSWERED",
        "UNAVAILABLE",
        "OUT_OF_SCOPE",
    }
    assert all(case.case_id.startswith("fictional-") for case in cases)


def test_passing_local_observations_produce_all_approved_metrics() -> None:
    report = evaluate(load_gold_cases(), _passing_results())

    assert report["case_count"] == 10
    assert report["metrics"] == {
        "evidence_recall_at_3": 1.0,
        "evidence_recall_at_5": 1.0,
        "mean_reciprocal_rank": 1.0,
        "citation_support_rate": 1.0,
        "abstention_accuracy": 1.0,
        "direct_path_accuracy": 1.0,
    }


def test_missing_retrieval_evidence_lowers_retrieval_metrics_without_affecting_schema() -> None:
    results = list(_passing_results())
    retrieval_index = next(
        index for index, case in enumerate(load_gold_cases()) if case.requires_retrieval
    )
    result = results[retrieval_index]
    results[retrieval_index] = ObservedResult(
        case_id=result.case_id,
        status=result.status,
        answer=result.answer,
        citations=result.citations,
        retrieved_sources=(ObservedSource(1, "unrelated fictional source"),),
        direct_lookup=result.direct_lookup,
    )

    report = evaluate(load_gold_cases(), results)

    assert report["metrics"]["evidence_recall_at_3"] == 0.75  # type: ignore[index]
    assert report["metrics"]["mean_reciprocal_rank"] == 0.75  # type: ignore[index]


def test_result_loader_rejects_unknown_case_ids(tmp_path: Path) -> None:
    result_path = tmp_path / "results.json"
    result_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "id": "unknown-case",
                        "status": "UNAVAILABLE",
                        "answer": "I couldn't find that in this document.",
                        "citations": [],
                        "retrieved_sources": [],
                        "direct_lookup": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GoldenDatasetError, match="exactly match"):
        evaluate(load_gold_cases(), load_observed_results(result_path))


def test_dataset_path_is_inside_the_project_evaluation_directory() -> None:
    assert DEFAULT_GOLD_PATH.name == "fictional_licence_gold_v0.json"
    assert DEFAULT_GOLD_PATH.parent.name == "evaluation"


def test_validation_only_command_never_requires_a_result_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--validate-gold"]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report == {"case_count": 10, "schema_version": "1", "status": "valid"}


@pytest.mark.parametrize("rank,recall3,recall5", [(1, 1, 1), (4, 0, 1), (6, 0, 0)])
def test_rank_metrics_have_correct_cutoffs(rank: int, recall3: int, recall5: int) -> None:
    case = next(case for case in load_gold_cases() if case.requires_retrieval)
    observed = next(result for result in _passing_results() if result.case_id == case.case_id)
    observed = replace(
        observed,
        retrieved_sources=(ObservedSource(1, "unrelated"),) * (rank - 1)
        + observed.retrieved_sources,
    )
    scores = score_case(case, observed)
    assert scores["evidence_recall_at_3"] == recall3
    assert scores["evidence_recall_at_5"] == recall5
    assert scores["mean_reciprocal_rank"] == 1 / rank


def test_failed_provider_is_scored_as_zero_and_stays_in_denominator() -> None:
    cases = load_gold_cases()
    observed = list(_passing_results())
    failure = parse_observed_results(
        {
            "results": [
                {
                    "id": cases[0].case_id,
                    "status": "ERROR",
                    "answer": "Evaluation failed.",
                    "citations": [],
                    "retrieved_sources": [],
                    "direct_lookup": False,
                    "error_code": "OCR_PROVIDER_ERROR",
                }
            ]
        }
    )[0]
    observed[0] = failure
    report = evaluate(cases, observed)
    assert report["error_count"] == 1
    assert report["metrics"]["direct_path_accuracy"] == 0.75  # type: ignore[index]
    assert report["metric_case_counts"]["direct_path_accuracy"] == 4  # type: ignore[index]
    assert all(value == 0 for value in score_case(cases[0], failure).values())


def test_equivalent_date_format_passes_but_changed_date_fails() -> None:
    case = next(case for case in load_gold_cases() if "issue-date" in case.case_id)
    observed = next(result for result in _passing_results() if result.case_id == case.case_id)
    assert score_case(case, replace(observed, answer="2019-06-16"))["direct_path_accuracy"] == 1
    assert score_case(case, replace(observed, answer="2019-06-17"))["direct_path_accuracy"] == 0


def test_partial_licence_number_does_not_pass() -> None:
    case = load_gold_cases()[0]
    observed = _passing_results()[0]
    assert (
        score_case(case, replace(observed, answer=observed.answer + "9"))["direct_path_accuracy"]
        == 0
    )


def test_duplicate_results_are_rejected_even_when_id_sets_match() -> None:
    observed = _passing_results()
    with pytest.raises(GoldenDatasetError, match="unique"):
        evaluate(load_gold_cases(), (*observed, observed[0]))


def test_multiline_evidence_uses_fragment_recall_and_complete_citation_coverage() -> None:
    case = next(case for case in load_gold_cases() if "address-paraphrase" in case.case_id)
    reference = next(result for result in _passing_results() if result.case_id == case.case_id)
    assert case.expected.source is not None
    fragments = tuple(ObservedSource(1, text) for text in case.expected.source.contains)
    unrelated = ObservedSource(1, "Unrelated text")
    result = replace(
        reference,
        citations=fragments,
        retrieved_sources=(unrelated, fragments[0], unrelated, fragments[1], fragments[2]),
    )
    scores = score_case(case, result)
    assert scores["evidence_recall_at_3"] == pytest.approx(1 / 3)
    assert scores["evidence_recall_at_5"] == 1
    assert scores["mean_reciprocal_rank"] == 0.5
    assert scores["citation_support_rate"] == 1
    assert score_case(case, replace(result, citations=fragments[:1]))["citation_support_rate"] == 0

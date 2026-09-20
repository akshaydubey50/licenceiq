"""Offline experiment integration checks; canned results are never benchmark claims."""

import asyncio
import copy
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.fictional_gold_eval import GoldenDatasetError
from scripts.run_fictional_gold_experiment import main, run_experiment
from scripts.upload_fictional_gold_dataset import load_fictional_items


class FakeDataset:
    def __init__(self) -> None:
        self.items = [
            SimpleNamespace(**copy.deepcopy(item), status="ACTIVE")
            for item in load_fictional_items()
        ]
        self.options: dict[str, Any] = {}
        self.drop_score = False

    def run_experiment(self, **kwargs: Any) -> Any:
        self.options = kwargs
        results = []
        for item in self.items:
            output = asyncio.run(kwargs["task"](item=item))
            scores = kwargs["evaluators"][0](
                output=output, input=item.input, expected_output=item.expected_output
            )
            results.append(SimpleNamespace(output=output, evaluations=scores))
        aggregates = kwargs["run_evaluators"][0](item_results=results)
        if self.drop_score:
            results[0].evaluations = []
        return SimpleNamespace(
            item_results=results,
            run_evaluations=aggregates,
            dataset_run_url="https://langfuse.invalid/experiment",
        )


class FixturePipeline:
    """Reference envelopes exercise reporting; they do not stand in for a live app run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_case = False

    def run_case(self, case_id: str, input: Any) -> dict[str, object]:
        self.calls.append((case_id, input))
        assert set(input) == {"sample", "question", "prior_questions"}
        if self.fail_case and len(self.calls) == 1:
            return {
                "id": case_id,
                "status": "ERROR",
                "answer": "Evaluation failed.",
                "citations": [],
                "retrieved_sources": [],
                "direct_lookup": False,
                "error_code": "OCR_PROVIDER_ERROR",
            }
        item = next(item for item in load_fictional_items() if item["id"] == case_id)
        expected = item["expected_output"]
        source = (
            []
            if expected["source_page"] is None
            else [
                {
                    "page_number": expected["source_page"],
                    "text": " ".join(expected["source_locator_text"]),
                }
            ]
        )  # type: ignore[arg-type]
        return {
            "id": case_id,
            "status": expected["status"],
            "answer": expected["answer_equals"] or " ".join(expected["answer_contains"]),  # type: ignore[arg-type]
            "citations": source,
            "retrieved_sources": source if item["metadata"]["requires_retrieval"] else [],
            "direct_lookup": item["metadata"]["expected_direct_lookup"],
            "error_code": None,
            "document_id": "this-extra-field-must-never-leave-the-adapter",
        }


def test_hosted_experiment_links_all_items_and_only_applicable_scores() -> None:
    dataset, pipeline = FakeDataset(), FixturePipeline()
    _, report = run_experiment(
        dataset, pipeline, run_name="offline", evaluation_factory=SimpleNamespace
    )
    assert len(pipeline.calls) == 10
    assert dataset.options["max_concurrency"] == 1
    assert report["case_count"] == 10
    assert report["error_count"] == 0
    assert report["metric_case_counts"] == {
        "evidence_recall_at_3": 4,
        "evidence_recall_at_5": 4,
        "mean_reciprocal_rank": 4,
        "citation_support_rate": 8,
        "abstention_accuracy": 2,
        "direct_path_accuracy": 4,
    }
    assert "document_id" not in repr(report)
    assert "this-extra-field" not in repr(report)


@pytest.mark.parametrize("change", ["input", "expected_output", "inactive", "missing"])
def test_remote_drift_stops_before_application_calls(change: str) -> None:
    dataset, pipeline = FakeDataset(), FixturePipeline()
    if change == "missing":
        dataset.items.pop()
    elif change == "inactive":
        dataset.items[0].status = "ARCHIVED"
    else:
        setattr(dataset.items[0], change, {"unreviewed": "change"})
    with pytest.raises(GoldenDatasetError, match="Hosted dataset"):
        run_experiment(dataset, pipeline, run_name="offline", evaluation_factory=SimpleNamespace)
    assert pipeline.calls == []


def test_error_item_remains_visible_and_reduces_aggregate_score() -> None:
    pipeline = FixturePipeline()
    pipeline.fail_case = True
    _, report = run_experiment(
        FakeDataset(), pipeline, run_name="offline", evaluation_factory=SimpleNamespace
    )
    assert report["error_count"] == 1
    assert report["metrics"]["direct_path_accuracy"] == 0.75  # type: ignore[index]


def test_silently_missing_sdk_score_is_not_reported_as_success() -> None:
    dataset = FakeDataset()
    dataset.drop_score = True
    with pytest.raises(GoldenDatasetError, match="omitted"):
        run_experiment(
            dataset, FixturePipeline(), run_name="offline", evaluation_factory=SimpleNamespace
        )


def test_default_mode_validates_without_sdk_or_live_pipeline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert main([]) == 0
    assert '"mode": "dry-run"' in capsys.readouterr().out

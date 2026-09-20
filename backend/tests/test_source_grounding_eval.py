"""Offline checks for the opt-in Langfuse evaluation foundation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import pytest

from scripts.source_grounding_eval import (
    EXPERIMENT_NAME,
    ExportConfig,
    ExportConfigurationError,
    LocalExperimentItem,
    build_local_dataset,
    categorize_envelope,
    load_export_config,
    main,
    run_langfuse_export,
    run_local_evaluation,
)


class FakeEvaluation:
    def __init__(
        self,
        *,
        name: str,
        value: int,
        comment: str,
        data_type: Literal["NUMERIC"],
    ) -> None:
        self.name = name
        self.value = value
        self.comment = comment
        self.data_type = data_type


class FakeExperimentClient:
    def __init__(self) -> None:
        self.call: dict[str, object] | None = None
        self.evaluations: list[FakeEvaluation] = []
        self.flushed = False
        self.stopped = False

    def run_experiment(
        self,
        *,
        name: str,
        description: str,
        data: list[LocalExperimentItem],
        task: Callable[..., object],
        evaluators: list[Callable[..., object]],
        max_concurrency: int,
        metadata: dict[str, str],
    ) -> object:
        self.call = {
            "name": name,
            "description": description,
            "data": data,
            "max_concurrency": max_concurrency,
            "metadata": metadata,
        }
        evaluator = evaluators[0]
        for item in data:
            output = task(item=item)
            result = evaluator(output=output, expected_output=item["expected_output"])
            assert isinstance(result, FakeEvaluation)
            self.evaluations.append(result)
        return object()

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.stopped = True


@pytest.mark.parametrize(
    ("status", "citation_count", "expected"),
    [
        ("ANSWERED", 1, "grounded_answer"),
        ("ANSWERED", 0, "uncited_answer"),
        ("UNAVAILABLE", 0, "safe_unavailable"),
        ("UNAVAILABLE", 1, "inconsistent_unavailable"),
        ("OUT_OF_SCOPE", 0, "safe_out_of_scope"),
        ("OUT_OF_SCOPE", 1, "inconsistent_out_of_scope"),
    ],
)
def test_envelope_categories_are_deterministic(
    status: str,
    citation_count: int,
    expected: str,
) -> None:
    assert categorize_envelope(status, citation_count) == expected  # type: ignore[arg-type]


def test_local_dataset_contains_only_allowlisted_synthetic_fields() -> None:
    dataset = build_local_dataset()

    assert dataset
    for item in dataset:
        assert set(item) == {"input", "expected_output", "metadata"}
        assert set(item["input"]) == {"fixture", "status", "citation_count"}
        assert set(item["expected_output"]) == {"category"}
        assert item["metadata"] == {"suite": "source_grounding_envelope_v1"}
    serialized = repr(dataset).casefold()
    for forbidden_field in (
        "question",
        "answer_text",
        "document_id",
        "user_id",
        "access_token",
        "secret_key",
        "public_key",
    ):
        assert forbidden_field not in serialized


def test_default_command_is_local_and_needs_no_environment(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    assert main([]) == 0
    output = capsys.readouterr().out
    assert '"case_count": 7' in output
    assert '"failed": 0' in output
    assert '"passed": 7' in output


def test_export_requires_dedicated_opt_in_and_complete_credentials() -> None:
    with pytest.raises(ExportConfigurationError, match="LICENCEIQ_LANGFUSE_EVAL_EXPORT"):
        load_export_config({})
    with pytest.raises(ExportConfigurationError, match="LANGFUSE_PUBLIC_KEY"):
        load_export_config({"LICENCEIQ_LANGFUSE_EVAL_EXPORT": "true"})
    with pytest.raises(ExportConfigurationError, match="valid HTTP"):
        load_export_config(
            {
                "LICENCEIQ_LANGFUSE_EVAL_EXPORT": "true",
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_BASE_URL": "file:///unsafe",
            }
        )


def test_export_cli_stops_before_sdk_use_without_dedicated_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LICENCEIQ_LANGFUSE_EVAL_EXPORT", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        main(["--export-langfuse"])

    assert exc_info.value.code == 2


def test_langfuse_adapter_exports_only_the_fixed_local_experiment() -> None:
    client = FakeExperimentClient()
    config = ExportConfig("pk-test", "sk-test", "https://langfuse.invalid")

    run_langfuse_export(config, client=client, evaluation_factory=FakeEvaluation)

    assert client.call is not None
    assert client.call["name"] == EXPERIMENT_NAME
    assert client.call["data"] == build_local_dataset()
    assert client.call["max_concurrency"] == 1
    assert client.flushed is True
    assert client.stopped is True
    assert len(client.evaluations) == len(build_local_dataset())
    assert all(result.name == "source_grounding_envelope_exact" for result in client.evaluations)
    assert all(result.value == 1 for result in client.evaluations)
    assert all(result.data_type == "NUMERIC" for result in client.evaluations)


def test_local_summary_covers_safe_and_violation_categories() -> None:
    summary = run_local_evaluation()

    assert summary["failed"] == 0
    assert summary["categories"] == {
        "grounded_answer": 2,
        "inconsistent_out_of_scope": 1,
        "inconsistent_unavailable": 1,
        "safe_out_of_scope": 1,
        "safe_unavailable": 1,
        "uncited_answer": 1,
    }

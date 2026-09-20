"""Run the reviewed fictional samples through LicenceIQ and publish a hosted experiment.

The default is a local validation. --run enables paid model calls and a Langfuse
experiment, bound to the existing reviewed dataset and isolated temporary storage.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from scripts.fictional_gold_eval import (
    GoldCase,
    GoldenDatasetError,
    evaluate,
    load_gold_cases,
    parse_observed_results,
    score_case,
)
from scripts.upload_fictional_gold_dataset import (
    DATASET_NAME,
    GOLD_PATH,
    PROJECT_ROOT,
    DatasetItem,
    load_fictional_items,
    load_upload_config,
    resolve_upload_environment,
)

EVALUATOR_VERSION = "fictional-gold-v0.2"
OUTPUT_ROOT = PROJECT_ROOT / ".runtime" / "evaluations"


class Pipeline(Protocol):
    """Only reviewed user input reaches the application, never expected answers."""

    def run_case(self, case_id: str, input: Mapping[str, object]) -> dict[str, object]: ...


class HostedDataset(Protocol):
    """Small SDK surface shared with the offline experiment test double."""

    @property
    def items(self) -> Sequence[Any]: ...

    def run_experiment(self, **kwargs: Any) -> Any: ...


def validate_hosted_dataset(dataset: HostedDataset, reviewed: Sequence[DatasetItem]) -> None:
    """Abort on remote edits or missing items instead of silently changing the benchmark."""
    expected = {item["id"]: item for item in reviewed}
    actual = {str(item.id): item for item in dataset.items}
    if len(actual) != len(dataset.items) or set(actual) != set(expected):
        raise GoldenDatasetError("Hosted dataset must contain the same ten reviewed case IDs.")
    for case_id, gold in expected.items():
        item = actual[case_id]
        if (
            getattr(item, "status", "ACTIVE") != "ACTIVE"
            or item.input != gold["input"]
            or item.expected_output != gold["expected_output"]
            or item.metadata != gold["metadata"]
        ):
            raise GoldenDatasetError("Hosted dataset differs from the reviewed local version.")


def run_experiment(
    dataset: HostedDataset,
    pipeline: Pipeline,
    *,
    run_name: str,
    evaluation_factory: Callable[..., Any],
    run_metadata: dict[str, str] | None = None,
) -> tuple[Any, dict[str, object]]:
    """Execute actual service outputs and attach six selectively applicable SDK scores."""
    reviewed = load_fictional_items()
    validate_hosted_dataset(dataset, reviewed)
    inputs_by_id = {item["id"]: item["input"] for item in reviewed}
    gold_by_id: dict[str, GoldCase] = {case.case_id: case for case in load_gold_cases()}
    collected: dict[str, dict[str, object]] = {}

    async def task(*, item: Any, **_: Any) -> dict[str, object]:
        # Never forward the SDK item object: it also contains expected_output.
        case_id = str(item.id)
        # The SDK owns an event loop. Sync application services use their own async upload bridge.
        output = await asyncio.to_thread(pipeline.run_case, case_id, inputs_by_id[case_id])
        observations = parse_observed_results({"results": [output]})
        if observations[0].case_id != case_id:
            raise GoldenDatasetError("Pipeline result has the wrong fictional case ID.")
        # Rebuild an allowlisted envelope, so an adapter cannot leak arbitrary extra fields.
        observed = observations[0]
        safe_output: dict[str, object] = {
            "id": case_id,
            "status": observed.status,
            "answer": observed.answer,
            "citations": [
                {"page_number": source.page_number, "text": source.text}
                for source in observed.citations
            ],
            "retrieved_sources": [
                {"page_number": source.page_number, "text": source.text}
                for source in observed.retrieved_sources
            ],
            "direct_lookup": observed.direct_lookup,
            "error_code": observed.error_code,
        }
        collected[case_id] = safe_output
        return safe_output

    def item_evaluator(*, output: Any, **_: Any) -> list[Any]:
        observed = parse_observed_results({"results": [output]})[0]
        scores = score_case(gold_by_id[observed.case_id], observed)
        return [
            evaluation_factory(name=name, value=value, data_type="NUMERIC")
            for name, value in scores.items()
        ]

    def run_evaluator(*, item_results: Any, **_: Any) -> list[Any]:
        # Item results are inspected below too; this aggregate uses the same canonical scorer.
        if len(item_results) != len(gold_by_id) or len(collected) != len(gold_by_id):
            raise GoldenDatasetError("The experiment did not produce every expected result.")
        report = evaluate(
            tuple(gold_by_id.values()),
            parse_observed_results({"results": list(collected.values())}),
        )
        metrics = report["metrics"]
        assert isinstance(metrics, dict)
        return [
            evaluation_factory(name=name, value=value, data_type="NUMERIC")
            for name, value in metrics.items()
            if value is not None
        ]

    sdk_result = dataset.run_experiment(
        name="LicenceIQ fictional document evaluation",
        run_name=run_name,
        description=(
            "Actual OCR, extraction and document Q&A on two supplied fictional samples; "
            "six deterministic reference metrics. Isolated filesystem storage; "
            "no API/auth benchmark."
        ),
        task=task,
        evaluators=[item_evaluator],
        run_evaluators=[run_evaluator],
        max_concurrency=1,
        metadata={
            **(run_metadata or {}),
            "data_classification": "fictional_only",
            "execution_profile": "isolated_application_services",
            "evaluator_version": EVALUATOR_VERSION,
            "dataset_sha256": hashlib.sha256(GOLD_PATH.read_bytes()).hexdigest(),
        },
    )
    if len(collected) != len(gold_by_id):
        raise GoldenDatasetError(
            "Incomplete experiment; missing cases cannot be treated as passing."
        )
    if len(sdk_result.item_results) != len(gold_by_id):
        raise GoldenDatasetError("The SDK returned an incomplete experiment.")
    for item_result in sdk_result.item_results:
        observed = parse_observed_results({"results": [item_result.output]})[0]
        expected_scores = score_case(gold_by_id[observed.case_id], observed)
        actual_scores = {score.name: score.value for score in item_result.evaluations}
        if actual_scores != expected_scores:
            raise GoldenDatasetError("The SDK omitted or changed an item score.")
    observations = parse_observed_results({"results": list(collected.values())})
    report = evaluate(tuple(gold_by_id.values()), observations)
    if {score.name: score.value for score in sdk_result.run_evaluations} != report["metrics"]:
        raise GoldenDatasetError("The SDK omitted or changed aggregate scores.")
    report.update(
        run_name=run_name,
        dataset=DATASET_NAME,
        evaluator_version=EVALUATOR_VERSION,
        experiment_url=getattr(sdk_result, "dataset_run_url", None),
        results=list(collected.values()),
    )
    return sdk_result, report


def _default_run_name() -> str:
    return "licenceiq-gold-v0-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _code_fingerprint() -> str:
    """Record reproducibility without exporting git paths or configuration secrets."""
    digest = hashlib.sha256()
    for relative in (
        "app/services/reading.py",
        "app/services/extraction.py",
        "app/services/questions.py",
        "app/services/question_guardrails.py",
        "app/providers/openai_answer.py",
        "app/providers/openai_query_rewrite.py",
        "scripts/fictional_eval_pipeline.py",
        "scripts/fictional_gold_eval.py",
        "scripts/run_fictional_gold_experiment.py",
    ):
        digest.update((Path(__file__).resolve().parents[1] / relative).read_bytes())
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Validate by default; run live only when the operator explicitly selects --run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="run real providers and publish scores")
    parser.add_argument("--run-name", default=None, help="optional unique experiment name")
    args = parser.parse_args(argv)
    reviewed = load_fictional_items()
    load_gold_cases()
    if not args.run:
        print(
            json.dumps(
                {"mode": "dry-run", "dataset": DATASET_NAME, "items": len(reviewed), "valid": True}
            )
        )
        return 0
    run_name = args.run_name or _default_run_name()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", run_name):
        parser.error("run-name must contain only letters, digits, underscores, periods or hyphens")

    from langfuse import Evaluation, Langfuse

    from scripts.fictional_eval_pipeline import FictionalPipeline

    config = load_upload_config(resolve_upload_environment(os.environ))
    client = Langfuse(
        public_key=config.public_key,
        secret_key=config.secret_key,
        base_url=config.base_url,
        environment="fictional-evaluation",
    )
    try:
        dataset = cast(HostedDataset, client.get_dataset(DATASET_NAME))
        validate_hosted_dataset(dataset, reviewed)
        with FictionalPipeline() as pipeline:
            if not pipeline.settings.openai_api_key.get_secret_value():
                raise GoldenDatasetError(
                    "OPENAI_API_KEY must be configured for the live experiment."
                )
            print(
                json.dumps(
                    {
                        "mode": "live",
                        "dataset": DATASET_NAME,
                        "run_name": run_name,
                        "items": len(reviewed),
                    }
                ),
                flush=True,
            )
            _, report = run_experiment(
                dataset,
                pipeline,
                run_name=run_name,
                evaluation_factory=Evaluation,
                run_metadata={
                    "code_sha256": _code_fingerprint(),
                    "ocr_model": pipeline.settings.ocr_model,
                    "extraction_model": pipeline.settings.extraction_model,
                    "question_model": pipeline.settings.question_model,
                    "embedding_model": pipeline.settings.question_embedding_model,
                    "guardrails_enabled": str(pipeline.settings.question_guardrails_enabled),
                },
            )
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_ROOT / f"{run_name}.json"
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        client.flush()
        print(
            json.dumps(
                {
                    "dataset": DATASET_NAME,
                    "run_name": run_name,
                    "case_count": report["case_count"],
                    "error_count": report["error_count"],
                    "metrics": report["metrics"],
                    "metric_case_counts": report["metric_case_counts"],
                    "experiment_url": report["experiment_url"],
                    "report_path": str(output_path),
                }
            )
        )
        return 0 if report["error_count"] == 0 else 1
    finally:
        client.shutdown()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Provider and SDK error messages can contain request payloads or credentials.
        print(json.dumps({"completed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None

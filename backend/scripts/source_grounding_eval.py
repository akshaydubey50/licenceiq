"""Run LicenceIQ's synthetic source-grounding envelope evaluation.

The default command is local and makes no network calls. Langfuse export is a
separate, double-opt-in path that sends only fixed labels and integer counts.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypedDict, cast
from urllib.parse import urlsplit

Status = Literal["ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE"]
Category = Literal[
    "grounded_answer",
    "safe_unavailable",
    "safe_out_of_scope",
    "uncited_answer",
    "inconsistent_unavailable",
    "inconsistent_out_of_scope",
]

EXPERIMENT_NAME = "licenceiq-source-grounding-envelope-v1"
EXPERIMENT_DESCRIPTION = (
    "Deterministic evaluation of synthetic status and citation-count envelopes only."
)
EXPORT_OPT_IN_ENV = "LICENCEIQ_LANGFUSE_EVAL_EXPORT"
REQUIRED_EXPORT_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


class CandidateInput(TypedDict):
    """Synthetic result envelope used by the local experiment task."""

    fixture: str
    status: Status
    citation_count: int


class ExpectedOutput(TypedDict):
    """Fixed safe category expected from one synthetic envelope."""

    category: Category


class ExperimentMetadata(TypedDict):
    """Allowlisted metadata shared by every synthetic item."""

    suite: str


class LocalExperimentItem(TypedDict):
    """Local Langfuse item containing no document or user content."""

    input: CandidateInput
    expected_output: ExpectedOutput
    metadata: ExperimentMetadata


class EvaluationFactory(Protocol):
    """Minimal constructor contract implemented by ``langfuse.Evaluation``."""

    def __call__(
        self,
        *,
        name: str,
        value: int,
        comment: str,
        data_type: Literal["NUMERIC"],
    ) -> object: ...


class ExperimentClient(Protocol):
    """Narrow SDK surface used by the export adapter and offline fakes."""

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
    ) -> object: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True)
class EnvelopeCase:
    """One reviewed synthetic category case."""

    fixture: str
    status: Status
    citation_count: int
    expected_category: Category


@dataclass(frozen=True)
class Score:
    """Deterministic result that is independent of the Langfuse SDK."""

    observed_category: Category
    expected_category: Category
    value: int

    @property
    def comment(self) -> str:
        """Return a fixed-label explanation safe for external export."""
        return f"observed={self.observed_category};expected={self.expected_category}"


@dataclass(frozen=True, repr=False)
class ExportConfig:
    """Complete credentials required for an explicitly enabled export."""

    public_key: str
    secret_key: str
    base_url: str


SYNTHETIC_CASES: tuple[EnvelopeCase, ...] = (
    EnvelopeCase("answered_with_one_citation", "ANSWERED", 1, "grounded_answer"),
    EnvelopeCase("answered_with_multiple_citations", "ANSWERED", 2, "grounded_answer"),
    EnvelopeCase("unavailable_without_citations", "UNAVAILABLE", 0, "safe_unavailable"),
    EnvelopeCase("out_of_scope_without_citations", "OUT_OF_SCOPE", 0, "safe_out_of_scope"),
    EnvelopeCase("answered_without_citations", "ANSWERED", 0, "uncited_answer"),
    EnvelopeCase(
        "unavailable_with_citation",
        "UNAVAILABLE",
        1,
        "inconsistent_unavailable",
    ),
    EnvelopeCase(
        "out_of_scope_with_citation",
        "OUT_OF_SCOPE",
        1,
        "inconsistent_out_of_scope",
    ),
)


class ExportConfigurationError(ValueError):
    """Raised when external export is not explicitly and completely configured."""


def categorize_envelope(status: Status, citation_count: int) -> Category:
    """Classify the source-grounding envelope using no document content."""
    if isinstance(citation_count, bool) or citation_count < 0:
        raise ValueError("citation_count must be a non-negative integer")
    if status == "ANSWERED":
        return "grounded_answer" if citation_count > 0 else "uncited_answer"
    if status == "UNAVAILABLE":
        return "safe_unavailable" if citation_count == 0 else "inconsistent_unavailable"
    if status == "OUT_OF_SCOPE":
        return "safe_out_of_scope" if citation_count == 0 else "inconsistent_out_of_scope"
    raise ValueError("status must be an allowlisted envelope status")


def score_envelope(output: Mapping[str, object], expected_output: Mapping[str, object]) -> Score:
    """Score one output against an expected fixed safe category."""
    status_value = output.get("status")
    citation_count = output.get("citation_count")
    expected_category_value = expected_output.get("category")
    if status_value not in {"ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE"}:
        raise ValueError("output status is not allowlisted")
    if not isinstance(citation_count, int) or isinstance(citation_count, bool):
        raise ValueError("output citation_count must be an integer")
    if expected_category_value not in {
        "grounded_answer",
        "safe_unavailable",
        "safe_out_of_scope",
        "uncited_answer",
        "inconsistent_unavailable",
        "inconsistent_out_of_scope",
    }:
        raise ValueError("expected category is not allowlisted")
    status = cast(Status, status_value)
    expected_category = cast(Category, expected_category_value)
    observed_category = categorize_envelope(status, citation_count)
    return Score(
        observed_category=observed_category,
        expected_category=expected_category,
        value=int(observed_category == expected_category),
    )


def build_local_dataset() -> list[LocalExperimentItem]:
    """Build a fresh list containing only reviewed synthetic labels and counts."""
    return [
        {
            "input": {
                "fixture": case.fixture,
                "status": case.status,
                "citation_count": case.citation_count,
            },
            "expected_output": {"category": case.expected_category},
            "metadata": {"suite": "source_grounding_envelope_v1"},
        }
        for case in SYNTHETIC_CASES
    ]


def run_local_evaluation() -> dict[str, object]:
    """Evaluate the fixed dataset locally without importing Langfuse."""
    scores = [
        score_envelope(item["input"], item["expected_output"])
        for item in build_local_dataset()
    ]
    categories = Counter(score.observed_category for score in scores)
    passed = sum(score.value for score in scores)
    return {
        "suite": "source_grounding_envelope_v1",
        "case_count": len(scores),
        "passed": passed,
        "failed": len(scores) - passed,
        "categories": dict(sorted(categories.items())),
    }


def load_export_config(environment: Mapping[str, str]) -> ExportConfig:
    """Require a dedicated opt-in plus complete Langfuse credentials."""
    if environment.get(EXPORT_OPT_IN_ENV, "").strip().casefold() != "true":
        raise ExportConfigurationError(f"{EXPORT_OPT_IN_ENV}=true is required for export")
    values = {name: environment.get(name, "").strip() for name in REQUIRED_EXPORT_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ExportConfigurationError(
            "Langfuse export requires: " + ", ".join(REQUIRED_EXPORT_ENV)
        )
    base_url = values["LANGFUSE_BASE_URL"]
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ExportConfigurationError("LANGFUSE_BASE_URL must be a valid HTTP(S) server URL")
    return ExportConfig(
        public_key=values["LANGFUSE_PUBLIC_KEY"],
        secret_key=values["LANGFUSE_SECRET_KEY"],
        base_url=base_url.rstrip("/"),
    )


def _experiment_task(*, item: Mapping[str, object], **_: object) -> object:
    """Return only the synthetic candidate envelope from a local item."""
    candidate = item.get("input")
    if not isinstance(candidate, Mapping):
        raise ValueError("experiment item input must be a mapping")
    return dict(candidate)


def _build_langfuse_evaluator(
    evaluation_factory: EvaluationFactory,
) -> Callable[..., object]:
    def evaluator(
        *,
        output: object,
        expected_output: object,
        **_: object,
    ) -> object:
        if not isinstance(output, Mapping) or not isinstance(expected_output, Mapping):
            raise ValueError("experiment output and expected_output must be mappings")
        score = score_envelope(output, expected_output)
        return evaluation_factory(
            name="source_grounding_envelope_exact",
            value=score.value,
            comment=score.comment,
            data_type="NUMERIC",
        )

    return evaluator


def run_langfuse_export(
    config: ExportConfig,
    *,
    client: ExperimentClient | None = None,
    evaluation_factory: EvaluationFactory | None = None,
) -> None:
    """Export the fixed local experiment through Langfuse SDK v4."""
    active_client = client
    active_evaluation_factory = evaluation_factory
    if active_client is None or active_evaluation_factory is None:
        from langfuse import Evaluation, Langfuse

        if active_client is None:
            active_client = cast(
                ExperimentClient,
                Langfuse(
                    public_key=config.public_key,
                    secret_key=config.secret_key,
                    base_url=config.base_url,
                ),
            )
        if active_evaluation_factory is None:
            active_evaluation_factory = cast(EvaluationFactory, Evaluation)
    try:
        active_client.run_experiment(
            name=EXPERIMENT_NAME,
            description=EXPERIMENT_DESCRIPTION,
            data=build_local_dataset(),
            task=_experiment_task,
            evaluators=[_build_langfuse_evaluator(active_evaluation_factory)],
            max_concurrency=1,
            metadata={"suite": "source_grounding_envelope_v1"},
        )
        active_client.flush()
    finally:
        active_client.shutdown()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=EXPERIMENT_DESCRIPTION)
    parser.add_argument(
        "--export-langfuse",
        action="store_true",
        help=(
            "export the fixed synthetic experiment; also requires "
            f"{EXPORT_OPT_IN_ENV}=true and complete Langfuse credentials"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run locally by default and export only through the explicit gated path."""
    args = _parser().parse_args(argv)
    local_summary = run_local_evaluation()
    print(json.dumps(local_summary, sort_keys=True))
    if not args.export_langfuse:
        return 0
    try:
        config = load_export_config(os.environ)
        run_langfuse_export(config)
    except ExportConfigurationError as exc:
        _parser().error(str(exc))
    print(json.dumps({"exported": True, "suite": "source_grounding_envelope_v1"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

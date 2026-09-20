"""Evaluate reviewed fictional LicenceIQ gold cases without altering the public API.

The evaluator consumes only an explicitly supplied local result file. It never reads
documents, calls providers, or exports to Langfuse. A later approved adapter may
produce the result file from an isolated fictional-sample application run.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

Status = Literal["ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE"]
ObservedStatus = Literal["ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE", "ERROR"]
GOLD_ROOT = Path(__file__).resolve().parents[2] / "evaluation"
DEFAULT_GOLD_PATH = GOLD_ROOT / "fictional_licence_gold_v0.json"


class GoldenDatasetError(ValueError):
    """Raised when reviewed gold data or a test-only run result is malformed."""


@dataclass(frozen=True)
class SourceExpectation:
    """Reviewed source text needed to validate an answer or retrieval rank."""

    page_number: int
    contains: tuple[str, ...]


@dataclass(frozen=True)
class ExpectedOutput:
    """One reviewed expected response, never inferred from a model output."""

    status: Status
    answer_contains: tuple[str, ...]
    answer_equals: str | None
    citation_required: bool
    minimum_citations: int
    source: SourceExpectation | None


@dataclass(frozen=True)
class GoldCase:
    """A single fictional document-Q&A evaluation case."""

    case_id: str
    expected: ExpectedOutput
    requires_retrieval: bool
    expected_direct_lookup: bool


@dataclass(frozen=True)
class ObservedSource:
    """Resolved source text supplied only by a test/evaluation adapter."""

    page_number: int
    text: str


@dataclass(frozen=True)
class ObservedResult:
    """The minimum non-production envelope required to calculate metrics."""

    case_id: str
    status: ObservedStatus
    answer: str
    citations: tuple[ObservedSource, ...]
    retrieved_sources: tuple[ObservedSource, ...]
    direct_lookup: bool
    error_code: str | None = None


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GoldenDatasetError(f"{label} must be an object")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenDatasetError(f"{label} must be a non-empty string")
    return value


def _require_string_list(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or (not allow_empty and not value)
        or not all(isinstance(item, str) and item for item in value)
    ):
        qualifier = "an array of strings" if allow_empty else "a non-empty array of strings"
        raise GoldenDatasetError(f"{label} must be {qualifier}")
    return tuple(value)


def _parse_status(value: object, label: str) -> Status:
    if value not in {"ANSWERED", "UNAVAILABLE", "OUT_OF_SCOPE"}:
        raise GoldenDatasetError(f"{label} must be ANSWERED, UNAVAILABLE, or OUT_OF_SCOPE")
    return value  # type: ignore[return-value]


def _parse_source(value: object, label: str) -> SourceExpectation:
    source = _require_mapping(value, label)
    page = source.get("source_page")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise GoldenDatasetError(f"{label}.source_page must be a positive integer")
    return SourceExpectation(
        page_number=page,
        contains=_require_string_list(source.get("source_contains"), f"{label}.source_contains"),
    )


def load_gold_cases(path: Path = DEFAULT_GOLD_PATH) -> tuple[GoldCase, ...]:
    """Load the human-reviewed v0 dataset and validate its small fixed contract."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GoldenDatasetError(f"could not read gold dataset: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GoldenDatasetError(f"gold dataset is not valid JSON: {path}") from exc
    root = _require_mapping(payload, "gold dataset")
    if root.get("schema_version") != "licenceiq.fictional-golden-dataset.v0":
        raise GoldenDatasetError("gold dataset schema_version is not supported")
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 10:
        raise GoldenDatasetError("gold dataset must contain exactly 10 cases")

    cases: list[GoldCase] = []
    for index, raw_case in enumerate(raw_cases):
        case = _require_mapping(raw_case, f"cases[{index}]")
        expected = _require_mapping(case.get("expected_output"), f"cases[{index}].expected_output")
        metadata = _require_mapping(case.get("metadata"), f"cases[{index}].metadata")
        status = _parse_status(expected.get("status"), f"cases[{index}].expected_output.status")
        source_page = expected.get("source_page")
        source_text = expected.get("source_locator_text")
        source = None
        if source_page is not None or source_text not in (None, []):
            source = _parse_source(
                {"source_page": source_page, "source_contains": source_text},
                f"cases[{index}].expected_output",
            )
        answer_equals = expected.get("answer_equals")
        if answer_equals is not None and not isinstance(answer_equals, str):
            raise GoldenDatasetError(
                f"cases[{index}].expected_output.answer_equals must be null or text"
            )
        citation_required = expected.get("citation_required")
        minimum_citations = expected.get("minimum_citations")
        if not isinstance(citation_required, bool):
            raise GoldenDatasetError(
                f"cases[{index}].expected_output.citation_required must be boolean"
            )
        if (
            not isinstance(minimum_citations, int)
            or isinstance(minimum_citations, bool)
            or minimum_citations < 0
        ):
            raise GoldenDatasetError(
                f"cases[{index}].expected_output.minimum_citations must be a non-negative integer"
            )
        if status == "ANSWERED" and (
            source is None or not citation_required or minimum_citations < 1
        ):
            raise GoldenDatasetError(f"cases[{index}] answered case needs expected source evidence")
        if status != "ANSWERED" and (
            source is not None or citation_required or minimum_citations != 0
        ):
            raise GoldenDatasetError(f"cases[{index}] abstention case cannot name source evidence")
        direct = metadata.get("expected_direct_lookup")
        retrieval = metadata.get("requires_retrieval")
        if not isinstance(direct, bool) or not isinstance(retrieval, bool):
            raise GoldenDatasetError(f"cases[{index}] evaluation flags must be boolean")
        if status == "ANSWERED" and direct == retrieval:
            raise GoldenDatasetError(
                f"cases[{index}] answered case must set exactly one of direct lookup or retrieval"
            )
        if status != "ANSWERED" and (direct or retrieval):
            raise GoldenDatasetError(
                f"cases[{index}] abstention case cannot require direct lookup or retrieval"
            )
        cases.append(
            GoldCase(
                case_id=_require_text(case.get("id"), f"cases[{index}].id"),
                expected=ExpectedOutput(
                    status=status,
                    answer_contains=_require_string_list(
                        expected.get("answer_contains"),
                        f"cases[{index}].expected_output.answer_contains",
                        allow_empty=status != "ANSWERED",
                    ),
                    answer_equals=answer_equals,
                    citation_required=citation_required,
                    minimum_citations=minimum_citations,
                    source=source,
                ),
                requires_retrieval=retrieval,
                expected_direct_lookup=direct,
            )
        )
    if len({case.case_id for case in cases}) != len(cases):
        raise GoldenDatasetError("gold dataset case ids must be unique")
    return tuple(cases)


def _parse_observed_source(value: object, label: str) -> ObservedSource:
    source = _require_mapping(value, label)
    page = source.get("page_number")
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise GoldenDatasetError(f"{label}.page_number must be a positive integer")
    return ObservedSource(page_number=page, text=_require_text(source.get("text"), f"{label}.text"))


def parse_observed_results(payload: object) -> tuple[ObservedResult, ...]:
    """Validate actual pipeline outputs, retaining provider failures in the denominator."""
    root = _require_mapping(payload, "evaluation results")
    raw_results = root.get("results")
    if not isinstance(raw_results, list):
        raise GoldenDatasetError("evaluation results must contain a results array")
    results: list[ObservedResult] = []
    for index, raw_result in enumerate(raw_results):
        result = _require_mapping(raw_result, f"results[{index}]")
        citations = result.get("citations")
        retrieved = result.get("retrieved_sources")
        if not isinstance(citations, list) or not isinstance(retrieved, list):
            raise GoldenDatasetError(f"results[{index}] must include source arrays")
        direct = result.get("direct_lookup")
        if not isinstance(direct, bool):
            raise GoldenDatasetError(f"results[{index}].direct_lookup must be boolean")
        status: ObservedStatus = (
            "ERROR"
            if result.get("status") == "ERROR"
            else _parse_status(result.get("status"), f"results[{index}].status")
        )
        error = result.get("error_code")
        if error is not None and (
            not isinstance(error, str) or re.fullmatch(r"[A-Z_]{1,80}", error) is None
        ):
            raise GoldenDatasetError("error_code must be a fixed uppercase category")
        if status == "ERROR" and (error is None or citations or retrieved or direct):
            raise GoldenDatasetError("failed observations need a code and no source claims")
        if status != "ERROR" and error is not None:
            raise GoldenDatasetError("successful observations cannot carry an error code")
        results.append(
            ObservedResult(
                case_id=_require_text(result.get("id"), f"results[{index}].id"),
                status=status,
                answer=_require_text(result.get("answer"), f"results[{index}].answer"),
                citations=tuple(
                    _parse_observed_source(value, f"results[{index}].citations")
                    for value in citations
                ),
                retrieved_sources=tuple(
                    _parse_observed_source(value, f"results[{index}].retrieved_sources")
                    for value in retrieved
                ),
                direct_lookup=direct,
                error_code=error,
            )
        )
    if len({result.case_id for result in results}) != len(results):
        raise GoldenDatasetError("evaluation result ids must be unique")
    return tuple(results)


def load_observed_results(path: Path) -> tuple[ObservedResult, ...]:
    """Read a local result envelope containing resolved source text, not document IDs."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenDatasetError(f"could not read evaluation results: {path}") from exc
    return parse_observed_results(payload)


def _normalized_text(value: str) -> str:
    """Ignore OCR layout punctuation and equivalent ISO/Indian numeric date formatting."""

    def normalize_date(match: re.Match[str]) -> str:
        parts = match.group().replace("/", "-").split("-")
        if len(parts[0]) == 4:
            year, month, day = (int(part) for part in parts)
        else:
            day, month, year = (int(part) for part in parts)
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return match.group()

    value = re.sub(
        r"\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b", normalize_date, value
    )
    return " ".join(re.findall(r"\w+", value.casefold()))


def _contains_text(text: str, value: str) -> bool:
    """Match complete normalized tokens so partial licence numbers cannot pass."""
    target = _normalized_text(value)
    return bool(target) and f" {target} " in f" {_normalized_text(text)} "


def _matches(expected: SourceExpectation, observed: ObservedSource) -> bool:
    """A reading block is relevant if it contains any reviewed evidence fragment."""
    return observed.page_number == expected.page_number and any(
        _contains_text(observed.text, value) for value in expected.contains
    )


def _coverage(expected: SourceExpectation, observed: Sequence[ObservedSource]) -> float:
    """Count reviewed fragments across blocks, including multi-line addresses/authorities."""
    matched = sum(
        any(
            source.page_number == expected.page_number and _contains_text(source.text, value)
            for source in observed
        )
        for value in expected.contains
    )
    return matched / len(expected.contains)


def _answer_matches(expected: ExpectedOutput, observed: ObservedResult) -> bool:
    if observed.status != expected.status:
        return False
    if expected.answer_equals is not None:
        return observed.answer == expected.answer_equals
    return all(_contains_text(observed.answer, value) for value in expected.answer_contains)


def score_case(case: GoldCase, result: ObservedResult) -> dict[str, float]:
    """Return only applicable metrics; an error contributes zero, never a dropped case."""
    if case.case_id != result.case_id:
        raise GoldenDatasetError("result does not belong to this gold case")
    answer_matches = _answer_matches(case.expected, result)
    source = case.expected.source
    supported = (
        result.status != "ERROR"
        and source is not None
        and _coverage(source, result.citations) == 1.0
        and len(result.citations) >= case.expected.minimum_citations
        and answer_matches
    )
    scores: dict[str, float] = {}
    if case.requires_retrieval:
        rank = (
            next(
                (
                    position
                    for position, block in enumerate(result.retrieved_sources, 1)
                    if source is not None and _matches(source, block)
                ),
                None,
            )
            if result.status != "ERROR"
            else None
        )
        scores["evidence_recall_at_3"] = (
            _coverage(source, result.retrieved_sources[:3])
            if source is not None and result.status != "ERROR"
            else 0.0
        )
        scores["evidence_recall_at_5"] = (
            _coverage(source, result.retrieved_sources[:5])
            if source is not None and result.status != "ERROR"
            else 0.0
        )
        scores["mean_reciprocal_rank"] = 1.0 / rank if rank else 0.0
    if case.expected.status == "ANSWERED":
        scores["citation_support_rate"] = float(supported)
    else:
        scores["abstention_accuracy"] = float(answer_matches and not result.citations)
    if case.expected_direct_lookup:
        scores["direct_path_accuracy"] = float(
            supported and result.direct_lookup and not result.retrieved_sources
        )
    return scores


def evaluate(cases: Sequence[GoldCase], results: Sequence[ObservedResult]) -> dict[str, object]:
    """Calculate approved deterministic metrics from reviewed expectations and local results."""
    observed_by_id = {result.case_id: result for result in results}
    expected_ids = {case.case_id for case in cases}
    if len(observed_by_id) != len(results) or len(expected_ids) != len(cases):
        raise GoldenDatasetError("case and result ids must be unique")
    if set(observed_by_id) != expected_ids:
        raise GoldenDatasetError("evaluation result ids must exactly match gold case ids")

    metric_values: dict[str, list[float]] = {
        name: []
        for name in (
            "evidence_recall_at_3",
            "evidence_recall_at_5",
            "mean_reciprocal_rank",
            "citation_support_rate",
            "abstention_accuracy",
            "direct_path_accuracy",
        )
    }
    case_results: list[dict[str, object]] = []

    for case in cases:
        result = observed_by_id[case.case_id]
        scores = score_case(case, result)
        for name, score in scores.items():
            metric_values[name].append(score)
        answer_matches = _answer_matches(case.expected, result)
        citation_matches = False
        rank: int | None = None
        if case.expected.source is not None:
            citation_matches = _coverage(case.expected.source, result.citations) == 1.0
            for index, source in enumerate(result.retrieved_sources, start=1):
                if _matches(case.expected.source, source):
                    rank = index
                    break
        has_required_citations = len(result.citations) >= case.expected.minimum_citations
        case_results.append(
            {
                "id": case.case_id,
                "answer_matches": answer_matches,
                "citation_supported": citation_matches,
                "has_required_citations": has_required_citations,
                "retrieval_rank": rank,
                "direct_lookup": result.direct_lookup,
                "error_code": result.error_code,
                "scores": scores,
            }
        )

    return {
        "schema_version": "1",
        "case_count": len(cases),
        "error_count": sum(result.status == "ERROR" for result in results),
        "metrics": {
            name: round(sum(values) / len(values), 4) if values else None
            for name, values in metric_values.items()
        },
        "metric_case_counts": {name: len(values) for name, values in metric_values.items()},
        "cases": case_results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Score fictional LicenceIQ gold-v0 results without provider or network calls."
    )
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD_PATH)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--results",
        type=Path,
        help="A test-only result envelope from an approved fictional-sample adapter.",
    )
    mode.add_argument(
        "--validate-gold",
        action="store_true",
        help="Validate the reviewed local dataset without running a provider or application flow.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Print one deterministic JSON report for reviewed local test results."""
    args = _parser().parse_args(argv)
    cases = load_gold_cases(args.gold)
    if args.validate_gold:
        report: dict[str, object] = {
            "schema_version": "1",
            "status": "valid",
            "case_count": len(cases),
        }
    else:
        if args.results is None:  # argparse enforces this; keeps static analysis explicit.
            raise GoldenDatasetError("provide --results or --validate-gold")
        report = evaluate(cases, load_observed_results(args.results))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

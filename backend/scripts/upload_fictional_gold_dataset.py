"""Validate and optionally upload LicenceIQ's reviewed fictional gold dataset.

The default command is a network-free dry run. Remote mutation requires the
explicit ``--upload`` flag and a complete Langfuse configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict, cast
from urllib.parse import urlsplit

DATASET_NAME = "licenceiq/fictional-gold-v0"
SCHEMA_VERSION = "licenceiq.fictional-golden-dataset.v0"
DATASET_ID = "fictional-licence-gold-v0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLD_PATH = PROJECT_ROOT / "evaluation" / "fictional_licence_gold_v0.json"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
REQUIRED_UPLOAD_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)
ALLOWED_SAMPLES = {
    "fictional_maharashtra_licence",
    "fictional_delhi_licence",
}
ROOT_KEYS = {"schema_version", "dataset_metadata", "case_contract", "cases"}
CASE_KEYS = {"id", "input", "expected_output", "metadata"}
INPUT_KEYS = {"sample", "question", "prior_questions"}
EXPECTED_OUTPUT_KEYS = {
    "status",
    "answer_equals",
    "answer_contains",
    "citation_required",
    "minimum_citations",
    "source_page",
    "source_locator_text",
}
METADATA_KEYS = {
    "task",
    "intent",
    "requires_retrieval",
    "expected_direct_lookup",
    "include_in_retrieval_rank_metrics",
}
PRIVACY_KEYS = {
    "classification",
    "contains_real_personal_data",
    "contains_runtime_document_ids",
    "contains_credentials_or_tokens",
    "contains_provider_trace_content",
    "external_upload_status",
}
FORBIDDEN_ITEM_KEYS = {
    "raw_image",
    "raw_image_bytes",
    "image_bytes",
    "local_path",
    "local_file_path",
    "file_path",
    "runtime_id",
    "runtime_document_id",
    "document_id",
    "trace_id",
    "source_trace_id",
    "observation_id",
    "source_observation_id",
}
LOCAL_PATH_PATTERN = re.compile(r"^(?:[a-zA-Z]:[\\/]|\\\\|file://|/(?:home|tmp|var)/)")


class DatasetValidationError(ValueError):
    """Raised when the input is not the reviewed fictional-only dataset contract."""


class UploadConfigurationError(ValueError):
    """Raised when an explicit upload lacks a complete safe configuration."""


class DatasetItem(TypedDict):
    """One validated Langfuse dataset item."""

    id: str
    input: dict[str, object]
    expected_output: dict[str, object]
    metadata: dict[str, object]


class DatasetClient(Protocol):
    """Narrow Langfuse SDK v4 surface used by the uploader and offline fakes."""

    def create_dataset_item(
        self,
        *,
        dataset_name: str,
        id: str,
        input: object,
        expected_output: object,
        metadata: object,
    ) -> object: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True, repr=False)
class UploadConfig:
    """Exact Langfuse credentials required only by the upload path."""

    public_key: str
    secret_key: str
    base_url: str


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise DatasetValidationError(f"{label} must be an object with string keys")
    return cast(Mapping[str, object], value)


def _require_exact_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise DatasetValidationError(f"{label} does not match the reviewed fictional schema")


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatasetValidationError(f"{label} must be non-empty text")
    return value


def _require_text_list(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DatasetValidationError(f"{label} must be an array of strings")
    return value


def _reject_unsafe_item_values(value: object, label: str) -> None:
    """Reject fields and values that must never reach the remote dataset."""
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise DatasetValidationError(f"{label} contains a non-text field name")
            if raw_key.casefold() in FORBIDDEN_ITEM_KEYS:
                raise DatasetValidationError(f"{label} contains forbidden field {raw_key}")
            _reject_unsafe_item_values(child, f"{label}.{raw_key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_unsafe_item_values(child, f"{label}[{index}]")
        return
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise DatasetValidationError(f"{label} contains raw bytes")
    if isinstance(value, Path):
        raise DatasetValidationError(f"{label} contains a local file path")
    if isinstance(value, str) and LOCAL_PATH_PATTERN.match(value.strip()):
        raise DatasetValidationError(f"{label} contains a local file path")


def _validate_dataset_markers(root: Mapping[str, object]) -> None:
    metadata = _require_mapping(root.get("dataset_metadata"), "dataset_metadata")
    if metadata.get("id") != DATASET_ID:
        raise DatasetValidationError("dataset_metadata.id is not the reviewed fictional dataset")
    privacy = _require_mapping(metadata.get("privacy"), "dataset_metadata.privacy")
    _require_exact_keys(privacy, PRIVACY_KEYS, "dataset_metadata.privacy")
    if privacy.get("classification") != "fictional_test_data_only":
        raise DatasetValidationError("dataset is not classified as fictional test data only")
    false_markers = (
        "contains_real_personal_data",
        "contains_runtime_document_ids",
        "contains_credentials_or_tokens",
        "contains_provider_trace_content",
    )
    if any(privacy.get(marker) is not False for marker in false_markers):
        raise DatasetValidationError("dataset privacy markers do not permit external upload")
    contract = _require_mapping(root.get("case_contract"), "case_contract")
    if contract.get("runtime_document_ids_forbidden") is not True:
        raise DatasetValidationError("dataset must forbid runtime document ids")
    source_policy = _require_mapping(
        metadata.get("source_policy"), "dataset_metadata.source_policy"
    )
    if source_policy.get("document_content_trust") != "untrusted_evidence_only":
        raise DatasetValidationError("document content must remain untrusted evidence only")


def load_fictional_items(path: Path = GOLD_PATH) -> tuple[DatasetItem, ...]:
    """Load and strictly validate the reviewed fictional-only source file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatasetValidationError(f"could not read fictional gold dataset: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"fictional gold dataset is not valid JSON: {path}") from exc

    root = _require_mapping(payload, "gold dataset")
    _require_exact_keys(root, ROOT_KEYS, "gold dataset")
    if root.get("schema_version") != SCHEMA_VERSION:
        raise DatasetValidationError("gold dataset schema_version is not supported")
    _validate_dataset_markers(root)
    raw_cases = root.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != 10:
        raise DatasetValidationError(
            "reviewed fictional gold dataset must contain exactly 10 cases"
        )

    items: list[DatasetItem] = []
    for index, raw_case in enumerate(raw_cases):
        label = f"cases[{index}]"
        case = _require_mapping(raw_case, label)
        _require_exact_keys(case, CASE_KEYS, label)
        case_id = _require_text(case.get("id"), f"{label}.id")
        if not case_id.startswith("fictional-"):
            raise DatasetValidationError(f"{label}.id must identify fictional data")

        input_value = _require_mapping(case.get("input"), f"{label}.input")
        expected_output = _require_mapping(case.get("expected_output"), f"{label}.expected_output")
        metadata = _require_mapping(case.get("metadata"), f"{label}.metadata")
        _require_exact_keys(input_value, INPUT_KEYS, f"{label}.input")
        _require_exact_keys(expected_output, EXPECTED_OUTPUT_KEYS, f"{label}.expected_output")
        _require_exact_keys(metadata, METADATA_KEYS, f"{label}.metadata")

        if input_value.get("sample") not in ALLOWED_SAMPLES:
            raise DatasetValidationError(
                f"{label}.input.sample is not an approved fictional sample"
            )
        _require_text(input_value.get("question"), f"{label}.input.question")
        _require_text_list(input_value.get("prior_questions"), f"{label}.input.prior_questions")
        _reject_unsafe_item_values(case, label)
        items.append(
            {
                "id": case_id,
                "input": dict(input_value),
                "expected_output": dict(expected_output),
                "metadata": dict(metadata),
            }
        )

    if len({item["id"] for item in items}) != len(items):
        raise DatasetValidationError("fictional dataset case ids must be unique")
    return tuple(items)


def load_upload_config(environment: Mapping[str, str]) -> UploadConfig:
    """Load exact credentials after the caller has explicitly selected upload."""
    values = {name: environment.get(name, "").strip() for name in REQUIRED_UPLOAD_ENV}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise UploadConfigurationError(
            "Langfuse upload requires: " + ", ".join(REQUIRED_UPLOAD_ENV)
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
        raise UploadConfigurationError(
            "LANGFUSE_BASE_URL must be a valid HTTP(S) server URL without credentials"
        )
    return UploadConfig(
        public_key=values["LANGFUSE_PUBLIC_KEY"],
        secret_key=values["LANGFUSE_SECRET_KEY"],
        base_url=base_url.rstrip("/"),
    )


def _parse_env_value(raw_value: str, label: str) -> str:
    """Parse one allowlisted dotenv value without expanding variables."""
    value = raw_value.strip()
    if not value or value[0] not in {"'", '"'}:
        return re.split(r"\s+#", value, maxsplit=1)[0].strip()
    quote = value[0]
    closing_index = value.find(quote, 1)
    remainder = value[closing_index + 1 :].strip() if closing_index >= 0 else ""
    if closing_index < 0 or (remainder and not remainder.startswith("#")):
        raise UploadConfigurationError(f"{label} has an invalid quoted value")
    return value[1:closing_index]


def load_allowlisted_env_file(path: Path) -> dict[str, str]:
    """Read only required Langfuse names from one dotenv file."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise UploadConfigurationError(f"could not read Langfuse env file: {path}") from exc

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, raw_value = line.partition("=")
        name = name.strip()
        if name not in REQUIRED_UPLOAD_ENV:
            continue
        if not separator:
            raise UploadConfigurationError(f"{path}:{line_number} has an invalid {name} assignment")
        values[name] = _parse_env_value(raw_value, f"{path}:{line_number} {name}")
    return values


def resolve_upload_environment(
    process_environment: Mapping[str, str], env_path: Path = DEFAULT_ENV_PATH
) -> dict[str, str]:
    """Merge allowlisted file values with explicit process overrides."""
    values = load_allowlisted_env_file(env_path)
    for name in REQUIRED_UPLOAD_ENV:
        if name in process_environment:
            values[name] = process_environment[name]
    return values


def upload_items(
    items: Sequence[DatasetItem],
    config: UploadConfig,
    *,
    client: DatasetClient | None = None,
) -> int:
    """Upload validated items through the Langfuse Python SDK v4 item API."""
    active_client = client
    if active_client is None:
        from langfuse import Langfuse

        active_client = cast(
            DatasetClient,
            Langfuse(
                public_key=config.public_key,
                secret_key=config.secret_key,
                base_url=config.base_url,
            ),
        )
    try:
        for item in items:
            active_client.create_dataset_item(
                dataset_name=DATASET_NAME,
                id=item["id"],
                input=item["input"],
                expected_output=item["expected_output"],
                metadata=item["metadata"],
            )
        active_client.flush()
        return len(items)
    finally:
        active_client.shutdown()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate LicenceIQ's reviewed fictional gold dataset and optionally upload it."
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="mutate the existing Langfuse dataset; requires complete Langfuse credentials",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="dotenv file used only for the three required Langfuse values (default: root .env)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client: DatasetClient | None = None,
) -> int:
    """Dry-run by default; upload only after an explicit flag and config check."""
    parser = _parser()
    args = parser.parse_args(argv)
    items = load_fictional_items()
    if not args.upload:
        print(
            json.dumps(
                {"dataset": DATASET_NAME, "items": len(items), "mode": "dry-run", "valid": True},
                sort_keys=True,
            )
        )
        return 0
    try:
        process_environment = os.environ if environment is None else environment
        upload_environment = resolve_upload_environment(process_environment, args.env_file)
        config = load_upload_config(upload_environment)
    except UploadConfigurationError as exc:
        parser.error(str(exc))
    uploaded = upload_items(items, config, client=client)
    print(
        json.dumps(
            {"dataset": DATASET_NAME, "items": uploaded, "mode": "upload", "uploaded": True},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

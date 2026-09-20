"""Offline checks for the explicitly gated fictional Langfuse dataset uploader."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts.upload_fictional_gold_dataset import (
    DATASET_NAME,
    GOLD_PATH,
    DatasetItem,
    DatasetValidationError,
    UploadConfig,
    load_allowlisted_env_file,
    load_fictional_items,
    main,
    resolve_upload_environment,
    upload_items,
)


class FakeDatasetClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.flushed = False
        self.stopped = False

    def create_dataset_item(
        self,
        *,
        dataset_name: str,
        id: str,
        input: object,
        expected_output: object,
        metadata: object,
    ) -> object:
        self.calls.append(
            {
                "dataset_name": dataset_name,
                "id": id,
                "input": input,
                "expected_output": expected_output,
                "metadata": metadata,
            }
        )
        return object()

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.stopped = True


def _write_changed_dataset(tmp_path: Path, change: Callable[[dict[str, Any]], object]) -> Path:
    payload: dict[str, Any] = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    change(payload)
    path = tmp_path / "gold.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_mapped_payload_preserves_reviewed_case_fields() -> None:
    source = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    items = load_fictional_items()

    assert len(items) == 10
    for item, case in zip(items, source["cases"], strict=True):
        assert item == {
            "id": case["id"],
            "input": case["input"],
            "expected_output": case["expected_output"],
            "metadata": case["metadata"],
        }
        assert set(item) == {"id", "input", "expected_output", "metadata"}


def test_default_command_is_a_dry_run_without_credentials_or_client(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([], environment={}) == 0

    assert json.loads(capsys.readouterr().out) == {
        "dataset": DATASET_NAME,
        "items": 10,
        "mode": "dry-run",
        "valid": True,
    }


def test_explicit_upload_uses_v4_dataset_item_payloads(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeDatasetClient()
    environment = {
        "LANGFUSE_PUBLIC_KEY": "pk-test",
        "LANGFUSE_SECRET_KEY": "sk-test",
        "LANGFUSE_BASE_URL": "https://langfuse.invalid",
    }

    assert (
        main(
            ["--upload", "--env-file", str(tmp_path / "missing.env")],
            environment=environment,
            client=client,
        )
        == 0
    )

    items = load_fictional_items()
    assert client.calls == [
        {
            "dataset_name": DATASET_NAME,
            "id": item["id"],
            "input": item["input"],
            "expected_output": item["expected_output"],
            "metadata": item["metadata"],
        }
        for item in items
    ]
    assert client.flushed is True
    assert client.stopped is True
    assert json.loads(capsys.readouterr().out)["uploaded"] is True


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.update(schema_version="unknown"),
        lambda payload: payload["dataset_metadata"]["privacy"].update(
            contains_real_personal_data=True
        ),
        lambda payload: payload["cases"][0]["input"].update(document_id="runtime-private-id"),
        lambda payload: payload["cases"][0]["input"].update(question="C:\\private\\licence.png"),
    ],
)
def test_invalid_or_nonfictional_schema_is_rejected(
    tmp_path: Path,
    change: Callable[[dict[str, Any]], object],
) -> None:
    path = _write_changed_dataset(tmp_path, change)

    with pytest.raises(DatasetValidationError):
        load_fictional_items(path)


def test_env_file_loads_only_required_values_and_process_environment_overrides(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                "UNRELATED_SECRET=must-not-load",
                "LANGFUSE_PUBLIC_KEY=pk-from-file",
                "LANGFUSE_SECRET_KEY='sk-from-file'",
                "export LANGFUSE_BASE_URL=https://file.langfuse.invalid # local config",
            )
        ),
        encoding="utf-8",
    )

    assert load_allowlisted_env_file(env_file) == {
        "LANGFUSE_PUBLIC_KEY": "pk-from-file",
        "LANGFUSE_SECRET_KEY": "sk-from-file",
        "LANGFUSE_BASE_URL": "https://file.langfuse.invalid",
    }
    assert resolve_upload_environment(
        {"LANGFUSE_PUBLIC_KEY": "pk-process", "UNRELATED_SECRET": "process-secret"},
        env_file,
    ) == {
        "LANGFUSE_PUBLIC_KEY": "pk-process",
        "LANGFUSE_SECRET_KEY": "sk-from-file",
        "LANGFUSE_BASE_URL": "https://file.langfuse.invalid",
    }


def test_explicit_upload_can_use_env_file_without_printing_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env_file = tmp_path / ".env"
    secrets = ("pk-private", "sk-private", "https://private.langfuse.invalid")
    env_file.write_text(
        "\n".join(
            (
                f"LANGFUSE_PUBLIC_KEY={secrets[0]}",
                f"LANGFUSE_SECRET_KEY={secrets[1]}",
                f"LANGFUSE_BASE_URL={secrets[2]}",
                "OTHER_PRIVATE_VALUE=never-loaded",
            )
        ),
        encoding="utf-8",
    )

    assert (
        main(
            ["--upload", "--env-file", str(env_file)],
            environment={},
            client=FakeDatasetClient(),
        )
        == 0
    )
    output = capsys.readouterr().out
    assert all(secret not in output for secret in (*secrets, "never-loaded"))


def test_missing_configuration_is_checked_only_for_explicit_upload(tmp_path: Path) -> None:
    assert main([], environment={}) == 0

    with pytest.raises(SystemExit) as exc_info:
        main(
            ["--upload", "--env-file", str(tmp_path / "missing.env")],
            environment={},
            client=FakeDatasetClient(),
        )

    assert exc_info.value.code == 2


def test_upload_adapter_can_be_exercised_with_an_offline_fake() -> None:
    client = FakeDatasetClient()
    items: tuple[DatasetItem, ...] = load_fictional_items()
    config = UploadConfig("pk-test", "sk-test", "https://langfuse.invalid")

    assert upload_items(items, config, client=client) == len(items)
    assert client.flushed is True
    assert client.stopped is True

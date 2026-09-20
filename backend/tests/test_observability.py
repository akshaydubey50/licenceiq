"""Offline checks for LicenceIQ's privacy-safe Langfuse boundary."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.observability import (
    LangfuseTraceClient,
    NullTraceClient,
    ObservationType,
    TraceStage,
    build_trace_client,
    safe_model_name,
    sanitize_metadata,
)


class FakeObservation:
    def __init__(self, *, fail_update: bool = False) -> None:
        self.fail_update = fail_update
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)
        if self.fail_update:
            raise RuntimeError("telemetry update unavailable")


class FakeContext:
    def __init__(self, observation: FakeObservation, *, fail_exit: bool = False) -> None:
        self.observation = observation
        self.fail_exit = fail_exit
        self.exit_args: list[tuple[object, object, object]] = []

    def __enter__(self) -> FakeObservation:
        return self.observation

    def __exit__(self, *args: object) -> None:
        self.exit_args.append((args[0], args[1], args[2]))
        if self.fail_exit:
            raise RuntimeError("telemetry exit unavailable")


class FakeLangfuseClient:
    def __init__(self, *, fail_start: bool = False, fail_update: bool = False) -> None:
        self.fail_start = fail_start
        self.observation = FakeObservation(fail_update=fail_update)
        self.context = FakeContext(self.observation, fail_exit=fail_update)
        self.starts: list[dict[str, Any]] = []
        self.flushed = False
        self.stopped = False

    def start_as_current_observation(self, **kwargs: Any) -> FakeContext:
        self.starts.append(kwargs)
        if self.fail_start:
            raise RuntimeError("telemetry start unavailable")
        return self.context

    def flush(self) -> None:
        self.flushed = True

    def shutdown(self) -> None:
        self.stopped = True


def test_langfuse_is_disabled_by_default_and_with_incomplete_credentials() -> None:
    default = Settings(_env_file=None)
    incomplete = Settings(
        _env_file=None,
        LANGFUSE_TRACING_ENABLED=True,
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_BASE_URL="https://cloud.langfuse.com",
    )

    assert default.langfuse_ready is False
    assert incomplete.langfuse_ready is False
    assert isinstance(build_trace_client(default), NullTraceClient)
    assert isinstance(build_trace_client(incomplete), NullTraceClient)


def test_langfuse_requires_explicit_io_capture_off() -> None:
    assert Settings(_env_file=None, LANGFUSE_CAPTURE_IO="false").langfuse_capture_io is False
    with pytest.raises(ValidationError):
        Settings(_env_file=None, LANGFUSE_CAPTURE_IO=True)


def test_metadata_and_model_labels_use_fixed_allowlists() -> None:
    metadata = sanitize_metadata(
        {
            "stage": "answer",
            "operation_type": "generation",
            "outcome": "success",
            "duration_ms": 12,
            "selected_block_count": 3,
            "citation_count": 1,
            "available": True,
            "question": "What is Jane Doe's licence number?",
            "answer": "DL-SECRET-123",
            "document_id": "private-document-id",
            "exception": "provider leaked a secret",
            "failure_category": "arbitrary_exception_text",
        }
    )

    assert metadata == {
        "stage": "answer",
        "operation_type": "generation",
        "outcome": "success",
        "duration_ms": 12,
        "selected_block_count": 3,
        "citation_count": 1,
        "available": True,
    }
    assert safe_model_name("gpt-4.1-mini") == "gpt-4.1-mini"
    assert safe_model_name("secret model name from document") == "unavailable"


def test_secret_bearing_provider_exception_is_never_sent_to_langfuse() -> None:
    fake = FakeLangfuseClient()
    tracer = LangfuseTraceClient(fake)

    with pytest.raises(RuntimeError, match="LICENCE-SECRET-9988"):
        tracer.run(
            stage=TraceStage.ANSWER,
            observation_type=ObservationType.GENERATION,
            model="gpt-4.1-mini",
            metadata={"question": "secret question"},
            operation=lambda: _raise_secret_exception(),
        )

    exported = repr((fake.starts, fake.observation.updates, fake.context.exit_args))
    assert "LICENCE-SECRET-9988" not in exported
    assert "secret question" not in exported
    assert fake.context.exit_args == [(None, None, None)]
    assert fake.observation.updates[0]["metadata"]["failure_category"] == "provider_error"
    assert fake.observation.updates[0]["input"] is None
    assert fake.observation.updates[0]["output"] is None


def test_telemetry_failures_do_not_block_provider_work() -> None:
    calls = 0

    def provider_call() -> str:
        nonlocal calls
        calls += 1
        return "provider-result"

    for fake in (
        FakeLangfuseClient(fail_start=True),
        FakeLangfuseClient(fail_update=True),
    ):
        tracer = LangfuseTraceClient(fake)
        assert (
            tracer.run(
                stage=TraceStage.OCR,
                observation_type=ObservationType.GENERATION,
                model="gpt-4.1-mini",
                operation=provider_call,
                success_metadata=lambda _: {"raw_output": "must be dropped"},
            )
            == "provider-result"
        )
        tracer.flush()
        tracer.shutdown()

    assert calls == 2


def test_question_turn_span_omits_model_and_private_io() -> None:
    fake = FakeLangfuseClient()
    tracer = LangfuseTraceClient(fake)

    result = tracer.run(
        stage=TraceStage.QUESTION,
        observation_type=ObservationType.SPAN,
        model=None,
        metadata={"document_id": "private-document-id"},
        operation=lambda: "safe-result",
        success_metadata=lambda _: {"available": True, "citation_count": 2},
    )

    assert result == "safe-result"
    started = fake.starts[0]
    assert started["name"] == "licenceiq.question"
    assert started["as_type"] == "span"
    assert "model" not in started
    assert started["input"] is None
    assert started["output"] is None
    assert started["metadata"] == {"stage": "question", "operation_type": "span"}
    assert fake.observation.updates[0]["metadata"] == {
        "stage": "question",
        "operation_type": "span",
        "outcome": "success",
        "duration_ms": fake.observation.updates[0]["metadata"]["duration_ms"],
        "available": True,
        "citation_count": 2,
    }


def _raise_secret_exception() -> str:
    raise RuntimeError("provider failed while processing LICENCE-SECRET-9988")

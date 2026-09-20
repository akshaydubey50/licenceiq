"""Privacy-safe, fail-open observability for LicenceIQ AI provider calls.

The integration deliberately uses manual Langfuse observations. Provider inputs,
outputs, identifiers, and exception messages never cross this boundary.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from enum import StrEnum
from time import perf_counter
from typing import Any, Protocol, TypeVar

from app.core.config import Settings
from app.providers.answer import AnswerCandidate, AnswerProvider, QuestionContext
from app.providers.embeddings import EmbeddingProvider, EmbeddingRequest, EmbeddingResult
from app.providers.extraction import ExtractionCandidate, ExtractionContext, LLMProvider
from app.providers.ocr import OCRProvider, OCRResult
from app.providers.query_rewrite import (
    QueryRewriteProvider,
    QueryRewriteRequest,
    QueryRewriteResult,
)

SafeMetadataValue = str | int | float | bool
T = TypeVar("T")


class TraceStage(StrEnum):
    """Fixed operation names that cannot contain document or user data."""

    OCR = "ocr"
    EXTRACT = "extract"
    EMBED = "embed"
    QUERY_REWRITE = "query_rewrite"
    ANSWER = "answer"


class ObservationType(StrEnum):
    """Langfuse observation types used by the provider boundary."""

    GENERATION = "generation"
    EMBEDDING = "embedding"


class TraceClient(Protocol):
    """Run provider work inside a trace without exposing its arguments or result."""

    def run(
        self,
        *,
        stage: TraceStage,
        observation_type: ObservationType,
        model: str,
        operation: Callable[[], T],
        metadata: Mapping[str, object] | None = None,
        success_metadata: Callable[[T], Mapping[str, object]] | None = None,
    ) -> T: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


class NullTraceClient:
    """Execute provider work unchanged when observability is disabled."""

    def run(
        self,
        *,
        stage: TraceStage,
        observation_type: ObservationType,
        model: str,
        operation: Callable[[], T],
        metadata: Mapping[str, object] | None = None,
        success_metadata: Callable[[T], Mapping[str, object]] | None = None,
    ) -> T:
        del stage, observation_type, model, metadata, success_metadata
        return operation()

    def flush(self) -> None:
        """No-op for lifecycle symmetry."""

    def shutdown(self) -> None:
        """No-op for lifecycle symmetry."""


_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
_STRING_VALUES: dict[str, frozenset[str]] = {
    "stage": frozenset(stage.value for stage in TraceStage),
    "operation_type": frozenset(item.value for item in ObservationType),
    "outcome": frozenset({"success", "failure"}),
    "failure_category": frozenset({"provider_error"}),
}
_COUNT_KEYS = frozenset(
    {
        "selected_block_count",
        "citation_count",
        "input_token_count",
        "output_token_count",
        "total_token_count",
        "duration_ms",
    }
)
_BOOLEAN_KEYS = frozenset({"available", "cache_hit", "fallback_used"})


def safe_model_name(value: str) -> str:
    """Return a bounded model label or a fixed replacement for unsafe text."""
    normalized = value.strip()
    return normalized if _MODEL_PATTERN.fullmatch(normalized) else "unavailable"


def sanitize_metadata(metadata: Mapping[str, object]) -> dict[str, SafeMetadataValue]:
    """Keep only fixed, typed fields approved for external telemetry."""
    sanitized: dict[str, SafeMetadataValue] = {}
    for key, value in metadata.items():
        allowed_strings = _STRING_VALUES.get(key)
        if allowed_strings is not None:
            if isinstance(value, str) and value in allowed_strings:
                sanitized[key] = value
            continue
        if key in _COUNT_KEYS:
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100_000_000:
                sanitized[key] = value
            continue
        if key in _BOOLEAN_KEYS and isinstance(value, bool):
            sanitized[key] = value
    return sanitized


class LangfuseTraceClient:
    """Create manual Langfuse observations with no input or output capture."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def run(
        self,
        *,
        stage: TraceStage,
        observation_type: ObservationType,
        model: str,
        operation: Callable[[], T],
        metadata: Mapping[str, object] | None = None,
        success_metadata: Callable[[T], Mapping[str, object]] | None = None,
    ) -> T:
        started = perf_counter()
        initial = {
            "stage": stage.value,
            "operation_type": observation_type.value,
            **(metadata or {}),
        }
        try:
            context = self._client.start_as_current_observation(
                name=f"licenceiq.{stage.value}",
                as_type=observation_type.value,
                model=safe_model_name(model),
                input=None,
                output=None,
                metadata=sanitize_metadata(initial),
            )
            observation = context.__enter__()
        except Exception:
            return operation()

        try:
            result = operation()
        except BaseException:
            self._safe_update(
                observation,
                {
                    **initial,
                    "outcome": "failure",
                    "failure_category": "provider_error",
                    "duration_ms": _duration_ms(started),
                },
                level="ERROR",
            )
            # Never hand provider exceptions to OpenTelemetry/Langfuse: exception
            # messages or trace locals can contain document content or credentials.
            self._safe_exit(context)
            raise

        completed = {**initial, "outcome": "success", "duration_ms": _duration_ms(started)}
        if success_metadata is not None:
            try:
                completed.update(success_metadata(result))
            except Exception:
                pass
        self._safe_update(observation, completed, level="DEFAULT")
        self._safe_exit(context)
        return result

    @staticmethod
    def _safe_update(observation: Any, metadata: Mapping[str, object], *, level: str) -> None:
        try:
            observation.update(
                input=None,
                output=None,
                metadata=sanitize_metadata(metadata),
                level=level,
            )
        except Exception:
            pass

    @staticmethod
    def _safe_exit(context: Any) -> None:
        try:
            context.__exit__(None, None, None)
        except Exception:
            pass

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception:
            pass

    def shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception:
            pass


def _duration_ms(started: float) -> int:
    return min(max(round((perf_counter() - started) * 1000), 0), 100_000_000)


def build_trace_client(settings: Settings) -> TraceClient:
    """Return Langfuse only for an explicit, complete configuration."""
    if not settings.langfuse_ready:
        return NullTraceClient()
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value().strip(),
            secret_key=settings.langfuse_secret_key.get_secret_value().strip(),
            base_url=settings.langfuse_base_url.strip(),
            environment=settings.environment,
            tracing_enabled=True,
            # Do not adopt third-party OpenTelemetry spans. This keeps future
            # OpenAI/framework instrumentation outside LicenceIQ's export path.
            should_export_span=_is_manual_langfuse_span,
        )
    except Exception:
        return NullTraceClient()
    return LangfuseTraceClient(client)


def _is_manual_langfuse_span(span: Any) -> bool:
    """Export only observations created through this manual Langfuse client."""
    scope = getattr(span, "instrumentation_scope", None)
    return getattr(scope, "name", None) == "langfuse-sdk"


class ObservedOCRProvider:
    """Trace OCR outcome without exporting image bytes or transcribed text."""

    def __init__(self, provider: OCRProvider, tracer: TraceClient, model: str) -> None:
        self._provider = provider
        self._tracer = tracer
        self._model = model

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        return self._tracer.run(
            stage=TraceStage.OCR,
            observation_type=ObservationType.GENERATION,
            model=self._model,
            operation=lambda: self._provider.extract(
                image_bytes,
                mime_type,
                timeout_seconds=timeout_seconds,
            ),
        )


class ObservedExtractionProvider:
    """Trace structured extraction without exporting reading or field values."""

    def __init__(self, provider: LLMProvider, tracer: TraceClient, model: str) -> None:
        self._provider = provider
        self._tracer = tracer
        self._model = model

    def extract_structured_data(
        self,
        context: ExtractionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> ExtractionCandidate:
        return self._tracer.run(
            stage=TraceStage.EXTRACT,
            observation_type=ObservationType.GENERATION,
            model=self._model,
            operation=lambda: self._provider.extract_structured_data(
                context,
                timeout_seconds=timeout_seconds,
            ),
        )


class ObservedEmbeddingProvider:
    """Trace embedding outcome without exporting source or query text."""

    def __init__(self, provider: EmbeddingProvider, tracer: TraceClient, model: str) -> None:
        self._provider = provider
        self._tracer = tracer
        self._model = model

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        return self._tracer.run(
            stage=TraceStage.EMBED,
            observation_type=ObservationType.EMBEDDING,
            model=self._model,
            operation=lambda: self._provider.embed(request, timeout_seconds=timeout_seconds),
        )


class ObservedQueryRewriteProvider:
    """Trace query rewriting without exporting current or previous questions."""

    def __init__(self, provider: QueryRewriteProvider, tracer: TraceClient, model: str) -> None:
        self._provider = provider
        self._tracer = tracer
        self._model = model

    def rewrite(
        self,
        request: QueryRewriteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryRewriteResult:
        return self._tracer.run(
            stage=TraceStage.QUERY_REWRITE,
            observation_type=ObservationType.GENERATION,
            model=self._model,
            operation=lambda: self._provider.rewrite(request, timeout_seconds=timeout_seconds),
        )


class ObservedAnswerProvider:
    """Trace grounded answers using counts and booleans only."""

    def __init__(self, provider: AnswerProvider, tracer: TraceClient, model: str) -> None:
        self._provider = provider
        self._tracer = tracer
        self._model = model

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate:
        return self._tracer.run(
            stage=TraceStage.ANSWER,
            observation_type=ObservationType.GENERATION,
            model=self._model,
            metadata={"selected_block_count": len(context.blocks)},
            operation=lambda: self._provider.answer_question(
                context,
                timeout_seconds=timeout_seconds,
            ),
            success_metadata=lambda result: {
                "available": result.status == "ANSWERED",
                "citation_count": len(result.block_ids),
            },
        )

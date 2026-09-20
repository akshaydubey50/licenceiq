"""Offline checks for the real-service fictional evaluation adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.providers.answer import AnswerCandidate, QuestionContext
from app.providers.embeddings import EmbeddingRequest, EmbeddingResult
from app.providers.extraction import (
    ExtractionCandidate,
    ExtractionContext,
    FieldCandidate,
)
from app.providers.ocr import OCRResult
from app.providers.query_rewrite import QueryIntent, QueryRewriteRequest, QueryRewriteResult
from app.schemas.common import ErrorCode
from app.services.question_guardrails import DisabledQuestionGuardrail
from scripts.fictional_eval_pipeline import FictionalPipeline


def _missing() -> FieldCandidate:
    return FieldCandidate(value=None, raw_value=None, block_ids=())


class StaticOCR:
    def __init__(self) -> None:
        self.calls = 0

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        del image_bytes, timeout_seconds
        assert mime_type == "image/png"
        self.calls += 1
        return OCRResult(
            lines=(
                "Name: PRIYA SHARMA",
                "DL No: MH12 20190001234",
                "Restriction: Corrective lenses required",
                "Address: Pune 411052",
            )
        )


class StaticExtraction:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[ExtractionContext] = []

    def extract_structured_data(
        self,
        context: ExtractionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> ExtractionCandidate:
        del timeout_seconds
        self.calls += 1
        self.contexts.append(context)
        by_text = {block.text: block.block_id for page in context.pages for block in page.blocks}
        return ExtractionCandidate(
            full_name=FieldCandidate(
                value="PRIYA SHARMA",
                raw_value="PRIYA SHARMA",
                block_ids=(by_text["Name: PRIYA SHARMA"],),
            ),
            licence_number=FieldCandidate(
                value="MH12 20190001234",
                raw_value="MH12 20190001234",
                block_ids=(by_text["DL No: MH12 20190001234"],),
            ),
            date_of_birth=_missing(),
            date_of_issue=_missing(),
            date_of_expiry=_missing(),
            address=_missing(),
            issuing_authority=_missing(),
            vehicle_classes=(),
            other_information=(),
            multiple_licences_detected=False,
        )


class StaticEmbeddings:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.requests: list[EmbeddingRequest] = []

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        del timeout_seconds
        self.requests.append(request)
        dimensions = self.settings.question_embedding_dimensions
        return EmbeddingResult(
            model=self.settings.question_embedding_model,
            dimensions=dimensions,
            vectors=tuple((1.0,) + (0.0,) * (dimensions - 1) for _ in request.texts),
        )


class StaticAnswer:
    def __init__(self) -> None:
        self.contexts: list[QuestionContext] = []

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate:
        del timeout_seconds
        self.contexts.append(context)
        block = next(item for item in context.blocks if "Corrective lenses" in item.text)
        return AnswerCandidate(
            status="ANSWERED",
            answer="Corrective lenses required",
            block_ids=(block.block_id,),
        )


class RecordingRewrite:
    def __init__(self) -> None:
        self.requests: list[QueryRewriteRequest] = []

    def rewrite(
        self,
        request: QueryRewriteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryRewriteResult:
        del timeout_seconds
        self.requests.append(request)
        return QueryRewriteResult(query="restriction", intent=QueryIntent.FOLLOW_UP)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        document_storage_backend="filesystem",
        document_metadata_backend="object_store",
        document_storage_dir=tmp_path / "ignored-by-adapter",
        question_embedding_dimensions=4,
        OPENAI_API_KEY="offline-provider-key",
        LANGFUSE_TRACING_ENABLED=True,
        question_model="preserved-question-model",
        question_guardrails_enabled=False,
    )


def _pipeline_parts(
    tmp_path: Path,
) -> tuple[
    Settings,
    StaticOCR,
    StaticExtraction,
    StaticAnswer,
    StaticEmbeddings,
    RecordingRewrite,
]:
    settings = _settings(tmp_path)
    return (
        settings,
        StaticOCR(),
        StaticExtraction(),
        StaticAnswer(),
        StaticEmbeddings(settings),
        RecordingRewrite(),
    )


def test_captures_actual_direct_and_retrieval_paths_and_caches_preparation(
    tmp_path: Path,
) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    with FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        direct = pipeline.run_case(
            "direct",
            {
                "sample": "fictional_maharashtra_licence",
                "question": "What is the licence number?",
                "prior_questions": [],
            },
        )
        retrieved = pipeline.run_case(
            "retrieval",
            {
                "sample": "fictional_maharashtra_licence",
                "question": "What restriction applies?",
                "prior_questions": [],
            },
        )

    assert direct == {
        "id": "direct",
        "status": "ANSWERED",
        "answer": "MH12 20190001234",
        "citations": [{"page_number": 1, "text": "DL No: MH12 20190001234"}],
        "retrieved_sources": [],
        "direct_lookup": True,
        "error_code": None,
    }
    assert retrieved["status"] == "ANSWERED"
    assert retrieved["direct_lookup"] is False
    assert retrieved["citations"] == [
        {"page_number": 1, "text": "Restriction: Corrective lenses required"}
    ]
    retrieved_sources = retrieved["retrieved_sources"]
    assert isinstance(retrieved_sources, list)
    assert {
        "page_number": 1,
        "text": "Restriction: Corrective lenses required",
    } in retrieved_sources
    assert ocr.calls == 1
    assert extraction.calls == 1


def test_history_comes_only_from_prior_questions_and_gold_data_is_not_forwarded(
    tmp_path: Path,
) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    secret_gold = "DO NOT FORWARD GOLD ANSWER"
    with FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        result = pipeline.run_case(
            "history",
            {
                "sample": "fictional_maharashtra_licence",
                "question": "What restriction applies there?",
                "prior_questions": ["What restrictions are printed?"],
                "expected_output": {"answer": secret_gold},
                "runtime_document_id": secret_gold,
            },
        )

    assert result["status"] == "ANSWERED"
    assert len(rewrite.requests) == 1
    assert rewrite.requests[0].question == "What restriction applies there?"
    assert rewrite.requests[0].previous_questions == ("What restrictions are printed?",)
    forwarded = repr(rewrite.requests + answer.contexts + extraction.contexts)
    assert secret_gold not in forwarded


def test_rejects_arbitrary_sample_paths_without_provider_work(tmp_path: Path) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    with FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        result = pipeline.run_case(
            "bad-sample",
            {
                "sample": "../private-real-licence.png",
                "question": "What is the licence number?",
                "prior_questions": [],
            },
        )

    assert result == {
        "id": "bad-sample",
        "status": "ERROR",
        "answer": "Evaluation case could not be completed.",
        "citations": [],
        "retrieved_sources": [],
        "direct_lookup": False,
        "error_code": "INVALID_REQUEST",
    }
    assert ocr.calls == 0
    assert extraction.calls == 0


class FailingOCR(StaticOCR):
    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        del image_bytes, mime_type, timeout_seconds
        self.calls += 1
        raise ApplicationError(
            ErrorCode.OCR_PROVIDER_ERROR,
            "sensitive provider detail and fictional content",
            502,
        )


def test_caches_preparation_errors_and_sanitizes_the_result(tmp_path: Path) -> None:
    settings, _ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    failing = FailingOCR()
    with FictionalPipeline(
        settings,
        ocr_provider=failing,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        first = pipeline.run_case(
            "failure-one",
            {
                "sample": "fictional_delhi_licence",
                "question": "What is the licence number?",
                "prior_questions": [],
            },
        )
        second = pipeline.run_case(
            "failure-two",
            {
                "sample": "fictional_delhi_licence",
                "question": "Who is the licence holder?",
                "prior_questions": [],
            },
        )

    assert first["error_code"] == second["error_code"] == "OCR_PROVIDER_ERROR"
    assert first["answer"] == second["answer"] == "Evaluation case could not be completed."
    assert "sensitive" not in repr((first, second))
    assert failing.calls == 1
    assert extraction.calls == 0


def test_context_removes_temporary_evaluation_storage(tmp_path: Path) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    with FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        storage_dir = pipeline.settings.document_storage_dir
        assert pipeline.settings.environment == "test"
        assert pipeline.settings.auth_mode == "capability"
        assert pipeline.settings.document_storage_backend == "filesystem"
        assert pipeline.settings.document_metadata_backend == "object_store"
        assert pipeline.settings.langfuse_tracing_enabled is False
        assert pipeline.settings.openai_api_key.get_secret_value() == "offline-provider-key"
        assert pipeline.settings.question_model == "preserved-question-model"
        assert pipeline.settings.question_guardrails_enabled is False
        assert storage_dir.exists()

    assert not storage_dir.parent.exists()


def test_unknown_failures_use_fixed_evaluation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    with FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    ) as pipeline:
        prepared = pipeline.run_case(
            "prepare",
            {
                "sample": "fictional_maharashtra_licence",
                "question": "What is the licence number?",
                "prior_questions": [],
            },
        )
        service = pipeline._required_question_service()

        def explode(*args: object, **kwargs: object) -> Any:
            del args, kwargs
            raise RuntimeError("private traceback detail")

        monkeypatch.setattr(service, "ask", explode)
        result = pipeline.run_case(
            "unexpected",
            {
                "sample": "fictional_maharashtra_licence",
                "question": "What restriction applies?",
                "prior_questions": [],
            },
        )

    assert prepared["status"] == "ANSWERED"
    assert result["status"] == "ERROR"
    assert result["error_code"] == "EVALUATION_ERROR"
    assert "private traceback detail" not in repr(result)


def test_enter_failure_cleans_temporary_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, ocr, extraction, answer, embeddings, rewrite = _pipeline_parts(tmp_path)
    pipeline = FictionalPipeline(
        settings,
        ocr_provider=ocr,
        llm_provider=extraction,
        answer_provider=answer,
        embedding_provider=embeddings,
        query_rewrite_provider=rewrite,
        question_guardrail=DisabledQuestionGuardrail(),
    )
    temporary_root = pipeline.settings.document_storage_dir.parent

    def fail_initialize(self: object) -> None:
        del self
        raise OSError("synthetic setup failure")

    monkeypatch.setattr(
        "scripts.fictional_eval_pipeline.FilesystemDocumentRepository.initialize",
        fail_initialize,
    )
    with pytest.raises(OSError, match="synthetic setup failure"):
        pipeline.__enter__()

    assert not temporary_root.exists()

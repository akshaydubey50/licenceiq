"""Run reviewed fictional evaluation cases through the real LicenceIQ services."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType

from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.config import PROJECT_ROOT, Settings
from app.core.errors import ApplicationError
from app.models.document import (
    Evidence,
    ExtractedField,
    QuestionHistoryEntry,
    QuestionRequest,
    QuestionResult,
    ReadingResult,
    SemanticIndex,
)
from app.providers.answer import AnswerProvider, QuestionBlock
from app.providers.embeddings import EmbeddingProvider
from app.providers.extraction import LLMProvider
from app.providers.ocr import OCRProvider
from app.providers.openai_answer import OpenAIAnswerProvider
from app.providers.openai_embeddings import OpenAIEmbeddingProvider
from app.providers.openai_extraction import OpenAIExtractionProvider
from app.providers.openai_ocr import OpenAIOCRProvider
from app.providers.openai_query_rewrite import OpenAIQueryRewriteProvider
from app.providers.query_rewrite import QueryRewriteProvider
from app.repositories.documents import FilesystemDocumentRepository
from app.schemas.common import ErrorCode
from app.services.documents import DocumentService
from app.services.extraction import ExtractionService
from app.services.question_guardrails import QuestionGuardrail, build_question_guardrail
from app.services.questions import QuestionService
from app.services.reading import ReadingService

_SAFE_ERROR_ANSWER = "Evaluation case could not be completed."
_SAMPLE_PATHS = {
    "fictional_maharashtra_licence": PROJECT_ROOT / "samples" / "fictional_maharashtra_licence.png",
    "fictional_delhi_licence": PROJECT_ROOT / "samples" / "fictional_delhi_licence.png",
}
_SAMPLE_SHA256 = {
    "fictional_maharashtra_licence": (
        "2235821d1adc61a59ff2764eb025d440c650a8b122f09f93797f49047347fd99"
    ),
    "fictional_delhi_licence": ("1e30a638ca16c504a2844cdaea81f2bf23eeca6b6bd73763f7775e1039381833"),
}


@dataclass(frozen=True, slots=True)
class _PreparedSample:
    document_id: str
    authorization: str
    reading: ReadingResult


@dataclass(frozen=True, slots=True)
class _PreparedFailure:
    error_code: str


class _EvaluationQuestionService(QuestionService):
    """Observe the existing direct and retrieval seams without changing their behavior."""

    direct_lookup: bool = False
    retrieved_blocks: tuple[QuestionBlock, ...] = ()

    def reset_capture(self) -> None:
        self.direct_lookup = False
        self.retrieved_blocks = ()

    def _direct_result(
        self,
        document_id: str,
        question: str,
        reading: ReadingResult,
        fields: tuple[ExtractedField, ...],
    ) -> QuestionResult:
        self.direct_lookup = True
        return super()._direct_result(document_id, question, reading, fields)

    def _retrieve(
        self,
        retrieval_query: str,
        reading: ReadingResult,
        semantic_index: SemanticIndex | None,
        deadline: float,
    ) -> tuple[QuestionBlock, ...]:
        selected = super()._retrieve(
            retrieval_query,
            reading,
            semantic_index,
            deadline,
        )
        self.retrieved_blocks = selected
        return selected


class FictionalPipeline:
    """Isolated context-managed adapter for the two reviewed fictional samples."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        ocr_provider: OCRProvider | None = None,
        llm_provider: LLMProvider | None = None,
        answer_provider: AnswerProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        query_rewrite_provider: QueryRewriteProvider | None = None,
        question_guardrail: QuestionGuardrail | None = None,
    ) -> None:
        base = settings if settings is not None else Settings()
        self._temporary = TemporaryDirectory(prefix="licenceiq-fictional-eval-")
        values = base.model_dump()
        values.update(
            environment="test",
            auth_mode="capability",
            self_registration_enabled=False,
            document_storage_backend="filesystem",
            document_metadata_backend="object_store",
            document_storage_dir=Path(self._temporary.name) / "documents",
            langfuse_tracing_enabled=False,
        )
        self.settings = Settings.model_validate(values)

        self._provided_ocr = ocr_provider
        self._provided_extraction = llm_provider
        self._provided_answer = answer_provider
        self._provided_embeddings = embedding_provider
        self._provided_rewrite = query_rewrite_provider
        self._provided_guardrail = question_guardrail
        self._document_service: DocumentService | None = None
        self._reading_service: ReadingService | None = None
        self._extraction_service: ExtractionService | None = None
        self._question_service: _EvaluationQuestionService | None = None
        self._prepared: dict[str, _PreparedSample | _PreparedFailure] = {}
        self._entered = False
        self._closed = False

    def __enter__(self) -> FictionalPipeline:
        if self._entered or self._closed:
            raise RuntimeError("FictionalPipeline contexts cannot be reused.")
        try:
            repository = FilesystemDocumentRepository(self.settings.document_storage_dir)
            repository.initialize()
            document_service = DocumentService(self.settings, repository)
            reading_service = ReadingService(
                self.settings,
                repository,
                document_service,
                self._provided_ocr
                if self._provided_ocr is not None
                else OpenAIOCRProvider(self.settings),
            )
            extraction_service = ExtractionService(
                self.settings,
                repository,
                document_service,
                self._provided_extraction
                if self._provided_extraction is not None
                else OpenAIExtractionProvider(self.settings),
            )
            question_service = _EvaluationQuestionService(
                self.settings,
                repository,
                document_service,
                self._provided_answer
                if self._provided_answer is not None
                else OpenAIAnswerProvider(self.settings),
                self._provided_embeddings
                if self._provided_embeddings is not None
                else OpenAIEmbeddingProvider(self.settings),
                self._provided_rewrite
                if self._provided_rewrite is not None
                else OpenAIQueryRewriteProvider(self.settings),
                self._provided_guardrail
                if self._provided_guardrail is not None
                else build_question_guardrail(self.settings),
                None,
            )
            question_service.reset_capture()
            self._document_service = document_service
            self._reading_service = reading_service
            self._extraction_service = extraction_service
            self._question_service = question_service
            self._entered = True
            return self
        except Exception:
            self.close()
            raise

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.close()

    def close(self) -> None:
        """Remove all temporary document bytes and metadata for this evaluation run."""
        if not self._closed:
            self._prepared.clear()
            self._document_service = None
            self._reading_service = None
            self._extraction_service = None
            self._question_service = None
            self._temporary.cleanup()
            self._closed = True
            self._entered = False

    def run_case(self, case_id: str, input: Mapping[str, object]) -> dict[str, object]:
        """Run one reviewed case and return a source-resolved, identifier-free envelope."""
        try:
            self._require_active()
            sample, request = self._parse_input(input)
            prepared = self._prepared.get(sample)
            if prepared is None:
                try:
                    prepared = self._prepare_sample(sample)
                except ApplicationError as exc:
                    prepared = _PreparedFailure(exc.code.value)
                except Exception:
                    prepared = _PreparedFailure("EVALUATION_ERROR")
                self._prepared[sample] = prepared
            if isinstance(prepared, _PreparedFailure):
                return self._error_result(case_id, prepared.error_code)

            question_service = self._required_question_service()
            question_service.reset_capture()
            result = question_service.ask(
                prepared.document_id,
                prepared.authorization,
                request,
            )
            citations = self._resolve_citations(prepared.reading, result)
            retrieved = self._resolve_retrieved(
                prepared.reading,
                question_service.retrieved_blocks,
            )
            return {
                "id": case_id,
                "status": result.status.value,
                "answer": result.answer,
                "citations": citations,
                "retrieved_sources": retrieved,
                "direct_lookup": question_service.direct_lookup,
                "error_code": None,
            }
        except ApplicationError as exc:
            return self._error_result(case_id, exc.code.value)
        except Exception:
            return self._error_result(case_id, "EVALUATION_ERROR")

    def _prepare_sample(self, sample: str) -> _PreparedSample:
        path = _SAMPLE_PATHS[sample]
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != _SAMPLE_SHA256[sample]:
            raise ApplicationError(ErrorCode.INVALID_FILE, "The fictional sample is invalid.", 400)
        upload = UploadFile(
            file=BytesIO(content),
            filename=path.name,
            headers=Headers({"content-type": "image/png"}),
        )
        try:
            uploaded = asyncio.run(self._required_document_service().upload(upload))
        finally:
            asyncio.run(upload.close())
        if uploaded.access_token is None:
            raise RuntimeError("Capability upload did not return a token.")
        authorization = f"Bearer {uploaded.access_token}"
        reading = self._required_reading_service().read(uploaded.document_id, authorization)
        self._required_extraction_service().extract(uploaded.document_id, authorization)
        return _PreparedSample(uploaded.document_id, authorization, reading)

    @staticmethod
    def _parse_input(input: Mapping[str, object]) -> tuple[str, QuestionRequest]:
        sample = input.get("sample")
        question = input.get("question")
        prior_questions = input.get("prior_questions", [])
        if (
            not isinstance(sample, str)
            or sample not in _SAMPLE_PATHS
            or not isinstance(question, str)
        ):
            raise ApplicationError(ErrorCode.INVALID_REQUEST, "Invalid evaluation input.", 400)
        if not isinstance(prior_questions, (list, tuple)) or not all(
            isinstance(item, str) for item in prior_questions
        ):
            raise ApplicationError(ErrorCode.INVALID_REQUEST, "Invalid evaluation input.", 400)
        try:
            request = QuestionRequest(
                question=question,
                history=tuple(QuestionHistoryEntry(question=item) for item in prior_questions),
            )
        except (TypeError, ValueError):
            raise ApplicationError(
                ErrorCode.INVALID_REQUEST,
                "Invalid evaluation input.",
                400,
            ) from None
        return sample, request

    @staticmethod
    def _reading_index(reading: ReadingResult) -> dict[str, Evidence]:
        return {
            block.block_id: block
            for page in reading.pages
            for block in page.blocks
            if block.block_id is not None
        }

    @classmethod
    def _resolve_citations(
        cls,
        reading: ReadingResult,
        result: QuestionResult,
    ) -> list[dict[str, object]]:
        evidence_by_id = cls._reading_index(reading)
        resolved: list[dict[str, object]] = []
        for citation in result.citations:
            evidence = evidence_by_id.get(citation.block_id)
            if evidence is None:
                raise RuntimeError("Question citation does not resolve to saved evidence.")
            page_number = evidence.page_number
            source_text = evidence.source_text
            if page_number != citation.page_number:
                raise RuntimeError("Question citation page does not match saved evidence.")
            resolved.append({"page_number": page_number, "text": source_text})
        return resolved

    @classmethod
    def _resolve_retrieved(
        cls,
        reading: ReadingResult,
        blocks: tuple[QuestionBlock, ...],
    ) -> list[dict[str, object]]:
        evidence_by_id = cls._reading_index(reading)
        resolved: list[dict[str, object]] = []
        for block in blocks:
            evidence = evidence_by_id.get(block.block_id)
            if evidence is None:
                raise RuntimeError("Retrieved block does not resolve to saved evidence.")
            page_number = evidence.page_number
            source_text = evidence.source_text
            if page_number != block.page_number or source_text != block.text:
                raise RuntimeError("Retrieved block does not match saved evidence.")
            resolved.append({"page_number": page_number, "text": source_text})
        return resolved

    @staticmethod
    def _error_result(case_id: str, error_code: str) -> dict[str, object]:
        return {
            "id": case_id,
            "status": "ERROR",
            "answer": _SAFE_ERROR_ANSWER,
            "citations": [],
            "retrieved_sources": [],
            "direct_lookup": False,
            "error_code": error_code,
        }

    def _require_active(self) -> None:
        if not self._entered or self._closed:
            raise RuntimeError("FictionalPipeline must be used as an active context manager.")

    def _required_document_service(self) -> DocumentService:
        if self._document_service is None:
            raise RuntimeError("FictionalPipeline is not active.")
        return self._document_service

    def _required_reading_service(self) -> ReadingService:
        if self._reading_service is None:
            raise RuntimeError("FictionalPipeline is not active.")
        return self._reading_service

    def _required_extraction_service(self) -> ExtractionService:
        if self._extraction_service is None:
            raise RuntimeError("FictionalPipeline is not active.")
        return self._extraction_service

    def _required_question_service(self) -> _EvaluationQuestionService:
        if self._question_service is None:
            raise RuntimeError("FictionalPipeline is not active.")
        return self._question_service

"""Exercise Phase 5 questions without live provider calls or persisted chat state."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from app.models.document import (
    DocumentPage,
    Evidence,
    ExtractedField,
    ExtractedLicence,
    ExtractionResult,
    ExtractionStatus,
    QuestionRequest,
    ReadingResult,
    ReadingStatus,
    ReviewFields,
    ReviewState,
)
from app.providers.answer import AnswerCandidate, QuestionContext
from app.providers.embeddings import EmbeddingRequest, EmbeddingResult
from app.repositories.documents import FilesystemDocumentRepository, StoredDocumentRecord
from app.schemas.common import ErrorCode

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
TOKEN = "phase-five-capability"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}


class StaticAnswerProvider:
    def __init__(self, candidate: AnswerCandidate) -> None:
        self.candidate = candidate
        self.calls = 0
        self.contexts: list[QuestionContext] = []
        self.timeouts: list[float | None] = []

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate:
        self.calls += 1
        self.contexts.append(context)
        self.timeouts.append(timeout_seconds)
        return self.candidate


class RaisingAnswerProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate:
        self.calls += 1
        raise self.error


class BlockingAnswerProvider(StaticAnswerProvider):
    def __init__(self, candidate: AnswerCandidate) -> None:
        super().__init__(candidate)
        self.started = Event()
        self.release = Event()

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate:
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().answer_question(context, timeout_seconds=timeout_seconds)


class FakeEmbeddingProvider:
    """Create deterministic offline vectors while retaining submitted text for assertions."""

    def __init__(self, config: Settings) -> None:
        self.model = config.question_embedding_model
        self.dimensions = config.question_embedding_dimensions
        self.requests: list[EmbeddingRequest] = []
        self.timeouts: list[float | None] = []

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        return EmbeddingResult(
            model=self.model,
            dimensions=self.dimensions,
            vectors=tuple(self._vector(text) for text in request.texts),
        )

    def _vector(self, text: str) -> tuple[float, ...]:
        normalized = text.casefold()
        values = [0.0] * self.dimensions
        categories = (
            ("name", "priya", "holder"),
            ("dl no", "licence number", "license number"),
            ("valid", "expiry", "expire"),
            ("cov", "vehicle", "lmv", "mcwg"),
            ("endorsement", "corrective", "lenses", "vision", "restriction"),
        )
        for index, terms in enumerate(categories):
            if index < self.dimensions and any(term in normalized for term in terms):
                values[index] = 1.0
        if not any(values):
            values[-1] = 1.0
        return tuple(values)


class BlockingEmbeddingProvider(FakeEmbeddingProvider):
    def __init__(self, config: Settings) -> None:
        super().__init__(config)
        self.started = Event()
        self.release = Event()

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().embed(request, timeout_seconds=timeout_seconds)


class MalformedEmbeddingProvider:
    def __init__(self, result: EmbeddingResult) -> None:
        self.result = result
        self.calls = 0

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        self.calls += 1
        return self.result


def answered(*block_ids: str) -> AnswerCandidate:
    return AnswerCandidate(
        status="ANSWERED",
        answer="Corrective lenses are required.",
        block_ids=block_ids,
    )


def unavailable() -> AnswerCandidate:
    return AnswerCandidate(
        status="UNAVAILABLE",
        answer="I couldn't find that in this document.",
        block_ids=(),
    )


def evidence(document_id: str, page: int, line: int, text: str) -> Evidence:
    return Evidence(
        document_id=document_id,
        page_number=page,
        source_text=text,
        block_id=f"page-{page}-line-{line}",
    )


def source_field(item: Evidence, value: str | None = None) -> ExtractedField:
    source_value = item.source_text if value is None else value
    return ExtractedField(value=source_value, raw_value=source_value, evidence=(item,))


def source_results(document_id: str) -> tuple[ReadingResult, ExtractionResult]:
    blocks = (
        evidence(document_id, 1, 1, "Name: PRIYA SHARMA"),
        evidence(document_id, 1, 2, "DL No: MH12 20260001234"),
        evidence(document_id, 1, 3, "Valid Till: 14/06/2041"),
        evidence(document_id, 1, 4, "COV: LMV"),
        evidence(document_id, 1, 5, "COV: MCWG"),
        evidence(document_id, 1, 6, "Endorsement: corrective lenses required"),
    )
    reading = ReadingResult(
        document_id=document_id,
        status=ReadingStatus.READ,
        pages=(
            DocumentPage(
                document_id=document_id,
                page_number=1,
                text="\n".join(item.source_text for item in blocks),
                blocks=blocks,
                method="ocr",
            ),
        ),
        created_at=NOW,
    )
    extraction = ExtractionResult(
        document_id=document_id,
        status=ExtractionStatus.EXTRACTED,
        licence=ExtractedLicence(
            document_id=document_id,
            full_name=source_field(blocks[0], "PRIYA SHARMA"),
            licence_number=source_field(blocks[1], "MH12 20260001234"),
            date_of_expiry=source_field(blocks[2], "14/06/2041"),
            vehicle_classes=(
                source_field(blocks[3], "LMV"),
                source_field(blocks[4], "MCWG"),
            ),
        ),
        created_at=NOW,
    )
    return reading, extraction


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "document_storage_dir": tmp_path / "documents",
    }
    values.update(overrides)
    return Settings(**values)


def make_application(
    tmp_path: Path,
    provider: Any,
    *,
    include_reading: bool = True,
    include_extraction: bool = True,
    now_provider: Any = lambda: NOW,
    embedding_provider: Any | None = None,
    **settings_overrides: Any,
) -> tuple[FastAPI, StoredDocumentRecord]:
    config = settings(tmp_path, **settings_overrides)
    semantic_provider = embedding_provider or FakeEmbeddingProvider(config)
    application = create_app(
        config,
        now_provider=now_provider,
        answer_provider=provider,
        embedding_provider=semantic_provider,
    )
    repository = cast(
        FilesystemDocumentRepository,
        application.state.document_service.repository,
    )
    repository.initialize()
    document_id = str(uuid4())
    reading, extraction = source_results(document_id)
    record = StoredDocumentRecord(
        document_id=document_id,
        filename="fictional-licence.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=config.document_retention_seconds),
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        reading=reading if include_reading else None,
        extraction=extraction if include_extraction else None,
    )
    repository.save(record, b"private")
    return application, record


def post_question(
    client: TestClient,
    document_id: str,
    question: object,
    headers: dict[str, str] | None = None,
) -> Response:
    return cast(
        Response,
        client.post(
            f"/api/documents/{document_id}/questions",
            headers=AUTHORIZATION if headers is None else headers,
            json={"question": question},
        ),
    )


@pytest.mark.parametrize(
    ("question", "answer", "block_ids"),
    [
        ("What is the holder name?", "PRIYA SHARMA", ["page-1-line-1"]),
        ("What is the licence number?", "MH12 20260001234", ["page-1-line-2"]),
        ("What is the expiry date?", "14/06/2041", ["page-1-line-3"]),
        ("Which vehicle classes are listed?", "LMV, MCWG", ["page-1-line-4", "page-1-line-5"]),
    ],
)
def test_direct_source_fields_bypass_provider(
    tmp_path: Path,
    question: str,
    answer: str,
    block_ids: list[str],
) -> None:
    provider = StaticAnswerProvider(unavailable())
    application, record = make_application(tmp_path, provider)
    repository = application.state.document_service.repository
    stored = repository.get(record.document_id)
    assert stored is not None and stored.extraction is not None
    source_extraction = stored.extraction
    stored.review = ReviewState(
        fields=ReviewFields(
            full_name="CORRECTED NAME",
            licence_number="CORRECTED NUMBER",
            date_of_birth=None,
            date_of_issue=None,
            date_of_expiry="01/01/2000",
            address=None,
            vehicle_classes=("BUS",),
            issuing_authority=None,
            other_information={},
        ),
        updated_at=NOW,
    )
    repository._write_metadata_atomic(stored, repository._metadata_path(record.document_id))

    with TestClient(application) as client:
        response = post_question(client, record.document_id, question)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["question"] == question
    assert body["status"] == "ANSWERED"
    assert body["answer"] == answer
    assert [item["block_id"] for item in body["citations"]] == block_ids
    assert provider.calls == 0
    assert application.state.question_service.embedding_provider.requests == []
    assert repository.get(record.document_id).extraction == source_extraction


def test_missing_direct_source_field_abstains_without_provider(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-1"))
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What is the date of birth?")
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["answer"] == "I couldn't find that in this document."
    assert response.json()["citations"] == []
    assert provider.calls == 0
    assert application.state.question_service.embedding_provider.requests == []


def test_broader_answer_uses_only_selected_reading_blocks(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == 200
    assert response.json()["status"] == "ANSWERED"
    assert response.json()["citations"] == [{"block_id": "page-1-line-6", "page_number": 1}]
    assert provider.calls == 1
    selected_ids = [block.block_id for block in provider.contexts[0].blocks]
    assert selected_ids[0] == "page-1-line-6"
    assert set(selected_ids) == {f"page-1-line-{line}" for line in range(1, 7)}
    assert provider.contexts[0].question == "What does the endorsement say?"


def test_semantic_only_question_selects_related_original_block(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "Are there any vision restrictions?")
    assert response.status_code == 200
    assert provider.contexts[0].blocks[0].block_id == "page-1-line-6"


def test_hybrid_scores_and_source_order_break_ties_deterministically(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-4"))
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "LMV restriction details")
    assert response.status_code == 200
    selected_ids = [block.block_id for block in provider.contexts[0].blocks]
    assert selected_ids[:3] == ["page-1-line-4", "page-1-line-5", "page-1-line-6"]


def test_semantic_index_is_reused_and_reloaded(tmp_path: Path) -> None:
    answer_provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, answer_provider)
    embeddings = application.state.question_service.embedding_provider
    with TestClient(application) as client:
        assert post_question(client, record.document_id, "Vision restrictions?").status_code == 200
        assert (
            post_question(client, record.document_id, "Any eyesight restriction?").status_code
            == 200
        )
    assert len(embeddings.requests) == 3
    assert len(embeddings.requests[0].texts) == 6
    assert len(embeddings.requests[1].texts) == len(embeddings.requests[2].texts) == 1

    config = settings(tmp_path)
    reloaded_embeddings = FakeEmbeddingProvider(config)
    reloaded = create_app(
        config,
        now_provider=lambda: NOW,
        answer_provider=StaticAnswerProvider(answered("page-1-line-6")),
        embedding_provider=reloaded_embeddings,
    )
    with TestClient(reloaded) as client:
        assert post_question(client, record.document_id, "Vision restriction?").status_code == 200
    assert len(reloaded_embeddings.requests) == 1
    assert len(reloaded_embeddings.requests[0].texts) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"question_embedding_model": "text-embedding-3-large"},
        {"question_embedding_dimensions": 128},
    ],
)
def test_model_or_dimension_change_invalidates_cached_index(
    tmp_path: Path,
    overrides: dict[str, Any],
) -> None:
    first_app, record = make_application(tmp_path, StaticAnswerProvider(answered("page-1-line-6")))
    with TestClient(first_app) as client:
        assert post_question(client, record.document_id, "Vision restriction?").status_code == 200

    config = settings(tmp_path, **overrides)
    embeddings = FakeEmbeddingProvider(config)
    changed_app = create_app(
        config,
        now_provider=lambda: NOW,
        answer_provider=StaticAnswerProvider(answered("page-1-line-6")),
        embedding_provider=embeddings,
    )
    with TestClient(changed_app) as client:
        assert post_question(client, record.document_id, "Vision restriction?").status_code == 200
    assert [len(request.texts) for request in embeddings.requests] == [6, 1]
    saved = changed_app.state.document_service.repository.get(record.document_id)
    assert saved is not None and saved.semantic_index is not None
    assert saved.semantic_index.model == config.question_embedding_model
    assert saved.semantic_index.dimensions == config.question_embedding_dimensions


def test_reading_change_invalidates_cached_index(tmp_path: Path) -> None:
    answer_provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, answer_provider)
    with TestClient(application) as client:
        assert post_question(client, record.document_id, "Vision restriction?").status_code == 200

    repository = application.state.document_service.repository
    stored = repository.get(record.document_id)
    assert stored is not None and stored.reading is not None
    page = stored.reading.pages[0]
    added = evidence(record.document_id, 1, 7, "Restriction code: VISION")
    stored.reading = stored.reading.model_copy(
        update={
            "pages": (
                page.model_copy(
                    update={
                        "text": f"{page.text}\n{added.source_text}",
                        "blocks": (*page.blocks, added),
                    }
                ),
            )
        }
    )
    repository._write_metadata_atomic(stored, repository._metadata_path(record.document_id))
    embeddings = application.state.question_service.embedding_provider
    before = len(embeddings.requests)
    with TestClient(application) as client:
        assert post_question(client, record.document_id, "Vision restriction?").status_code == 200
    assert [len(request.texts) for request in embeddings.requests[before:]] == [7, 1]


def test_provider_unavailable_has_fixed_answer_and_no_citations(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(unavailable())
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == 200
    assert response.json()["status"] == "UNAVAILABLE"
    assert response.json()["citations"] == []


@pytest.mark.parametrize(
    "candidate",
    [
        AnswerCandidate.model_construct(
            status="ANSWERED",
            answer="Private",
            block_ids=("unknown",),
        ),
        AnswerCandidate.model_construct(
            status="ANSWERED",
            answer="Private",
            block_ids=("page-1-line-6", "page-1-line-6"),
        ),
        AnswerCandidate.model_construct(
            status="ANSWERED",
            answer="Private",
            block_ids=("other-document-page-1-line-6",),
        ),
        AnswerCandidate.model_construct(status="ANSWERED", answer="Private", block_ids=()),
    ],
)
def test_invalid_provider_citations_fail_safely(
    tmp_path: Path,
    candidate: AnswerCandidate,
) -> None:
    application, record = make_application(tmp_path, StaticAnswerProvider(candidate))
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "QUESTION_PROVIDER_ERROR"
    assert "Private" not in response.text


@pytest.mark.parametrize("authorization", [None, "Bearer wrong"])
def test_question_requires_capability(
    tmp_path: Path,
    authorization: str | None,
) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, provider)
    headers = {"Authorization": authorization} if authorization is not None else {}
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What is the name?", headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert provider.calls == 0
    assert application.state.question_service.embedding_provider.requests == []


def test_question_prerequisites_are_ordered(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-6"))
    unread_app, unread = make_application(
        tmp_path / "unread", provider, include_reading=False, include_extraction=False
    )
    unextracted_app, unextracted = make_application(
        tmp_path / "unextracted", provider, include_extraction=False
    )
    with TestClient(unread_app) as client:
        unread_response = post_question(client, unread.document_id, "What is the name?")
    with TestClient(unextracted_app) as client:
        unextracted_response = post_question(client, unextracted.document_id, "What is the name?")
    assert unread_response.status_code == 409
    assert unread_response.json()["error"]["code"] == "READING_REQUIRED"
    assert unextracted_response.status_code == 404
    assert unextracted_response.json()["error"]["code"] == "EXTRACTION_NOT_FOUND"


@pytest.mark.parametrize("question", ["", "   ", "x" * 501, 12, None])
def test_invalid_question_payload_is_controlled(tmp_path: Path, question: object) -> None:
    application, record = make_application(tmp_path, StaticAnswerProvider(unavailable()))
    with TestClient(application) as client:
        response = post_question(client, record.document_id, question)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_QUESTION"


def test_unknown_and_malformed_payload_are_invalid(tmp_path: Path) -> None:
    application, record = make_application(tmp_path, StaticAnswerProvider(unavailable()))
    endpoint = f"/api/documents/{record.document_id}/questions"
    with TestClient(application) as client:
        unknown = client.post(
            endpoint,
            headers=AUTHORIZATION,
            json={"question": "What is the name?", "unknown": True},
        )
        malformed = client.post(
            endpoint,
            headers={**AUTHORIZATION, "Content-Type": "application/json"},
            content=b"{",
        )
    assert unknown.status_code == malformed.status_code == 400
    assert unknown.json()["error"]["code"] == "INVALID_QUESTION"
    assert malformed.json()["error"]["code"] == "INVALID_QUESTION"


@pytest.mark.parametrize(
    ("error", "expected_code", "status_code"),
    [
        (
            ApplicationError(
                ErrorCode.QUESTION_NOT_CONFIGURED,
                "Document questions are not configured.",
                503,
            ),
            "QUESTION_NOT_CONFIGURED",
            503,
        ),
        (
            ApplicationError(ErrorCode.QUESTION_TIMEOUT, "Question timed out.", 504),
            "QUESTION_TIMEOUT",
            504,
        ),
        (RuntimeError("PRIVATE_PROVIDER_DETAIL"), "QUESTION_PROVIDER_ERROR", 502),
    ],
)
def test_provider_errors_are_controlled(
    tmp_path: Path,
    error: Exception,
    expected_code: str,
    status_code: int,
) -> None:
    application, record = make_application(tmp_path, RaisingAnswerProvider(error))
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == expected_code
    assert "PRIVATE_PROVIDER_DETAIL" not in response.text


def test_relevant_oversize_block_fails_before_provider(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(unavailable())
    application, record = make_application(
        tmp_path,
        provider,
        question_max_selected_characters=20,
    )
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUESTION_TOO_LARGE"
    assert provider.calls == 0


def test_duplicate_question_is_suppressed(tmp_path: Path) -> None:
    provider = BlockingAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, provider)
    service = application.state.question_service
    request = QuestionRequest(question="What does the endorsement say?")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.ask, record.document_id, f"Bearer {TOKEN}", request)
        assert provider.started.wait(timeout=2)
        with pytest.raises(ApplicationError) as duplicate:
            service.ask(record.document_id, f"Bearer {TOKEN}", request)
        provider.release.set()
        assert first.result(timeout=2).status == "ANSWERED"
    assert duplicate.value.code == ErrorCode.QUESTION_IN_PROGRESS
    assert provider.calls == 1


@pytest.mark.parametrize("lifecycle", ["delete", "expire"])
def test_late_provider_response_cannot_outlive_document(
    tmp_path: Path,
    lifecycle: str,
) -> None:
    current = NOW
    provider = BlockingAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(
        tmp_path,
        provider,
        now_provider=lambda: current,
        document_retention_seconds=60,
    )
    service = application.state.question_service
    repository = application.state.document_service.repository
    request = QuestionRequest(question="What does the endorsement say?")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.ask, record.document_id, f"Bearer {TOKEN}", request)
        assert provider.started.wait(timeout=2)
        if lifecycle == "delete":
            repository.delete(record)
        else:
            current = NOW + timedelta(minutes=2)
        provider.release.set()
        with pytest.raises(ApplicationError) as error:
            future.result(timeout=2)
    assert error.value.code == ErrorCode.DOCUMENT_NOT_FOUND


def test_question_results_are_not_persisted(tmp_path: Path) -> None:
    provider = StaticAnswerProvider(answered("page-1-line-6"))
    application, record = make_application(tmp_path, provider)
    repository = application.state.document_service.repository
    before = repository.get(record.document_id)
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "What does the endorsement say?")
    assert response.status_code == 200
    after = repository.get(record.document_id)
    assert before is not None and before.semantic_index is None
    assert after is not None and after.semantic_index is not None
    assert after.model_copy(update={"semantic_index": None}) == before


@pytest.mark.parametrize(
    "result",
    [
        EmbeddingResult.model_construct(
            model="text-embedding-3-small",
            dimensions=256,
            vectors=((1.0,) * 256,),
        ),
        EmbeddingResult.model_construct(
            model="text-embedding-3-small",
            dimensions=256,
            vectors=((1.0,) * 255,) * 6,
        ),
        EmbeddingResult.model_construct(
            model="text-embedding-3-small",
            dimensions=256,
            vectors=((float("nan"),) + (1.0,) * 255,) * 6,
        ),
        EmbeddingResult.model_construct(
            model="text-embedding-3-small",
            dimensions=256,
            vectors=((0.0,) * 256,) * 6,
        ),
        EmbeddingResult.model_construct(
            model="wrong-model",
            dimensions=256,
            vectors=((1.0,) * 256,) * 6,
        ),
    ],
)
def test_malformed_embedding_results_fail_without_publishing_partial_index(
    tmp_path: Path,
    result: EmbeddingResult,
) -> None:
    answer_provider = StaticAnswerProvider(answered("page-1-line-6"))
    embeddings = MalformedEmbeddingProvider(result)
    application, record = make_application(
        tmp_path,
        answer_provider,
        embedding_provider=embeddings,
    )
    with TestClient(application) as client:
        response = post_question(client, record.document_id, "Vision restriction?")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "QUESTION_PROVIDER_ERROR"
    assert answer_provider.calls == 0
    saved = application.state.document_service.repository.get(record.document_id)
    assert saved is not None and saved.semantic_index is None


@pytest.mark.parametrize("lifecycle", ["delete", "expire"])
def test_index_build_cannot_publish_after_document_lifecycle_ends(
    tmp_path: Path,
    lifecycle: str,
) -> None:
    current = NOW
    config = settings(tmp_path, document_retention_seconds=60)
    embeddings = BlockingEmbeddingProvider(config)
    application, record = make_application(
        tmp_path,
        StaticAnswerProvider(answered("page-1-line-6")),
        embedding_provider=embeddings,
        now_provider=lambda: current,
        document_retention_seconds=60,
    )
    service = application.state.question_service
    repository = application.state.document_service.repository
    request = QuestionRequest(question="Vision restriction?")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.ask, record.document_id, f"Bearer {TOKEN}", request)
        assert embeddings.started.wait(timeout=2)
        if lifecycle == "delete":
            repository.delete(record)
        else:
            current = NOW + timedelta(minutes=2)
        embeddings.release.set()
        with pytest.raises(ApplicationError) as error:
            future.result(timeout=2)
    assert error.value.code == ErrorCode.DOCUMENT_NOT_FOUND

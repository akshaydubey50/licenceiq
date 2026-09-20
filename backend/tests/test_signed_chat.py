"""Offline authorization and lifecycle checks for signed-user chat continuation."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.documents import router
from app.core.auth import AuthenticationError
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.models.document import (
    DocumentPage,
    Evidence,
    QuestionResult,
    QuestionStatus,
    ReadingResult,
    ReadingStatus,
)
from app.repositories.documents import ChatPersistenceUnavailable, StoredDocumentRecord
from app.schemas.auth import AuthenticatedUser
from app.services.documents import DocumentCredentials, DocumentService
from app.services.reading import ReadingService

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


class StubAuthService:
    """Resolve deterministic bearer subjects without signing real tokens."""

    def authenticate_authorization(self, authorization: str | None) -> AuthenticatedUser:
        if authorization == "Bearer owner-a":
            return AuthenticatedUser(subject="owner-a")
        if authorization == "Bearer owner-b":
            return AuthenticatedUser(subject="owner-b")
        raise AuthenticationError


class DurableRepository:
    """Minimal durable repository substitute for route and ownership tests."""

    def __init__(self, records: tuple[StoredDocumentRecord, ...]) -> None:
        self.records = {record.document_id: record for record in records}
        self.history: dict[str, tuple[QuestionResult, ...]] = {}
        self.list_limit: int | None = None

    def initialize(self) -> None: ...

    def get(self, document_id: str) -> StoredDocumentRecord | None:
        return self.records.get(document_id)

    def cleanup_expired(self, now: datetime) -> int:
        return 0

    def list_owned(
        self, owner_subject: str, now: datetime, *, limit: int
    ) -> tuple[StoredDocumentRecord, ...]:
        self.list_limit = limit
        records = tuple(
            record
            for record in sorted(
                self.records.values(), key=lambda item: item.created_at, reverse=True
            )
            if record.owner_subject == owner_subject and record.expires_at > now
        )
        return records[:limit]

    def get_chat_history(
        self,
        document_id: str,
        owner_subject: str,
        now: datetime,
        *,
        limit: int,
    ) -> tuple[QuestionResult, ...]:
        record = self.records.get(document_id)
        if record is None or record.owner_subject != owner_subject or record.expires_at <= now:
            return ()
        return self.history.get(document_id, ())[-limit:]

    def clear_chat_history(self, document_id: str, owner_subject: str) -> None:
        record = self.records.get(document_id)
        if record is not None and record.owner_subject == owner_subject:
            self.history.pop(document_id, None)

    def save_chat_turn_if_current(
        self,
        snapshot: StoredDocumentRecord,
        result: QuestionResult,
        now: datetime,
    ) -> bool:
        self.history[snapshot.document_id] = (*self.history.get(snapshot.document_id, ()), result)
        return True


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "auth_mode": "hybrid",
        "jwt_signing_key": "x" * 32,
        "bootstrap_username": "owner",
        "bootstrap_subject": "owner-a",
        "bootstrap_password_hash": "$argon2id$v=19$m=65536,t=3,p=4$fixture$fixture",
        "document_storage_backend": "minio",
        "document_metadata_backend": "postgres",
        "database_url": "postgresql+psycopg://test:test@db.invalid/licenceiq",
        "minio_endpoint": "minio.invalid:9000",
        "minio_access_key": "test",
        "minio_secret_key": "test-secret",
        "minio_secure": False,
    }
    values.update(overrides)
    return Settings(**values)


def record(owner: str | None = "owner-a", *, created_at: datetime = NOW) -> StoredDocumentRecord:
    return StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="licence.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=created_at,
        expires_at=NOW + timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        owner_subject=owner,
        access_token_hash=None if owner is not None else "ab" * 32,
    )


def reading(document_id: str) -> ReadingResult:
    block = Evidence(
        document_id=document_id,
        page_number=1,
        source_text="Licence source text",
        block_id="page-1",
    )
    return ReadingResult(
        document_id=document_id,
        status=ReadingStatus.READ,
        pages=(
            DocumentPage(
                document_id=document_id,
                page_number=1,
                text=block.source_text,
                blocks=(block,),
                method="native_text",
            ),
        ),
        created_at=NOW,
    )


def app_for(service: DocumentService) -> FastAPI:
    app = FastAPI()
    app.state.document_service = service
    register_error_handlers(app)
    app.include_router(router)
    return app


def test_list_is_jwt_only_bounded_and_never_includes_guest_documents() -> None:
    owned = tuple(record(created_at=NOW - timedelta(minutes=index)) for index in range(55))
    guest = record(owner=None)
    repository = DurableRepository((*owned, guest))
    service = DocumentService(settings(), repository, lambda: NOW, StubAuthService())  # type: ignore[arg-type]

    with TestClient(app_for(service)) as client:
        anonymous = client.get("/api/documents")
        guest_response = client.get(
            "/api/documents", headers={"X-Document-Capability": "guest-capability"}
        )
        response = client.get("/api/documents", headers={"Authorization": "Bearer owner-a"})

    assert anonymous.status_code == 401
    assert guest_response.status_code == 401
    assert response.status_code == 200
    assert len(response.json()["documents"]) == 50
    assert repository.list_limit == 50
    assert guest.document_id not in {item["document_id"] for item in response.json()["documents"]}


def test_history_access_is_owner_scoped_with_generic_not_found_and_delete() -> None:
    owned = record()
    repository = DurableRepository((owned,))
    service = DocumentService(settings(), repository, lambda: NOW, StubAuthService())  # type: ignore[arg-type]

    with TestClient(app_for(service)) as client:
        cross_owner = client.get(
            f"/api/documents/{owned.document_id}/chat-history",
            headers={"Authorization": "Bearer owner-b"},
        )
        missing = client.get(
            f"/api/documents/{uuid4()}/chat-history",
            headers={"Authorization": "Bearer owner-b"},
        )
        cleared = client.delete(
            f"/api/documents/{owned.document_id}/chat-history",
            headers={"Authorization": "Bearer owner-a"},
        )

    assert cross_owner.status_code == missing.status_code == 404
    assert (
        cross_owner.json()["error"]
        == missing.json()["error"]
        == {
            "code": "DOCUMENT_NOT_FOUND",
            "message": "The document was not found.",
        }
    )
    assert cleared.status_code == 204


def test_non_postgres_profile_returns_controlled_history_unavailable(tmp_path: Any) -> None:
    from app.repositories.documents import FilesystemDocumentRepository

    config = settings().model_copy(
        update={
            "document_storage_backend": "filesystem",
            "document_metadata_backend": "object_store",
            "document_storage_dir": tmp_path / "documents",
        }
    )
    service = DocumentService(
        config,
        FilesystemDocumentRepository(config.document_storage_dir),
        lambda: NOW,
        StubAuthService(),  # type: ignore[arg-type]
    )

    with TestClient(app_for(service)) as client:
        response = client.get("/api/documents", headers={"Authorization": "Bearer owner-a"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_HISTORY_UNAVAILABLE"


def test_postgres_outage_returns_controlled_history_unavailable() -> None:
    class UnavailableRepository(DurableRepository):
        def list_owned(
            self, owner_subject: str, now: datetime, *, limit: int
        ) -> tuple[StoredDocumentRecord, ...]:
            raise ChatPersistenceUnavailable

    service = DocumentService(
        settings(),
        UnavailableRepository(()),
        lambda: NOW,
        StubAuthService(),  # type: ignore[arg-type]
    )

    with TestClient(app_for(service)) as client:
        response = client.get("/api/documents", headers={"Authorization": "Bearer owner-a"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_HISTORY_UNAVAILABLE"


def test_successful_reread_clears_saved_history() -> None:
    owned = record().model_copy(update={"reading": None})
    saved_reading = reading(owned.document_id)
    owned = owned.model_copy(update={"reading": saved_reading})
    repository = DurableRepository((owned,))
    repository.history[owned.document_id] = (
        QuestionResult(
            document_id=owned.document_id,
            question="What is shown?",
            status=QuestionStatus.UNAVAILABLE,
            answer="I couldn't find that in this document.",
            citations=(),
            created_at=NOW,
        ),
    )
    document_service = DocumentService(
        settings(),
        repository,
        lambda: NOW,
        StubAuthService(),  # type: ignore[arg-type]
    )
    reading_service = ReadingService(
        settings(),
        repository,  # type: ignore[arg-type]
        document_service,
        object(),  # type: ignore[arg-type]
        lambda: NOW,
    )

    result = reading_service.read(
        owned.document_id,
        DocumentCredentials(authorization="Bearer owner-a"),
    )

    assert result == saved_reading
    assert repository.history.get(owned.document_id) is None

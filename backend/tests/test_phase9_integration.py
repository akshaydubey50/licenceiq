"""Exercise Phase 9 ownership and MinIO-repository integration without live infrastructure."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pwdlib import PasswordHash
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.main import create_app
from app.repositories.documents import MinioDocumentRepository, StoredDocumentRecord
from app.repositories.object_store import ObjectStoreError


class MemoryObjectStore:
    """Small private-store double that exercises repository ordering and cleanup."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_write = False
        self.fail_delete_keys: set[str] = set()

    def initialize(self) -> None:
        return None

    def generate_key(self) -> str:
        return str(uuid4())

    def put(self, key: str, content: bytes, *, content_type: str) -> None:
        if self.fail_write:
            raise ObjectStoreError("write")
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectStoreError("read") from None

    def delete(self, key: str) -> None:
        if key in self.fail_delete_keys:
            raise ObjectStoreError("delete")
        self.objects.pop(key, None)

    def list_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))


def png_bytes() -> bytes:
    """Build a valid tiny image without an external file fixture."""
    output = BytesIO()
    Image.new("RGB", (8, 6), color=(31, 78, 121)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def jwt_settings(tmp_path: Path) -> Settings:
    """Use an offline-only bootstrap account and temporary filesystem documents."""
    password_hash = PasswordHash.recommended().hash("correct horse battery staple")
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="jwt",
        jwt_signing_key=SecretStr("offline-test-signing-key-that-is-at-least-32-bytes"),
        jwt_issuer="https://licenceiq.test",
        jwt_audience="licenceiq-browser",
        bootstrap_username="candidate",
        bootstrap_password_hash=SecretStr(password_hash),
        bootstrap_subject="candidate-001",
        document_storage_dir=tmp_path / "documents",
    )


@pytest.fixture
def jwt_client(jwt_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(jwt_settings)) as client:
        yield client


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": "candidate", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_jwt_mode_binds_uploaded_document_to_its_token_subject(jwt_client: TestClient) -> None:
    token = _login(jwt_client)
    headers = {"Authorization": f"Bearer {token}"}

    missing = jwt_client.post(
        "/api/documents", files={"file": ("licence.png", png_bytes(), "image/png")}
    )
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    created = jwt_client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("licence.png", png_bytes(), "image/png")},
    )
    assert created.status_code == 201, created.text
    assert created.json()["access_token"] is None
    document_id = str(created.json()["document_id"])

    application = cast(FastAPI, jwt_client.app)
    app_service = application.state.auth_service
    foreign_token = app_service.issue_access_token("different-subject").access_token
    foreign = jwt_client.get(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {foreign_token}"},
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    owned = jwt_client.get(f"/api/documents/{document_id}", headers=headers)
    assert owned.status_code == 200


def test_minio_repository_cleans_content_when_metadata_publish_fails() -> None:
    content_store = MemoryObjectStore()
    metadata_store = MemoryObjectStore()
    metadata_store.fail_write = True
    repository = MinioDocumentRepository(content_store, metadata_store)
    now = datetime.now(UTC)
    record = StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="licence.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        owner_subject="candidate-001",
    )

    with pytest.raises(ObjectStoreError, match="write"):
        repository.save(record, b"content")

    assert content_store.objects == {}
    assert metadata_store.objects == {}


def test_minio_expiry_cleanup_continues_after_one_delete_failure() -> None:
    content_store = MemoryObjectStore()
    metadata_store = MemoryObjectStore()
    repository = MinioDocumentRepository(content_store, metadata_store)
    now = datetime.now(UTC)

    failed_record = StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="failed.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=now - timedelta(hours=2),
        expires_at=now - timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        owner_subject="candidate-001",
    )
    removable_record = failed_record.model_copy(
        update={"document_id": str(uuid4()), "storage_key": str(uuid4())}
    )
    live_record = failed_record.model_copy(
        update={
            "document_id": str(uuid4()),
            "storage_key": str(uuid4()),
            "expires_at": now + timedelta(hours=1),
        }
    )
    for record in (failed_record, removable_record, live_record):
        repository.save(record, b"content")
    content_store.fail_delete_keys.add(failed_record.storage_key)

    assert repository.cleanup_expired(now) == 1
    assert repository.get(failed_record.document_id) == failed_record
    assert repository.get(removable_record.document_id) is None
    assert repository.get(live_record.document_id) == live_record


def test_production_requires_minio_and_jwt_safeguards() -> None:
    with pytest.raises(ValidationError, match="Production requires JWT authentication"):
        Settings(_env_file=None, environment="production", cors_origins=["https://app.example"])

    settings = Settings(
        _env_file=None,
        environment="production",
        cors_origins=["https://app.example"],
        auth_mode="jwt",
        jwt_signing_key=SecretStr("production-signing-key-that-is-at-least-32-bytes"),
        bootstrap_username="candidate",
        bootstrap_password_hash=SecretStr("$argon2id$v=19$m=65536,t=3,p=4$placeholder"),
        bootstrap_subject="candidate-001",
        document_storage_backend="minio",
        document_metadata_backend="postgres",
        database_url=SecretStr(
            "postgresql+psycopg://licenceiq:offline-password@db.example:5432/licenceiq"
        ),
        minio_endpoint="minio.internal:9000",
        minio_access_key=SecretStr("access-key"),
        minio_secret_key=SecretStr("secret-key"),
    )

    assert settings.auth_mode == "jwt"
    assert settings.document_storage_backend == "minio"

    insecure_values = settings.model_dump()
    insecure_values["minio_secure"] = False
    with pytest.raises(ValidationError, match="Production requires secure MinIO transport"):
        Settings(_env_file=None, **insecure_values)

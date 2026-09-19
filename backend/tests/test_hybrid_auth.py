"""Verify strict separation between hybrid guest capabilities and user JWTs."""

import hashlib
from collections.abc import Iterator
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
from app.providers.ocr import OCRResult


class StubOCR:
    """Return deterministic text without an external provider call."""

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        return OCRResult(lines=("Fictional driving licence",))


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), color=(31, 78, 121)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def hybrid_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        auth_mode="hybrid",
        jwt_signing_key=SecretStr("offline-test-signing-key-that-is-at-least-32-bytes"),
        jwt_issuer="https://licenceiq.test",
        jwt_audience="licenceiq-browser",
        bootstrap_username="candidate",
        bootstrap_password_hash=SecretStr(
            PasswordHash.recommended().hash("correct horse battery staple")
        ),
        bootstrap_subject="candidate-001",
        document_storage_dir=tmp_path / "documents",
    )


@pytest.fixture
def hybrid_client(hybrid_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(hybrid_settings, ocr_provider=StubOCR())) as client:
        yield client


def _upload(client: TestClient, headers: dict[str, str] | None = None):
    return client.post(
        "/api/documents",
        headers=headers,
        files={"file": ("licence.png", png_bytes(), "image/png")},
    )


def _login(client: TestClient) -> str:
    response = client.post(
        "/api/auth/login",
        json={"username": "candidate", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def test_hybrid_guest_upload_uses_only_document_capability(
    hybrid_client: TestClient, hybrid_settings: Settings
) -> None:
    created = _upload(hybrid_client)
    assert created.status_code == 201, created.text
    payload = created.json()
    document_id = str(payload["document_id"])
    capability = str(payload["access_token"])
    capability_headers = {"X-Document-Capability": capability}

    assert capability
    stored_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in hybrid_settings.document_storage_dir.glob("*.json")
    )
    assert capability not in stored_text
    assert hashlib.sha256(capability.encode()).hexdigest() in stored_text
    assert hybrid_client.get(f"/api/documents/{document_id}").status_code == 404

    metadata = hybrid_client.get(f"/api/documents/{document_id}", headers=capability_headers)
    assert metadata.status_code == 200
    assert "access_token" not in metadata.json()

    file_response = hybrid_client.get(
        f"/api/documents/{document_id}/file", headers=capability_headers
    )
    assert file_response.status_code == 200
    assert file_response.content == png_bytes()

    reading = hybrid_client.post(f"/api/documents/{document_id}/read", headers=capability_headers)
    assert reading.status_code == 200, reading.text
    assert reading.json()["pages"][0]["text"] == "Fictional driving licence"

    wrong = hybrid_client.get(
        f"/api/documents/{document_id}",
        headers={"X-Document-Capability": "wrong"},
    )
    assert wrong.status_code == 404
    assert wrong.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    bearer_capability = hybrid_client.get(
        f"/api/documents/{document_id}",
        headers={"Authorization": f"Bearer {capability}"},
    )
    assert bearer_capability.status_code == 401
    assert bearer_capability.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_hybrid_authenticated_and_guest_documents_are_isolated(
    hybrid_client: TestClient,
) -> None:
    token = _login(hybrid_client)
    user_headers = {"Authorization": f"Bearer {token}"}
    user_created = _upload(hybrid_client, user_headers)
    guest_created = _upload(hybrid_client)

    assert user_created.status_code == 201
    assert user_created.json()["access_token"] is None
    assert guest_created.status_code == 201
    user_id = str(user_created.json()["document_id"])
    guest_id = str(guest_created.json()["document_id"])
    guest_capability = str(guest_created.json()["access_token"])

    assert hybrid_client.get(f"/api/documents/{user_id}", headers=user_headers).status_code == 200
    assert hybrid_client.get(f"/api/documents/{guest_id}", headers=user_headers).status_code == 404
    assert (
        hybrid_client.get(
            f"/api/documents/{user_id}",
            headers={"X-Document-Capability": guest_capability},
        ).status_code
        == 404
    )

    application = cast(FastAPI, hybrid_client.app)
    foreign_token = application.state.auth_service.issue_access_token("different-user").access_token
    foreign = hybrid_client.get(
        f"/api/documents/{user_id}",
        headers={"Authorization": f"Bearer {foreign_token}"},
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_hybrid_rejects_invalid_or_ambiguous_credentials(hybrid_client: TestClient) -> None:
    guest_created = _upload(hybrid_client)
    guest_id = str(guest_created.json()["document_id"])
    capability = str(guest_created.json()["access_token"])
    token = _login(hybrid_client)

    invalid_jwt = hybrid_client.get(
        f"/api/documents/{uuid4()}",
        headers={"Authorization": "Bearer invalid"},
    )
    assert invalid_jwt.status_code == 401
    assert invalid_jwt.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

    both = hybrid_client.get(
        f"/api/documents/{guest_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Document-Capability": capability,
        },
    )
    assert both.status_code == 400
    assert both.json()["error"]["code"] == "INVALID_REQUEST"

    upload_with_capability = _upload(hybrid_client, {"X-Document-Capability": capability})
    assert upload_with_capability.status_code == 400
    assert upload_with_capability.json()["error"]["code"] == "INVALID_REQUEST"


def test_hybrid_configuration_requires_jwt_settings_and_stays_out_of_production(
    hybrid_settings: Settings,
) -> None:
    assert hybrid_settings.auth_mode == "hybrid"

    with pytest.raises(ValidationError, match="JWT signing key must contain at least 32 bytes"):
        Settings(_env_file=None, environment="test", auth_mode="hybrid")

    production_values = hybrid_settings.model_dump()
    production_values.update(
        environment="production",
        cors_origins=["https://app.example"],
        document_storage_backend="minio",
        minio_endpoint="minio.internal:9000",
        minio_access_key=SecretStr("access-key"),
        minio_secret_key=SecretStr("secret-key"),
    )
    with pytest.raises(ValidationError, match="Production requires JWT authentication"):
        Settings(_env_file=None, **production_values)


def test_cors_allows_hybrid_document_capability_header(hybrid_client: TestClient) -> None:
    response = hybrid_client.options(
        "/api/documents/example",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Document-Capability",
        },
    )
    assert response.status_code == 200
    assert "X-Document-Capability" in response.headers["access-control-allow-headers"]

"""Verify the public foundation without network providers or infrastructure."""

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from app.models.document import Evidence, ExtractedLicence
from app.schemas.common import ErrorCode


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Keep tests independent of developer environment files."""
    return TestClient(
        create_app(
            Settings(
                _env_file=None,
                environment="test",
                document_storage_dir=tmp_path / "documents",
            )
        )
    )


def test_health_is_live_and_correlated(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert UUID(response.headers["x-request-id"])


def test_configured_frontend_can_read_health(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unconfigured_origin_is_not_allowed(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "https://untrusted.example"})
    assert "access-control-allow-origin" not in response.headers


def test_preflight_allows_phase_one_methods_and_authorization(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-methods"] == "GET, POST, PUT, DELETE"

    authorization = client.options(
        "/api/documents/example",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert authorization.status_code == 200
    assert "Authorization" in authorization.headers["access-control-allow-headers"]


def test_upload_requires_the_multipart_file_field(client: TestClient) -> None:
    response = client.post("/api/documents")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert response.json()["request_id"] == response.headers["x-request-id"]


def test_unexpected_error_is_sanitized(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
        )
    )

    @application.get("/test-error")
    async def fail() -> None:
        raise RuntimeError("private provider response and personal information")

    response = TestClient(application).get(
        "/test-error", headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private" not in response.text
    assert "private provider" not in caplog.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert response.headers["x-request-id"] == response.json()["request_id"]


def test_controlled_error_preserves_public_message(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
        )
    )

    @application.get("/test-controlled-error")
    async def fail() -> None:
        raise ApplicationError(ErrorCode.INVALID_REQUEST, "Please check the request.", 400)

    response = TestClient(application).get("/test-controlled-error")
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "Please check the request."


def test_validation_error_does_not_echo_input(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
        )
    )

    @application.get("/test-validation")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    response = TestClient(application).get("/test-validation?value=private-document-data")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert "private-document-data" not in response.text


@pytest.mark.parametrize("origin", ["*", "file://local", "https://example.com/path"])
def test_configuration_rejects_unsafe_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=[origin])


def test_missing_fields_are_immutable_and_do_not_share_state() -> None:
    first = ExtractedLicence(document_id="one")
    second = ExtractedLicence(document_id="two")
    with pytest.raises(ValidationError):
        first.full_name.value = "changed"  # type: ignore[misc]
    assert second.full_name.value is None
    assert second.full_name.warnings == ()
    assert second.vehicle_classes == ()


def test_evidence_requires_one_based_page_numbers() -> None:
    with pytest.raises(ValidationError):
        Evidence(document_id="one", page_number=0, source_text="A source excerpt")

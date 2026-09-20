"""Exercise deterministic two-panel splitting and private child isolation."""

import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pwdlib import PasswordHash
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from app.models.document import ExtractedLicence, ExtractionResult, ExtractionStatus
from app.repositories.documents import DocumentRepository, StoredDocumentRecord

TOKEN = "source-capability"
MULTIPLE_LICENCES_WARNING = (
    "More than one licence was detected. Upload a document containing a single licence."
)


def two_panel_png() -> bytes:
    """Create distinct panels so tests can verify crop order and byte isolation."""
    image = Image.new("RGB", (24, 16), color=(0, 0, 0))
    image.paste((220, 20, 60), (0, 0, 12, 16))
    image.paste((30, 80, 220), (12, 0, 24, 16))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def png(size: tuple[int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color=(40, 90, 140)).save(output, format="PNG")
    return output.getvalue()


def extraction(document_id: str, *, multiple: bool) -> ExtractionResult:
    return ExtractionResult(
        document_id=document_id,
        status=(
            ExtractionStatus.EXTRACTED_WITH_WARNINGS if multiple else ExtractionStatus.EXTRACTED
        ),
        licence=ExtractedLicence(document_id=document_id),
        warnings=(MULTIPLE_LICENCES_WARNING,) if multiple else (),
        created_at=datetime.now(UTC),
    )


def make_application(
    tmp_path: Path,
    *,
    content: bytes | None = None,
    mime_type: str = "image/png",
    extraction_state: Literal["none", "single", "multiple"] = "multiple",
    auth_mode: Literal["capability", "hybrid"] = "capability",
) -> tuple[FastAPI, StoredDocumentRecord]:
    settings_values: dict[str, object] = {
        "_env_file": None,
        "environment": "test",
        "auth_mode": auth_mode,
        "document_storage_dir": tmp_path / "documents",
    }
    if auth_mode == "hybrid":
        settings_values.update(
            jwt_signing_key=SecretStr("offline-test-signing-key-that-is-at-least-32-bytes"),
            jwt_issuer="https://licenceiq.test",
            jwt_audience="licenceiq-browser",
            bootstrap_username="candidate",
            bootstrap_password_hash=SecretStr(
                PasswordHash.recommended().hash("correct horse battery staple")
            ),
            bootstrap_subject="candidate-001",
        )
    application = create_app(Settings(**settings_values))  # type: ignore[arg-type]
    repository = cast(DocumentRepository, application.state.document_service.repository)
    repository.initialize()
    document_id = str(uuid4())
    now = datetime.now(UTC)
    record = StoredDocumentRecord(
        document_id=document_id,
        filename="paired-licences.png" if mime_type == "image/png" else "paired-licences.pdf",
        mime_type=mime_type,
        size_bytes=len(content or b"%PDF-1.7"),
        created_at=now,
        expires_at=now + timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        extraction=(
            None
            if extraction_state == "none"
            else extraction(document_id, multiple=extraction_state == "multiple")
        ),
    )
    repository.save(record, content or b"%PDF-1.7")
    return application, record


def split(
    client: TestClient,
    document_id: str,
    *,
    token: str = TOKEN,
    hybrid_guest: bool = False,
):
    header = "X-Document-Capability" if hybrid_guest else "Authorization"
    value = token if hybrid_guest else f"Bearer {token}"
    return client.post(
        f"/api/documents/{document_id}/split",
        headers={header: value},
    )


def test_split_rejects_unauthorized_source_without_revealing_it(tmp_path: Path) -> None:
    application, record = make_application(tmp_path, content=two_panel_png())
    with TestClient(application) as client:
        response = split(client, record.document_id, token="wrong")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.parametrize("extraction_state", ["none", "single"])
def test_split_requires_multi_licence_extraction_warning(
    tmp_path: Path,
    extraction_state: Literal["none", "single"],
) -> None:
    application, record = make_application(
        tmp_path,
        content=two_panel_png(),
        extraction_state=extraction_state,
    )
    with TestClient(application) as client:
        response = split(client, record.document_id)
    assert response.status_code == 409
    assert response.json()["error"] == {
        "code": "INVALID_REQUEST",
        "message": "This document is not eligible for splitting.",
    }


def test_split_rejects_pdf_even_with_multi_licence_warning(tmp_path: Path) -> None:
    application, record = make_application(tmp_path, mime_type="application/pdf")
    with TestClient(application) as client:
        response = split(client, record.document_id)
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE"


@pytest.mark.parametrize("size", [(8, 8), (40, 8)])
def test_split_rejects_non_two_panel_geometry(tmp_path: Path, size: tuple[int, int]) -> None:
    application, record = make_application(tmp_path, content=png(size))
    with TestClient(application) as client:
        response = split(client, record.document_id)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE"


def test_split_guest_children_have_fresh_credentials_and_source_crops(tmp_path: Path) -> None:
    source_content = two_panel_png()
    application, source = make_application(
        tmp_path,
        content=source_content,
        auth_mode="hybrid",
    )
    repository = cast(DocumentRepository, application.state.document_service.repository)
    with TestClient(application) as client:
        response = split(client, source.document_id, hybrid_guest=True)
        assert response.status_code == 201, response.text
        body = response.json()
        children = body["documents"]
        child_contents = []
        for child in children:
            child_response = client.get(
                f"/api/documents/{child['document_id']}/file",
                headers={"X-Document-Capability": child["access_token"]},
            )
            assert child_response.status_code == 200
            child_contents.append(child_response.content)

        source_response = client.get(
            f"/api/documents/{source.document_id}/file",
            headers={"X-Document-Capability": TOKEN},
        )

    assert body["parent_document_id"] == source.document_id
    assert len(children) == 2
    assert children[0]["document_id"] != children[1]["document_id"]
    child_tokens = {child["access_token"] for child in children}
    assert len(child_tokens) == 2
    assert TOKEN not in child_tokens
    assert all(child["mime_type"] == "image/png" for child in children)
    assert all(child["status"] == "UPLOADED" for child in children)
    assert source_response.status_code == 200
    assert source_response.content == source_content

    expected_colours = [(220, 20, 60), (30, 80, 220)]
    for content, colour in zip(child_contents, expected_colours, strict=True):
        with Image.open(BytesIO(content)) as image:
            assert image.format == "PNG"
            assert image.size == (12, 16)
            assert image.getpixel((5, 8)) == colour

    source_record = repository.get(source.document_id)
    assert source_record is not None and source_record.extraction is not None
    child_records = [repository.get(child["document_id"]) for child in children]
    assert all(record is not None for record in child_records)
    for record in child_records:
        assert record is not None
        assert record.owner_subject is None
        assert record.reading is None
        assert record.semantic_index is None
        assert record.extraction is None
        assert record.review is None
    assert len({record.storage_key for record in child_records if record is not None}) == 2

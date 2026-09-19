"""Exercise validated storage, capability isolation, and temporary cleanup."""

import asyncio
import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from starlette.types import Message, Scope

from app.core.config import Settings
from app.main import create_app
from app.repositories.documents import FilesystemDocumentRepository, StoredDocumentRecord


def image_bytes(image_format: str, *, size: tuple[int, int] = (8, 6)) -> bytes:
    """Create a tiny real image so validation covers complete Pillow decoding."""
    output = BytesIO()
    Image.new("RGB", size, color=(31, 78, 121)).save(output, format=image_format)
    return output.getvalue()


def pdf_bytes(page_count: int = 1) -> bytes:
    """Create a structurally valid PDF without any external provider."""
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=300)
    writer.write(output)
    return output.getvalue()


def encrypted_pdf_bytes() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


def multipart_body(content: bytes) -> bytes:
    """Build a valid single-file body for direct chunked ASGI request tests."""
    return (
        b"--x\r\n"
        b'Content-Disposition: form-data; name="file"; filename="licence.png"\r\n'
        b"Content-Type: image/png\r\n\r\n" + content + b"\r\n--x--\r\n"
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        document_storage_dir=tmp_path / "documents",
        max_upload_file_bytes=1024 * 1024,
        max_upload_request_bytes=1024 * 1024 + 4096,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "licence.png",
    content_type: str = "image/png",
) -> dict[str, Any]:
    response = client.post("/api/documents", files={"file": (filename, content, content_type)})
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return cast(dict[str, Any], response.json())


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_pages"),
    [
        ("licence.png", "image/png", image_bytes("PNG"), 1),
        ("licence.jpg", "image/jpeg", image_bytes("JPEG"), 1),
        ("licence.pdf", "application/pdf", pdf_bytes(2), 2),
    ],
)
def test_valid_files_are_stored_and_privately_retrievable(
    client: TestClient,
    settings: Settings,
    filename: str,
    content_type: str,
    content: bytes,
    expected_pages: int,
) -> None:
    created = upload(client, content, filename=filename, content_type=content_type)
    assert created["filename"] == filename
    assert created["mime_type"] == content_type
    assert created["size_bytes"] == len(content)
    assert created["status"] == "UPLOADED"
    assert created["page_count"] == expected_pages
    assert created["access_token"]

    stored_text = "\n".join(
        path.read_text(encoding="utf-8") for path in settings.document_storage_dir.glob("*.json")
    )
    assert created["access_token"] not in stored_text
    assert hashlib.sha256(created["access_token"].encode()).hexdigest() in stored_text
    assert filename not in [path.name for path in settings.document_storage_dir.glob("*.bin")]

    headers = {"Authorization": f"Bearer {created['access_token']}"}
    metadata = client.get(f"/api/documents/{created['document_id']}", headers=headers)
    assert metadata.status_code == 200
    assert metadata.headers["cache-control"] == "no-store"
    assert "access_token" not in metadata.json()

    file_response = client.get(f"/api/documents/{created['document_id']}/file", headers=headers)
    assert file_response.status_code == 200
    assert file_response.content == content
    assert file_response.headers["content-type"] == content_type
    assert file_response.headers["cache-control"] == "no-store"
    assert file_response.headers["x-content-type-options"] == "nosniff"
    assert "inline" in file_response.headers["content-disposition"]


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_code"),
    [
        ("empty.png", "image/png", b"", "INVALID_FILE"),
        ("notes.txt", "text/plain", b"hello", "UNSUPPORTED_FILE"),
        ("wrong.png", "image/jpeg", image_bytes("PNG"), "INVALID_FILE"),
        ("spoof.png", "image/png", b"not a png", "INVALID_FILE"),
        ("truncated.jpg", "image/jpeg", b"\xff\xd8\xff\xe0broken", "INVALID_FILE"),
        ("broken.pdf", "application/pdf", b"%PDF-1.7\nbroken", "INVALID_FILE"),
    ],
)
def test_invalid_empty_unsupported_and_spoofed_files_are_rejected(
    client: TestClient,
    filename: str,
    content_type: str,
    content: bytes,
    expected_code: str,
) -> None:
    response = client.post("/api/documents", files={"file": (filename, content, content_type)})
    assert response.status_code in {400, 415}
    assert response.json()["error"]["code"] == expected_code


def test_encrypted_and_excessive_documents_are_rejected(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
            max_pdf_pages=1,
            max_image_dimension=4,
            max_image_pixels=16,
        )
    )
    with TestClient(application) as bounded_client:
        encrypted = bounded_client.post(
            "/api/documents",
            files={"file": ("locked.pdf", encrypted_pdf_bytes(), "application/pdf")},
        )
        pages = bounded_client.post(
            "/api/documents",
            files={"file": ("pages.pdf", pdf_bytes(2), "application/pdf")},
        )
        dimensions = bounded_client.post(
            "/api/documents",
            files={"file": ("large.png", image_bytes("PNG"), "image/png")},
        )
    for response in (encrypted, pages, dimensions):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_FILE"
    assert list((tmp_path / "documents").iterdir()) == []


def test_actual_file_limit_is_enforced_while_streaming(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
            max_upload_file_bytes=64,
            max_upload_request_bytes=4096,
        )
    )
    with TestClient(application) as limited_client:
        response = limited_client.post(
            "/api/documents",
            files={"file": ("large.png", b"x" * 65, "image/png")},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list((tmp_path / "documents").iterdir()) == []


def test_upload_rejects_extra_files_or_fields(client: TestClient) -> None:
    extra_file = client.post(
        "/api/documents",
        files=[
            ("file", ("one.png", image_bytes("PNG"), "image/png")),
            ("file", ("two.png", image_bytes("PNG"), "image/png")),
        ],
    )
    extra_field = client.post(
        "/api/documents",
        files={"file": ("one.png", image_bytes("PNG"), "image/png")},
        data={"note": "private"},
    )
    for response in (extra_file, extra_field):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"
        assert "private" not in response.text


@pytest.mark.parametrize("complete_file_before_overflow", [False, True])
def test_body_limit_counts_streams_without_content_length(
    tmp_path: Path, complete_file_before_overflow: bool
) -> None:
    """Reject both partial files and valid files followed by an oversized epilogue."""
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
            max_upload_file_bytes=1024 if complete_file_before_overflow else 64,
            max_upload_request_bytes=2048 if complete_file_before_overflow else 160,
        )
    )
    sent: list[Message] = []
    multipart = multipart_body(image_bytes("PNG"))
    chunks = iter(
        [multipart, b"x" * 3000]
        if complete_file_before_overflow
        else [multipart[:140], multipart[140:]]
    )

    async def receive() -> Message:
        try:
            body = next(chunks)
            return {"type": "http.request", "body": body, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/documents",
        "raw_path": b"/api/documents",
        "query_string": b"",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
        "client": ("test", 1),
        "server": ("test", 80),
        "state": {},
    }
    asyncio.run(application(scope, receive, send))

    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body)["error"]["code"] == "FILE_TOO_LARGE"
    assert not (tmp_path / "documents").exists()


def test_trailing_slash_upload_is_also_bounded_without_content_length(tmp_path: Path) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
            max_upload_file_bytes=64,
            max_upload_request_bytes=160,
        )
    )
    sent: list[Message] = []
    multipart = multipart_body(image_bytes("PNG"))
    chunks = iter([multipart[:140], multipart[140:]])

    async def receive() -> Message:
        try:
            body = next(chunks)
            return {"type": "http.request", "body": body, "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/documents/",
        "raw_path": b"/api/documents/",
        "query_string": b"",
        "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
        "client": ("test", 1),
        "server": ("test", 80),
        "state": {},
    }
    asyncio.run(application(scope, receive, send))
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    assert start["status"] == 413
    assert json.loads(body)["error"]["code"] == "FILE_TOO_LARGE"
    assert not (tmp_path / "documents").exists()


def test_path_filename_is_reduced_to_a_safe_leaf(client: TestClient) -> None:
    created = upload(
        client,
        image_bytes("PNG"),
        filename="../../private\\folder/licence.png",
    )
    assert created["filename"] == "licence.png"


def test_capability_failures_are_indistinguishable_and_document_scoped(
    client: TestClient,
) -> None:
    first = upload(client, image_bytes("PNG"), filename="first.png")
    second = upload(client, image_bytes("PNG"), filename="second.png")
    cases = [
        (first["document_id"], {}),
        (first["document_id"], {"Authorization": "Bearer wrong"}),
        (first["document_id"], {"Authorization": f"Bearer {second['access_token']}"}),
        (str(uuid4()), {"Authorization": f"Bearer {first['access_token']}"}),
        ("not-a-uuid", {"Authorization": f"Bearer {first['access_token']}"}),
    ]
    bodies = []
    for document_id, headers in cases:
        response = client.get(f"/api/documents/{document_id}", headers=headers)
        assert response.status_code == 404
        bodies.append(response.json()["error"])
    assert bodies == [
        {"code": "DOCUMENT_NOT_FOUND", "message": "The document was not found."}
    ] * len(cases)


def test_wrong_capability_cannot_read_file_or_delete_document(client: TestClient) -> None:
    created = upload(client, image_bytes("PNG"))
    wrong = {"Authorization": "Bearer wrong"}
    file_response = client.get(f"/api/documents/{created['document_id']}/file", headers=wrong)
    delete_response = client.delete(f"/api/documents/{created['document_id']}", headers=wrong)
    for response in (file_response, delete_response):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"

    valid = client.get(
        f"/api/documents/{created['document_id']}",
        headers={"Authorization": f"Bearer {created['access_token']}"},
    )
    assert valid.status_code == 200


def test_delete_removes_bytes_and_metadata(client: TestClient, settings: Settings) -> None:
    created = upload(client, image_bytes("PNG"))
    headers = {"Authorization": f"Bearer {created['access_token']}"}
    response = client.delete(f"/api/documents/{created['document_id']}", headers=headers)
    assert response.status_code == 204
    assert response.headers["cache-control"] == "no-store"
    assert list(settings.document_storage_dir.iterdir()) == []
    missing = client.get(f"/api/documents/{created['document_id']}", headers=headers)
    assert missing.status_code == 404


def test_expired_document_is_removed_on_operation(tmp_path: Path) -> None:
    current = datetime(2026, 9, 19, 8, tzinfo=UTC)

    def now() -> datetime:
        return current

    settings = Settings(
        _env_file=None,
        environment="test",
        document_storage_dir=tmp_path / "documents",
        document_retention_seconds=60,
    )
    with TestClient(create_app(settings, now_provider=now)) as client:
        created = upload(client, image_bytes("PNG"))
        current += timedelta(seconds=61)
        response = client.get(
            f"/api/documents/{created['document_id']}",
            headers={"Authorization": f"Bearer {created['access_token']}"},
        )
    assert response.status_code == 404
    assert list(settings.document_storage_dir.iterdir()) == []


def test_expired_capability_is_denied_when_cleanup_cannot_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = datetime(2026, 9, 19, 8, tzinfo=UTC)
    settings = Settings(
        _env_file=None,
        environment="test",
        document_storage_dir=tmp_path / "documents",
        document_retention_seconds=1,
    )
    application = create_app(settings, now_provider=lambda: current)
    with TestClient(application) as client:
        created = upload(client, image_bytes("PNG"))
        current += timedelta(seconds=2)
        repository = application.state.document_service.repository

        def fail_delete(_: StoredDocumentRecord) -> None:
            raise OSError("simulated cleanup failure")

        monkeypatch.setattr(repository, "delete", fail_delete)
        response = client.get(
            f"/api/documents/{created['document_id']}",
            headers={"Authorization": f"Bearer {created['access_token']}"},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_startup_removes_expired_documents(tmp_path: Path) -> None:
    storage = tmp_path / "documents"
    repository = FilesystemDocumentRepository(storage)
    old = datetime(2026, 9, 18, tzinfo=UTC)
    record = StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="old.png",
        mime_type="image/png",
        size_bytes=3,
        created_at=old,
        expires_at=old + timedelta(seconds=60),
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash="0" * 64,
    )
    repository.save(record, b"old")

    settings = Settings(_env_file=None, environment="test", document_storage_dir=storage)
    with TestClient(create_app(settings, now_provider=lambda: datetime(2026, 9, 19, tzinfo=UTC))):
        pass
    assert list(storage.iterdir()) == []


def test_failed_metadata_write_cleans_staged_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FilesystemDocumentRepository(tmp_path / "documents")
    now = datetime.now(UTC)
    record = StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="licence.png",
        mime_type="image/png",
        size_bytes=3,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash="0" * 64,
    )

    def fail(_: StoredDocumentRecord, __: Path) -> None:
        raise OSError("simulated metadata failure")

    monkeypatch.setattr(repository, "_write_metadata_atomic", fail)
    with pytest.raises(OSError, match="simulated metadata failure"):
        repository.save(record, b"abc")
    assert list(repository.root.iterdir()) == []


def test_storage_keys_are_uuid_generated_and_not_client_paths(
    client: TestClient, settings: Settings
) -> None:
    created = upload(client, image_bytes("PNG"), filename="friendly licence.png")
    metadata_path = next(settings.document_storage_dir.glob("*.json"))
    stored = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert str(UUID(stored["storage_key"])) == stored["storage_key"]
    assert stored["storage_key"] not in created
    assert "storage_key" not in created

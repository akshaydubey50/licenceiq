"""Exercise private, bounded page reading without live provider calls."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from app.providers.ocr import OCRResult
from app.repositories.documents import FilesystemDocumentRepository, StoredDocumentRecord
from app.schemas.common import ErrorCode


class RecordingOCR:
    """Return deterministic pages while retaining only safe call metadata."""

    def __init__(self, *pages: tuple[str, ...]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, float | None, tuple[int, int]]] = []

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        with Image.open(BytesIO(image_bytes)) as image:
            size = image.size
        self.calls.append((mime_type, timeout_seconds, size))
        lines = self.pages.pop(0) if self.pages else ()
        return OCRResult(lines=lines)


class FailingOCR:
    def __init__(self, code: ErrorCode, status_code: int) -> None:
        self.code = code
        self.status_code = status_code
        self.calls = 0

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        self.calls += 1
        raise ApplicationError(self.code, "Safe provider failure.", self.status_code)


class BlockingOCR:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("The test did not release the OCR call.")
        return OCRResult(lines=("Fictional licence text",))


def image_bytes(*, size: tuple[int, int] = (80, 40)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color="white").save(output, format="PNG")
    return output.getvalue()


def scanned_pdf_bytes(*, size: tuple[int, int] = (120, 80)) -> bytes:
    output = BytesIO()
    with Image.new("RGB", size, color="white") as image:
        image.save(output, format="PDF")
    return output.getvalue()


def native_pdf_bytes() -> bytes:
    """Create a one-page standard-font PDF that pypdf can extract offline."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        b"BT /F1 12 Tf 20 120 Td "
        b"(Fictional native licence page contains more than forty alphanumeric characters.) "
        b"Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def mixed_pdf_bytes() -> bytes:
    writer = PdfWriter()
    for source in (native_pdf_bytes(), scanned_pdf_bytes()):
        reader = PdfReader(BytesIO(source))
        writer.add_page(reader.pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "document_storage_dir": tmp_path / "documents",
        "max_upload_file_bytes": 2 * 1024 * 1024,
        "max_upload_request_bytes": 2 * 1024 * 1024 + 4096,
    }
    values.update(overrides)
    return Settings(**values)


def upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "licence.png",
    mime_type: str = "image/png",
) -> dict[str, Any]:
    response = client.post("/api/documents", files={"file": (filename, content, mime_type)})
    assert response.status_code == 201, response.text
    return cast(dict[str, Any], response.json())


def headers(created: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {created['access_token']}"}


def test_native_pdf_reads_without_ocr_and_cache_survives_app_restart(tmp_path: Path) -> None:
    config = settings(tmp_path)
    provider = RecordingOCR()
    with TestClient(create_app(config, ocr_provider=provider)) as client:
        created = upload(
            client,
            native_pdf_bytes(),
            filename="native.pdf",
            mime_type="application/pdf",
        )
        first = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )
        second = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    page = first.json()["pages"][0]
    assert page["method"] == "native_text"
    assert page["page_number"] == 1
    assert page["blocks"][0]["block_id"] == "page-1-line-1"
    assert page["blocks"][0]["source_text"] == page["text"]
    assert page["blocks"][0]["confidence"] is None
    assert page["blocks"][0]["bounding_box"] is None
    assert provider.calls == []

    failing_provider = FailingOCR(ErrorCode.OCR_PROVIDER_ERROR, 502)
    with TestClient(create_app(config, ocr_provider=failing_provider)) as restarted:
        saved = restarted.get(
            f"/api/documents/{created['document_id']}/reading", headers=headers(created)
        )
    assert saved.status_code == 200
    assert saved.json() == first.json()


@pytest.mark.parametrize(
    ("filename", "mime_type", "content"),
    [
        ("licence.png", "image/png", image_bytes()),
        ("scan.pdf", "application/pdf", scanned_pdf_bytes()),
    ],
)
def test_image_and_scanned_pdf_use_prepared_ocr_page(
    tmp_path: Path, filename: str, mime_type: str, content: bytes
) -> None:
    provider = RecordingOCR(("Line one", "Line two"))
    with TestClient(create_app(settings(tmp_path), ocr_provider=provider)) as client:
        created = upload(client, content, filename=filename, mime_type=mime_type)
        response = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )
    assert response.status_code == 200
    assert response.json()["status"] == "READ"
    assert response.json()["pages"][0]["method"] == "ocr"
    assert response.json()["pages"][0]["text"] == "Line one\nLine two"
    assert provider.calls[0][0] == "image/png"
    assert 0 < cast(float, provider.calls[0][1]) <= 45


def test_mixed_pdf_preserves_page_methods_and_warns_for_blank_page(tmp_path: Path) -> None:
    provider = RecordingOCR(())
    with TestClient(create_app(settings(tmp_path), ocr_provider=provider)) as client:
        created = upload(
            client,
            mixed_pdf_bytes(),
            filename="mixed.pdf",
            mime_type="application/pdf",
        )
        response = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READ_WITH_WARNINGS"
    assert [page["method"] for page in body["pages"]] == ["native_text", "ocr"]
    assert body["pages"][1]["text"] == ""
    assert body["warnings"] == ["Page 2 did not contain readable text."]
    assert len(provider.calls) == 1


def test_all_blank_and_oversized_results_are_not_published(tmp_path: Path) -> None:
    cases = [
        (RecordingOCR(()), settings(tmp_path / "blank"), "NO_READABLE_TEXT"),
        (
            RecordingOCR(("123456789",)),
            settings(tmp_path / "large", max_reading_characters=8),
            "READING_TOO_LARGE",
        ),
    ]
    for provider, config, expected_code in cases:
        with TestClient(create_app(config, ocr_provider=provider)) as client:
            created = upload(client, image_bytes())
            response = client.post(
                f"/api/documents/{created['document_id']}/read", headers=headers(created)
            )
            missing = client.get(
                f"/api/documents/{created['document_id']}/reading", headers=headers(created)
            )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == expected_code
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "READING_NOT_FOUND"


@pytest.mark.parametrize(
    ("code", "status_code"),
    [(ErrorCode.OCR_PROVIDER_ERROR, 502), (ErrorCode.OCR_TIMEOUT, 504)],
)
def test_provider_failures_do_not_publish_partial_results(
    tmp_path: Path, code: ErrorCode, status_code: int
) -> None:
    provider = FailingOCR(code, status_code)
    with TestClient(create_app(settings(tmp_path), ocr_provider=provider)) as client:
        created = upload(client, image_bytes())
        response = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )
        missing = client.get(
            f"/api/documents/{created['document_id']}/reading", headers=headers(created)
        )
    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert missing.status_code == 404
    assert provider.calls == 1


def test_reading_capability_isolated_before_cache_or_provider_access(tmp_path: Path) -> None:
    provider = RecordingOCR(("Private page",))
    with TestClient(create_app(settings(tmp_path), ocr_provider=provider)) as client:
        created = upload(client, image_bytes())
        wrong = {"Authorization": "Bearer wrong"}
        first = client.post(f"/api/documents/{created['document_id']}/read", headers=wrong)
        saved = client.get(f"/api/documents/{created['document_id']}/reading", headers=wrong)
    assert first.status_code == saved.status_code == 404
    assert first.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert saved.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert provider.calls == []


def test_duplicate_read_returns_conflict_without_duplicate_provider_work(tmp_path: Path) -> None:
    provider = BlockingOCR()
    application = create_app(settings(tmp_path), ocr_provider=provider)
    with TestClient(application) as client:
        created = upload(client, image_bytes())
        with ThreadPoolExecutor(max_workers=1) as executor:
            first_future = executor.submit(
                client.post,
                f"/api/documents/{created['document_id']}/read",
                headers=headers(created),
            )
            assert provider.started.wait(timeout=2)
            duplicate = client.post(
                f"/api/documents/{created['document_id']}/read", headers=headers(created)
            )
            provider.release.set()
            first = first_future.result(timeout=5)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "READING_IN_PROGRESS"
    assert first.status_code == 200
    assert provider.calls == 1


def test_delete_during_read_prevents_late_publication(tmp_path: Path) -> None:
    provider = BlockingOCR()
    config = settings(tmp_path)
    with TestClient(create_app(config, ocr_provider=provider)) as client:
        created = upload(client, image_bytes())
        with ThreadPoolExecutor(max_workers=1) as executor:
            read_future = executor.submit(
                client.post,
                f"/api/documents/{created['document_id']}/read",
                headers=headers(created),
            )
            assert provider.started.wait(timeout=2)
            deleted = client.delete(
                f"/api/documents/{created['document_id']}", headers=headers(created)
            )
            provider.release.set()
            read_response = read_future.result(timeout=5)
    assert deleted.status_code == 204
    assert read_response.status_code == 404
    assert read_response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert list(config.document_storage_dir.iterdir()) == []


def test_expiry_during_read_prevents_late_publication(tmp_path: Path) -> None:
    current = datetime(2026, 9, 19, 8, tzinfo=UTC)
    provider = BlockingOCR()
    config = settings(tmp_path, document_retention_seconds=1)
    with TestClient(
        create_app(config, now_provider=lambda: current, ocr_provider=provider)
    ) as client:
        created = upload(client, image_bytes())
        with ThreadPoolExecutor(max_workers=1) as executor:
            read_future = executor.submit(
                client.post,
                f"/api/documents/{created['document_id']}/read",
                headers=headers(created),
            )
            assert provider.started.wait(timeout=2)
            current += timedelta(seconds=2)
            provider.release.set()
            read_response = read_future.result(timeout=5)
    assert read_response.status_code == 404
    assert read_response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert list(config.document_storage_dir.iterdir()) == []


def test_delete_retains_metadata_when_byte_removal_needs_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = FilesystemDocumentRepository(tmp_path / "documents")
    created_at = datetime(2026, 9, 19, 8, tzinfo=UTC)
    record = StoredDocumentRecord(
        document_id="6c65d15e-7c1c-4dc4-a610-5cdd6348c2f6",
        filename="licence.png",
        mime_type="image/png",
        size_bytes=3,
        created_at=created_at,
        expires_at=created_at + timedelta(hours=1),
        page_count=1,
        storage_key="826f31e7-fcf7-474f-925d-8f64a590a18d",
        access_token_hash="0" * 64,
    )
    repository.save(record, b"abc")
    content_path = next(repository.root.glob("*.bin"))
    metadata_path = next(repository.root.glob("*.json"))
    original_unlink = Path.unlink
    fail_once = True

    def flaky_unlink(path: Path, *args: Any, **kwargs: Any) -> None:
        nonlocal fail_once
        if path == content_path and fail_once:
            fail_once = False
            raise OSError("simulated byte removal failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    with pytest.raises(OSError, match="simulated byte removal failure"):
        repository.delete(record)
    assert content_path.exists()
    assert metadata_path.exists()

    repository.delete(record)
    assert list(repository.root.iterdir()) == []


def test_page_raster_is_reduced_before_provider_call(tmp_path: Path) -> None:
    provider = RecordingOCR(("Readable",))
    config = settings(
        tmp_path,
        ocr_max_image_dimension=128,
        ocr_max_image_pixels=128 * 96,
    )
    with TestClient(create_app(config, ocr_provider=provider)) as client:
        created = upload(
            client,
            scanned_pdf_bytes(size=(1200, 800)),
            filename="scan.pdf",
            mime_type="application/pdf",
        )
        response = client.post(
            f"/api/documents/{created['document_id']}/read", headers=headers(created)
        )
    assert response.status_code == 200
    width, height = provider.calls[0][2]
    assert max(width, height) <= 128
    assert width * height <= 128 * 96

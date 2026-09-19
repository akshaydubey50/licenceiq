"""Exercise Phase 4 review persistence without live provider calls."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from app.core.config import Settings
from app.main import create_app
from app.models.document import (
    Evidence,
    ExtractedField,
    ExtractedLicence,
    ExtractionResult,
    ExtractionStatus,
    ReviewFields,
    ReviewState,
)
from app.repositories.documents import FilesystemDocumentRepository, StoredDocumentRecord

NOW = datetime(2026, 9, 19, 12, tzinfo=UTC)
TOKEN = "phase-four-capability"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}


def extracted_field(document_id: str, value: str | None, line: int) -> ExtractedField:
    if value is None:
        return ExtractedField()
    evidence = Evidence(
        document_id=document_id,
        page_number=1,
        source_text=value,
        block_id=f"page-1-line-{line}",
    )
    return ExtractedField(value=value, raw_value=value, evidence=(evidence,))


def extraction(document_id: str, *, full_name: str = "PRIYA SHARMA") -> ExtractionResult:
    licence = ExtractedLicence(
        document_id=document_id,
        full_name=extracted_field(document_id, full_name, 1),
        licence_number=extracted_field(document_id, "MH12 20260001234", 2),
        date_of_birth=extracted_field(document_id, "07/11/1994", 3),
        date_of_issue=extracted_field(document_id, "15/06/2021", 4),
        date_of_expiry=extracted_field(document_id, "14/06/2041", 5),
        address=extracted_field(document_id, "12 Lotus Road", 6),
        vehicle_classes=(
            extracted_field(document_id, "LMV", 7),
            extracted_field(document_id, "MCWG", 8),
        ),
        issuing_authority=extracted_field(document_id, "Pune RTO", 9),
        other_information={
            "Blood Group": extracted_field(document_id, "B+", 10),
            "Restriction": extracted_field(document_id, None, 11),
        },
    )
    return ExtractionResult(
        document_id=document_id,
        status=ExtractionStatus.EXTRACTED,
        licence=licence,
        created_at=NOW,
    )


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
    *,
    include_extraction: bool = True,
    expires_at: datetime | None = None,
) -> tuple[FastAPI, StoredDocumentRecord]:
    config = settings(tmp_path)
    application = create_app(config, now_provider=lambda: NOW)
    repository = cast(
        FilesystemDocumentRepository,
        application.state.document_service.repository,
    )
    repository.initialize()
    document_id = str(uuid4())
    record = StoredDocumentRecord(
        document_id=document_id,
        filename="fictional-licence.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=NOW,
        expires_at=expires_at or NOW + timedelta(hours=1),
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        extraction=extraction(document_id) if include_extraction else None,
    )
    repository.save(record, b"private")
    return application, record


def review_fields(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "full_name": "PRIYA SHARMA",
        "licence_number": "MH12 20260001234",
        "date_of_birth": "07/11/1994",
        "date_of_issue": "15/06/2021",
        "date_of_expiry": "14/06/2041",
        "address": "12 Lotus Road",
        "vehicle_classes": ["LMV", "MCWG"],
        "issuing_authority": "Pune RTO",
        "other_information": {"Blood Group": "B+", "Restriction": None},
    }
    values.update(overrides)
    return values


def put_fields(
    client: TestClient,
    document_id: str,
    fields: object,
    headers: dict[str, str] | None = None,
) -> Response:
    return cast(
        Response,
        client.put(
            f"/api/documents/{document_id}/fields",
            headers=AUTHORIZATION if headers is None else headers,
            json={"fields": fields},
        ),
    )


def test_default_review_is_derived_without_persistence(tmp_path: Path) -> None:
    application, record = make_application(tmp_path)
    repository = application.state.document_service.repository
    with TestClient(application) as client:
        response = client.get(
            f"/api/documents/{record.document_id}/fields",
            headers=AUTHORIZATION,
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["document_id"] == record.document_id
    assert body["updated_at"] is None
    assert body["reviewed"]["full_name"] == {
        "current_value": "PRIYA SHARMA",
        "is_edited": False,
    }
    assert body["reviewed"]["vehicle_classes"] == {
        "current_value": ["LMV", "MCWG"],
        "is_edited": False,
    }
    assert body["reviewed"]["other_information"]["Restriction"] == {
        "current_value": None,
        "is_edited": False,
    }
    assert repository.get(record.document_id).review is None


def test_review_persists_reloads_and_preserves_source_extraction(tmp_path: Path) -> None:
    config = settings(tmp_path)
    application, record = make_application(tmp_path)
    repository = application.state.document_service.repository
    original_extraction = repository.get(record.document_id).extraction
    corrected = review_fields(
        full_name="  Priya Sharma  ",
        licence_number="  MH12 20260001234 ",
        address=None,
        vehicle_classes=["MCWG", " LMV ", "TR"],
        other_information={"Blood Group": None, "Restriction": "  Corrective lenses "},
    )

    with TestClient(application) as client:
        saved = put_fields(client, record.document_id, corrected)
    assert saved.status_code == 200
    assert saved.headers["cache-control"] == "no-store"
    body = saved.json()
    assert body["updated_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert body["reviewed"]["full_name"] == {
        "current_value": "Priya Sharma",
        "is_edited": True,
    }
    assert body["reviewed"]["licence_number"]["is_edited"] is False
    assert body["reviewed"]["address"] == {"current_value": None, "is_edited": True}
    assert body["reviewed"]["vehicle_classes"] == {
        "current_value": ["MCWG", "LMV", "TR"],
        "is_edited": True,
    }
    assert body["reviewed"]["other_information"]["Blood Group"] == {
        "current_value": None,
        "is_edited": True,
    }
    assert body["reviewed"]["other_information"]["Restriction"] == {
        "current_value": "Corrective lenses",
        "is_edited": True,
    }
    stored = repository.get(record.document_id)
    assert stored.extraction == original_extraction
    assert stored.extraction.licence.full_name.value == "PRIYA SHARMA"
    assert stored.extraction.licence.full_name.current_value is None
    assert stored.extraction.licence.full_name.is_edited is False

    restarted = create_app(config, now_provider=lambda: NOW)
    with TestClient(restarted) as client:
        reloaded = client.get(
            f"/api/documents/{record.document_id}/fields",
            headers=AUTHORIZATION,
        )
    assert reloaded.status_code == 200
    assert reloaded.json() == body


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize("authorization", [None, "Bearer wrong"])
def test_review_requires_document_capability(
    tmp_path: Path,
    method: str,
    authorization: str | None,
) -> None:
    application, record = make_application(tmp_path)
    headers = {"Authorization": authorization} if authorization is not None else {}
    with TestClient(application) as client:
        if method == "get":
            response = client.get(
                f"/api/documents/{record.document_id}/fields",
                headers=headers,
            )
        else:
            response = put_fields(client, record.document_id, review_fields(), headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.parametrize("method", ["get", "put"])
def test_review_requires_saved_extraction(tmp_path: Path, method: str) -> None:
    application, record = make_application(tmp_path, include_extraction=False)
    with TestClient(application) as client:
        if method == "get":
            response = client.get(
                f"/api/documents/{record.document_id}/fields",
                headers=AUTHORIZATION,
            )
        else:
            response = put_fields(client, record.document_id, review_fields())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "EXTRACTION_NOT_FOUND"


@pytest.mark.parametrize(
    "payload",
    [
        {**review_fields(), "unknown": "value"},
        {key: value for key, value in review_fields().items() if key != "address"},
        review_fields(full_name="   "),
        review_fields(address="x" * 4097),
        review_fields(vehicle_classes=["LMV", " lmv "]),
        review_fields(vehicle_classes=["LMV", "   "]),
        review_fields(vehicle_classes=["x" * 4097]),
        review_fields(other_information={"Blood Group": "B+"}),
        review_fields(other_information={"Blood Group": "B+", "Restriction": None, "Unknown": "x"}),
    ],
)
def test_invalid_review_values_are_controlled(tmp_path: Path, payload: dict[str, Any]) -> None:
    application, record = make_application(tmp_path)
    with TestClient(application) as client:
        response = put_fields(client, record.document_id, payload)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REVIEW"
    assert "4097" not in response.text


def test_unknown_wrapper_and_malformed_json_are_invalid_review(tmp_path: Path) -> None:
    application, record = make_application(tmp_path)
    endpoint = f"/api/documents/{record.document_id}/fields"
    with TestClient(application) as client:
        unknown = client.put(
            endpoint,
            headers=AUTHORIZATION,
            json={"fields": review_fields(), "unknown": True},
        )
        malformed = client.put(
            endpoint,
            headers={**AUTHORIZATION, "Content-Type": "application/json"},
            content=b"{",
        )
    for response in (unknown, malformed):
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REVIEW"


def test_invalid_put_document_identity_is_invalid_review(tmp_path: Path) -> None:
    application, _ = make_application(tmp_path)
    with TestClient(application) as client:
        response = put_fields(client, "not-a-uuid", review_fields())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REVIEW"


def test_delete_wins_over_late_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application, record = make_application(tmp_path)
    repository = application.state.document_service.repository
    original = repository.save_review_if_current

    def delete_then_save(
        snapshot: StoredDocumentRecord,
        review: ReviewState,
        now: datetime,
    ) -> bool:
        repository.delete(snapshot)
        return original(snapshot, review, now)

    monkeypatch.setattr(repository, "save_review_if_current", delete_then_save)
    with TestClient(application) as client:
        response = put_fields(client, record.document_id, review_fields(full_name="Changed"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert repository.get(record.document_id) is None


def test_expiry_wins_over_late_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expires_at = NOW + timedelta(seconds=1)
    application, record = make_application(tmp_path, expires_at=expires_at)
    repository = application.state.document_service.repository
    original = repository.save_review_if_current

    def expire_then_save(
        snapshot: StoredDocumentRecord,
        review: ReviewState,
        _: datetime,
    ) -> bool:
        return original(snapshot, review, expires_at)

    monkeypatch.setattr(repository, "save_review_if_current", expire_then_save)
    with TestClient(application) as client:
        response = put_fields(client, record.document_id, review_fields(full_name="Changed"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert repository.get(record.document_id).review is None


@pytest.mark.parametrize("changed_part", ["record", "extraction"])
def test_repository_rejects_replaced_record_or_extraction(
    tmp_path: Path,
    changed_part: str,
) -> None:
    application, snapshot = make_application(tmp_path)
    repository = application.state.document_service.repository
    current = snapshot
    if changed_part == "record":
        current = current.model_copy(update={"storage_key": str(uuid4())})
    else:
        current = current.model_copy(
            update={"extraction": extraction(snapshot.document_id, full_name="OTHER HOLDER")}
        )
    repository._write_metadata_atomic(
        current,
        repository._metadata_path(snapshot.document_id),
    )
    review = ReviewState(fields=ReviewFields(**review_fields()), updated_at=NOW)

    assert repository.save_review_if_current(snapshot, review, NOW) is False
    assert repository.get(snapshot.document_id).review is None

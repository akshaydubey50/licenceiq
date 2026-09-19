"""Exercise evidence-backed extraction without live provider calls."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.main import create_app
from app.models.document import (
    DocumentPage,
    Evidence,
    ExtractionResult,
    ReadingResult,
    ReadingStatus,
)
from app.providers.extraction import (
    AdditionalFieldCandidate,
    ExtractionCandidate,
    ExtractionContext,
    FieldCandidate,
)
from app.repositories.documents import StoredDocumentRecord
from app.schemas.common import ErrorCode

NOW = datetime(2026, 9, 19, 10, tzinfo=UTC)
TOKEN = "test-document-capability"
AUTHORIZATION = f"Bearer {TOKEN}"


def null_field() -> FieldCandidate:
    return FieldCandidate(value=None, raw_value=None, block_ids=())


def field(value: str, raw_value: str, *block_ids: str) -> FieldCandidate:
    return FieldCandidate(value=value, raw_value=raw_value, block_ids=block_ids)


def candidate(**overrides: Any) -> ExtractionCandidate:
    values: dict[str, Any] = {
        "full_name": null_field(),
        "licence_number": null_field(),
        "date_of_birth": null_field(),
        "date_of_issue": null_field(),
        "date_of_expiry": null_field(),
        "address": null_field(),
        "issuing_authority": null_field(),
        "vehicle_classes": (),
        "other_information": (),
        "multiple_licences_detected": False,
    }
    values.update(overrides)
    return ExtractionCandidate(**values)


def reading(document_id: str) -> ReadingResult:
    first_page_lines = (
        "DL No: MH12 20260001234",
        "Name: PRIYA SHARMA",
        "DOB: 07/11/1994   DOI: 15/06/2021",
        "Address: 12 Lotus Road",
        "Pune Maharashtra 411001",
        "Class of Vehicle: LMV, MCWG",
        "Issuing Authority: Pune RTO",
        "Blood Group: B+",
    )
    first_page_blocks = tuple(
        Evidence(
            document_id=document_id,
            page_number=1,
            source_text=text,
            block_id=f"page-1-line-{index}",
        )
        for index, text in enumerate(first_page_lines, start=1)
    )
    second_page_blocks = (
        Evidence(
            document_id=document_id,
            page_number=2,
            source_text="Validity: 14/06/2041",
            block_id="page-2-line-1",
        ),
    )
    return ReadingResult(
        document_id=document_id,
        status=ReadingStatus.READ,
        pages=(
            DocumentPage(
                document_id=document_id,
                page_number=1,
                text="\n".join(first_page_lines),
                blocks=first_page_blocks,
                method="ocr",
            ),
            DocumentPage(
                document_id=document_id,
                page_number=2,
                text="Validity: 14/06/2041",
                blocks=second_page_blocks,
                method="ocr",
            ),
        ),
        created_at=NOW,
    )


def complete_candidate() -> ExtractionCandidate:
    return candidate(
        full_name=field("PRIYA SHARMA", "Name: PRIYA SHARMA", "page-1-line-2"),
        licence_number=field("MH12 20260001234", "DL No: MH12 20260001234", "page-1-line-1"),
        date_of_birth=field("07/11/1994", "DOB: 07/11/1994", "page-1-line-3"),
        date_of_issue=field("15/06/2021", "DOI: 15/06/2021", "page-1-line-3"),
        date_of_expiry=field("14/06/2041", "Validity: 14/06/2041", "page-2-line-1"),
        address=field(
            "12 Lotus Road Pune Maharashtra 411001",
            "Address: 12 Lotus Road Pune Maharashtra 411001",
            "page-1-line-5",
            "page-1-line-4",
        ),
        issuing_authority=field("Pune RTO", "Issuing Authority: Pune RTO", "page-1-line-7"),
        vehicle_classes=(
            field("LMV", "LMV", "page-1-line-6"),
            field("MCWG", "MCWG", "page-1-line-6"),
        ),
        other_information=(
            AdditionalFieldCandidate(
                name="Blood Group",
                value="B+",
                raw_value="Blood Group: B+",
                block_ids=("page-1-line-8",),
            ),
        ),
    )


class StaticProvider:
    def __init__(self, output: object) -> None:
        self.output = output
        self.calls = 0
        self.contexts: list[ExtractionContext] = []

    def extract_structured_data(
        self,
        context: ExtractionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        self.calls += 1
        self.contexts.append(context)
        return self.output


class BlockingProvider(StaticProvider):
    def __init__(self, output: ExtractionCandidate) -> None:
        super().__init__(output)
        self.started = threading.Event()
        self.release = threading.Event()

    def extract_structured_data(
        self,
        context: ExtractionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> ExtractionCandidate:
        self.calls += 1
        self.contexts.append(context)
        self.started.set()
        if not self.release.wait(timeout=5):
            raise AssertionError("The test did not release the extraction call.")
        return self.output  # type: ignore[return-value]


def make_application(
    tmp_path: Path,
    provider: object,
    *,
    include_reading: bool = True,
    now_provider: Any = None,
    **setting_overrides: Any,
) -> tuple[Any, StoredDocumentRecord]:
    values: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "document_storage_dir": tmp_path / "documents",
    }
    values.update(setting_overrides)
    settings = Settings(**values)
    now = now_provider or (lambda: NOW)
    application = create_app(settings, now_provider=now, llm_provider=provider)  # type: ignore[arg-type]
    repository = application.state.document_service.repository
    repository.initialize()
    document_id = str(uuid4())
    record = StoredDocumentRecord(
        document_id=document_id,
        filename="fictional-licence.png",
        mime_type="image/png",
        size_bytes=7,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=settings.document_retention_seconds),
        page_count=2,
        storage_key=str(uuid4()),
        access_token_hash=hashlib.sha256(TOKEN.encode()).hexdigest(),
        reading=reading(document_id) if include_reading else None,
    )
    repository.save(record, b"private")
    return application, record


def post_extract(
    client: TestClient, document_id: str, authorization: str = AUTHORIZATION
) -> Response:
    return cast(
        Response,
        client.post(
            f"/api/documents/{document_id}/extract",
            headers={"Authorization": authorization},
        ),
    )


def test_complete_extraction_is_evidence_backed_cached_and_retrievable(tmp_path: Path) -> None:
    provider = StaticProvider(complete_candidate())
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
        cached_post = post_extract(client, record.document_id)
        cached_get = client.get(
            f"/api/documents/{record.document_id}/extraction",
            headers={"Authorization": AUTHORIZATION},
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == cached_post.json() == cached_get.json()
    assert provider.calls == 1
    body = response.json()
    assert body["status"] == "EXTRACTED"
    assert body["licence"]["full_name"]["value"] == "PRIYA SHARMA"
    assert body["licence"]["date_of_birth"]["value"] == "07/11/1994"
    assert [item["value"] for item in body["licence"]["vehicle_classes"]] == [
        "LMV",
        "MCWG",
    ]
    assert body["licence"]["other_information"]["Blood Group"]["value"] == "B+"
    address = body["licence"]["address"]
    assert [item["block_id"] for item in address["evidence"]] == [
        "page-1-line-4",
        "page-1-line-5",
    ]
    assert address["current_value"] is None
    assert address["is_edited"] is False
    assert tuple(page.page_number for page in provider.contexts[0].pages) == (1, 2)


def test_null_fields_remain_empty_without_warnings(tmp_path: Path) -> None:
    provider = StaticProvider(candidate())
    application, record = make_application(tmp_path, provider)
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
    assert response.status_code == 200
    assert response.json()["status"] == "EXTRACTED"
    assert response.json()["licence"]["full_name"] == {
        "value": None,
        "raw_value": None,
        "evidence": [],
        "current_value": None,
        "is_edited": False,
        "warnings": [],
    }


def test_unsupported_field_is_dropped_with_safe_warning(tmp_path: Path) -> None:
    output = candidate(
        full_name=field("INVENTED PERSON", "INVENTED PERSON", "page-1-line-2"),
        licence_number=field("MH12 20260001234", "DL No: MH12 20260001234", "page-1-line-1"),
    )
    application, record = make_application(tmp_path, StaticProvider(output))
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "EXTRACTED_WITH_WARNINGS"
    assert body["licence"]["full_name"]["value"] is None
    assert body["licence"]["full_name"]["raw_value"] is None
    assert body["licence"]["full_name"]["evidence"] == []
    assert body["licence"]["full_name"]["warnings"]
    assert "INVENTED PERSON" not in response.text
    assert body["licence"]["licence_number"]["value"] == "MH12 20260001234"


@pytest.mark.parametrize(
    "invalid_field",
    [
        FieldCandidate.model_construct(
            value="PRIYA SHARMA", raw_value="PRIYA SHARMA", block_ids=()
        ),
        field("PRIYA SHARMA", "PRIYA SHARMA", "page-99-line-1"),
        field("PRIYA SHARMA", "PRIYA SHARMA", "other-document-block"),
    ],
    ids=["missing-evidence", "unknown-evidence", "cross-document-evidence"],
)
def test_invalid_evidence_fails_whole_request(
    tmp_path: Path, invalid_field: FieldCandidate
) -> None:
    output = candidate().model_copy(update={"full_name": invalid_field})
    application, record = make_application(tmp_path, StaticProvider(output))
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
        missing = client.get(
            f"/api/documents/{record.document_id}/extraction",
            headers={"Authorization": AUTHORIZATION},
        )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "EXTRACTION_PROVIDER_ERROR"
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "EXTRACTION_NOT_FOUND"


def test_invalid_additional_names_fail_whole_request(tmp_path: Path) -> None:
    additional = AdditionalFieldCandidate(
        name="full_name",
        value="PRIYA SHARMA",
        raw_value="Name: PRIYA SHARMA",
        block_ids=("page-1-line-2",),
    )
    application, record = make_application(
        tmp_path, StaticProvider(candidate(other_information=(additional,)))
    )
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "EXTRACTION_PROVIDER_ERROR"


def test_multiple_licences_suppress_all_candidate_values(tmp_path: Path) -> None:
    output = complete_candidate().model_copy(update={"multiple_licences_detected": True})
    application, record = make_application(tmp_path, StaticProvider(output))
    with TestClient(application) as client:
        response = post_extract(client, record.document_id)
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "EXTRACTED_WITH_WARNINGS"
    assert body["licence"]["full_name"]["value"] is None
    assert body["licence"]["licence_number"]["value"] is None
    assert body["licence"]["vehicle_classes"] == []
    assert body["licence"]["other_information"] == {}
    assert "single licence" in body["warnings"][0].lower()


def test_capability_and_reading_are_required_before_extraction(tmp_path: Path) -> None:
    provider = StaticProvider(candidate())
    application, record = make_application(tmp_path, provider, include_reading=False)
    with TestClient(application) as client:
        unauthorized = post_extract(client, record.document_id, "Bearer wrong")
        unread = post_extract(client, record.document_id)
        missing = client.get(
            f"/api/documents/{record.document_id}/extraction",
            headers={"Authorization": AUTHORIZATION},
        )
    assert unauthorized.status_code == 404
    assert unauthorized.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
    for response in (unread, missing):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "READING_REQUIRED"
    assert provider.calls == 0


def test_duplicate_call_is_suppressed_then_cached(tmp_path: Path) -> None:
    provider = BlockingProvider(candidate())
    application, record = make_application(tmp_path, provider)
    service = application.state.extraction_service
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.extract, record.document_id, AUTHORIZATION)
        assert provider.started.wait(timeout=2)
        with pytest.raises(ApplicationError) as duplicate:
            service.extract(record.document_id, AUTHORIZATION)
        assert duplicate.value.code == ErrorCode.EXTRACTION_IN_PROGRESS
        provider.release.set()
        result = first.result(timeout=2)
    cached = service.extract(record.document_id, AUTHORIZATION)
    assert result == cached
    assert provider.calls == 1


def test_process_capacity_is_bounded_without_starting_provider_work(tmp_path: Path) -> None:
    provider = StaticProvider(candidate())
    application, record = make_application(tmp_path, provider)
    service = application.state.extraction_service
    acquired = [service._capacity.acquire(blocking=False) for _ in range(4)]
    try:
        with pytest.raises(ApplicationError) as busy:
            service.extract(record.document_id, AUTHORIZATION)
    finally:
        for was_acquired in acquired:
            if was_acquired:
                service._capacity.release()
    assert acquired == [True, True, True, True]
    assert busy.value.code == ErrorCode.EXTRACTION_IN_PROGRESS
    assert provider.calls == 0


@pytest.mark.parametrize("lifecycle", ["delete", "expire"])
def test_late_provider_response_cannot_resurrect_document(tmp_path: Path, lifecycle: str) -> None:
    current = NOW
    provider = BlockingProvider(candidate())
    application, record = make_application(
        tmp_path, provider, now_provider=lambda: current, document_retention_seconds=60
    )
    service = application.state.extraction_service
    repository = application.state.document_service.repository
    with ThreadPoolExecutor(max_workers=1) as executor:
        work = executor.submit(service.extract, record.document_id, AUTHORIZATION)
        assert provider.started.wait(timeout=2)
        if lifecycle == "delete":
            repository.delete(record)
        else:
            current += timedelta(seconds=61)
        provider.release.set()
        with pytest.raises(ApplicationError) as failure:
            work.result(timeout=2)
    assert failure.value.code == ErrorCode.DOCUMENT_NOT_FOUND
    assert repository.get(record.document_id) is None


def test_provider_failure_timeout_and_input_limit_are_controlled(tmp_path: Path) -> None:
    class FailingProvider:
        def extract_structured_data(
            self, context: ExtractionContext, *, timeout_seconds: float | None = None
        ) -> ExtractionCandidate:
            raise RuntimeError("private model output")

    failed_app, failed_record = make_application(tmp_path / "failed", FailingProvider())
    with TestClient(failed_app) as client:
        failed = post_extract(client, failed_record.document_id)
    assert failed.status_code == 502
    assert failed.json()["error"]["code"] == "EXTRACTION_PROVIDER_ERROR"
    assert "private model output" not in failed.text

    large_app, large_record = make_application(
        tmp_path / "large",
        StaticProvider(candidate()),
        extraction_max_input_characters=10,
    )
    with TestClient(large_app) as client:
        too_large = post_extract(client, large_record.document_id)
    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "EXTRACTION_TOO_LARGE"

    timeout_provider = StaticProvider(candidate())
    timeout_app, timeout_record = make_application(tmp_path / "timeout", timeout_provider)
    clock = [0.0]
    timeout_app.state.extraction_service.monotonic_provider = lambda: clock[0]

    def advance_time(
        context: ExtractionContext, *, timeout_seconds: float | None = None
    ) -> ExtractionCandidate:
        clock[0] = 121.0
        return candidate()

    timeout_provider.extract_structured_data = advance_time  # type: ignore[method-assign]
    with TestClient(timeout_app) as client:
        timed_out = post_extract(client, timeout_record.document_id)
    assert timed_out.status_code == 504
    assert timed_out.json()["error"]["code"] == "EXTRACTION_TIMEOUT"


def test_cache_is_document_scoped(tmp_path: Path) -> None:
    first_provider = StaticProvider(candidate())
    first_app, first_record = make_application(tmp_path / "first", first_provider)
    second_provider = StaticProvider(complete_candidate())
    second_app, second_record = make_application(tmp_path / "second", second_provider)
    with TestClient(first_app) as first_client, TestClient(second_app) as second_client:
        first = post_extract(first_client, first_record.document_id)
        second = post_extract(second_client, second_record.document_id)
        cross_access = first_client.get(
            f"/api/documents/{first_record.document_id}/extraction",
            headers={"Authorization": f"Bearer {TOKEN}-wrong"},
        )
    assert first.json()["document_id"] == first_record.document_id
    assert second.json()["document_id"] == second_record.document_id
    assert first.json()["licence"]["full_name"]["value"] is None
    assert second.json()["licence"]["full_name"]["value"] == "PRIYA SHARMA"
    assert cross_access.status_code == 404
    assert cross_access.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_default_provider_is_not_called_at_startup_and_reports_not_configured(
    tmp_path: Path,
) -> None:
    _, record = make_application(tmp_path, StaticProvider(candidate()))
    unconfigured = create_app(
        Settings(
            _env_file=None,
            environment="test",
            document_storage_dir=tmp_path / "documents",
        ),
        now_provider=lambda: NOW,
    )
    with TestClient(unconfigured) as client:
        response = post_extract(client, record.document_id)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EXTRACTION_NOT_CONFIGURED"


def test_cached_result_models_reject_field_reassignment(tmp_path: Path) -> None:
    application, record = make_application(tmp_path, StaticProvider(candidate()))
    service = application.state.extraction_service
    result = service.extract(record.document_id, AUTHORIZATION)
    assert isinstance(result, ExtractionResult)
    with pytest.raises(ValidationError):
        result.document_id = "another-document"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        result.licence.full_name.value = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.warnings.append("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        result.licence.full_name.warnings.append("changed")  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        result.licence.full_name.evidence.append(  # type: ignore[attr-defined]
            Evidence(document_id=record.document_id, page_number=1, source_text="changed")
        )
    with pytest.raises(AttributeError):
        result.licence.vehicle_classes.append(result.licence.full_name)  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        result.licence.other_information["changed"] = result.licence.full_name  # type: ignore[index]

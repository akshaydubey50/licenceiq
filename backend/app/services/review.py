"""Validated review derivation and atomic persistence for extracted licences."""

import unicodedata
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from app.core.errors import ApplicationError
from app.models.document import (
    ExtractedField,
    ExtractionResult,
    FieldsResult,
    ReviewedField,
    ReviewedLicence,
    ReviewedVehicleClasses,
    ReviewFields,
    ReviewState,
    ReviewUpdate,
)
from app.repositories.documents import DocumentRepository, StoredDocumentRecord
from app.schemas.common import ErrorCode
from app.services.documents import DocumentCredential, DocumentService

_PRIMARY_FIELDS = (
    "full_name",
    "licence_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "address",
    "issuing_authority",
)


class ReviewService:
    """Keep source extraction immutable while exposing durable reviewer corrections."""

    def __init__(
        self,
        repository: DocumentRepository,
        document_service: DocumentService,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.document_service = document_service
        self.now_provider = now_provider or (lambda: datetime.now(UTC))

    def get_fields(self, document_id: str, authorization: DocumentCredential) -> FieldsResult:
        record = self.document_service.authorized_record(document_id, authorization)
        extraction = self._require_extraction(record)
        return self._result(record, extraction)

    def update_fields(
        self,
        document_id: str,
        authorization: DocumentCredential,
        update: ReviewUpdate,
    ) -> FieldsResult:
        self._validate_document_id(document_id)
        snapshot = self.document_service.authorized_record(document_id, authorization)
        extraction = self._require_extraction(snapshot)
        self._validate_fields(update.fields, extraction)

        review = ReviewState(fields=update.fields, updated_at=self.now_provider())
        try:
            saved = self.repository.save_review_if_current(
                snapshot,
                review,
                review.updated_at,
            )
        except OSError as exc:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR,
                "The reviewed fields could not be saved. Please try again.",
                500,
            ) from exc
        if not saved:
            self.document_service.cleanup_expired()
            raise self.document_service.not_found()

        current = self.document_service.authorized_record(document_id, authorization)
        current_extraction = self._require_extraction(current)
        if current.review is None:
            raise self.document_service.not_found()
        return self._result(current, current_extraction)

    @staticmethod
    def _validate_document_id(document_id: str) -> None:
        try:
            canonical = str(UUID(document_id))
        except ValueError:
            canonical = ""
        if canonical != document_id:
            raise ReviewService.invalid_review()

    @staticmethod
    def _require_extraction(record: StoredDocumentRecord) -> ExtractionResult:
        if record.extraction is None:
            raise ApplicationError(
                ErrorCode.EXTRACTION_NOT_FOUND,
                "The document has not been extracted yet.",
                404,
            )
        return record.extraction

    @staticmethod
    def _validate_fields(fields: ReviewFields, extraction: ExtractionResult) -> None:
        expected_keys = set(extraction.licence.other_information)
        if set(fields.other_information) != expected_keys:
            raise ReviewService.invalid_review()

        normalized_vehicle_values = [
            ReviewService._normalize_vehicle(value) for value in fields.vehicle_classes
        ]
        if len(normalized_vehicle_values) != len(set(normalized_vehicle_values)):
            raise ReviewService.invalid_review()

    @staticmethod
    def _normalize_vehicle(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(normalized.split())

    @staticmethod
    def _result(
        record: StoredDocumentRecord,
        extraction: ExtractionResult,
    ) -> FieldsResult:
        source = extraction.licence
        stored = record.review.fields if record.review is not None else None

        primary: dict[str, ReviewedField] = {}
        for name in _PRIMARY_FIELDS:
            source_field = getattr(source, name)
            current_value = getattr(stored, name) if stored is not None else source_field.value
            primary[name] = ReviewService._reviewed_field(current_value, source_field)

        source_vehicles = tuple(
            item.value for item in source.vehicle_classes if item.value is not None
        )
        current_vehicles = stored.vehicle_classes if stored is not None else source_vehicles
        source_other = source.other_information
        current_other: Mapping[str, str | None] = (
            stored.other_information
            if stored is not None
            else {name: field.value for name, field in source_other.items()}
        )
        reviewed = ReviewedLicence(
            document_id=record.document_id,
            vehicle_classes=ReviewedVehicleClasses(
                current_value=current_vehicles,
                is_edited=current_vehicles != source_vehicles,
            ),
            other_information={
                name: ReviewService._reviewed_field(current_other[name], source_field)
                for name, source_field in source_other.items()
            },
            **primary,
        )
        return FieldsResult(
            document_id=record.document_id,
            extraction=extraction,
            reviewed=reviewed,
            updated_at=record.review.updated_at if record.review is not None else None,
        )

    @staticmethod
    def _reviewed_field(
        current_value: str | None,
        source_field: ExtractedField,
    ) -> ReviewedField:
        return ReviewedField(
            current_value=current_value,
            is_edited=current_value != source_field.value,
        )

    @staticmethod
    def invalid_review() -> ApplicationError:
        return ApplicationError(
            ErrorCode.INVALID_REVIEW,
            "The reviewed fields are invalid.",
            400,
        )

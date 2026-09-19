"""Bounded structured extraction with local evidence validation and caching."""

import threading
import time
import unicodedata
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.models.document import (
    Evidence,
    ExtractedField,
    ExtractedLicence,
    ExtractionResult,
    ExtractionStatus,
    ReadingResult,
)
from app.providers.extraction import (
    ExtractionBlock,
    ExtractionCandidate,
    ExtractionContext,
    ExtractionPage,
    FieldCandidate,
    LLMProvider,
)
from app.repositories.documents import DocumentRepository, StoredDocumentRecord
from app.schemas.common import ErrorCode
from app.services.documents import DocumentCredential, DocumentService

_MAX_CONCURRENT_EXTRACTIONS = 4
_PRIMARY_FIELD_NAMES = {
    "full_name",
    "licence_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "address",
    "vehicle_classes",
    "issuing_authority",
    "other_information",
}
_PRIMARY_FIELDS = (
    "full_name",
    "licence_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "address",
    "issuing_authority",
)
_UNSUPPORTED_WARNING = "This value could not be verified against the document reading."
_MULTIPLE_LICENCES_WARNING = (
    "More than one licence was detected. Upload a document containing a single licence."
)


class ExtractionService:
    """Extract one private reading and publish only locally supported fields."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        document_service: DocumentService,
        llm_provider: LLMProvider,
        now_provider: Callable[[], datetime] | None = None,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.document_service = document_service
        self.llm_provider = llm_provider
        self.now_provider = now_provider or (lambda: datetime.now(UTC))
        self.monotonic_provider = monotonic_provider or time.monotonic
        self._active_guard = threading.Lock()
        self._active_documents: set[str] = set()
        self._capacity = threading.BoundedSemaphore(_MAX_CONCURRENT_EXTRACTIONS)

    def extract(self, document_id: str, authorization: DocumentCredential) -> ExtractionResult:
        """Return a cached result or perform one bounded extraction for this document."""
        initial = self.document_service.authorized_record(document_id, authorization)
        self._require_reading(initial)
        if initial.extraction is not None:
            return initial.extraction

        self._begin_extraction(document_id)
        capacity_acquired = self._capacity.acquire(blocking=False)
        if not capacity_acquired:
            self._end_extraction(document_id)
            raise self._in_progress()
        try:
            # Recheck after claiming the slot so a just-published result becomes a cache hit.
            record = self.document_service.authorized_record(document_id, authorization)
            reading = self._require_reading(record)
            if record.extraction is not None:
                return record.extraction

            context = self._build_context(reading)
            deadline = self.monotonic_provider() + self.settings.extraction_timeout_seconds
            try:
                candidate = self.llm_provider.extract_structured_data(
                    context,
                    timeout_seconds=self._remaining(deadline),
                )
                candidate = ExtractionCandidate.model_validate(candidate)
            except ApplicationError:
                raise
            except (ValidationError, ValueError, TypeError, AttributeError):
                raise self._provider_error() from None
            except Exception:
                # Provider exceptions may contain private model output or document text.
                raise self._provider_error() from None
            self._check_deadline(deadline)

            result = self._validate_candidate(reading, candidate)
            self._check_deadline(deadline)
            try:
                published = self.repository.save_extraction_if_current(
                    record, result, self.now_provider()
                )
            except OSError as exc:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR,
                    "The licence extraction could not be saved. Please try again.",
                    500,
                ) from exc
            if not published:
                self.document_service.cleanup_expired()
                raise self.document_service.not_found()

            saved = self.document_service.authorized_record(document_id, authorization)
            if saved.extraction is None:
                raise self.document_service.not_found()
            return saved.extraction
        finally:
            self._capacity.release()
            self._end_extraction(document_id)

    def get_saved(self, document_id: str, authorization: DocumentCredential) -> ExtractionResult:
        """Retrieve the cached result without starting provider work."""
        record = self.document_service.authorized_record(document_id, authorization)
        self._require_reading(record)
        if record.extraction is None:
            raise ApplicationError(
                ErrorCode.EXTRACTION_NOT_FOUND,
                "The document has not been extracted yet.",
                404,
            )
        return record.extraction

    @staticmethod
    def _require_reading(record: StoredDocumentRecord) -> ReadingResult:
        if record.reading is None:
            raise ApplicationError(
                ErrorCode.READING_REQUIRED,
                "Read the document before starting structured extraction.",
                409,
            )
        return record.reading

    def _build_context(self, reading: ReadingResult) -> ExtractionContext:
        total_characters = 0
        pages: list[ExtractionPage] = []
        try:
            for page in reading.pages:
                blocks: list[ExtractionBlock] = []
                for evidence in page.blocks:
                    if evidence.block_id is None:
                        raise self._too_large()
                    total_characters += len(evidence.source_text)
                    if total_characters > self.settings.extraction_max_input_characters:
                        raise self._too_large()
                    blocks.append(
                        ExtractionBlock(block_id=evidence.block_id, text=evidence.source_text)
                    )
                pages.append(ExtractionPage(page_number=page.page_number, blocks=tuple(blocks)))
            return ExtractionContext(document_id=reading.document_id, pages=tuple(pages))
        except ApplicationError:
            raise
        except (ValidationError, ValueError, TypeError):
            # Transport bounds are stricter than reading storage bounds by design.
            raise self._too_large() from None

    def _validate_candidate(
        self, reading: ReadingResult, candidate: ExtractionCandidate
    ) -> ExtractionResult:
        evidence_by_id, evidence_order = self._evidence_index(reading)
        all_candidates = [
            *(getattr(candidate, name) for name in _PRIMARY_FIELDS),
            *candidate.vehicle_classes,
            *candidate.other_information,
        ]
        for field_candidate in all_candidates:
            self._validate_evidence_ids(field_candidate, evidence_by_id)
        self._validate_additional_names(candidate)

        created_at = self.now_provider()
        if candidate.multiple_licences_detected:
            return ExtractionResult(
                document_id=reading.document_id,
                status=ExtractionStatus.EXTRACTED_WITH_WARNINGS,
                licence=ExtractedLicence(document_id=reading.document_id),
                warnings=(_MULTIPLE_LICENCES_WARNING,),
                created_at=created_at,
            )

        extracted_primary = {
            name: self._validated_field(getattr(candidate, name), evidence_by_id, evidence_order)
            for name in _PRIMARY_FIELDS
        }
        vehicle_classes = tuple(
            self._validated_field(item, evidence_by_id, evidence_order)
            for item in candidate.vehicle_classes
        )
        other_information = {
            item.name: self._validated_field(item, evidence_by_id, evidence_order)
            for item in candidate.other_information
        }
        licence = ExtractedLicence(
            document_id=reading.document_id,
            vehicle_classes=vehicle_classes,
            other_information=other_information,
            **extracted_primary,
        )
        has_warnings = any(field.warnings for field in self._all_fields(licence))
        return ExtractionResult(
            document_id=reading.document_id,
            status=(
                ExtractionStatus.EXTRACTED_WITH_WARNINGS
                if has_warnings
                else ExtractionStatus.EXTRACTED
            ),
            licence=licence,
            warnings=(
                ("Some values were left blank because their evidence could not be verified.",)
                if has_warnings
                else ()
            ),
            created_at=created_at,
        )

    @staticmethod
    def _evidence_index(
        reading: ReadingResult,
    ) -> tuple[dict[str, Evidence], dict[str, int]]:
        evidence_by_id: dict[str, Evidence] = {}
        evidence_order: dict[str, int] = {}
        for page in reading.pages:
            for evidence in page.blocks:
                if evidence.block_id is None or evidence.block_id in evidence_by_id:
                    raise ExtractionService._provider_error()
                evidence_order[evidence.block_id] = len(evidence_order)
                evidence_by_id[evidence.block_id] = evidence
        return evidence_by_id, evidence_order

    @staticmethod
    def _validate_evidence_ids(
        candidate: FieldCandidate, evidence_by_id: dict[str, Evidence]
    ) -> None:
        if candidate.value is None:
            if candidate.raw_value is not None or candidate.block_ids:
                raise ExtractionService._provider_error()
            return
        if candidate.raw_value is None or not candidate.block_ids:
            raise ExtractionService._provider_error()
        if len(candidate.block_ids) != len(set(candidate.block_ids)):
            raise ExtractionService._provider_error()
        if any(block_id not in evidence_by_id for block_id in candidate.block_ids):
            raise ExtractionService._provider_error()

    @staticmethod
    def _validate_additional_names(candidate: ExtractionCandidate) -> None:
        seen: set[str] = set()
        for item in candidate.other_information:
            normalized_name = item.name.strip().casefold()
            if not normalized_name or normalized_name in _PRIMARY_FIELD_NAMES:
                raise ExtractionService._provider_error()
            if normalized_name in seen:
                raise ExtractionService._provider_error()
            seen.add(normalized_name)

    @staticmethod
    def _validated_field(
        candidate: FieldCandidate,
        evidence_by_id: dict[str, Evidence],
        evidence_order: dict[str, int],
    ) -> ExtractedField:
        if candidate.value is None:
            return ExtractedField()
        evidence = tuple(
            evidence_by_id[block_id]
            for block_id in sorted(candidate.block_ids, key=evidence_order.__getitem__)
        )
        source = " ".join(item.source_text for item in evidence)
        if not (
            ExtractionService._is_supported(candidate.value, source)
            and candidate.raw_value is not None
            and ExtractionService._is_supported(candidate.raw_value, source)
        ):
            return ExtractedField(warnings=(_UNSUPPORTED_WARNING,))
        return ExtractedField(
            value=candidate.value,
            raw_value=candidate.raw_value,
            evidence=evidence,
        )

    @staticmethod
    def _is_supported(value: str, source: str) -> bool:
        normalized_value = ExtractionService._normalize_for_support(value)
        normalized_source = ExtractionService._normalize_for_support(source)
        return bool(normalized_value) and normalized_value in normalized_source

    @staticmethod
    def _normalize_for_support(value: str) -> str:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return "".join(
            character
            for character in normalized
            if not character.isspace() and not unicodedata.category(character).startswith("P")
        )

    @staticmethod
    def _all_fields(licence: ExtractedLicence) -> Iterable[ExtractedField]:
        yield licence.full_name
        yield licence.licence_number
        yield licence.date_of_birth
        yield licence.date_of_issue
        yield licence.date_of_expiry
        yield licence.address
        yield from licence.vehicle_classes
        yield licence.issuing_authority
        yield from licence.other_information.values()

    def _begin_extraction(self, document_id: str) -> None:
        with self._active_guard:
            if document_id in self._active_documents:
                raise self._in_progress()
            self._active_documents.add(document_id)

    def _end_extraction(self, document_id: str) -> None:
        with self._active_guard:
            self._active_documents.discard(document_id)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.monotonic_provider()
        if remaining <= 0:
            raise self._timeout()
        return remaining

    def _check_deadline(self, deadline: float) -> None:
        _ = self._remaining(deadline)

    @staticmethod
    def _in_progress() -> ApplicationError:
        return ApplicationError(
            ErrorCode.EXTRACTION_IN_PROGRESS,
            "This document is already being extracted. Please try again shortly.",
            409,
        )

    @staticmethod
    def _provider_error() -> ApplicationError:
        return ApplicationError(
            ErrorCode.EXTRACTION_PROVIDER_ERROR,
            "The licence extraction service could not process this document. Please try again.",
            502,
        )

    @staticmethod
    def _timeout() -> ApplicationError:
        return ApplicationError(
            ErrorCode.EXTRACTION_TIMEOUT,
            "Licence extraction took too long. Please try again.",
            504,
        )

    @staticmethod
    def _too_large() -> ApplicationError:
        return ApplicationError(
            ErrorCode.EXTRACTION_TOO_LARGE,
            "The document reading is too large for structured extraction.",
            422,
        )

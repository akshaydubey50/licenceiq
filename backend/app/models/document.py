"""Initial document and evidence contracts mirrored by frontend domain types."""

import math
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)


class DomainModel(BaseModel):
    """Reject accidental schema drift at domain boundaries."""

    model_config = ConfigDict(extra="forbid")


class ProcessingStatus(StrEnum):
    """The document lifecycle; no transitions are executed in Phase 0."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
    FAILED = "FAILED"


class ReadingStatus(StrEnum):
    """Outcome of page reading without implying structured extraction."""

    READ = "READ"
    READ_WITH_WARNINGS = "READ_WITH_WARNINGS"


class ExtractionStatus(StrEnum):
    """Outcome of evidence validation for one cached structured extraction."""

    EXTRACTED = "EXTRACTED"
    EXTRACTED_WITH_WARNINGS = "EXTRACTED_WITH_WARNINGS"


class QuestionStatus(StrEnum):
    """Whether one ephemeral answer is supported by the source document."""

    ANSWERED = "ANSWERED"
    UNAVAILABLE = "UNAVAILABLE"


NormalizedCoordinate = Annotated[float, Field(ge=0, le=1)]


class Evidence(DomainModel):
    """An excerpt tied to its source document and one-based page number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page_number: int = Field(ge=1)
    source_text: str
    block_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: (
        tuple[
            NormalizedCoordinate,
            NormalizedCoordinate,
            NormalizedCoordinate,
            NormalizedCoordinate,
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_bounding_box(self) -> "Evidence":
        """Keep optional boxes normalized and ordered for future providers."""
        if self.bounding_box is not None:
            left, top, right, bottom = self.bounding_box
            if left > right or top > bottom:
                raise ValueError("Bounding-box coordinates must be ordered.")
        return self


class DocumentPage(DomainModel):
    """Normalized page text and immutable source evidence from one read method."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    page_number: int = Field(ge=1)
    text: str = ""
    blocks: tuple[Evidence, ...] = ()
    method: Literal["native_text", "ocr"]


class ReadingResult(DomainModel):
    """Saved page-level reading for one private document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    status: ReadingStatus
    pages: tuple[DocumentPage, ...]
    warnings: tuple[str, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def validate_page_identity(self) -> "ReadingResult":
        """Reject cross-document, duplicated, or out-of-order evidence."""
        expected_pages = tuple(range(1, len(self.pages) + 1))
        actual_pages = tuple(page.page_number for page in self.pages)
        if actual_pages != expected_pages:
            raise ValueError("Reading pages must be one-based and contiguous.")
        for page in self.pages:
            if page.document_id != self.document_id:
                raise ValueError("Reading pages must belong to the reading document.")
            for block in page.blocks:
                if block.document_id != self.document_id or block.page_number != page.page_number:
                    raise ValueError("Evidence must belong to its containing page.")
        return self


class SemanticIndex(DomainModel):
    """Private vectors tied to one exact immutable reading and provider configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document_id: str
    reading_sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    model: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    dimensions: int = Field(ge=1, le=3072)
    block_ids: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200)], ...]
    vectors: tuple[tuple[float, ...], ...]

    @model_validator(mode="after")
    def validate_vectors(self) -> "SemanticIndex":
        """Reject partial, reordered, malformed, non-finite, or unusable vector data."""
        if not self.block_ids or len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("Semantic index block IDs must be nonempty and unique.")
        if len(self.vectors) != len(self.block_ids):
            raise ValueError("Semantic index vector count must match its block IDs.")
        for vector in self.vectors:
            if len(vector) != self.dimensions:
                raise ValueError("Semantic index vectors must match the configured dimensions.")
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("Semantic index vectors must contain finite values.")
            if not any(value != 0 for value in vector):
                raise ValueError("Semantic index vectors must be nonzero.")
        return self


class ExtractedField(DomainModel):
    """Keep the AI value, source text, and human-reviewed value distinguishable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: str | None = None
    raw_value: str | None = None
    evidence: tuple[Evidence, ...] = ()
    current_value: str | None = None
    is_edited: bool = False
    warnings: tuple[str, ...] = ()


class ExtractedLicence(DomainModel):
    """Nullable licence fields; sample values are never baked into these defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    full_name: ExtractedField = Field(default_factory=ExtractedField)
    licence_number: ExtractedField = Field(default_factory=ExtractedField)
    date_of_birth: ExtractedField = Field(default_factory=ExtractedField)
    date_of_issue: ExtractedField = Field(default_factory=ExtractedField)
    date_of_expiry: ExtractedField = Field(default_factory=ExtractedField)
    address: ExtractedField = Field(default_factory=ExtractedField)
    vehicle_classes: tuple[ExtractedField, ...] = ()
    issuing_authority: ExtractedField = Field(default_factory=ExtractedField)
    other_information: Mapping[str, ExtractedField] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_evidence_identity(self) -> "ExtractedLicence":
        """Prevent evidence from another document entering a final extraction."""
        object.__setattr__(
            self,
            "other_information",
            MappingProxyType(dict(self.other_information)),
        )
        fields = [
            self.full_name,
            self.licence_number,
            self.date_of_birth,
            self.date_of_issue,
            self.date_of_expiry,
            self.address,
            *self.vehicle_classes,
            self.issuing_authority,
            *self.other_information.values(),
        ]
        if any(
            evidence.document_id != self.document_id
            for extracted_field in fields
            for evidence in extracted_field.evidence
        ):
            raise ValueError("Extraction evidence must belong to the extraction document.")
        return self

    @field_serializer("other_information")
    def serialize_other_information(
        self, value: Mapping[str, ExtractedField]
    ) -> dict[str, ExtractedField]:
        """Expose the immutable mapping through the existing JSON object shape."""
        return dict(value)


class ExtractionResult(DomainModel):
    """Immutable final structured extraction cached with its private document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    status: ExtractionStatus
    licence: ExtractedLicence
    warnings: tuple[str, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def validate_document_identity(self) -> "ExtractionResult":
        if self.licence.document_id != self.document_id:
            raise ValueError("The extracted licence must belong to the result document.")
        return self


ReviewText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
]


class ReviewFields(DomainModel):
    """One complete, validated set of reviewer-entered values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    full_name: ReviewText | None
    licence_number: ReviewText | None
    date_of_birth: ReviewText | None
    date_of_issue: ReviewText | None
    date_of_expiry: ReviewText | None
    address: ReviewText | None
    vehicle_classes: tuple[ReviewText, ...] = Field(max_length=100)
    issuing_authority: ReviewText | None
    other_information: Mapping[str, ReviewText | None] = Field(max_length=100)

    @model_validator(mode="after")
    def freeze_other_information(self) -> "ReviewFields":
        """Prevent stored reviewer values from being mutated through a shared mapping."""
        object.__setattr__(
            self,
            "other_information",
            MappingProxyType(dict(self.other_information)),
        )
        return self

    @field_serializer("other_information")
    def serialize_other_information(self, value: Mapping[str, str | None]) -> dict[str, str | None]:
        return dict(value)


class ReviewUpdate(DomainModel):
    """Require the browser to submit one complete review under ``fields``."""

    fields: ReviewFields


class ReviewState(DomainModel):
    """Durable reviewer state kept separate from immutable extraction facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: ReviewFields
    updated_at: datetime


class ReviewedField(DomainModel):
    """A current reviewer value and its server-derived provenance flag."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_value: str | None
    is_edited: bool


class ReviewedVehicleClasses(DomainModel):
    """The ordered vehicle-class review and its aggregate edited state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_value: tuple[str, ...]
    is_edited: bool


class ReviewedLicence(DomainModel):
    """Reviewer-facing values derived without copying extraction evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    full_name: ReviewedField
    licence_number: ReviewedField
    date_of_birth: ReviewedField
    date_of_issue: ReviewedField
    date_of_expiry: ReviewedField
    address: ReviewedField
    vehicle_classes: ReviewedVehicleClasses
    issuing_authority: ReviewedField
    other_information: Mapping[str, ReviewedField]

    @model_validator(mode="after")
    def freeze_other_information(self) -> "ReviewedLicence":
        object.__setattr__(
            self,
            "other_information",
            MappingProxyType(dict(self.other_information)),
        )
        return self

    @field_serializer("other_information")
    def serialize_other_information(
        self, value: Mapping[str, ReviewedField]
    ) -> dict[str, ReviewedField]:
        return dict(value)


class FieldsResult(DomainModel):
    """Immutable extraction plus a separately derived or stored review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    extraction: ExtractionResult
    reviewed: ReviewedLicence
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_document_identity(self) -> "FieldsResult":
        if (
            self.extraction.document_id != self.document_id
            or self.reviewed.document_id != self.document_id
        ):
            raise ValueError("Extraction and review must belong to the result document.")
        return self


QuestionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class QuestionRequest(DomainModel):
    """One bounded question; unknown request fields remain invalid."""

    question: QuestionText


class QuestionCitation(DomainModel):
    """A public source pointer without repeating private document text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    block_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    page_number: int = Field(ge=1)


class QuestionResult(DomainModel):
    """An ephemeral grounded answer that is never persisted by the backend."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    question: QuestionText
    status: QuestionStatus
    answer: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    citations: tuple[QuestionCitation, ...] = Field(max_length=20)
    created_at: datetime

    @model_validator(mode="after")
    def validate_answer_and_citations(self) -> "QuestionResult":
        unavailable = "I couldn't find that in this document."
        if self.status is QuestionStatus.ANSWERED:
            if not self.answer.strip() or not self.citations:
                raise ValueError("Answered questions require text and citations.")
        elif self.answer != unavailable or self.citations:
            raise ValueError("Unavailable questions use the fixed safe answer without citations.")
        return self


class Document(DomainModel):
    """Client-safe metadata: storage paths and provider secrets never belong here."""

    document_id: str
    filename: str
    mime_type: Literal["application/pdf", "image/png", "image/jpeg"]
    size_bytes: int = Field(ge=0)
    status: ProcessingStatus = ProcessingStatus.UPLOADED
    created_at: datetime
    page_count: int | None = Field(default=None, ge=1)
    warnings: list[str] = Field(default_factory=list)


class DocumentUploadResponse(Document):
    """Upload result with a capability only for capability or hybrid guest uploads."""

    access_token: str | None = None

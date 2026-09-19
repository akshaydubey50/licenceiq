"""Typed transport contract for structured extraction providers."""

from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200)]
CandidateText = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
AdditionalFieldName = Annotated[str, StringConstraints(min_length=1, max_length=100)]


class _StrictTransportModel(BaseModel):
    """Reject coercion and unknown fields at the provider boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ExtractionBlock(_StrictTransportModel):
    """One stored reading block made available to the extraction model."""

    block_id: Identifier
    text: Annotated[str, StringConstraints(min_length=1, max_length=16_000)]


class ExtractionPage(_StrictTransportModel):
    """Ordered blocks from one one-based document page."""

    page_number: int = Field(ge=1, le=1000)
    blocks: tuple[ExtractionBlock, ...] = Field(max_length=2000)


class ExtractionContext(_StrictTransportModel):
    """Private reading content supplied to a provider, independent of storage."""

    document_id: Identifier
    pages: tuple[ExtractionPage, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_order_and_identity(self) -> "ExtractionContext":
        """Require ordered pages and globally unique evidence identifiers."""
        page_numbers = tuple(page.page_number for page in self.pages)
        if page_numbers != tuple(sorted(page_numbers)) or len(set(page_numbers)) != len(
            page_numbers
        ):
            raise ValueError("Extraction pages must be unique and ordered.")
        block_ids = [block.block_id for page in self.pages for block in page.blocks]
        if not block_ids:
            raise ValueError("Extraction context must contain at least one reading block.")
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Extraction block IDs must be unique.")
        return self


class FieldCandidate(_StrictTransportModel):
    """A source-formatted candidate and the reading blocks that support it."""

    value: CandidateText | None
    raw_value: CandidateText | None
    block_ids: tuple[Identifier, ...] = Field(max_length=50)

    @model_validator(mode="after")
    def validate_null_and_evidence(self) -> "FieldCandidate":
        """Keep missing values empty and present values evidence-backed."""
        if self.value is None:
            if self.raw_value is not None or self.block_ids:
                raise ValueError("A missing candidate cannot contain source evidence.")
        elif self.raw_value is None or not self.block_ids:
            raise ValueError("A present candidate requires raw text and block IDs.")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("Candidate block IDs must be unique.")
        return self


class AdditionalFieldCandidate(FieldCandidate):
    """A directly stated relevant fact outside the primary licence fields."""

    name: AdditionalFieldName


class ExtractionCandidate(_StrictTransportModel):
    """Strict model output before deterministic source-evidence validation."""

    full_name: FieldCandidate
    licence_number: FieldCandidate
    date_of_birth: FieldCandidate
    date_of_issue: FieldCandidate
    date_of_expiry: FieldCandidate
    address: FieldCandidate
    issuing_authority: FieldCandidate
    vehicle_classes: tuple[FieldCandidate, ...] = Field(max_length=100)
    other_information: tuple[AdditionalFieldCandidate, ...] = Field(max_length=100)
    multiple_licences_detected: bool


class LLMProvider(Protocol):
    """Extract candidates from one document reading within a caller time budget."""

    def extract_structured_data(
        self,
        context: ExtractionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> ExtractionCandidate: ...

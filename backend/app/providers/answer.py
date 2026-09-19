"""Strict provider-neutral transport for grounded document answers."""

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.document import QuestionText

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=200)]
SAFE_UNAVAILABLE_ANSWER = "I couldn't find that in this document."


class _StrictTransportModel(BaseModel):
    """Reject coercion and unknown data at the answer-provider boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class QuestionBlock(_StrictTransportModel):
    """One selected reading block made available to the answer provider."""

    block_id: Identifier
    page_number: int = Field(ge=1, le=1000)
    text: Annotated[str, StringConstraints(min_length=1, max_length=16_000)]


class QuestionContext(_StrictTransportModel):
    """The only private context supplied for one provider answer."""

    question: QuestionText
    blocks: tuple[QuestionBlock, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_blocks(self) -> "QuestionContext":
        block_ids = tuple(block.block_id for block in self.blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("Question block IDs must be unique.")
        return self


class AnswerCandidate(_StrictTransportModel):
    """Strict model output before current-document citation validation."""

    status: Literal["ANSWERED", "UNAVAILABLE"]
    answer: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    block_ids: tuple[Identifier, ...] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_status_shape(self) -> "AnswerCandidate":
        if self.status == "ANSWERED":
            if self.answer != self.answer.strip() or not self.block_ids:
                raise ValueError("Answered output requires trimmed text and citations.")
        elif self.answer != SAFE_UNAVAILABLE_ANSWER or self.block_ids:
            raise ValueError("Unavailable output must use the fixed safe response.")
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("Answer citations must be unique.")
        return self


class AnswerProvider(Protocol):
    """Answer from selected source blocks within the caller's remaining budget."""

    def answer_question(
        self,
        context: QuestionContext,
        *,
        timeout_seconds: float | None = None,
    ) -> AnswerCandidate: ...

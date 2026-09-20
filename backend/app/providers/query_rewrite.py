"""Strict provider-neutral contracts for retrieval-only query rewriting."""

from enum import StrEnum
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.models.document import QuestionText


class QueryIntent(StrEnum):
    """Controlled retrieval intents; none authorizes answering the question."""

    LOOKUP = "LOOKUP"
    FOLLOW_UP = "FOLLOW_UP"
    CLARIFICATION = "CLARIFICATION"


class _StrictRewriteModel(BaseModel):
    """Reject coercion and unknown values at the rewrite-provider boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class QueryRewriteRequest(_StrictRewriteModel):
    """Only the current question and bounded prior user questions may leave the service."""

    question: QuestionText
    previous_questions: tuple[QuestionText, ...] = Field(min_length=1, max_length=3)


class QueryRewriteResult(_StrictRewriteModel):
    """A concise retrieval query, never an answer or evidence container."""

    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    intent: QueryIntent


class QueryRewriteProvider(Protocol):
    """Resolve conversational references without receiving document contents."""

    def rewrite(
        self,
        request: QueryRewriteRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> QueryRewriteResult: ...

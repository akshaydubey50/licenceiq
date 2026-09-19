"""Strict provider-neutral transport for temporary semantic retrieval vectors."""

import math
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class _StrictEmbeddingModel(BaseModel):
    """Reject coercion and unknown values at the embedding-provider boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EmbeddingRequest(_StrictEmbeddingModel):
    """One ordered, bounded collection of untrusted plain-text inputs."""

    texts: tuple[Annotated[str, StringConstraints(min_length=1, max_length=200_000)], ...] = Field(
        min_length=1, max_length=2000
    )


class EmbeddingResult(_StrictEmbeddingModel):
    """Validated vectors in the same order as the submitted request texts."""

    model: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    dimensions: int = Field(ge=1, le=3072)
    vectors: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_vectors(self) -> "EmbeddingResult":
        for vector in self.vectors:
            if len(vector) != self.dimensions:
                raise ValueError("Embedding vectors must match the declared dimensions.")
            if not all(math.isfinite(value) for value in vector):
                raise ValueError("Embedding vectors must contain finite values.")
            if not any(value != 0 for value in vector):
                raise ValueError("Embedding vectors must be nonzero.")
        return self


class EmbeddingProvider(Protocol):
    """Embed ordered text without receiving document files or other private state."""

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult: ...

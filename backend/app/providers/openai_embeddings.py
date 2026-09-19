"""OpenAI embeddings adapter with bounded input and strict response validation."""

import logging

from openai import APIError, APITimeoutError, OpenAI
from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.providers.embeddings import EmbeddingRequest, EmbeddingResult
from app.schemas.common import ErrorCode

logging.getLogger("openai").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class OpenAIEmbeddingProvider:
    """Send only ordered reading text or one active question to the Embeddings API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float | None = None,
    ) -> EmbeddingResult:
        key = self.settings.openai_api_key.get_secret_value().strip()
        if not key:
            raise ApplicationError(
                ErrorCode.QUESTION_NOT_CONFIGURED,
                "Document questions need an OpenAI API key configured on the server.",
                503,
            )
        if (
            len(request.texts) > self.settings.question_embedding_max_blocks
            or sum(len(text) for text in request.texts)
            > self.settings.question_embedding_max_characters
        ):
            raise self._too_large()

        timeout = min(
            self.settings.question_embedding_timeout_seconds,
            timeout_seconds
            if timeout_seconds is not None
            else self.settings.question_embedding_timeout_seconds,
        )
        if timeout <= 0:
            raise self._timeout()

        try:
            with OpenAI(api_key=key, timeout=timeout, max_retries=0) as client:
                response = client.embeddings.create(
                    input=list(request.texts),
                    model=self.settings.question_embedding_model,
                    dimensions=self.settings.question_embedding_dimensions,
                    encoding_format="float",
                )
            if len(response.data) != len(request.texts):
                raise self._provider_error()
            by_index = {item.index: tuple(item.embedding) for item in response.data}
            if set(by_index) != set(range(len(request.texts))):
                raise self._provider_error()
            return EmbeddingResult(
                model=self.settings.question_embedding_model,
                dimensions=self.settings.question_embedding_dimensions,
                vectors=tuple(by_index[index] for index in range(len(request.texts))),
            )
        except APITimeoutError:
            raise self._timeout() from None
        except ApplicationError:
            raise
        except (APIError, ValidationError, ValueError, TypeError, AttributeError):
            raise self._provider_error() from None

    @staticmethod
    def _provider_error() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_PROVIDER_ERROR,
            "The document question service could not prepare this question. Please try again.",
            502,
        )

    @staticmethod
    def _timeout() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_TIMEOUT,
            "The document question took too long. Please try again.",
            504,
        )

    @staticmethod
    def _too_large() -> ApplicationError:
        return ApplicationError(
            ErrorCode.QUESTION_TOO_LARGE,
            "The document evidence is too large to prepare safely.",
            422,
        )

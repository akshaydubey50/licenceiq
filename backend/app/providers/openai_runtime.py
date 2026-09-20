"""Safe, document-free OpenAI reachability checks for local operator startup."""

from dataclasses import dataclass

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI

from app.core.config import Settings

_PREFLIGHT_INPUT = "Reply with exactly the word READY."
_PREFLIGHT_TIMEOUT_SECONDS = 15.0
_PREFLIGHT_MAX_OUTPUT_TOKENS = 16


class OpenAIRuntimeCheckError(RuntimeError):
    """A safe startup failure that contains no credential, provider body, or document data."""


@dataclass(frozen=True, slots=True)
class OpenAIRuntimeCheck:
    """The bounded result of one successful OpenAI OCR-model reachability check."""

    model: str


def verify_openai_ocr_runtime(settings: Settings) -> OpenAIRuntimeCheck:
    """Verify key, network, and configured OCR model without sending a document."""
    key = settings.openai_api_key.get_secret_value().strip()
    if not key:
        raise OpenAIRuntimeCheckError("OPENAI_API_KEY is not configured.")

    timeout = min(settings.ocr_timeout_seconds, _PREFLIGHT_TIMEOUT_SECONDS)
    try:
        with OpenAI(api_key=key, timeout=timeout, max_retries=0) as client:
            response = client.responses.create(
                model=settings.ocr_model,
                input=_PREFLIGHT_INPUT,
                max_output_tokens=_PREFLIGHT_MAX_OUTPUT_TOKENS,
                store=False,
            )
    except APITimeoutError:
        raise OpenAIRuntimeCheckError("The OpenAI OCR preflight timed out.") from None
    except APIConnectionError:
        message = "The OpenAI OCR preflight could not reach the provider."
        raise OpenAIRuntimeCheckError(message) from None
    except APIStatusError as error:
        request_id = getattr(error, "request_id", None)
        suffix = f" Request ID: {request_id}." if request_id else ""
        raise OpenAIRuntimeCheckError(
            f"The OpenAI OCR preflight received HTTP {error.status_code}.{suffix}"
        ) from None
    except APIError:
        raise OpenAIRuntimeCheckError("The OpenAI OCR preflight received an API error.") from None
    except (ValueError, TypeError, AttributeError):
        message = "The OpenAI OCR preflight received an invalid response."
        raise OpenAIRuntimeCheckError(message) from None

    if response.status != "completed":
        raise OpenAIRuntimeCheckError("The OpenAI OCR preflight did not complete.")
    return OpenAIRuntimeCheck(model=settings.ocr_model)

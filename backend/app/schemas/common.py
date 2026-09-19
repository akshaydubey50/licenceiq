"""Small shared contracts for health and controlled errors."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness only; this does not assert that future providers are available."""

    status: Literal["ok"] = "ok"


class ErrorCode(StrEnum):
    """Stable public failure categories used by the browser client."""

    INVALID_REQUEST = "INVALID_REQUEST"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    INVALID_FILE = "INVALID_FILE"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    DOCUMENT_NOT_FOUND = "DOCUMENT_NOT_FOUND"
    READING_NOT_FOUND = "READING_NOT_FOUND"
    READING_IN_PROGRESS = "READING_IN_PROGRESS"
    NO_READABLE_TEXT = "NO_READABLE_TEXT"
    OCR_NOT_CONFIGURED = "OCR_NOT_CONFIGURED"
    OCR_PROVIDER_ERROR = "OCR_PROVIDER_ERROR"
    OCR_TIMEOUT = "OCR_TIMEOUT"
    READING_TOO_LARGE = "READING_TOO_LARGE"
    READING_REQUIRED = "READING_REQUIRED"
    EXTRACTION_NOT_FOUND = "EXTRACTION_NOT_FOUND"
    EXTRACTION_IN_PROGRESS = "EXTRACTION_IN_PROGRESS"
    EXTRACTION_NOT_CONFIGURED = "EXTRACTION_NOT_CONFIGURED"
    EXTRACTION_PROVIDER_ERROR = "EXTRACTION_PROVIDER_ERROR"
    EXTRACTION_TIMEOUT = "EXTRACTION_TIMEOUT"
    EXTRACTION_TOO_LARGE = "EXTRACTION_TOO_LARGE"
    INVALID_REVIEW = "INVALID_REVIEW"
    INVALID_QUESTION = "INVALID_QUESTION"
    QUESTION_IN_PROGRESS = "QUESTION_IN_PROGRESS"
    QUESTION_NOT_CONFIGURED = "QUESTION_NOT_CONFIGURED"
    QUESTION_PROVIDER_ERROR = "QUESTION_PROVIDER_ERROR"
    QUESTION_TIMEOUT = "QUESTION_TIMEOUT"
    QUESTION_TOO_LARGE = "QUESTION_TOO_LARGE"


class ErrorDetail(BaseModel):
    """A safe, client-facing error without request bodies or stack traces."""

    code: ErrorCode
    message: str


class ErrorResponse(BaseModel):
    """Consistent error envelope with a correlation identifier."""

    error: ErrorDetail
    request_id: str

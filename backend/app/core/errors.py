"""Map application and framework failures to a stable public error envelope."""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.schemas.common import ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


class ApplicationError(Exception):
    """A deliberately public error raised by future service-layer operations."""

    def __init__(self, code: ErrorCode, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def error_response(
    request: Request, *, code: ErrorCode, message: str, status_code: int
) -> JSONResponse:
    """Build an error without including potentially sensitive input values."""
    request_id = getattr(request.state, "request_id", str(uuid4()))
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message), request_id=request_id)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Log only safe metadata and hide exception text from both client and server logs."""
    logger.error(
        "Unexpected API error: request_id=%s exception_type=%s",
        getattr(request.state, "request_id", "unavailable"),
        type(exc).__name__,
    )
    return error_response(
        request,
        code=ErrorCode.INTERNAL_ERROR,
        message="Something went wrong. Please try again.",
        status_code=500,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install sanitized handlers in one place, keeping API routes thin."""

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError) -> JSONResponse:
        return error_response(
            request, code=exc.code, message=exc.message, status_code=exc.status_code
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request,
            code=ErrorCode.INVALID_REQUEST,
            message="The request contains invalid or missing information.",
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        response = error_response(
            request,
            code=ErrorCode.HTTP_ERROR,
            message=str(exc.detail),
            status_code=exc.status_code,
        )
        # Preserve protocol headers such as Allow on a 405 response.
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        return unexpected_error_response(request, exc)

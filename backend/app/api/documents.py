"""Thin HTTP routes for the Phase 1 document service."""

from typing import Annotated, cast

from fastapi import APIRouter, File, Header, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.core.errors import ApplicationError
from app.models.document import (
    Document,
    DocumentUploadResponse,
    ExtractionResult,
    FieldsResult,
    QuestionRequest,
    QuestionResult,
    ReadingResult,
    ReviewUpdate,
)
from app.schemas.common import ErrorCode
from app.services.documents import DocumentService
from app.services.extraction import ExtractionService
from app.services.questions import QuestionService
from app.services.reading import ReadingService
from app.services.review import ReviewService

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _service(request: Request) -> DocumentService:
    return cast(DocumentService, request.app.state.document_service)


def _reading_service(request: Request) -> ReadingService:
    return cast(ReadingService, request.app.state.reading_service)


def _extraction_service(request: Request) -> ExtractionService:
    return cast(ExtractionService, request.app.state.extraction_service)


def _review_service(request: Request) -> ReviewService:
    document_service = _service(request)
    return ReviewService(
        document_service.repository,
        document_service,
        document_service.now_provider,
    )


def _question_service(request: Request) -> QuestionService:
    return cast(QuestionService, request.app.state.question_service)


def _safe_content_disposition(filename: str) -> str:
    """Use RFC 5987 encoding so filenames cannot inject response headers."""
    from urllib.parse import quote

    ascii_fallback = "".join(
        c if 32 <= ord(c) < 127 and c not in {'"', "\\"} else "_" for c in filename
    )
    return f"inline; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.post("", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    form = await request.form()
    parts = list(form.multi_items())
    if len(parts) != 1 or parts[0][0] != "file" or parts[0][1] is not file:
        raise ApplicationError(
            ErrorCode.INVALID_REQUEST,
            "Upload exactly one file using the file field.",
            400,
        )
    result = await _service(request).upload(file, authorization)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=result.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{document_id}", response_model=Document)
def get_document(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    result = _service(request).get(document_id, authorization)
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.post("/{document_id}/read", response_model=ReadingResult)
async def read_document(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    result = await run_in_threadpool(_reading_service(request).read, document_id, authorization)
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.get("/{document_id}/reading", response_model=ReadingResult)
def get_document_reading(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    result = _reading_service(request).get_saved(document_id, authorization)
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.post("/{document_id}/extract", response_model=ExtractionResult)
async def extract_document(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    result = await run_in_threadpool(
        _extraction_service(request).extract, document_id, authorization
    )
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.get("/{document_id}/extraction", response_model=ExtractionResult)
def get_document_extraction(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    result = _extraction_service(request).get_saved(document_id, authorization)
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.get("/{document_id}/fields", response_model=FieldsResult)
def get_document_fields(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    result = _review_service(request).get_fields(document_id, authorization)
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.put("/{document_id}/fields", response_model=FieldsResult)
async def update_document_fields(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    try:
        payload = await request.json()
        update = ReviewUpdate.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        raise ReviewService.invalid_review() from None
    result = await run_in_threadpool(
        _review_service(request).update_fields,
        document_id,
        authorization,
        update,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.get("/{document_id}/file")
def get_document_file(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    record, content = _service(request).get_file(document_id, authorization)
    return StreamingResponse(
        iter([content]),
        media_type=record.mime_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": _safe_content_disposition(record.filename),
        },
    )


@router.post("/{document_id}/questions", response_model=QuestionResult)
async def ask_document_question(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    try:
        payload = await request.json()
        question = QuestionRequest.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        raise QuestionService.invalid_question() from None
    result = await run_in_threadpool(
        _question_service(request).ask,
        document_id,
        authorization,
        question,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    request: Request,
    document_id: str,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    _service(request).delete(document_id, authorization)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})

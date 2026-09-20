"""Application factory for the LicenceIQ API."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.core.auth import AuthConfig, AuthService
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers, unexpected_error_response
from app.core.upload_limit import UploadBodyLimitMiddleware
from app.providers.answer import AnswerProvider
from app.providers.embeddings import EmbeddingProvider
from app.providers.extraction import LLMProvider
from app.providers.ocr import OCRProvider
from app.providers.openai_answer import OpenAIAnswerProvider
from app.providers.openai_embeddings import OpenAIEmbeddingProvider
from app.providers.openai_extraction import OpenAIExtractionProvider
from app.providers.openai_ocr import OpenAIOCRProvider
from app.repositories.documents import (
    DocumentRepository,
    FilesystemDocumentRepository,
    MinioDocumentRepository,
)
from app.repositories.object_store import MinioObjectStore
from app.services.documents import DocumentService
from app.services.extraction import ExtractionService
from app.services.question_guardrails import QuestionGuardrail, build_question_guardrail
from app.services.questions import QuestionService
from app.services.reading import ReadingService


def create_app(
    settings: Settings | None = None,
    *,
    now_provider: Callable[[], datetime] | None = None,
    ocr_provider: OCRProvider | None = None,
    llm_provider: LLMProvider | None = None,
    answer_provider: AnswerProvider | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    question_guardrail: QuestionGuardrail | None = None,
) -> FastAPI:
    """Compose configuration, storage, cross-cutting handlers, and routes."""
    config = settings if settings is not None else get_settings()
    repository = _build_document_repository(config)
    auth_service = _build_auth_service(config, now_provider)
    document_service = DocumentService(config, repository, now_provider, auth_service)
    reading_service = ReadingService(
        config,
        repository,
        document_service,
        ocr_provider if ocr_provider is not None else OpenAIOCRProvider(config),
        now_provider,
    )
    extraction_service = ExtractionService(
        config,
        repository,
        document_service,
        llm_provider if llm_provider is not None else OpenAIExtractionProvider(config),
        now_provider,
    )
    question_service = QuestionService(
        config,
        repository,
        document_service,
        answer_provider if answer_provider is not None else OpenAIAnswerProvider(config),
        embedding_provider if embedding_provider is not None else OpenAIEmbeddingProvider(config),
        question_guardrail if question_guardrail is not None else build_question_guardrail(config),
        now_provider,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        repository.initialize()
        document_service.cleanup_expired()
        yield

    application = FastAPI(
        title=config.app_name,
        description="LicenceIQ private document reading, extraction, review, and Q&A API.",
        version="0.1.0",
        docs_url="/docs" if config.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = config
    application.state.document_service = document_service
    application.state.reading_service = reading_service
    application.state.extraction_service = extraction_service
    application.state.question_service = question_service
    if auth_service is not None:
        application.state.auth_service = auth_service
    application.add_middleware(UploadBodyLimitMiddleware, max_bytes=config.max_upload_request_bytes)

    @application.middleware("http")
    async def correlate_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Generate our own safe correlation ID rather than trusting arbitrary headers."""
        request.state.request_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            # Catch inside CORS so errors remain readable and Uvicorn cannot log raw details.
            response = unexpected_error_response(request, exc)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    application.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "X-Document-Capability"],
        expose_headers=["X-Request-ID", "Content-Disposition"],
    )
    register_error_handlers(application)
    application.include_router(health_router)
    if auth_service is not None:
        application.include_router(auth_router)
    application.include_router(documents_router)
    return application


def _build_document_repository(config: Settings) -> DocumentRepository:
    """Select explicit local storage or a private MinIO repository from validated settings."""
    if config.document_storage_backend == "filesystem":
        return FilesystemDocumentRepository(config.document_storage_dir)

    client = Minio(
        config.minio_endpoint,
        access_key=config.minio_access_key.get_secret_value(),
        secret_key=config.minio_secret_key.get_secret_value(),
        secure=config.minio_secure,
    )
    return MinioDocumentRepository(
        MinioObjectStore(
            client,
            bucket=config.minio_bucket,
            prefix=f"{config.minio_prefix}/content",
        ),
        MinioObjectStore(
            client,
            bucket=config.minio_bucket,
            prefix=f"{config.minio_prefix}/metadata",
        ),
    )


def _build_auth_service(
    config: Settings, now_provider: Callable[[], datetime] | None
) -> AuthService | None:
    """Construct the bootstrap JWT service only when its protected mode is enabled."""
    if config.auth_mode == "capability":
        return None
    return AuthService(
        AuthConfig(
            signing_key=config.jwt_signing_key,
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
            bootstrap_username=config.bootstrap_username,
            bootstrap_password_hash=config.bootstrap_password_hash,
            bootstrap_subject=config.bootstrap_subject,
            access_token_ttl_seconds=config.jwt_access_token_ttl_seconds,
        ),
        now_provider=now_provider,
    )


app = create_app()

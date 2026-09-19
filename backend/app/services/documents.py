"""Document validation, capability checks, and temporary lifecycle orchestration."""

import hashlib
import hmac
import logging
import secrets
import warnings
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import PurePath
from uuid import uuid4

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.auth import AuthenticationError, AuthService
from app.core.config import Settings
from app.core.errors import ApplicationError
from app.models.document import Document, DocumentUploadResponse, ProcessingStatus
from app.repositories.documents import DocumentRepository, StoredDocumentRecord
from app.repositories.object_store import ObjectStoreError
from app.schemas.common import ErrorCode

_ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
_IMAGE_FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG"}

# pypdf diagnostics can include fragments from malformed private documents.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)


class DocumentService:
    """Apply the Phase 1 contract without exposing persistence details to routes."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        now_provider: Callable[[], datetime] | None = None,
        auth_service: AuthService | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.now_provider = now_provider or (lambda: datetime.now(UTC))
        self.auth_service = auth_service

    def cleanup_expired(self) -> int:
        return self.repository.cleanup_expired(self.now_provider())

    async def upload(
        self, upload: UploadFile, authorization: str | None = None
    ) -> DocumentUploadResponse:
        owner_subject = self._authenticated_subject(authorization)
        await run_in_threadpool(self.cleanup_expired)
        filename = self._safe_filename(upload.filename)
        mime_type = self._validate_declared_type(filename, upload.content_type)
        content = await self._read_bounded(upload)
        return await run_in_threadpool(
            self._validate_and_store,
            filename,
            mime_type,
            content,
            owner_subject,
        )

    def _validate_and_store(
        self, filename: str, mime_type: str, content: bytes, owner_subject: str | None
    ) -> DocumentUploadResponse:
        """Decode and persist on a worker thread so uploads do not block the event loop."""
        page_count = self._validate_content(content, mime_type)

        created_at = self.now_provider()
        document_id = str(uuid4())
        access_token = (
            secrets.token_urlsafe(32) if self.settings.auth_mode == "capability" else None
        )
        record = StoredDocumentRecord(
            document_id=document_id,
            filename=filename,
            mime_type=mime_type,
            size_bytes=len(content),
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self.settings.document_retention_seconds),
            page_count=page_count,
            storage_key=str(uuid4()),
            access_token_hash=self._hash_token(access_token) if access_token is not None else None,
            owner_subject=owner_subject,
        )
        self.repository.save(record, content)
        return DocumentUploadResponse(
            **self._public_document(record).model_dump(), access_token=access_token
        )

    def get(self, document_id: str, authorization: str | None) -> Document:
        record = self.authorized_record(document_id, authorization)
        return self._public_document(record)

    def authorized_record(
        self, document_id: str, authorization: str | None
    ) -> StoredDocumentRecord:
        """Resolve a live private record through the indistinguishable capability check."""
        return self._authorized_record(document_id, authorization)

    def get_file(
        self, document_id: str, authorization: str | None
    ) -> tuple[StoredDocumentRecord, bytes]:
        record = self._authorized_record(document_id, authorization)
        try:
            return record, self.repository.read_content(record)
        except (OSError, ObjectStoreError) as exc:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR, "The document could not be read. Please try again.", 500
            ) from exc

    def delete(self, document_id: str, authorization: str | None) -> None:
        record = self._authorized_record(document_id, authorization)
        try:
            self.repository.delete(record)
        except (OSError, ObjectStoreError) as exc:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR,
                "The document could not be removed. Please try again.",
                500,
            ) from exc

    def _authorized_record(
        self, document_id: str, authorization: str | None
    ) -> StoredDocumentRecord:
        self.cleanup_expired()
        record = self.repository.get(document_id)
        if record is None or record.expires_at <= self.now_provider():
            raise self.not_found()
        if self.settings.auth_mode == "jwt":
            if record.owner_subject != self._authenticated_subject(authorization):
                raise self.not_found()
            return record

        supplied_token = self._bearer_token(authorization)
        if (
            supplied_token is None
            or record.access_token_hash is None
            or not hmac.compare_digest(self._hash_token(supplied_token), record.access_token_hash)
        ):
            raise self.not_found()
        return record

    def _authenticated_subject(self, authorization: str | None) -> str | None:
        """Resolve the current JWT identity only in the explicitly configured JWT mode."""
        if self.settings.auth_mode == "capability":
            return None
        if self.auth_service is None:
            raise ApplicationError(
                ErrorCode.INTERNAL_ERROR,
                "Authentication is temporarily unavailable. Please try again.",
                500,
            )
        try:
            return self.auth_service.authenticate_authorization(authorization).subject
        except AuthenticationError:
            raise ApplicationError(
                ErrorCode.AUTHENTICATION_REQUIRED,
                "Authentication is required.",
                401,
            ) from None

    async def _read_bounded(self, upload: UploadFile) -> bytes:
        content = bytearray()
        try:
            while chunk := await upload.read(64 * 1024):
                content.extend(chunk)
                if len(content) > self.settings.max_upload_file_bytes:
                    raise ApplicationError(
                        ErrorCode.FILE_TOO_LARGE,
                        "The file is larger than the 10 MB upload limit.",
                        413,
                    )
        finally:
            await upload.close()
        if not content:
            raise ApplicationError(ErrorCode.INVALID_FILE, "The selected file is empty.", 400)
        return bytes(content)

    def _validate_content(self, content: bytes, mime_type: str) -> int:
        if mime_type == "application/pdf":
            if not content.startswith(b"%PDF-"):
                raise self._spoofed_file()
            return self._validate_pdf(content)

        expected_format = _IMAGE_FORMATS[mime_type]
        if mime_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise self._spoofed_file()
        if mime_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
            raise self._spoofed_file()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as probe:
                    if probe.format != expected_format:
                        raise self._spoofed_file()
                    width, height = probe.size
                    if (
                        width > self.settings.max_image_dimension
                        or height > self.settings.max_image_dimension
                        or width * height > self.settings.max_image_pixels
                    ):
                        raise ApplicationError(
                            ErrorCode.INVALID_FILE,
                            "The image dimensions are too large.",
                            400,
                        )
                    probe.verify()
                with Image.open(BytesIO(content)) as decoded:
                    decoded.load()
        except ApplicationError:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as exc:
            raise ApplicationError(
                ErrorCode.INVALID_FILE, "The image is malformed or unreadable.", 400
            ) from exc
        return 1

    def _validate_pdf(self, content: bytes) -> int:
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted:
                raise ApplicationError(
                    ErrorCode.INVALID_FILE, "Encrypted PDFs are not supported.", 400
                )
            page_count = len(reader.pages)
            if page_count == 0:
                raise ApplicationError(
                    ErrorCode.INVALID_FILE, "The PDF does not contain any pages.", 400
                )
            if page_count > self.settings.max_pdf_pages:
                raise ApplicationError(
                    ErrorCode.INVALID_FILE,
                    f"The PDF exceeds the {self.settings.max_pdf_pages}-page limit.",
                    400,
                )
            for page in reader.pages:
                _ = page.mediabox
        except ApplicationError:
            raise
        except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
            raise ApplicationError(
                ErrorCode.INVALID_FILE, "The PDF is malformed or unreadable.", 400
            ) from exc
        return page_count

    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        leaf = PurePath((filename or "").replace("\\", "/")).name.strip()
        leaf = "".join(character for character in leaf if character >= " " and character != "\x7f")
        if not leaf or leaf in {".", ".."}:
            raise ApplicationError(ErrorCode.INVALID_FILE, "A valid filename is required.", 400)
        return leaf[:255]

    @staticmethod
    def _validate_declared_type(filename: str, content_type: str | None) -> str:
        extension = PurePath(filename).suffix.lower()
        expected = _ALLOWED_TYPES.get(extension)
        if expected is None or content_type not in set(_ALLOWED_TYPES.values()):
            raise ApplicationError(
                ErrorCode.UNSUPPORTED_FILE,
                "Choose a PDF, PNG, JPG, or JPEG file.",
                415,
            )
        if content_type != expected:
            raise ApplicationError(
                ErrorCode.INVALID_FILE,
                "The filename and declared file type do not match.",
                400,
            )
        return expected

    @staticmethod
    def _public_document(record: StoredDocumentRecord) -> Document:
        return Document(
            document_id=record.document_id,
            filename=record.filename,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            status=ProcessingStatus.UPLOADED,
            created_at=record.created_at,
            page_count=record.page_count,
            warnings=[],
        )

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        if authorization is None:
            return None
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or " " in token:
            return None
        return token

    @staticmethod
    def not_found() -> ApplicationError:
        return ApplicationError(ErrorCode.DOCUMENT_NOT_FOUND, "The document was not found.", 404)

    @staticmethod
    def _spoofed_file() -> ApplicationError:
        return ApplicationError(
            ErrorCode.INVALID_FILE, "The file content does not match its type.", 400
        )

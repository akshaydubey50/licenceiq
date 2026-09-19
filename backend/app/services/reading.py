"""Bounded page reading with native PDF text and page-image OCR fallback."""

import math
import threading
import time
import warnings
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings
from app.core.errors import ApplicationError
from app.models.document import (
    DocumentPage,
    Evidence,
    ReadingResult,
    ReadingStatus,
)
from app.providers.ocr import OCRProvider
from app.repositories.documents import DocumentRepository, StoredDocumentRecord
from app.schemas.common import ErrorCode
from app.services.documents import DocumentCredential, DocumentService

_PDFIUM_LOCK = threading.Lock()
_MAX_CONCURRENT_READS = 4


class ReadingService:
    """Read and atomically cache private page evidence for one process."""

    def __init__(
        self,
        settings: Settings,
        repository: DocumentRepository,
        document_service: DocumentService,
        ocr_provider: OCRProvider,
        now_provider: Callable[[], datetime] | None = None,
        monotonic_provider: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.document_service = document_service
        self.ocr_provider = ocr_provider
        self.now_provider = now_provider or (lambda: datetime.now(UTC))
        self.monotonic_provider = monotonic_provider or time.monotonic
        self._active_guard = threading.Lock()
        self._active_documents: set[str] = set()
        self._capacity = threading.BoundedSemaphore(_MAX_CONCURRENT_READS)

    def read(self, document_id: str, authorization: DocumentCredential) -> ReadingResult:
        """Return cached evidence or perform one bounded, nonduplicated read."""
        initial = self.document_service.authorized_record(document_id, authorization)
        if initial.reading is not None:
            return initial.reading
        self._begin_read(document_id)
        capacity_acquired = self._capacity.acquire(blocking=False)
        if not capacity_acquired:
            self._end_read(document_id)
            raise self._in_progress()
        try:
            # Recheck after claiming the slot so a just-completed read becomes a cache hit.
            record = self.document_service.authorized_record(document_id, authorization)
            if record.reading is not None:
                return record.reading
            try:
                content = self.repository.read_content(record)
            except OSError as exc:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR,
                    "The document could not be read. Please try again.",
                    500,
                ) from exc
            deadline = self.monotonic_provider() + self.settings.reading_timeout_seconds
            result = self._read_document(record, content, deadline)
            self._check_deadline(deadline)
            try:
                published = self.repository.save_reading_if_current(
                    record, result, self.now_provider()
                )
            except OSError as exc:
                raise ApplicationError(
                    ErrorCode.INTERNAL_ERROR,
                    "The document reading could not be saved. Please try again.",
                    500,
                ) from exc
            if not published:
                self.document_service.cleanup_expired()
                raise self.document_service.not_found()
            saved = self.repository.get(document_id)
            if saved is None or saved.reading is None:
                raise self.document_service.not_found()
            return saved.reading
        finally:
            self._capacity.release()
            self._end_read(document_id)

    def get_saved(self, document_id: str, authorization: DocumentCredential) -> ReadingResult:
        """Retrieve a private cached read without starting provider work."""
        record = self.document_service.authorized_record(document_id, authorization)
        if record.reading is None:
            raise ApplicationError(
                ErrorCode.READING_NOT_FOUND,
                "The document has not been read yet.",
                404,
            )
        return record.reading

    def _begin_read(self, document_id: str) -> None:
        with self._active_guard:
            if document_id in self._active_documents:
                raise self._in_progress()
            self._active_documents.add(document_id)

    def _end_read(self, document_id: str) -> None:
        with self._active_guard:
            self._active_documents.discard(document_id)

    def _read_document(
        self, record: StoredDocumentRecord, content: bytes, deadline: float
    ) -> ReadingResult:
        if record.mime_type == "application/pdf":
            pages = self._read_pdf(record, content, deadline)
        elif record.mime_type in {"image/png", "image/jpeg"}:
            pages = (self._read_image(record, content, deadline),)
        else:
            raise ApplicationError(ErrorCode.INVALID_FILE, "The document type is invalid.", 400)

        warnings_list = tuple(
            f"Page {page.page_number} did not contain readable text."
            for page in pages
            if not page.text
        )
        if len(warnings_list) == len(pages):
            raise ApplicationError(
                ErrorCode.NO_READABLE_TEXT,
                "No readable text was found in the document.",
                422,
            )
        status = ReadingStatus.READ_WITH_WARNINGS if warnings_list else ReadingStatus.READ
        return ReadingResult(
            document_id=record.document_id,
            status=status,
            pages=pages,
            warnings=warnings_list,
            created_at=self.now_provider(),
        )

    def _read_pdf(
        self, record: StoredDocumentRecord, content: bytes, deadline: float
    ) -> tuple[DocumentPage, ...]:
        try:
            reader = PdfReader(BytesIO(content), strict=True)
            if reader.is_encrypted or len(reader.pages) != record.page_count:
                raise self._invalid_file()
            pages: list[DocumentPage] = []
            total_characters = 0
            for index, page in enumerate(reader.pages):
                self._check_deadline(deadline)
                try:
                    native_text = page.extract_text() or ""
                except (KeyError, TypeError, ValueError, PdfReadError):
                    native_text = ""
                if self._native_text_is_usable(native_text):
                    page_result = self._page_from_lines(
                        record.document_id,
                        index + 1,
                        "native_text",
                        native_text.splitlines(),
                    )
                else:
                    image_bytes = self._render_pdf_page(content, index, deadline)
                    page_result = self._ocr_page(
                        record.document_id, index + 1, image_bytes, deadline
                    )
                total_characters += len(page_result.text)
                self._check_size(total_characters)
                pages.append(page_result)
            return tuple(pages)
        except ApplicationError:
            raise
        except (PdfReadError, OSError, ValueError, KeyError, TypeError) as exc:
            raise self._invalid_file() from exc

    def _read_image(
        self, record: StoredDocumentRecord, content: bytes, deadline: float
    ) -> DocumentPage:
        prepared = self._prepare_image(content)
        page = self._ocr_page(record.document_id, 1, prepared, deadline)
        self._check_size(len(page.text))
        return page

    def _ocr_page(
        self,
        document_id: str,
        page_number: int,
        image_bytes: bytes,
        deadline: float,
    ) -> DocumentPage:
        remaining = self._remaining(deadline)
        result = self.ocr_provider.extract(
            image_bytes,
            "image/png",
            timeout_seconds=min(self.settings.ocr_timeout_seconds, remaining),
        )
        self._check_deadline(deadline)
        return self._page_from_lines(document_id, page_number, "ocr", result.lines)

    def _render_pdf_page(self, content: bytes, page_index: int, deadline: float) -> bytes:
        """Render under the process lock; native parsing itself cannot be interrupted."""
        lock_acquired = _PDFIUM_LOCK.acquire(timeout=self._remaining(deadline))
        if not lock_acquired:
            raise self._timeout()
        try:
            self._check_deadline(deadline)
            document: pdfium.PdfDocument | None = None
            page: pdfium.PdfPage | None = None
            bitmap: pdfium.PdfBitmap | None = None
            try:
                document = pdfium.PdfDocument(content)
                page = document[page_index]
                width, height = page.get_size()
                scale = self._render_scale(width, height)
                bitmap = page.render(scale=scale)
                rendered = bitmap.to_pil().copy()
            except (pdfium.PdfiumError, IndexError, OSError, ValueError, OverflowError) as exc:
                raise self._invalid_file() from exc
            finally:
                if bitmap is not None:
                    bitmap.close()
                if page is not None:
                    page.close()
                if document is not None:
                    document.close()
        finally:
            _PDFIUM_LOCK.release()
        self._check_deadline(deadline)
        try:
            output = BytesIO()
            with rendered:
                rendered.convert("RGB").save(output, format="PNG")
            return output.getvalue()
        except (OSError, ValueError) as exc:
            raise self._invalid_file() from exc

    def _prepare_image(self, content: bytes) -> bytes:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(content)) as source:
                    oriented = ImageOps.exif_transpose(source)
                    rgb = oriented.convert("RGB")
            target = self._target_size(*rgb.size)
            if target != rgb.size:
                resized = rgb.resize(target, Image.Resampling.LANCZOS)
                rgb.close()
                rgb = resized
            output = BytesIO()
            with rgb:
                rgb.save(output, format="PNG")
            return output.getvalue()
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            SyntaxError,
            ValueError,
        ) as exc:
            raise self._invalid_file() from exc

    def _render_scale(self, width: float, height: float) -> float:
        if width <= 0 or height <= 0 or not math.isfinite(width) or not math.isfinite(height):
            raise self._invalid_file()
        max_dimension = self.settings.ocr_max_image_dimension
        max_pixels = self.settings.ocr_max_image_pixels
        scale = min(
            2.0,
            max_dimension / width,
            max_dimension / height,
            math.sqrt(max_pixels / (width * height)),
        )
        for _ in range(4):
            pixel_width = max(1, math.ceil(width * scale))
            pixel_height = max(1, math.ceil(height * scale))
            if (
                pixel_width <= max_dimension
                and pixel_height <= max_dimension
                and pixel_width * pixel_height <= max_pixels
            ):
                if scale <= 0 or not math.isfinite(scale):
                    raise self._invalid_file()
                return scale
            correction = min(
                max_dimension / pixel_width,
                max_dimension / pixel_height,
                math.sqrt(max_pixels / (pixel_width * pixel_height)),
            )
            scale *= correction * 0.999999
        raise self._invalid_file()

    def _target_size(self, width: int, height: int) -> tuple[int, int]:
        if width <= 0 or height <= 0:
            raise self._invalid_file()
        max_dimension = self.settings.ocr_max_image_dimension
        max_pixels = self.settings.ocr_max_image_pixels
        reduction = min(
            1.0,
            max_dimension / width,
            max_dimension / height,
            math.sqrt(max_pixels / (width * height)),
        )
        return max(1, int(width * reduction)), max(1, int(height * reduction))

    @staticmethod
    def _native_text_is_usable(text: str) -> bool:
        if sum(character.isalnum() for character in text) < 40 or not text:
            return False
        acceptable = sum(
            character.isprintable() or character in {"\n", "\r", "\t"} for character in text
        )
        return acceptable / len(text) >= 0.8

    @staticmethod
    def _page_from_lines(
        document_id: str,
        page_number: int,
        method: Literal["native_text", "ocr"],
        lines: Iterable[str],
    ) -> DocumentPage:
        normalized: list[str] = []
        for supplied_line in lines:
            for line in supplied_line.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                visible_line = line.strip()
                if visible_line:
                    normalized.append(visible_line)
        blocks = tuple(
            Evidence(
                document_id=document_id,
                page_number=page_number,
                source_text=line,
                block_id=f"page-{page_number}-line-{line_number}",
            )
            for line_number, line in enumerate(normalized, start=1)
        )
        return DocumentPage(
            document_id=document_id,
            page_number=page_number,
            text="\n".join(normalized),
            blocks=blocks,
            method=method,
        )

    def _check_size(self, characters: int) -> None:
        if characters > self.settings.max_reading_characters:
            raise ApplicationError(
                ErrorCode.READING_TOO_LARGE,
                "The document contains too much text to read safely.",
                422,
            )

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.monotonic_provider()
        if remaining <= 0:
            raise self._timeout()
        return remaining

    def _check_deadline(self, deadline: float) -> None:
        _ = self._remaining(deadline)

    @staticmethod
    def _in_progress() -> ApplicationError:
        return ApplicationError(
            ErrorCode.READING_IN_PROGRESS,
            "This document is already being read. Please try again shortly.",
            409,
        )

    @staticmethod
    def _timeout() -> ApplicationError:
        return ApplicationError(
            ErrorCode.OCR_TIMEOUT,
            "Document reading took too long. Please try again with fewer pages.",
            504,
        )

    @staticmethod
    def _invalid_file() -> ApplicationError:
        return ApplicationError(
            ErrorCode.INVALID_FILE,
            "The document is malformed or unreadable.",
            400,
        )

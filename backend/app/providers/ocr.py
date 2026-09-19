"""Minimal OCR contract independent of HTTP, storage, and licence extraction."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OCRResult:
    """Transcribed lines only; evidence identity is assigned by the page reader."""

    lines: tuple[str, ...]


class OCRProvider(Protocol):
    """Read one prepared page image within the caller's remaining time budget."""

    def extract(
        self,
        image_bytes: bytes,
        mime_type: str,
        *,
        timeout_seconds: float | None = None,
    ) -> OCRResult: ...

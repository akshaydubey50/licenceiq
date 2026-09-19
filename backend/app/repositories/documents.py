"""Private filesystem persistence for validated temporary documents."""

import json
import os
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.document import ExtractionResult, ReadingResult, ReviewState, SemanticIndex
from app.repositories.object_store import ObjectStoreError, PrivateObjectStore


class StoredDocumentRecord(BaseModel):
    """Internal metadata kept separate from client-safe document contracts."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    expires_at: datetime
    page_count: int
    storage_key: str
    access_token_hash: str | None = None
    owner_subject: str | None = None
    reading: ReadingResult | None = None
    semantic_index: SemanticIndex | None = None
    extraction: ExtractionResult | None = None
    review: ReviewState | None = None


class DocumentRepository(Protocol):
    """Persistence operations used by document lifecycle services."""

    def initialize(self) -> None: ...

    def save(self, record: StoredDocumentRecord, content: bytes) -> None: ...

    def get(self, document_id: str) -> StoredDocumentRecord | None: ...

    def read_content(self, record: StoredDocumentRecord) -> bytes: ...

    def save_reading_if_current(
        self, snapshot: StoredDocumentRecord, reading: ReadingResult, now: datetime
    ) -> bool: ...

    def save_semantic_index_if_current(
        self, snapshot: StoredDocumentRecord, semantic_index: SemanticIndex, now: datetime
    ) -> bool: ...

    def save_extraction_if_current(
        self, snapshot: StoredDocumentRecord, extraction: ExtractionResult, now: datetime
    ) -> bool: ...

    def save_review_if_current(
        self, snapshot: StoredDocumentRecord, review: ReviewState, now: datetime
    ) -> bool: ...

    def delete(self, record: StoredDocumentRecord) -> None: ...

    def cleanup_expired(self, now: datetime) -> int: ...


class FilesystemDocumentRepository:
    """Persist bytes under generated keys and metadata in non-public sidecars."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = RLock()

    def initialize(self) -> None:
        with self._lock:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def save(self, record: StoredDocumentRecord, content: bytes) -> None:
        """Publish content before metadata and remove both if either write fails."""
        with self._lock:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            content_path = self._content_path(record.storage_key)
            metadata_path = self._metadata_path(record.document_id)
            content_temp = content_path.with_suffix(".tmp")
            try:
                self._write_bytes_atomic(content_temp, content_path, content)
                self._write_metadata_atomic(record, metadata_path)
            except Exception:
                content_temp.unlink(missing_ok=True)
                content_path.unlink(missing_ok=True)
                metadata_path.with_suffix(".tmp").unlink(missing_ok=True)
                metadata_path.unlink(missing_ok=True)
                raise

    def get(self, document_id: str) -> StoredDocumentRecord | None:
        with self._lock:
            return self._get_unlocked(document_id)

    def read_content(self, record: StoredDocumentRecord) -> bytes:
        with self._lock:
            return self._content_path(record.storage_key).read_bytes()

    def save_reading_if_current(
        self,
        snapshot: StoredDocumentRecord,
        reading: ReadingResult,
        now: datetime,
    ) -> bool:
        """Atomically publish only while the exact source document remains live."""
        if reading.document_id != snapshot.document_id:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if (
                current is None
                or current.expires_at <= now
                or current.storage_key != snapshot.storage_key
                or current.created_at != snapshot.created_at
                or current.access_token_hash != snapshot.access_token_hash
            ):
                return False
            if current.reading is not None:
                return True
            updated = current.model_copy(update={"reading": reading, "semantic_index": None})
            self._write_metadata_atomic(updated, self._metadata_path(current.document_id))
            return True

    def save_semantic_index_if_current(
        self,
        snapshot: StoredDocumentRecord,
        semantic_index: SemanticIndex,
        now: datetime,
    ) -> bool:
        """Atomically replace the private index only for the exact live reading."""
        if snapshot.reading is None or semantic_index.document_id != snapshot.document_id:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if (
                current is None
                or current.expires_at <= now
                or current.storage_key != snapshot.storage_key
                or current.created_at != snapshot.created_at
                or current.access_token_hash != snapshot.access_token_hash
                or current.reading != snapshot.reading
            ):
                return False
            if current.semantic_index == semantic_index:
                return True
            updated = current.model_copy(update={"semantic_index": semantic_index})
            self._write_metadata_atomic(updated, self._metadata_path(current.document_id))
            return True

    def save_extraction_if_current(
        self,
        snapshot: StoredDocumentRecord,
        extraction: ExtractionResult,
        now: datetime,
    ) -> bool:
        """Publish only while the exact live record and reading still match."""
        if extraction.document_id != snapshot.document_id or snapshot.reading is None:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if (
                current is None
                or current.expires_at <= now
                or current.storage_key != snapshot.storage_key
                or current.created_at != snapshot.created_at
                or current.access_token_hash != snapshot.access_token_hash
                or current.reading != snapshot.reading
            ):
                return False
            if current.extraction is not None:
                return True
            updated = current.model_copy(update={"extraction": extraction})
            self._write_metadata_atomic(updated, self._metadata_path(current.document_id))
            return True

    def save_review_if_current(
        self,
        snapshot: StoredDocumentRecord,
        review: ReviewState,
        now: datetime,
    ) -> bool:
        """Publish review values only while the exact extracted document is live."""
        if snapshot.extraction is None:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if (
                current is None
                or current.expires_at <= now
                or current.storage_key != snapshot.storage_key
                or current.created_at != snapshot.created_at
                or current.access_token_hash != snapshot.access_token_hash
                or current.extraction != snapshot.extraction
            ):
                return False
            updated = current.model_copy(update={"review": review})
            self._write_metadata_atomic(updated, self._metadata_path(current.document_id))
            return True

    def delete(self, record: StoredDocumentRecord) -> None:
        """Retain retryable metadata if byte removal fails."""
        with self._lock:
            self._content_path(record.storage_key).unlink(missing_ok=True)
            self._metadata_path(record.document_id).unlink(missing_ok=True)

    def cleanup_expired(self, now: datetime) -> int:
        """Best-effort removal of expired records and their content."""
        with self._lock:
            if not self.root.exists():
                return 0
            removed = 0
            for metadata_path in self.root.glob("*.json"):
                try:
                    record = StoredDocumentRecord.model_validate_json(
                        metadata_path.read_text(encoding="utf-8")
                    )
                    if record.expires_at <= now:
                        self.delete(record)
                        removed += 1
                except (OSError, ValueError):
                    # Corrupt metadata is not trusted and is never exposed through the API.
                    continue
            return removed

    def _get_unlocked(self, document_id: str) -> StoredDocumentRecord | None:
        try:
            path = self._metadata_path(document_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        try:
            return StoredDocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _metadata_path(self, document_id: str) -> Path:
        normalized = str(UUID(document_id))
        return self.root / f"{normalized}.json"

    def _content_path(self, storage_key: str) -> Path:
        normalized = str(UUID(storage_key))
        return self.root / f"{normalized}.bin"

    @staticmethod
    def _write_bytes_atomic(temp: Path, destination: Path, content: bytes) -> None:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        temp.replace(destination)

    @staticmethod
    def _write_metadata_atomic(record: StoredDocumentRecord, destination: Path) -> None:
        temp = destination.with_suffix(".tmp")
        payload = json.dumps(record.model_dump(mode="json"), separators=(",", ":"))
        try:
            with temp.open("x", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            temp.replace(destination)
        except Exception:
            temp.unlink(missing_ok=True)
            raise


class MinioDocumentRepository:
    """Persist private document bytes and metadata through two generated-key object stores.

    The content store and metadata store use distinct prefixes in one private bucket. Metadata
    keys reuse the generated document ID, and original filenames or bearer values never become
    object names. The process lock preserves the same in-process conditional update guarantees
    as the local repository; a multi-process deployment needs an additional durable compare-and-
    swap layer before it can run with multiple backend workers.
    """

    def __init__(
        self, content_store: PrivateObjectStore, metadata_store: PrivateObjectStore
    ) -> None:
        self._content_store = content_store
        self._metadata_store = metadata_store
        self._lock = RLock()

    def initialize(self) -> None:
        with self._lock:
            self._content_store.initialize()
            self._metadata_store.initialize()

    def save(self, record: StoredDocumentRecord, content: bytes) -> None:
        """Publish bytes before metadata and remove newly created objects on failure."""
        with self._lock:
            try:
                self._content_store.put(record.storage_key, content, content_type=record.mime_type)
                self._write_metadata(record)
            except Exception:
                self._best_effort_delete(self._metadata_store, record.document_id)
                self._best_effort_delete(self._content_store, record.storage_key)
                raise

    def get(self, document_id: str) -> StoredDocumentRecord | None:
        with self._lock:
            return self._get_unlocked(document_id)

    def read_content(self, record: StoredDocumentRecord) -> bytes:
        with self._lock:
            return self._content_store.get(record.storage_key)

    def save_reading_if_current(
        self,
        snapshot: StoredDocumentRecord,
        reading: ReadingResult,
        now: datetime,
    ) -> bool:
        """Publish a reading only when its immutable document snapshot is still current."""
        if reading.document_id != snapshot.document_id:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if not self._matches_snapshot(current, snapshot, now):
                return False
            assert current is not None
            if current.reading is not None:
                return True
            self._write_metadata(
                current.model_copy(update={"reading": reading, "semantic_index": None})
            )
            return True

    def save_semantic_index_if_current(
        self,
        snapshot: StoredDocumentRecord,
        semantic_index: SemanticIndex,
        now: datetime,
    ) -> bool:
        """Replace the private index only for the exact live reading snapshot."""
        if snapshot.reading is None or semantic_index.document_id != snapshot.document_id:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if not self._matches_snapshot(current, snapshot, now) or current is None:
                return False
            if current.reading != snapshot.reading:
                return False
            if current.semantic_index == semantic_index:
                return True
            self._write_metadata(current.model_copy(update={"semantic_index": semantic_index}))
            return True

    def save_extraction_if_current(
        self,
        snapshot: StoredDocumentRecord,
        extraction: ExtractionResult,
        now: datetime,
    ) -> bool:
        """Publish extraction only while the original reading still matches exactly."""
        if extraction.document_id != snapshot.document_id or snapshot.reading is None:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if not self._matches_snapshot(current, snapshot, now) or current is None:
                return False
            if current.reading != snapshot.reading:
                return False
            if current.extraction is not None:
                return True
            self._write_metadata(current.model_copy(update={"extraction": extraction}))
            return True

    def save_review_if_current(
        self,
        snapshot: StoredDocumentRecord,
        review: ReviewState,
        now: datetime,
    ) -> bool:
        """Persist reviewer values only while the exact extraction remains current."""
        if snapshot.extraction is None:
            return False
        with self._lock:
            current = self._get_unlocked(snapshot.document_id)
            if not self._matches_snapshot(current, snapshot, now) or current is None:
                return False
            if current.extraction != snapshot.extraction:
                return False
            self._write_metadata(current.model_copy(update={"review": review}))
            return True

    def delete(self, record: StoredDocumentRecord) -> None:
        """Keep metadata retriable if original-byte deletion fails."""
        with self._lock:
            self._content_store.delete(record.storage_key)
            self._metadata_store.delete(record.document_id)

    def cleanup_expired(self, now: datetime) -> int:
        """Remove expired valid metadata records and their associated private bytes."""
        with self._lock:
            removed = 0
            for document_id in self._metadata_store.list_keys():
                record = self._get_unlocked(document_id)
                if record is not None and record.expires_at <= now:
                    self.delete(record)
                    removed += 1
            return removed

    def _get_unlocked(self, document_id: str) -> StoredDocumentRecord | None:
        try:
            normalized = str(UUID(document_id))
        except (AttributeError, TypeError, ValueError):
            return None
        try:
            payload = self._metadata_store.get(normalized)
            return StoredDocumentRecord.model_validate_json(payload)
        except (ObjectStoreError, ValueError):
            # Metadata must not be exposed or trusted when an object is absent or malformed.
            return None

    def _write_metadata(self, record: StoredDocumentRecord) -> None:
        payload = json.dumps(record.model_dump(mode="json"), separators=(",", ":")).encode("utf-8")
        self._metadata_store.put(record.document_id, payload, content_type="application/json")

    @staticmethod
    def _matches_snapshot(
        current: StoredDocumentRecord | None,
        snapshot: StoredDocumentRecord,
        now: datetime,
    ) -> bool:
        return (
            current is not None
            and current.expires_at > now
            and current.storage_key == snapshot.storage_key
            and current.created_at == snapshot.created_at
            and current.access_token_hash == snapshot.access_token_hash
            and current.owner_subject == snapshot.owner_subject
        )

    @staticmethod
    def _best_effort_delete(store: PrivateObjectStore, key: str) -> None:
        try:
            store.delete(key)
        except ObjectStoreError:
            pass

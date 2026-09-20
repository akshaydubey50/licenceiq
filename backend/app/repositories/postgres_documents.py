"""PostgreSQL metadata with private object storage for original document bytes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from app.models.document import (
    ExtractionResult,
    QuestionResult,
    ReadingResult,
    ReviewState,
    SemanticIndex,
)
from app.persistence.models import (
    EMBEDDING_DIMENSIONS,
    app_users,
    block_embeddings,
    chat_turns,
    documents,
    embedding_sets,
    evidence_blocks,
    reading_pages,
    readings,
)
from app.repositories.documents import ChatPersistenceUnavailable, StoredDocumentRecord
from app.repositories.object_store import ObjectStoreError, PrivateObjectStore

_ACTIVE = "ACTIVE"
_DELETION_PENDING = "DELETION_PENDING"
_DELETION_FAILED = "DELETION_FAILED"


class _ConditionalWriteRejected(Exception):
    """Roll back a conditional write when its normalized source rows do not match."""


class PostgresDocumentRepository:
    """Keep document domain metadata in PostgreSQL and original bytes in object storage.

    ``record_json`` is the exact current domain snapshot used to hydrate the existing
    ``StoredDocumentRecord`` contract. Relational columns hold the immutable identity,
    access, expiry, lifecycle, and compare-and-swap fields needed to update that snapshot
    safely across backend processes.
    """

    def __init__(
        self,
        engine: Engine,
        content_store: PrivateObjectStore,
        *,
        owner_issuer: str,
    ) -> None:
        if not owner_issuer:
            raise ValueError("owner_issuer must not be empty.")
        self._engine = engine
        self._content_store = content_store
        self._owner_issuer = owner_issuer

    def initialize(self) -> None:
        """Initialize blob storage without creating or migrating database tables."""
        self._content_store.initialize()

    def save(self, record: StoredDocumentRecord, content: bytes) -> None:
        """Publish one blob and its authoritative PostgreSQL metadata atomically enough.

        The database transaction remains uncommitted while the blob is written. A database
        failure removes the generated-key blob best-effort, so MinIO never becomes a metadata
        fallback or a second source of record truth.
        """
        document_id = self._uuid(record.document_id, field="document_id")
        object_key = str(self._uuid(record.storage_key, field="storage_key"))
        capability_hash = self._capability_hash(record.access_token_hash)
        self._validate_access_principal(record, capability_hash)
        if len(content) != record.size_bytes:
            raise ValueError("Document content size does not match its metadata.")

        blob_write_attempted = False
        try:
            with self._engine.begin() as connection:
                owner_user_id = self._owner_user_id(
                    connection,
                    subject=record.owner_subject,
                    created_at=record.created_at,
                )
                connection.execute(
                    sa.insert(documents).values(
                        id=document_id,
                        owner_user_id=owner_user_id,
                        owner_subject=record.owner_subject,
                        capability_hash=capability_hash,
                        object_key=object_key,
                        content_sha256=hashlib.sha256(content).digest(),
                        safe_filename=record.filename,
                        mime_type=record.mime_type,
                        size_bytes=record.size_bytes,
                        page_count=record.page_count,
                        lifecycle_state=_ACTIVE,
                        version=1,
                        record_json=self._record_payload(record),
                        expires_at=record.expires_at,
                        created_at=record.created_at,
                        updated_at=record.created_at,
                    )
                )
                blob_write_attempted = True
                self._content_store.put(object_key, content, content_type=record.mime_type)
        except Exception:
            if blob_write_attempted:
                self._best_effort_delete(object_key)
            raise

    def get(self, document_id: str) -> StoredDocumentRecord | None:
        """Hydrate the current active record exclusively from PostgreSQL."""
        try:
            normalized_id = self._uuid(document_id, field="document_id")
        except ValueError:
            return None
        statement = sa.select(documents.c.record_json).where(
            documents.c.id == normalized_id,
            documents.c.lifecycle_state == _ACTIVE,
        )
        with self._engine.connect() as connection:
            payload = connection.execute(statement).scalar_one_or_none()
        return self._hydrate(payload)

    def list_owned(
        self, owner_subject: str, now: datetime, *, limit: int
    ) -> tuple[StoredDocumentRecord, ...]:
        """Return only active, unexpired records for one JWT subject."""
        statement = (
            sa.select(documents.c.record_json)
            .where(
                documents.c.owner_subject == owner_subject,
                documents.c.lifecycle_state == _ACTIVE,
                documents.c.expires_at > now,
            )
            .order_by(documents.c.created_at.desc(), documents.c.id.desc())
            .limit(limit)
        )
        try:
            with self._engine.connect() as connection:
                payloads = tuple(connection.execute(statement).scalars())
        except sa.exc.SQLAlchemyError as exc:
            raise ChatPersistenceUnavailable from exc
        return tuple(
            record for payload in payloads if (record := self._hydrate(payload)) is not None
        )

    def save_chat_turn_if_current(
        self,
        snapshot: StoredDocumentRecord,
        result: QuestionResult,
        now: datetime,
    ) -> bool:
        """Insert a validated result only while its owned source reading is unchanged."""
        if (
            snapshot.owner_subject is None
            or snapshot.reading is None
            or result.document_id != snapshot.document_id
        ):
            return False
        try:
            document_id = self._uuid(snapshot.document_id, field="document_id")
        except ValueError:
            return False
        reading_sha256 = self._reading_sha256(snapshot.reading)
        try:
            with self._engine.begin() as connection:
                row = self._locked_row(connection, document_id)
                current = self._hydrate(None if row is None else row["record_json"])
                if (
                    not self._matches_snapshot(current, snapshot, now)
                    or current is None
                    or current.owner_subject != snapshot.owner_subject
                    or current.reading != snapshot.reading
                ):
                    return False
                connection.execute(
                    sa.insert(chat_turns).values(
                        id=uuid4(),
                        document_id=document_id,
                        reading_sha256=reading_sha256,
                        question=result.question,
                        status=result.status.value,
                        answer=result.answer,
                        citations_json=[
                            citation.model_dump(mode="json") for citation in result.citations
                        ],
                        created_at=result.created_at,
                    )
                )
        except sa.exc.SQLAlchemyError as exc:
            raise ChatPersistenceUnavailable from exc
        return True

    def get_chat_history(
        self,
        document_id: str,
        owner_subject: str,
        now: datetime,
        *,
        limit: int,
    ) -> tuple[QuestionResult, ...]:
        """Load bounded current-reading turns through an owner-scoped query."""
        try:
            normalized_id = self._uuid(document_id, field="document_id")
        except ValueError:
            return ()
        statement = (
            sa.select(
                chat_turns.c.question,
                chat_turns.c.status,
                chat_turns.c.answer,
                chat_turns.c.citations_json,
                chat_turns.c.created_at,
            )
            .select_from(
                chat_turns.join(
                    documents,
                    chat_turns.c.document_id == documents.c.id,
                ).join(
                    readings,
                    sa.and_(
                        chat_turns.c.document_id == readings.c.document_id,
                        chat_turns.c.reading_sha256 == readings.c.reading_sha256,
                    ),
                )
            )
            .where(
                documents.c.id == normalized_id,
                documents.c.owner_subject == owner_subject,
                documents.c.lifecycle_state == _ACTIVE,
                documents.c.expires_at > now,
            )
            .order_by(chat_turns.c.created_at.desc(), chat_turns.c.id.desc())
            .limit(limit)
        )
        try:
            with self._engine.connect() as connection:
                rows = tuple(connection.execute(statement).mappings())
            return tuple(
                QuestionResult.model_validate(
                    {
                        "document_id": str(normalized_id),
                        "question": row["question"],
                        "status": row["status"],
                        "answer": row["answer"],
                        "citations": row["citations_json"],
                        "created_at": self._restore_timezone(row["created_at"], now),
                    }
                )
                for row in reversed(rows)
            )
        except (sa.exc.SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
            raise ChatPersistenceUnavailable from exc

    @staticmethod
    def _restore_timezone(value: datetime, reference: datetime) -> datetime:
        """Normalize timezone-dropping test dialects; PostgreSQL already returns aware values."""
        if value.tzinfo is None and reference.tzinfo is not None:
            return value.replace(tzinfo=reference.tzinfo)
        return value

    def clear_chat_history(self, document_id: str, owner_subject: str) -> None:
        """Delete turns only when the document still belongs to the supplied subject."""
        try:
            normalized_id = self._uuid(document_id, field="document_id")
        except ValueError:
            return
        owned_document = sa.select(documents.c.id).where(
            documents.c.id == normalized_id,
            documents.c.owner_subject == owner_subject,
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.delete(chat_turns).where(
                        chat_turns.c.document_id == owned_document.scalar_subquery()
                    )
                )
        except sa.exc.SQLAlchemyError as exc:
            raise ChatPersistenceUnavailable from exc

    def read_content(self, record: StoredDocumentRecord) -> bytes:
        """Read the original bytes using only the generated document object key."""
        return self._content_store.get(record.storage_key)

    def save_reading_if_current(
        self,
        snapshot: StoredDocumentRecord,
        reading: ReadingResult,
        now: datetime,
    ) -> bool:
        """Publish the first reading while the immutable live snapshot still matches."""
        if reading.document_id != snapshot.document_id or not reading.pages:
            return False

        def update(current: StoredDocumentRecord) -> StoredDocumentRecord | None:
            if current.reading is not None:
                return current if current.reading == reading else None
            return current.model_copy(update={"reading": reading, "semantic_index": None})

        return self._conditional_update(
            snapshot,
            now,
            update,
            persist_normalized=lambda connection, document_id: self._persist_reading(
                connection, document_id, reading
            ),
        )

    def save_semantic_index_if_current(
        self,
        snapshot: StoredDocumentRecord,
        semantic_index: SemanticIndex,
        now: datetime,
    ) -> bool:
        """Replace vectors only for the exact live reading used to compute them."""
        if (
            snapshot.reading is None
            or semantic_index.document_id != snapshot.document_id
            or semantic_index.dimensions != EMBEDDING_DIMENSIONS
            or semantic_index.reading_sha256 != self._reading_sha256(snapshot.reading).hex()
        ):
            return False

        def update(current: StoredDocumentRecord) -> StoredDocumentRecord | None:
            if current.reading != snapshot.reading:
                return None
            if current.semantic_index == semantic_index:
                return current
            return current.model_copy(update={"semantic_index": semantic_index})

        return self._conditional_update(
            snapshot,
            now,
            update,
            persist_normalized=lambda connection, document_id: self._persist_semantic_index(
                connection, document_id, semantic_index, now
            ),
        )

    def save_extraction_if_current(
        self,
        snapshot: StoredDocumentRecord,
        extraction: ExtractionResult,
        now: datetime,
    ) -> bool:
        """Publish the first extraction only for its unchanged source reading."""
        if snapshot.reading is None or extraction.document_id != snapshot.document_id:
            return False

        def update(current: StoredDocumentRecord) -> StoredDocumentRecord | None:
            if current.reading != snapshot.reading:
                return None
            if current.extraction is not None:
                return current if current.extraction == extraction else None
            return current.model_copy(update={"extraction": extraction})

        return self._conditional_update(snapshot, now, update)

    def save_review_if_current(
        self,
        snapshot: StoredDocumentRecord,
        review: ReviewState,
        now: datetime,
    ) -> bool:
        """Save reviewer values only while their exact extraction remains current."""
        if snapshot.extraction is None:
            return False

        def update(current: StoredDocumentRecord) -> StoredDocumentRecord | None:
            if current.extraction != snapshot.extraction:
                return None
            if current.review == review:
                return current
            # A review may be revised, but a stale review snapshot must not overwrite a
            # newer edit made after the caller read it.
            if current.review != snapshot.review:
                return None
            return current.model_copy(update={"review": review})

        return self._conditional_update(snapshot, now, update)

    def delete(self, record: StoredDocumentRecord) -> None:
        """Delete bytes first while retaining retryable PostgreSQL lifecycle state."""
        document_id = self._uuid(record.document_id, field="document_id")
        with self._engine.begin() as connection:
            row = self._locked_row(connection, document_id)
            if row is None or row["object_key"] != record.storage_key:
                return
            connection.execute(
                sa.update(documents)
                .where(documents.c.id == document_id, documents.c.version == row["version"])
                .values(
                    lifecycle_state=_DELETION_PENDING,
                    version=row["version"] + 1,
                    updated_at=datetime.now(tz=record.created_at.tzinfo),
                )
            )

        try:
            self._content_store.delete(record.storage_key)
        except Exception:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.update(documents)
                    .where(
                        documents.c.id == document_id,
                        documents.c.object_key == record.storage_key,
                        documents.c.lifecycle_state == _DELETION_PENDING,
                    )
                    .values(lifecycle_state=_DELETION_FAILED, version=documents.c.version + 1)
                )
            raise

        with self._engine.begin() as connection:
            connection.execute(
                sa.delete(documents).where(
                    documents.c.id == document_id,
                    documents.c.object_key == record.storage_key,
                    documents.c.lifecycle_state == _DELETION_PENDING,
                )
            )

    def cleanup_expired(self, now: datetime) -> int:
        """Best-effort deletion of expired records without listing object storage."""
        statement = sa.select(documents.c.record_json).where(documents.c.expires_at <= now)
        with self._engine.connect() as connection:
            payloads = tuple(connection.execute(statement).scalars())

        removed = 0
        for payload in payloads:
            record = self._hydrate(payload)
            if record is None or record.expires_at > now:
                continue
            try:
                self.delete(record)
            except ObjectStoreError:
                continue
            removed += 1
        return removed

    def _conditional_update(
        self,
        snapshot: StoredDocumentRecord,
        now: datetime,
        build_updated: Callable[[StoredDocumentRecord], StoredDocumentRecord | None],
        *,
        persist_normalized: Callable[[Connection, UUID], None] | None = None,
    ) -> bool:
        try:
            document_id = self._uuid(snapshot.document_id, field="document_id")
        except ValueError:
            return False
        try:
            with self._engine.begin() as connection:
                row = self._locked_row(connection, document_id)
                current = self._hydrate(None if row is None else row["record_json"])
                if not self._matches_snapshot(current, snapshot, now):
                    return False
                assert current is not None and row is not None
                updated = build_updated(current)
                if updated is None:
                    return False
                if updated == current:
                    return True
                result = connection.execute(
                    sa.update(documents)
                    .where(
                        documents.c.id == document_id,
                        documents.c.lifecycle_state == _ACTIVE,
                        documents.c.version == row["version"],
                    )
                    .values(
                        record_json=self._record_payload(updated),
                        page_count=updated.page_count,
                        version=row["version"] + 1,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    return False
                if persist_normalized is not None:
                    persist_normalized(connection, document_id)
                return True
        except _ConditionalWriteRejected:
            return False

    @staticmethod
    def _persist_reading(
        connection: Connection,
        document_id: UUID,
        reading: ReadingResult,
    ) -> None:
        """Insert one normalized reading tree in the document update transaction."""
        reading_id = uuid4()
        methods = {page.method for page in reading.pages}
        aggregate_method = next(iter(methods)) if len(methods) == 1 else "hybrid"
        connection.execute(
            sa.insert(readings).values(
                id=reading_id,
                document_id=document_id,
                reading_sha256=PostgresDocumentRepository._reading_sha256(reading),
                method=aggregate_method,
                status=reading.status.value,
                page_count=len(reading.pages),
                warnings_json=list(reading.warnings),
                created_at=reading.created_at,
            )
        )
        for page in reading.pages:
            page_id = uuid4()
            connection.execute(
                sa.insert(reading_pages).values(
                    id=page_id,
                    reading_id=reading_id,
                    page_number=page.page_number,
                    text=page.text,
                    text_sha256=hashlib.sha256(page.text.encode("utf-8")).digest(),
                    method=page.method,
                )
            )
            for block_order, block in enumerate(page.blocks):
                source_block_id = block.block_id or (
                    f"page-{page.page_number}-block-{block_order + 1}"
                )
                connection.execute(
                    sa.insert(evidence_blocks).values(
                        id=uuid4(),
                        document_id=document_id,
                        reading_id=reading_id,
                        page_id=page_id,
                        source_block_id=source_block_id,
                        block_order=block_order,
                        kind="text",
                        source_text=block.source_text,
                        text_sha256=hashlib.sha256(block.source_text.encode("utf-8")).digest(),
                        bounding_box_json=(
                            list(block.bounding_box)
                            if block.bounding_box is not None
                            # JSONB encodes Python None as JSON null. The schema reserves
                            # a database NULL for absent geometry, so make that distinction
                            # explicit instead of weakening its array-only constraint.
                            else sa.null()
                        ),
                        confidence=block.confidence,
                    )
                )

    @staticmethod
    def _persist_semantic_index(
        connection: Connection,
        document_id: UUID,
        semantic_index: SemanticIndex,
        now: datetime,
    ) -> None:
        """Replace the document's normalized vector set using persisted evidence IDs."""
        reading_row = (
            connection.execute(
                sa.select(readings.c.id).where(
                    readings.c.document_id == document_id,
                    readings.c.reading_sha256 == bytes.fromhex(semantic_index.reading_sha256),
                )
            )
            .mappings()
            .one_or_none()
        )
        if reading_row is None:
            raise _ConditionalWriteRejected
        evidence_rows = connection.execute(
            sa.select(evidence_blocks.c.id, evidence_blocks.c.source_block_id).where(
                evidence_blocks.c.document_id == document_id,
                evidence_blocks.c.reading_id == reading_row["id"],
                evidence_blocks.c.source_block_id.in_(semantic_index.block_ids),
            )
        ).mappings()
        evidence_by_source = {row["source_block_id"]: row["id"] for row in evidence_rows}
        if set(evidence_by_source) != set(semantic_index.block_ids):
            raise _ConditionalWriteRejected

        connection.execute(
            sa.delete(embedding_sets).where(embedding_sets.c.document_id == document_id)
        )
        embedding_set_id = uuid4()
        connection.execute(
            sa.insert(embedding_sets).values(
                id=embedding_set_id,
                document_id=document_id,
                reading_id=reading_row["id"],
                reading_sha256=bytes.fromhex(semantic_index.reading_sha256),
                model_name=semantic_index.model,
                dimensions=semantic_index.dimensions,
                created_at=now,
            )
        )
        connection.execute(
            sa.insert(block_embeddings),
            [
                {
                    "embedding_set_id": embedding_set_id,
                    "document_id": document_id,
                    "evidence_block_id": evidence_by_source[source_block_id],
                    "block_order": block_order,
                    "embedding": list(vector),
                    "created_at": now,
                }
                for block_order, (source_block_id, vector) in enumerate(
                    zip(semantic_index.block_ids, semantic_index.vectors, strict=True)
                )
            ],
        )

    @staticmethod
    def _reading_sha256(reading: ReadingResult) -> bytes:
        """Match the semantic service's exact immutable reading digest."""
        return hashlib.sha256(reading.model_dump_json().encode("utf-8")).digest()

    @staticmethod
    def _locked_row(connection: Connection, document_id: UUID) -> sa.RowMapping | None:
        statement = (
            sa.select(
                documents.c.object_key,
                documents.c.version,
                documents.c.lifecycle_state,
                documents.c.record_json,
            )
            .where(documents.c.id == document_id)
            .with_for_update()
        )
        return connection.execute(statement).mappings().one_or_none()

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
    def _record_payload(record: StoredDocumentRecord) -> dict[str, Any]:
        return record.model_dump(mode="json")

    @staticmethod
    def _hydrate(payload: object) -> StoredDocumentRecord | None:
        if not isinstance(payload, dict):
            return None
        try:
            # JSONB drivers return dictionaries. Re-enter through Pydantic's JSON mode so
            # strict immutable tuple fields retain the same behavior as existing sidecars.
            return StoredDocumentRecord.model_validate_json(json.dumps(payload))
        except (TypeError, ValueError, ValidationError):
            return None

    @staticmethod
    def _uuid(value: str, *, field: str) -> UUID:
        try:
            parsed = UUID(value)
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"{field} must be a canonical UUID.") from None
        if str(parsed) != value:
            raise ValueError(f"{field} must be a canonical UUID.")
        return parsed

    @staticmethod
    def _capability_hash(value: str | None) -> bytes | None:
        if value is None:
            return None
        try:
            decoded = bytes.fromhex(value)
        except ValueError:
            raise ValueError("access_token_hash must be a SHA-256 hex digest.") from None
        if len(decoded) != 32 or value != value.lower():
            raise ValueError("access_token_hash must be a SHA-256 hex digest.")
        return decoded

    @staticmethod
    def _validate_access_principal(
        record: StoredDocumentRecord, capability_hash: bytes | None
    ) -> None:
        if (record.owner_subject is None) == (capability_hash is None):
            raise ValueError("Document metadata must contain exactly one access principal.")
        if record.owner_subject == "":
            raise ValueError("owner_subject must not be empty.")

    def _owner_user_id(
        self,
        connection: Connection,
        *,
        subject: str | None,
        created_at: datetime,
    ) -> UUID | None:
        """Resolve or create the JWT principal inside the document transaction."""
        if subject is None:
            return None
        statement = sa.select(app_users.c.id).where(
            app_users.c.issuer == self._owner_issuer,
            app_users.c.subject == subject,
            app_users.c.status == "ACTIVE",
        )
        existing = cast(UUID | None, connection.execute(statement).scalar_one_or_none())
        if existing is not None:
            return existing

        user_id = uuid4()
        try:
            with connection.begin_nested():
                connection.execute(
                    sa.insert(app_users).values(
                        id=user_id,
                        issuer=self._owner_issuer,
                        subject=subject,
                        status="ACTIVE",
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
        except IntegrityError:
            existing = cast(UUID | None, connection.execute(statement).scalar_one_or_none())
            if existing is None:
                raise
            return existing
        return user_id

    def _best_effort_delete(self, object_key: str) -> None:
        try:
            self._content_store.delete(object_key)
        except ObjectStoreError:
            pass

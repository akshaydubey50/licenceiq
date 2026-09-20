"""Offline contract checks for PostgreSQL metadata and private blob persistence."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool

import app.repositories.postgres_documents as postgres_module
from app.models.document import (
    DocumentPage,
    Evidence,
    ExtractedLicence,
    ExtractionResult,
    ExtractionStatus,
    QuestionCitation,
    QuestionResult,
    QuestionStatus,
    ReadingResult,
    ReadingStatus,
    ReviewFields,
    ReviewState,
    SemanticIndex,
)
from app.repositories.documents import StoredDocumentRecord
from app.repositories.object_store import ObjectStoreError
from app.repositories.postgres_documents import PostgresDocumentRepository

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


class FakeObjectStore:
    """Keep unit tests provider-free while recording every blob key used."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.put_keys: list[str] = []
        self.initialized = False
        self.fail_delete: set[str] = set()

    def initialize(self) -> None:
        self.initialized = True

    def generate_key(self) -> str:
        return str(uuid4())

    def put(self, key: str, content: bytes, *, content_type: str) -> None:
        assert content_type
        self.put_keys.append(key)
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectStoreError("read") from None

    def delete(self, key: str) -> None:
        if key in self.fail_delete:
            raise ObjectStoreError("delete")
        self.objects.pop(key, None)

    def list_keys(self) -> tuple[str, ...]:
        raise AssertionError("PostgreSQL cleanup must not list blob storage as metadata.")


@pytest.fixture
def repository(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]]:
    """Use SQLite only as an offline SQLAlchemy transaction harness."""
    metadata = sa.MetaData()
    users_table = sa.Table(
        "app_users",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(320), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("issuer", "subject"),
    )
    documents_table = sa.Table(
        "documents",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(as_uuid=True)),
        sa.Column("owner_subject", sa.String(320)),
        sa.Column("capability_hash", sa.LargeBinary(32)),
        sa.Column("object_key", sa.String(512), nullable=False, unique=True),
        sa.Column("content_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("safe_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("page_count", sa.Integer),
        sa.Column("lifecycle_state", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("record_json", sa.JSON, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    readings_table = sa.Table(
        "readings",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("warnings_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    chat_turns_table = sa.Table(
        "chat_turns",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer", sa.String(4096), nullable=False),
        sa.Column("citations_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    pages_table = sa.Table(
        "reading_pages",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("reading_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
    )
    blocks_table = sa.Table(
        "evidence_blocks",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reading_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("page_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("source_block_id", sa.String(256), nullable=False),
        sa.Column("block_order", sa.Integer, nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("bounding_box_json", sa.JSON),
        sa.Column("confidence", sa.Float),
    )
    sets_table = sa.Table(
        "embedding_sets",
        metadata,
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reading_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    embeddings_table = sa.Table(
        "block_embeddings",
        metadata,
        sa.Column("embedding_set_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("evidence_block_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("block_order", sa.Integer, nullable=False),
        sa.Column("embedding", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    tables = {
        "app_users": users_table,
        "documents": documents_table,
        "readings": readings_table,
        "chat_turns": chat_turns_table,
        "reading_pages": pages_table,
        "evidence_blocks": blocks_table,
        "embedding_sets": sets_table,
        "block_embeddings": embeddings_table,
    }
    for name, table in tables.items():
        monkeypatch.setattr(postgres_module, name, table)
    store = FakeObjectStore()
    return (
        PostgresDocumentRepository(engine, store, owner_issuer="https://issuer.example"),
        store,
        engine,
        tables,
    )


def make_record(
    *, expires_at: datetime, filename: str = "private licence.png"
) -> StoredDocumentRecord:
    content = b"private-document"
    return StoredDocumentRecord(
        document_id=str(uuid4()),
        filename=filename,
        mime_type="image/png",
        size_bytes=len(content),
        created_at=NOW - timedelta(hours=1),
        expires_at=expires_at,
        page_count=1,
        storage_key=str(uuid4()),
        access_token_hash="ab" * 32,
    )


def make_reading(document_id: str) -> ReadingResult:
    return ReadingResult(
        document_id=document_id,
        status=ReadingStatus.READ,
        pages=(
            DocumentPage(
                document_id=document_id,
                page_number=1,
                text="Licence source text",
                blocks=(
                    Evidence(
                        document_id=document_id,
                        page_number=1,
                        source_text="Licence source text",
                        block_id="page-1",
                        confidence=0.95,
                    ),
                ),
                method="native_text",
            ),
        ),
        created_at=NOW,
    )


def make_owned_record(*, expires_at: datetime, created_at: datetime = NOW) -> StoredDocumentRecord:
    content = b"private-document"
    return StoredDocumentRecord(
        document_id=str(uuid4()),
        filename="owned.png",
        mime_type="image/png",
        size_bytes=len(content),
        created_at=created_at,
        expires_at=expires_at,
        page_count=1,
        storage_key=str(uuid4()),
        owner_subject="owner-a",
    )


def make_question_result(document_id: str) -> QuestionResult:
    return QuestionResult(
        document_id=document_id,
        question="What is shown?",
        status=QuestionStatus.ANSWERED,
        answer="The source says Licence source text.",
        citations=(QuestionCitation(block_id="page-1", page_number=1),),
        created_at=NOW,
    )


def make_extraction(document_id: str) -> ExtractionResult:
    return ExtractionResult(
        document_id=document_id,
        status=ExtractionStatus.EXTRACTED,
        licence=ExtractedLicence(document_id=document_id),
        created_at=NOW,
    )


def make_review(value: str) -> ReviewState:
    return ReviewState(
        fields=ReviewFields(
            full_name=value,
            licence_number=None,
            date_of_birth=None,
            date_of_issue=None,
            date_of_expiry=None,
            address=None,
            vehicle_classes=(),
            issuing_authority=None,
            other_information={},
        ),
        updated_at=NOW,
    )


def test_round_trip_keeps_blob_key_free_of_filename_and_capability(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, store, _engine, _table = repository
    record = make_record(expires_at=NOW + timedelta(hours=1))

    repo.initialize()
    repo.save(record, b"private-document")

    assert store.initialized is True
    assert store.put_keys == [record.storage_key]
    assert record.filename not in store.put_keys[0]
    assert record.access_token_hash not in store.put_keys[0]
    assert repo.get(record.document_id) == record
    assert repo.read_content(record) == b"private-document"
    assert repo.get("not-a-uuid") is None


def test_owned_document_resolves_an_app_user_principal(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, _store, engine, tables = repository
    owned = make_record(expires_at=NOW + timedelta(hours=1)).model_copy(
        update={"access_token_hash": None, "owner_subject": "user-123"}
    )

    repo.save(owned, b"private-document")

    with engine.connect() as connection:
        user = connection.execute(sa.select(tables["app_users"])).mappings().one()
        document = connection.execute(sa.select(tables["documents"])).mappings().one()
    assert user["issuer"] == "https://issuer.example"
    assert user["subject"] == "user-123"
    assert document["owner_user_id"] == user["id"]
    assert document["owner_subject"] == "user-123"
    assert document["capability_hash"] is None


def test_conditional_results_round_trip_and_stale_review_is_rejected(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, _store, engine, tables = repository
    record = make_record(expires_at=NOW + timedelta(hours=1))
    repo.save(record, b"private-document")

    reading = make_reading(record.document_id)
    assert repo.save_reading_if_current(record, reading, NOW) is True
    read_snapshot = repo.get(record.document_id)
    assert read_snapshot is not None and read_snapshot.reading == reading
    with engine.connect() as connection:
        normalized_reading = connection.execute(sa.select(tables["readings"])).mappings().one()
        normalized_page = connection.execute(sa.select(tables["reading_pages"])).mappings().one()
        normalized_block = connection.execute(sa.select(tables["evidence_blocks"])).mappings().one()
    assert (
        normalized_reading["reading_sha256"]
        == hashlib.sha256(reading.model_dump_json().encode("utf-8")).digest()
    )
    assert normalized_page["method"] == "native_text"
    assert normalized_block["source_block_id"] == "page-1"
    assert normalized_block["confidence"] == 0.95
    assert normalized_block["bounding_box_json"] is None

    vector = (1.0,) + (0.0,) * 255
    semantic = SemanticIndex(
        document_id=record.document_id,
        reading_sha256=hashlib.sha256(reading.model_dump_json().encode("utf-8")).hexdigest(),
        model="offline-test",
        dimensions=256,
        block_ids=("page-1",),
        vectors=(vector,),
    )
    assert repo.save_semantic_index_if_current(read_snapshot, semantic, NOW) is True
    semantic_snapshot = repo.get(record.document_id)
    assert semantic_snapshot is not None and semantic_snapshot.semantic_index == semantic
    with engine.connect() as connection:
        normalized_set = connection.execute(sa.select(tables["embedding_sets"])).mappings().one()
        normalized_embedding = (
            connection.execute(sa.select(tables["block_embeddings"])).mappings().one()
        )
    assert normalized_set["dimensions"] == 256
    assert normalized_set["reading_id"] == normalized_reading["id"]
    assert normalized_embedding["evidence_block_id"] == normalized_block["id"]
    assert normalized_embedding["embedding"] == list(vector)

    extraction = make_extraction(record.document_id)
    assert repo.save_extraction_if_current(semantic_snapshot, extraction, NOW) is True
    extraction_snapshot = repo.get(record.document_id)
    assert extraction_snapshot is not None and extraction_snapshot.extraction == extraction

    first_review = make_review("First review")
    assert repo.save_review_if_current(extraction_snapshot, first_review, NOW) is True
    assert repo.save_review_if_current(extraction_snapshot, make_review("Stale edit"), NOW) is False
    stored = repo.get(record.document_id)
    assert stored is not None and stored.review == first_review


def test_stale_source_snapshot_and_wrong_embedding_dimension_are_rejected(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, _store, engine, tables = repository
    record = make_record(expires_at=NOW + timedelta(hours=1))
    repo.save(record, b"private-document")
    reading = make_reading(record.document_id)
    assert repo.save_reading_if_current(record, reading, NOW) is True

    stale = record.model_copy(update={"storage_key": str(uuid4())})
    assert repo.save_reading_if_current(stale, reading, NOW) is False
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(tables["readings"])
            ).scalar_one()
            == 1
        )
    unsupported = SemanticIndex(
        document_id=record.document_id,
        reading_sha256="ef" * 32,
        model="wrong-size",
        dimensions=2,
        block_ids=("page-1",),
        vectors=((1.0, 0.0),),
    )
    current = repo.get(record.document_id)
    assert current is not None
    assert repo.save_semantic_index_if_current(current, unsupported, NOW) is False
    missing_evidence = SemanticIndex(
        document_id=record.document_id,
        reading_sha256=hashlib.sha256(reading.model_dump_json().encode("utf-8")).hexdigest(),
        model="offline-test",
        dimensions=256,
        block_ids=("missing-block",),
        vectors=((1.0,) + (0.0,) * 255,),
    )
    assert repo.save_semantic_index_if_current(current, missing_evidence, NOW) is False
    assert repo.get(record.document_id) == current
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.select(sa.func.count()).select_from(tables["embedding_sets"])
            ).scalar_one()
            == 0
        )


def test_owned_document_list_is_newest_first_bounded_and_excludes_guests(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, _store, _engine, _tables = repository
    for index in range(52):
        record = make_owned_record(
            expires_at=NOW + timedelta(hours=1),
            created_at=NOW - timedelta(minutes=index),
        )
        repo.save(record, b"private-document")
    guest = make_record(expires_at=NOW + timedelta(hours=1), filename="guest.png")
    repo.save(guest, b"private-document")

    records = repo.list_owned("owner-a", NOW, limit=50)

    assert len(records) == 50
    assert all(record.owner_subject == "owner-a" for record in records)
    assert all(record.filename != "guest.png" for record in records)
    assert tuple(record.created_at for record in records) == tuple(
        sorted((record.created_at for record in records), reverse=True)
    )


def test_validated_chat_result_round_trips_with_citations_and_can_be_cleared(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, _store, engine, tables = repository
    record = make_owned_record(expires_at=NOW + timedelta(hours=1))
    repo.save(record, b"private-document")
    reading = make_reading(record.document_id)
    assert repo.save_reading_if_current(record, reading, NOW) is True
    snapshot = repo.get(record.document_id)
    assert snapshot is not None and snapshot.reading == reading
    result = make_question_result(record.document_id)

    assert repo.save_chat_turn_if_current(snapshot, result, NOW) is True
    assert repo.get_chat_history(record.document_id, "owner-b", NOW, limit=100) == ()
    assert repo.get_chat_history(record.document_id, "owner-a", NOW, limit=100) == (result,)

    with engine.connect() as connection:
        row = connection.execute(sa.select(tables["chat_turns"])).mappings().one()
    assert row["question"] == result.question
    assert row["citations_json"] == [{"block_id": "page-1", "page_number": 1}]
    assert (
        row["reading_sha256"] == hashlib.sha256(reading.model_dump_json().encode("utf-8")).digest()
    )

    repo.clear_chat_history(record.document_id, "owner-b")
    assert repo.get_chat_history(record.document_id, "owner-a", NOW, limit=100) == (result,)
    repo.clear_chat_history(record.document_id, "owner-a")
    assert repo.get_chat_history(record.document_id, "owner-a", NOW, limit=100) == ()


def test_cleanup_and_delete_use_postgres_records_and_retry_failed_blob_removal(
    repository: tuple[PostgresDocumentRepository, FakeObjectStore, sa.Engine, dict[str, sa.Table]],
) -> None:
    repo, store, engine, tables = repository
    table = tables["documents"]
    expired = make_record(expires_at=NOW - timedelta(minutes=1), filename="expired.png")
    live = make_record(expires_at=NOW + timedelta(hours=1), filename="live.png")
    repo.save(expired, b"private-document")
    repo.save(live, b"private-document")
    store.fail_delete.add(expired.storage_key)

    assert repo.cleanup_expired(NOW) == 0
    with engine.connect() as connection:
        retained = connection.execute(
            sa.select(table.c.lifecycle_state).where(table.c.id == uuid4_from(expired.document_id))
        ).scalar_one()
    assert retained == "DELETION_FAILED"

    store.fail_delete.clear()
    assert repo.cleanup_expired(NOW) == 1
    assert expired.storage_key not in store.objects
    repo.delete(live)
    assert live.storage_key not in store.objects
    assert repo.get(live.document_id) is None
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 0


def uuid4_from(value: str) -> UUID:
    """Return a UUID without weakening the production repository's canonical check."""
    return UUID(value)


def test_follow_up_migration_declares_record_and_page_method_contract() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    output = StringIO()
    config.output_buffer = output

    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["20260920_0004"]
    assert script.get_revision("20260920_0003").down_revision == "20260920_0002"
    assert "ADD COLUMN owner_subject" in sql
    assert "ADD COLUMN record_json JSONB" in sql
    assert "ADD COLUMN method VARCHAR(32)" in sql
    assert "ck_documents_record_document_id_matches" in sql
    assert "ck_documents_record_object_key_matches" in sql
    assert "ck_documents_record_capability_hash_matches" in sql
    assert "ck_reading_pages_method_allowed" in sql
    assert "embedding vector(256) not null" in " ".join(sql.lower().split())

"""Offline checks for the optional PostgreSQL durable schema."""

from __future__ import annotations

import re
from functools import lru_cache
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.persistence.database import metadata
from app.persistence.models import EMBEDDING_DIMENSIONS

BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "app_users",
    "local_credentials",
    "auth_sessions",
    "documents",
    "readings",
    "reading_pages",
    "evidence_blocks",
    "extractions",
    "extraction_evidence_links",
    "reviews",
    "embedding_sets",
    "block_embeddings",
    "chat_turns",
}


def _alembic_config() -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    return config


@lru_cache(maxsize=1)
def _upgrade_sql() -> str:
    output = StringIO()
    config = _alembic_config()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    return output.getvalue()


def test_migration_history_is_a_linear_chain() -> None:
    script = ScriptDirectory.from_config(_alembic_config())

    assert script.get_heads() == ["20260920_0004"]
    assert script.get_base() == "20260920_0001"
    assert script.get_revision("20260920_0002").down_revision == "20260920_0001"
    assert script.get_revision("20260920_0003").down_revision == "20260920_0002"
    assert script.get_revision("20260920_0004").down_revision == "20260920_0003"


def test_metadata_declares_the_complete_durable_schema() -> None:
    assert set(metadata.tables) == EXPECTED_TABLES
    assert EMBEDDING_DIMENSIONS == 256
    assert str(metadata.tables["block_embeddings"].c.embedding.type) == "VECTOR(256)"
    chat_foreign_keys = tuple(metadata.tables["chat_turns"].foreign_key_constraints)
    assert len(chat_foreign_keys) == 1
    assert chat_foreign_keys[0].ondelete == "CASCADE"


def test_document_delete_or_expiry_cascades_through_readings_to_chat_turns() -> None:
    reading_foreign_key = next(
        constraint
        for constraint in metadata.tables["readings"].foreign_key_constraints
        if constraint.referred_table.name == "documents"
    )
    chat_foreign_key = next(iter(metadata.tables["chat_turns"].foreign_key_constraints))

    assert reading_foreign_key.ondelete == "CASCADE"
    assert chat_foreign_key.referred_table.name == "readings"
    assert chat_foreign_key.ondelete == "CASCADE"


def test_offline_upgrade_sql_contains_security_and_isolation_contracts() -> None:
    sql = _upgrade_sql()
    compact_sql = " ".join(sql.split())
    compact_sql_lower = compact_sql.lower()
    created_tables = set(re.findall(r"CREATE TABLE ([a-z_]+)", sql))

    assert created_tables == EXPECTED_TABLES | {"alembic_version"}
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert sql.index("CREATE EXTENSION IF NOT EXISTS vector") < sql.index("CREATE TABLE app_users")
    assert "ck_documents_exactly_one_access_principal" in sql
    assert "ck_local_credentials_password_hash_argon2" in sql
    assert "uq_local_credentials_username" in sql
    assert "uq_documents_object_key" in sql
    assert "uq_documents_capability_hash" in sql
    assert "ck_documents_content_sha256" in sql
    assert "ck_documents_expiry_after_creation" in sql
    assert "PENDING_UPLOAD" in sql and "DELETION_PENDING" in sql
    assert "uq_reading_pages_source_order" in sql
    assert "uq_evidence_blocks_source_id" in sql
    assert "uq_evidence_blocks_source_order" in sql
    assert "uq_extractions_document_version" in sql
    assert "uq_reviews_document_version" in sql
    assert "uq_embedding_sets_reading_model_dimensions" in sql
    assert "fk_extract_links_block" in sql
    assert "fk_block_embeddings_block" in sql
    assert "fk_chat_turns_reading" in sql
    assert "ck_chat_turns_status_allowed" in sql
    assert "CREATE INDEX ix_chat_turns_document_created" in sql
    assert "embedding vector(256) not null" in compact_sql_lower
    assert (
        "generated always as (to_tsvector('simple', coalesce(text, ''))) stored"
        in compact_sql_lower
    )
    assert "CREATE INDEX ix_reading_pages_search" in sql and "USING gin" in sql
    assert "CREATE INDEX ix_evidence_blocks_search" in sql and "USING gin" in sql
    assert "USING hnsw" not in sql.lower()

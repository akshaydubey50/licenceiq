"""Create the private durable schema foundation.

Revision ID: 20260920_0001
Revises: None
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create the append-oriented document, evidence, review, and retrieval schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "app_users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("issuer", sa.String(512), nullable=False),
        sa.Column("subject", sa.String(320), nullable=False),
        sa.Column("status", sa.String(32), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("issuer <> ''", name="ck_app_users_issuer_nonempty"),
        sa.CheckConstraint("subject <> ''", name="ck_app_users_subject_nonempty"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_app_users_status_allowed"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_app_users_timestamps_ordered"),
        sa.PrimaryKeyConstraint("id", name="pk_app_users"),
        sa.UniqueConstraint("issuer", "subject", name="uq_app_users_issuer_subject"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("sid", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("jti", sa.String(128), nullable=False),
        sa.Column("issued_at", TIMESTAMPTZ, nullable=False),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
        sa.Column("revoked_at", TIMESTAMPTZ),
        sa.CheckConstraint("expires_at > issued_at", name="ck_auth_sessions_expiry_after_issue"),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= issued_at",
            name="ck_auth_sessions_revocation_after_issue",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_auth_sessions_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sid", name="pk_auth_sessions"),
        sa.UniqueConstraint("jti", name="uq_auth_sessions_jti"),
    )
    op.create_index("ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"])
    op.create_index(
        "ix_auth_sessions_active_expiry",
        "auth_sessions",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "documents",
        sa.Column("id", UUID, nullable=False),
        sa.Column("owner_user_id", UUID),
        sa.Column("capability_hash", sa.LargeBinary(32)),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("content_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("safe_filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer()),
        sa.Column(
            "lifecycle_state", sa.String(32), server_default="PENDING_UPLOAD", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "(owner_user_id IS NOT NULL) <> (capability_hash IS NOT NULL)",
            name="ck_documents_exactly_one_access_principal",
        ),
        sa.CheckConstraint(
            "octet_length(capability_hash) = 32", name="ck_documents_capability_sha256"
        ),
        sa.CheckConstraint("octet_length(content_sha256) = 32", name="ck_documents_content_sha256"),
        sa.CheckConstraint("object_key <> ''", name="ck_documents_object_key_nonempty"),
        sa.CheckConstraint(
            "safe_filename <> '' AND safe_filename !~ '[\\\\/]'",
            name="ck_documents_safe_filename",
        ),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf', 'image/png', 'image/jpeg')",
            name="ck_documents_mime_type_allowed",
        ),
        sa.CheckConstraint("size_bytes BETWEEN 1 AND 10485760", name="ck_documents_size_bounds"),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count BETWEEN 1 AND 20",
            name="ck_documents_page_bounds",
        ),
        sa.CheckConstraint(
            "lifecycle_state IN ('PENDING_UPLOAD', 'ACTIVE', 'DELETION_PENDING', "
            "'DELETION_FAILED')",
            name="ck_documents_lifecycle_state_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="ck_documents_version_positive"),
        sa.CheckConstraint("updated_at >= created_at", name="ck_documents_timestamps_ordered"),
        sa.CheckConstraint("expires_at > created_at", name="ck_documents_expiry_after_creation"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["app_users.id"],
            name="fk_documents_owner_user_id_app_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("capability_hash", name="uq_documents_capability_hash"),
        sa.UniqueConstraint("object_key", name="uq_documents_object_key"),
    )
    op.create_index("ix_documents_expiry", "documents", ["expires_at"])
    op.create_index("ix_documents_owner_created", "documents", ["owner_user_id", "created_at"])
    op.create_index("ix_documents_state_updated", "documents", ["lifecycle_state", "updated_at"])

    op.create_table(
        "readings",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("warnings_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("octet_length(reading_sha256) = 32", name="ck_readings_reading_sha256"),
        sa.CheckConstraint(
            "method IN ('native_text', 'ocr', 'hybrid')", name="ck_readings_method_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('READ', 'READ_WITH_WARNINGS')", name="ck_readings_status_allowed"
        ),
        sa.CheckConstraint("page_count BETWEEN 1 AND 20", name="ck_readings_page_bounds"),
        sa.CheckConstraint(
            "jsonb_typeof(warnings_json) = 'array'", name="ck_readings_warnings_array"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_readings_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_readings"),
        sa.UniqueConstraint("document_id", "id", name="uq_readings_document_id"),
        sa.UniqueConstraint("document_id", "id", "reading_sha256", name="uq_readings_scope_sha"),
        sa.UniqueConstraint("document_id", "reading_sha256", name="uq_readings_document_sha"),
    )
    op.create_index("ix_readings_document_created", "readings", ["document_id", "created_at"])

    op.create_table(
        "reading_pages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True),
        ),
        sa.CheckConstraint("page_number >= 1", name="ck_reading_pages_page_number_positive"),
        sa.CheckConstraint("octet_length(text_sha256) = 32", name="ck_reading_pages_text_sha256"),
        sa.ForeignKeyConstraint(
            ["reading_id"],
            ["readings.id"],
            name="fk_reading_pages_reading_id_readings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reading_pages"),
        sa.UniqueConstraint("reading_id", "id", name="uq_reading_pages_reading_id"),
        sa.UniqueConstraint("reading_id", "page_number", name="uq_reading_pages_source_order"),
    )
    op.create_index(
        "ix_reading_pages_search", "reading_pages", ["search_vector"], postgresql_using="gin"
    )

    op.create_table(
        "evidence_blocks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("page_id", UUID, nullable=False),
        sa.Column("source_block_id", sa.String(256), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("bounding_box_json", JSONB),
        sa.Column("confidence", sa.Float()),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(source_text, ''))", persisted=True),
        ),
        sa.CheckConstraint("block_order >= 0", name="ck_evidence_blocks_block_order_nonnegative"),
        sa.CheckConstraint(
            "source_block_id <> ''", name="ck_evidence_blocks_source_block_id_nonempty"
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'field', 'table', 'image')",
            name="ck_evidence_blocks_kind_allowed",
        ),
        sa.CheckConstraint("source_text <> ''", name="ck_evidence_blocks_source_text_nonempty"),
        sa.CheckConstraint("octet_length(text_sha256) = 32", name="ck_evidence_blocks_text_sha256"),
        sa.CheckConstraint(
            "bounding_box_json IS NULL OR jsonb_typeof(bounding_box_json) = 'array'",
            name="ck_evidence_blocks_bounding_box_array",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="ck_evidence_blocks_confidence_bounds",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_id"],
            ["readings.document_id", "readings.id"],
            name="fk_evidence_blocks_document_id_reading_id_readings",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reading_id", "page_id"],
            ["reading_pages.reading_id", "reading_pages.id"],
            name="fk_evidence_blocks_reading_id_page_id_reading_pages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_blocks"),
        sa.UniqueConstraint("document_id", "id", name="uq_evidence_blocks_document_id"),
        sa.UniqueConstraint("document_id", "reading_id", "id", name="uq_evidence_blocks_scope_id"),
        sa.UniqueConstraint("reading_id", "source_block_id", name="uq_evidence_blocks_source_id"),
        sa.UniqueConstraint("page_id", "block_order", name="uq_evidence_blocks_source_order"),
    )
    op.create_index(
        "ix_evidence_blocks_document_order",
        "evidence_blocks",
        ["document_id", "reading_id", "page_id", "block_order"],
    )
    op.create_index(
        "ix_evidence_blocks_search",
        "evidence_blocks",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.create_table(
        "extractions",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("extraction_version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("extraction_json", JSONB, nullable=False),
        sa.Column("warnings_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("extraction_version >= 1", name="ck_extractions_version_positive"),
        sa.CheckConstraint(
            "status IN ('EXTRACTED', 'EXTRACTED_WITH_WARNINGS')",
            name="ck_extractions_status_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(extraction_json) = 'object'", name="ck_extractions_payload_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(warnings_json) = 'array'", name="ck_extractions_warnings_array"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_id"],
            ["readings.document_id", "readings.id"],
            name="fk_extractions_document_id_reading_id_readings",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_extractions"),
        sa.UniqueConstraint("document_id", "id", name="uq_extractions_document_id"),
        sa.UniqueConstraint("document_id", "reading_id", "id", name="uq_extractions_scope_id"),
        sa.UniqueConstraint(
            "document_id", "extraction_version", name="uq_extractions_document_version"
        ),
    )
    op.create_index("ix_extractions_document_created", "extractions", ["document_id", "created_at"])

    op.create_table(
        "extraction_evidence_links",
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("extraction_id", UUID, nullable=False),
        sa.Column("json_pointer", sa.String(1024), nullable=False),
        sa.Column("evidence_block_id", UUID, nullable=False),
        sa.Column("link_order", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "json_pointer LIKE '/%'", name="ck_extraction_evidence_links_json_pointer_absolute"
        ),
        sa.CheckConstraint(
            "link_order >= 0", name="ck_extraction_evidence_links_link_order_nonnegative"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_id", "evidence_block_id"],
            ["evidence_blocks.document_id", "evidence_blocks.reading_id", "evidence_blocks.id"],
            name="fk_extract_links_block",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_id", "extraction_id"],
            ["extractions.document_id", "extractions.reading_id", "extractions.id"],
            name="fk_extract_links_extraction",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "extraction_id",
            "json_pointer",
            "evidence_block_id",
            name="pk_extraction_evidence_links",
        ),
        sa.UniqueConstraint(
            "extraction_id",
            "json_pointer",
            "link_order",
            name="uq_extraction_evidence_link_order",
        ),
    )
    op.create_index(
        "ix_extraction_evidence_links_document",
        "extraction_evidence_links",
        ["document_id", "extraction_id"],
    )

    op.create_table(
        "reviews",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("extraction_id", UUID, nullable=False),
        sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("review_json", JSONB, nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("review_version >= 1", name="ck_reviews_version_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(review_json) = 'object'", name="ck_reviews_payload_object"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "extraction_id"],
            ["extractions.document_id", "extractions.id"],
            name="fk_reviews_document_id_extraction_id_extractions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reviews"),
        sa.UniqueConstraint("document_id", "review_version", name="uq_reviews_document_version"),
    )
    op.create_index("ix_reviews_document_created", "reviews", ["document_id", "created_at"])

    op.create_table(
        "embedding_sets",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "octet_length(reading_sha256) = 32", name="ck_embedding_sets_reading_sha256"
        ),
        sa.CheckConstraint("model_name <> ''", name="ck_embedding_sets_model_name_nonempty"),
        sa.CheckConstraint("dimensions = 256", name="ck_embedding_sets_dimensions_supported"),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_id", "reading_sha256"],
            ["readings.document_id", "readings.id", "readings.reading_sha256"],
            name="fk_embedding_sets_reading",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_embedding_sets"),
        sa.UniqueConstraint("document_id", "id", name="uq_embedding_sets_document_id"),
        sa.UniqueConstraint(
            "document_id",
            "reading_sha256",
            "model_name",
            "dimensions",
            name="uq_embedding_sets_reading_model_dimensions",
        ),
    )
    op.create_index(
        "ix_embedding_sets_document_reading", "embedding_sets", ["document_id", "reading_id"]
    )

    op.create_table(
        "block_embeddings",
        sa.Column("embedding_set_id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("evidence_block_id", UUID, nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(256), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("block_order >= 0", name="ck_block_embeddings_block_order_nonnegative"),
        sa.ForeignKeyConstraint(
            ["document_id", "embedding_set_id"],
            ["embedding_sets.document_id", "embedding_sets.id"],
            name="fk_block_embeddings_set",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "evidence_block_id"],
            ["evidence_blocks.document_id", "evidence_blocks.id"],
            name="fk_block_embeddings_block",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "embedding_set_id", "evidence_block_id", name="pk_block_embeddings"
        ),
        sa.UniqueConstraint(
            "embedding_set_id", "block_order", name="uq_block_embeddings_source_order"
        ),
    )
    op.create_index(
        "ix_block_embeddings_document_set",
        "block_embeddings",
        ["document_id", "embedding_set_id"],
    )


def downgrade() -> None:
    """Remove only LicenceIQ-owned tables; retain the shared vector extension."""
    op.drop_table("block_embeddings")
    op.drop_table("embedding_sets")
    op.drop_table("reviews")
    op.drop_table("extraction_evidence_links")
    op.drop_table("extractions")
    op.drop_table("evidence_blocks")
    op.drop_table("reading_pages")
    op.drop_table("readings")
    op.drop_table("documents")
    op.drop_table("auth_sessions")
    op.drop_table("app_users")

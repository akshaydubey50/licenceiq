"""PostgreSQL schema metadata for private LicenceIQ durable records.

The tables deliberately keep source data and reviewer corrections separate. Generated opaque
object keys locate private MinIO objects; filenames, bearer capabilities, and licence content
must never be used as object keys.
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.persistence.database import metadata

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMPTZ = sa.DateTime(timezone=True)
SHA256_LENGTH = 32
EMBEDDING_DIMENSIONS = 256
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_PAGES = 20

app_users = sa.Table(
    "app_users",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("issuer", sa.String(512), nullable=False),
    sa.Column("subject", sa.String(320), nullable=False),
    sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("issuer", "subject", name="uq_app_users_issuer_subject"),
    sa.CheckConstraint("issuer <> ''", name="issuer_nonempty"),
    sa.CheckConstraint("subject <> ''", name="subject_nonempty"),
    sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status_allowed"),
    sa.CheckConstraint("updated_at >= created_at", name="timestamps_ordered"),
)

local_credentials = sa.Table(
    "local_credentials",
    metadata,
    sa.Column("user_id", UUID, primary_key=True),
    sa.Column("normalized_username", sa.String(64), nullable=False),
    sa.Column("password_hash", sa.String(512), nullable=False),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
    sa.UniqueConstraint("normalized_username", name="uq_local_credentials_username"),
    sa.CheckConstraint(
        "normalized_username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
        name="username_format",
    ),
    sa.CheckConstraint("password_hash LIKE '$argon2%'", name="password_hash_argon2"),
    sa.CheckConstraint("updated_at >= created_at", name="timestamps_ordered"),
)

auth_sessions = sa.Table(
    "auth_sessions",
    metadata,
    sa.Column("sid", UUID, primary_key=True),
    sa.Column("user_id", UUID, nullable=False),
    sa.Column("jti", sa.String(128), nullable=False),
    sa.Column("issued_at", TIMESTAMPTZ, nullable=False),
    sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
    sa.Column("revoked_at", TIMESTAMPTZ),
    sa.ForeignKeyConstraint(["user_id"], ["app_users.id"], ondelete="CASCADE"),
    sa.UniqueConstraint("jti", name="uq_auth_sessions_jti"),
    sa.CheckConstraint("expires_at > issued_at", name="expiry_after_issue"),
    sa.CheckConstraint(
        "revoked_at IS NULL OR revoked_at >= issued_at", name="revocation_after_issue"
    ),
)
sa.Index("ix_auth_sessions_user_expiry", auth_sessions.c.user_id, auth_sessions.c.expires_at)
sa.Index(
    "ix_auth_sessions_active_expiry",
    auth_sessions.c.expires_at,
    postgresql_where=auth_sessions.c.revoked_at.is_(None),
)

documents = sa.Table(
    "documents",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("owner_user_id", UUID),
    sa.Column("owner_subject", sa.String(320)),
    sa.Column("capability_hash", sa.LargeBinary(SHA256_LENGTH)),
    sa.Column("object_key", sa.String(512), nullable=False),
    sa.Column("content_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("safe_filename", sa.String(255), nullable=False),
    sa.Column("mime_type", sa.String(128), nullable=False),
    sa.Column("size_bytes", sa.BigInteger, nullable=False),
    sa.Column("page_count", sa.Integer),
    sa.Column("lifecycle_state", sa.String(32), nullable=False, server_default="PENDING_UPLOAD"),
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    sa.Column("record_json", JSONB, nullable=False),
    sa.Column("expires_at", TIMESTAMPTZ, nullable=False),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(["owner_user_id"], ["app_users.id"], ondelete="RESTRICT"),
    sa.UniqueConstraint("object_key", name="uq_documents_object_key"),
    sa.UniqueConstraint("capability_hash", name="uq_documents_capability_hash"),
    sa.CheckConstraint(
        "(owner_subject IS NOT NULL) <> (capability_hash IS NOT NULL)",
        name="exactly_one_access_principal",
    ),
    sa.CheckConstraint(
        "(owner_user_id IS NOT NULL) = (owner_subject IS NOT NULL)",
        name="owner_user_requires_subject",
    ),
    sa.CheckConstraint(
        "owner_subject IS NULL OR owner_subject <> ''", name="owner_subject_nonempty"
    ),
    sa.CheckConstraint("octet_length(capability_hash) = 32", name="capability_sha256"),
    sa.CheckConstraint("octet_length(content_sha256) = 32", name="content_sha256"),
    sa.CheckConstraint("object_key <> ''", name="object_key_nonempty"),
    sa.CheckConstraint("safe_filename <> '' AND safe_filename !~ '[\\\\/]'", name="safe_filename"),
    sa.CheckConstraint(
        "mime_type IN ('application/pdf', 'image/png', 'image/jpeg')", name="mime_type_allowed"
    ),
    sa.CheckConstraint(f"size_bytes BETWEEN 1 AND {MAX_DOCUMENT_BYTES}", name="size_bounds"),
    sa.CheckConstraint(
        f"page_count IS NULL OR page_count BETWEEN 1 AND {MAX_DOCUMENT_PAGES}",
        name="page_bounds",
    ),
    sa.CheckConstraint(
        "lifecycle_state IN ('PENDING_UPLOAD', 'ACTIVE', 'DELETION_PENDING', 'DELETION_FAILED')",
        name="lifecycle_state_allowed",
    ),
    sa.CheckConstraint("version >= 1", name="version_positive"),
    sa.CheckConstraint("jsonb_typeof(record_json) = 'object'", name="record_json_object"),
    sa.CheckConstraint(
        "record_json ->> 'document_id' IS NOT DISTINCT FROM id::text",
        name="record_document_id_matches",
    ),
    sa.CheckConstraint(
        "record_json ->> 'storage_key' IS NOT DISTINCT FROM object_key",
        name="record_object_key_matches",
    ),
    sa.CheckConstraint(
        "record_json ->> 'owner_subject' IS NOT DISTINCT FROM owner_subject",
        name="record_owner_subject_matches",
    ),
    sa.CheckConstraint(
        "decode(record_json ->> 'access_token_hash', 'hex') IS NOT DISTINCT FROM capability_hash",
        name="record_capability_hash_matches",
    ),
    sa.CheckConstraint(
        "record_json ->> 'filename' IS NOT DISTINCT FROM safe_filename",
        name="record_filename_matches",
    ),
    sa.CheckConstraint(
        "record_json ->> 'mime_type' IS NOT DISTINCT FROM mime_type",
        name="record_mime_type_matches",
    ),
    sa.CheckConstraint(
        "(record_json ->> 'size_bytes')::bigint IS NOT DISTINCT FROM size_bytes",
        name="record_size_matches",
    ),
    sa.CheckConstraint(
        "(record_json ->> 'page_count')::integer IS NOT DISTINCT FROM page_count",
        name="record_page_count_matches",
    ),
    sa.CheckConstraint(
        "(record_json ->> 'created_at')::timestamptz IS NOT DISTINCT FROM created_at",
        name="record_created_at_matches",
    ),
    sa.CheckConstraint(
        "(record_json ->> 'expires_at')::timestamptz IS NOT DISTINCT FROM expires_at",
        name="record_expires_at_matches",
    ),
    sa.CheckConstraint("updated_at >= created_at", name="timestamps_ordered"),
    sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
)
sa.Index("ix_documents_owner_created", documents.c.owner_user_id, documents.c.created_at)
sa.Index("ix_documents_expiry", documents.c.expires_at)
sa.Index("ix_documents_state_updated", documents.c.lifecycle_state, documents.c.updated_at)

readings = sa.Table(
    "readings",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("method", sa.String(32), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("page_count", sa.Integer, nullable=False),
    sa.Column("warnings_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
    sa.UniqueConstraint("document_id", "id", name="uq_readings_document_id"),
    sa.UniqueConstraint("document_id", "id", "reading_sha256", name="uq_readings_scope_sha"),
    sa.UniqueConstraint("document_id", "reading_sha256", name="uq_readings_document_sha"),
    sa.CheckConstraint("octet_length(reading_sha256) = 32", name="reading_sha256"),
    sa.CheckConstraint("method IN ('native_text', 'ocr', 'hybrid')", name="method_allowed"),
    sa.CheckConstraint("status IN ('READ', 'READ_WITH_WARNINGS')", name="status_allowed"),
    sa.CheckConstraint(f"page_count BETWEEN 1 AND {MAX_DOCUMENT_PAGES}", name="page_bounds"),
    sa.CheckConstraint("jsonb_typeof(warnings_json) = 'array'", name="warnings_array"),
)
sa.Index("ix_readings_document_created", readings.c.document_id, readings.c.created_at)

chat_turns = sa.Table(
    "chat_turns",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("question", sa.String(500), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("answer", sa.String(4096), nullable=False),
    sa.Column("citations_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_sha256"],
        ["readings.document_id", "readings.reading_sha256"],
        ondelete="CASCADE",
    ),
    sa.CheckConstraint("octet_length(reading_sha256) = 32", name="reading_sha256"),
    sa.CheckConstraint("question <> ''", name="question_nonempty"),
    sa.CheckConstraint("answer <> ''", name="answer_nonempty"),
    sa.CheckConstraint(
        "status IN ('ANSWERED', 'UNAVAILABLE', 'OUT_OF_SCOPE')", name="status_allowed"
    ),
    sa.CheckConstraint("jsonb_typeof(citations_json) = 'array'", name="citations_array"),
)
sa.Index("ix_chat_turns_document_created", chat_turns.c.document_id, chat_turns.c.created_at)

reading_pages = sa.Table(
    "reading_pages",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("reading_id", UUID, nullable=False),
    sa.Column("page_number", sa.Integer, nullable=False),
    sa.Column("text", sa.Text, nullable=False, server_default=""),
    sa.Column("text_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("method", sa.String(32), nullable=False),
    sa.Column(
        "search_vector",
        postgresql.TSVECTOR(),
        sa.Computed("to_tsvector('simple', coalesce(text, ''))", persisted=True),
    ),
    sa.ForeignKeyConstraint(["reading_id"], ["readings.id"], ondelete="CASCADE"),
    sa.UniqueConstraint("reading_id", "id", name="uq_reading_pages_reading_id"),
    sa.UniqueConstraint("reading_id", "page_number", name="uq_reading_pages_source_order"),
    sa.CheckConstraint("page_number >= 1", name="page_number_positive"),
    sa.CheckConstraint("octet_length(text_sha256) = 32", name="text_sha256"),
    sa.CheckConstraint("method IN ('native_text', 'ocr')", name="method_allowed"),
)
sa.Index("ix_reading_pages_search", reading_pages.c.search_vector, postgresql_using="gin")

evidence_blocks = sa.Table(
    "evidence_blocks",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_id", UUID, nullable=False),
    sa.Column("page_id", UUID, nullable=False),
    sa.Column("source_block_id", sa.String(256), nullable=False),
    sa.Column("block_order", sa.Integer, nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("source_text", sa.Text, nullable=False),
    sa.Column("text_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("bounding_box_json", JSONB),
    sa.Column("confidence", sa.Float),
    sa.Column(
        "search_vector",
        postgresql.TSVECTOR(),
        sa.Computed("to_tsvector('simple', coalesce(source_text, ''))", persisted=True),
    ),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_id"],
        ["readings.document_id", "readings.id"],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["reading_id", "page_id"],
        ["reading_pages.reading_id", "reading_pages.id"],
        ondelete="CASCADE",
    ),
    sa.UniqueConstraint("document_id", "reading_id", "id", name="uq_evidence_blocks_scope_id"),
    sa.UniqueConstraint("document_id", "id", name="uq_evidence_blocks_document_id"),
    sa.UniqueConstraint("reading_id", "source_block_id", name="uq_evidence_blocks_source_id"),
    sa.UniqueConstraint("page_id", "block_order", name="uq_evidence_blocks_source_order"),
    sa.CheckConstraint("block_order >= 0", name="block_order_nonnegative"),
    sa.CheckConstraint("source_block_id <> ''", name="source_block_id_nonempty"),
    sa.CheckConstraint("kind IN ('text', 'field', 'table', 'image')", name="kind_allowed"),
    sa.CheckConstraint("source_text <> ''", name="source_text_nonempty"),
    sa.CheckConstraint("octet_length(text_sha256) = 32", name="text_sha256"),
    sa.CheckConstraint(
        "bounding_box_json IS NULL OR jsonb_typeof(bounding_box_json) = 'array'",
        name="bounding_box_array",
    ),
    sa.CheckConstraint(
        "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_bounds"
    ),
)
sa.Index(
    "ix_evidence_blocks_document_order",
    evidence_blocks.c.document_id,
    evidence_blocks.c.reading_id,
    evidence_blocks.c.page_id,
    evidence_blocks.c.block_order,
)
sa.Index("ix_evidence_blocks_search", evidence_blocks.c.search_vector, postgresql_using="gin")

extractions = sa.Table(
    "extractions",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_id", UUID, nullable=False),
    sa.Column("extraction_version", sa.Integer, nullable=False),
    sa.Column("schema_version", sa.String(64), nullable=False),
    sa.Column("status", sa.String(40), nullable=False),
    sa.Column("extraction_json", JSONB, nullable=False),
    sa.Column("warnings_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_id"],
        ["readings.document_id", "readings.id"],
        ondelete="CASCADE",
    ),
    sa.UniqueConstraint("document_id", "reading_id", "id", name="uq_extractions_scope_id"),
    sa.UniqueConstraint("document_id", "id", name="uq_extractions_document_id"),
    sa.UniqueConstraint(
        "document_id", "extraction_version", name="uq_extractions_document_version"
    ),
    sa.CheckConstraint("extraction_version >= 1", name="version_positive"),
    sa.CheckConstraint("status IN ('EXTRACTED', 'EXTRACTED_WITH_WARNINGS')", name="status_allowed"),
    sa.CheckConstraint("jsonb_typeof(extraction_json) = 'object'", name="payload_object"),
    sa.CheckConstraint("jsonb_typeof(warnings_json) = 'array'", name="warnings_array"),
)
sa.Index("ix_extractions_document_created", extractions.c.document_id, extractions.c.created_at)

extraction_evidence_links = sa.Table(
    "extraction_evidence_links",
    metadata,
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_id", UUID, nullable=False),
    sa.Column("extraction_id", UUID, nullable=False),
    sa.Column("json_pointer", sa.String(1024), nullable=False),
    sa.Column("evidence_block_id", UUID, nullable=False),
    sa.Column("link_order", sa.Integer, nullable=False, server_default="0"),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_id", "extraction_id"],
        ["extractions.document_id", "extractions.reading_id", "extractions.id"],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_id", "evidence_block_id"],
        ["evidence_blocks.document_id", "evidence_blocks.reading_id", "evidence_blocks.id"],
        ondelete="RESTRICT",
    ),
    sa.PrimaryKeyConstraint(
        "extraction_id", "json_pointer", "evidence_block_id", name="pk_extraction_evidence_links"
    ),
    sa.UniqueConstraint(
        "extraction_id", "json_pointer", "link_order", name="uq_extraction_evidence_link_order"
    ),
    sa.CheckConstraint("json_pointer LIKE '/%'", name="json_pointer_absolute"),
    sa.CheckConstraint("link_order >= 0", name="link_order_nonnegative"),
)
sa.Index(
    "ix_extraction_evidence_links_document",
    extraction_evidence_links.c.document_id,
    extraction_evidence_links.c.extraction_id,
)

reviews = sa.Table(
    "reviews",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("extraction_id", UUID, nullable=False),
    sa.Column("review_version", sa.Integer, nullable=False),
    sa.Column("review_json", JSONB, nullable=False),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(
        ["document_id", "extraction_id"],
        ["extractions.document_id", "extractions.id"],
        ondelete="CASCADE",
    ),
    sa.UniqueConstraint("document_id", "review_version", name="uq_reviews_document_version"),
    sa.CheckConstraint("review_version >= 1", name="version_positive"),
    sa.CheckConstraint("jsonb_typeof(review_json) = 'object'", name="payload_object"),
)
sa.Index("ix_reviews_document_created", reviews.c.document_id, reviews.c.created_at)

embedding_sets = sa.Table(
    "embedding_sets",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("reading_id", UUID, nullable=False),
    sa.Column("reading_sha256", sa.LargeBinary(SHA256_LENGTH), nullable=False),
    sa.Column("model_name", sa.String(200), nullable=False),
    sa.Column("dimensions", sa.Integer, nullable=False),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(
        ["document_id", "reading_id", "reading_sha256"],
        ["readings.document_id", "readings.id", "readings.reading_sha256"],
        ondelete="CASCADE",
    ),
    sa.UniqueConstraint("document_id", "id", name="uq_embedding_sets_document_id"),
    sa.UniqueConstraint(
        "document_id",
        "reading_sha256",
        "model_name",
        "dimensions",
        name="uq_embedding_sets_reading_model_dimensions",
    ),
    sa.CheckConstraint("octet_length(reading_sha256) = 32", name="reading_sha256"),
    sa.CheckConstraint("model_name <> ''", name="model_name_nonempty"),
    sa.CheckConstraint(f"dimensions = {EMBEDDING_DIMENSIONS}", name="dimensions_supported"),
)
sa.Index(
    "ix_embedding_sets_document_reading", embedding_sets.c.document_id, embedding_sets.c.reading_id
)

block_embeddings = sa.Table(
    "block_embeddings",
    metadata,
    sa.Column("embedding_set_id", UUID, nullable=False),
    sa.Column("document_id", UUID, nullable=False),
    sa.Column("evidence_block_id", UUID, nullable=False),
    sa.Column("block_order", sa.Integer, nullable=False),
    sa.Column("embedding", Vector(EMBEDDING_DIMENSIONS), nullable=False),
    sa.Column("created_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
    sa.ForeignKeyConstraint(
        ["document_id", "embedding_set_id"],
        ["embedding_sets.document_id", "embedding_sets.id"],
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["document_id", "evidence_block_id"],
        ["evidence_blocks.document_id", "evidence_blocks.id"],
        ondelete="CASCADE",
    ),
    sa.PrimaryKeyConstraint("embedding_set_id", "evidence_block_id", name="pk_block_embeddings"),
    sa.UniqueConstraint("embedding_set_id", "block_order", name="uq_block_embeddings_source_order"),
    sa.CheckConstraint("block_order >= 0", name="block_order_nonnegative"),
)
sa.Index(
    "ix_block_embeddings_document_set",
    block_embeddings.c.document_id,
    block_embeddings.c.embedding_set_id,
)

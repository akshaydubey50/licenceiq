"""Add the exact durable document-record contract.

Revision ID: 20260920_0002
Revises: 20260920_0001
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0002"
down_revision: str | None = "20260920_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    """Store the complete domain snapshot and preserve per-page read methods."""
    op.add_column("documents", sa.Column("owner_subject", sa.String(320)))
    op.add_column("documents", sa.Column("record_json", JSONB))
    op.add_column("reading_pages", sa.Column("method", sa.String(32)))

    # The foundation was not yet activated by the application, but these backfills keep the
    # follow-up migration safe for any manually created foundation rows.
    op.execute(
        """
        UPDATE documents AS document
        SET owner_subject = app_user.subject
        FROM app_users AS app_user
        WHERE document.owner_user_id = app_user.id
          AND document.owner_subject IS NULL
        """
    )
    op.execute(
        """
        UPDATE documents
        SET page_count = 1
        WHERE page_count IS NULL
        """
    )
    op.execute(
        """
        UPDATE documents
        SET record_json = jsonb_build_object(
            'document_id', id::text,
            'filename', safe_filename,
            'mime_type', mime_type,
            'size_bytes', size_bytes,
            'created_at', created_at,
            'expires_at', expires_at,
            'page_count', page_count,
            'storage_key', object_key,
            'access_token_hash', CASE
                WHEN capability_hash IS NULL THEN NULL
                ELSE encode(capability_hash, 'hex')
            END,
            'owner_subject', owner_subject,
            'reading', NULL,
            'semantic_index', NULL,
            'extraction', NULL,
            'review', NULL
        )
        WHERE record_json IS NULL
        """
    )
    op.execute(
        """
        UPDATE reading_pages AS page
        SET method = CASE
            WHEN reading.method = 'ocr' THEN 'ocr'
            ELSE 'native_text'
        END
        FROM readings AS reading
        WHERE page.reading_id = reading.id
          AND page.method IS NULL
        """
    )

    op.alter_column("documents", "record_json", existing_type=JSONB, nullable=False)
    op.alter_column("reading_pages", "method", existing_type=sa.String(32), nullable=False)

    op.drop_constraint(
        "ck_documents_exactly_one_access_principal", "documents", type_="check"
    )
    op.create_check_constraint(
        "ck_documents_exactly_one_access_principal",
        "documents",
        "(owner_subject IS NOT NULL) <> (capability_hash IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_documents_owner_user_requires_subject",
        "documents",
        "(owner_user_id IS NOT NULL) = (owner_subject IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_documents_owner_subject_nonempty",
        "documents",
        "owner_subject IS NULL OR owner_subject <> ''",
    )
    op.create_check_constraint(
        "ck_documents_record_json_object",
        "documents",
        "jsonb_typeof(record_json) = 'object'",
    )
    op.create_check_constraint(
        "ck_documents_record_document_id_matches",
        "documents",
        "record_json ->> 'document_id' IS NOT DISTINCT FROM id::text",
    )
    op.create_check_constraint(
        "ck_documents_record_object_key_matches",
        "documents",
        "record_json ->> 'storage_key' IS NOT DISTINCT FROM object_key",
    )
    op.create_check_constraint(
        "ck_documents_record_owner_subject_matches",
        "documents",
        "record_json ->> 'owner_subject' IS NOT DISTINCT FROM owner_subject",
    )
    op.create_check_constraint(
        "ck_documents_record_capability_hash_matches",
        "documents",
        "decode(record_json ->> 'access_token_hash', 'hex') "
        "IS NOT DISTINCT FROM capability_hash",
    )
    op.create_check_constraint(
        "ck_documents_record_filename_matches",
        "documents",
        "record_json ->> 'filename' IS NOT DISTINCT FROM safe_filename",
    )
    op.create_check_constraint(
        "ck_documents_record_mime_type_matches",
        "documents",
        "record_json ->> 'mime_type' IS NOT DISTINCT FROM mime_type",
    )
    op.create_check_constraint(
        "ck_documents_record_size_matches",
        "documents",
        "(record_json ->> 'size_bytes')::bigint IS NOT DISTINCT FROM size_bytes",
    )
    op.create_check_constraint(
        "ck_documents_record_page_count_matches",
        "documents",
        "(record_json ->> 'page_count')::integer IS NOT DISTINCT FROM page_count",
    )
    op.create_check_constraint(
        "ck_documents_record_created_at_matches",
        "documents",
        "(record_json ->> 'created_at')::timestamptz IS NOT DISTINCT FROM created_at",
    )
    op.create_check_constraint(
        "ck_documents_record_expires_at_matches",
        "documents",
        "(record_json ->> 'expires_at')::timestamptz IS NOT DISTINCT FROM expires_at",
    )
    op.create_check_constraint(
        "ck_reading_pages_method_allowed",
        "reading_pages",
        "method IN ('native_text', 'ocr')",
    )


def downgrade() -> None:
    """Return to the normalized-only foundation contract."""
    op.drop_constraint("ck_reading_pages_method_allowed", "reading_pages", type_="check")
    op.drop_constraint("ck_documents_record_expires_at_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_created_at_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_page_count_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_size_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_mime_type_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_filename_matches", "documents", type_="check")
    op.drop_constraint(
        "ck_documents_record_capability_hash_matches", "documents", type_="check"
    )
    op.drop_constraint("ck_documents_record_owner_subject_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_object_key_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_document_id_matches", "documents", type_="check")
    op.drop_constraint("ck_documents_record_json_object", "documents", type_="check")
    op.drop_constraint("ck_documents_owner_subject_nonempty", "documents", type_="check")
    op.drop_constraint("ck_documents_owner_user_requires_subject", "documents", type_="check")
    op.drop_constraint(
        "ck_documents_exactly_one_access_principal", "documents", type_="check"
    )
    op.create_check_constraint(
        "ck_documents_exactly_one_access_principal",
        "documents",
        "(owner_user_id IS NOT NULL) <> (capability_hash IS NOT NULL)",
    )
    op.drop_column("reading_pages", "method")
    op.drop_column("documents", "record_json")
    op.drop_column("documents", "owner_subject")

"""Add reading-scoped durable chat history for authenticated document owners.

Revision ID: 20260920_0004
Revises: 20260920_0003
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0004"
down_revision: str | None = "20260920_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Persist only validated public answer fields and their immutable reading digest."""
    op.create_table(
        "chat_turns",
        sa.Column("id", UUID, nullable=False),
        sa.Column("document_id", UUID, nullable=False),
        sa.Column("reading_sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer", sa.String(4096), nullable=False),
        sa.Column("citations_json", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, nullable=False),
        sa.CheckConstraint(
            "octet_length(reading_sha256) = 32", name="ck_chat_turns_reading_sha256"
        ),
        sa.CheckConstraint("question <> ''", name="ck_chat_turns_question_nonempty"),
        sa.CheckConstraint("answer <> ''", name="ck_chat_turns_answer_nonempty"),
        sa.CheckConstraint(
            "status IN ('ANSWERED', 'UNAVAILABLE', 'OUT_OF_SCOPE')",
            name="ck_chat_turns_status_allowed",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(citations_json) = 'array'", name="ck_chat_turns_citations_array"
        ),
        sa.ForeignKeyConstraint(
            ["document_id", "reading_sha256"],
            ["readings.document_id", "readings.reading_sha256"],
            name="fk_chat_turns_reading",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chat_turns"),
    )
    op.create_index(
        "ix_chat_turns_document_created",
        "chat_turns",
        ["document_id", "created_at"],
    )


def downgrade() -> None:
    """Remove saved chat without altering documents or source readings."""
    op.drop_index("ix_chat_turns_document_created", table_name="chat_turns")
    op.drop_table("chat_turns")

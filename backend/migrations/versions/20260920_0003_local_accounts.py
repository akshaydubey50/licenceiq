"""Add durable Argon2 credentials for opt-in local accounts.

Revision ID: 20260920_0003
Revises: 20260920_0002
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260920_0003"
down_revision: str | None = "20260920_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create one normalized local credential per opaque application principal."""
    op.create_table(
        "local_credentials",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("normalized_username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "normalized_username ~ '^[a-z0-9][a-z0-9._-]{2,63}$'",
            name="ck_local_credentials_username_format",
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2%'",
            name="ck_local_credentials_password_hash_argon2",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_local_credentials_timestamps_ordered",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_local_credentials_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_local_credentials"),
        sa.UniqueConstraint(
            "normalized_username",
            name="uq_local_credentials_username",
        ),
    )


def downgrade() -> None:
    """Remove local credentials while retaining opaque users and sessions."""
    op.drop_table("local_credentials")

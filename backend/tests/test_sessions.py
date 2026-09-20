"""Offline database-harness checks for durable principal and JWT session records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

import app.persistence.sessions as sessions_module
from app.persistence.sessions import AccountAlreadyExistsError, PostgresSessionStore

NOW = datetime(2026, 9, 20, 12, tzinfo=UTC)


def _store(monkeypatch):
    """Use a relational harness without requiring a live PostgreSQL service."""
    metadata = sa.MetaData()
    users = sa.Table(
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
    sessions = sa.Table(
        "auth_sessions",
        metadata,
        sa.Column("sid", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("jti", sa.String(128), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    credentials = sa.Table(
        "local_credentials",
        metadata,
        sa.Column("user_id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("normalized_username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    engine = sa.create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    monkeypatch.setattr(sessions_module, "app_users", users)
    monkeypatch.setattr(sessions_module, "auth_sessions", sessions)
    monkeypatch.setattr(sessions_module, "local_credentials", credentials)
    return PostgresSessionStore(engine), engine, users, credentials


def test_session_store_revokes_only_the_exact_active_token(monkeypatch) -> None:
    store, engine, users, _ = _store(monkeypatch)
    issuer = "https://licenceiq.test"
    subject = "candidate-001"
    expires_at = NOW + timedelta(minutes=15)

    first = store.create_session(
        issuer=issuer,
        subject=subject,
        jti="first-token",
        issued_at=NOW,
        expires_at=expires_at,
    )
    second = store.create_session(
        issuer=issuer,
        subject=subject,
        jti="second-token",
        issued_at=NOW,
        expires_at=expires_at,
    )

    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(users)).scalar_one() == 1
    assert store.session_is_active(
        issuer=issuer, subject=subject, sid=first, jti="first-token", now=NOW
    )
    assert store.revoke_session(
        issuer=issuer, subject=subject, sid=first, jti="first-token", now=NOW
    )
    assert not store.session_is_active(
        issuer=issuer, subject=subject, sid=first, jti="first-token", now=NOW
    )
    assert store.session_is_active(
        issuer=issuer, subject=subject, sid=second, jti="second-token", now=NOW
    )


def test_session_store_rejects_expired_mismatched_and_disabled_principals(monkeypatch) -> None:
    store, engine, users, _ = _store(monkeypatch)
    issuer = "https://licenceiq.test"
    subject = "candidate-001"
    sid = store.create_session(
        issuer=issuer,
        subject=subject,
        jti="active-token",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=1),
    )

    assert not store.session_is_active(
        issuer=issuer, subject="another-user", sid=sid, jti="active-token", now=NOW
    )
    assert not store.session_is_active(
        issuer=issuer, subject=subject, sid=sid, jti="wrong-token", now=NOW
    )
    assert not store.session_is_active(
        issuer=issuer,
        subject=subject,
        sid=sid,
        jti="active-token",
        now=NOW + timedelta(minutes=2),
    )
    with engine.begin() as connection:
        connection.execute(
            sa.update(users)
            .where(users.c.issuer == issuer, users.c.subject == subject)
            .values(status="DISABLED")
        )
    assert not store.session_is_active(
        issuer=issuer, subject=subject, sid=sid, jti="active-token", now=NOW
    )
    assert not store.revoke_session(
        issuer=issuer, subject=subject, sid=uuid4(), jti="active-token", now=NOW
    )


def test_local_account_creation_is_atomic_unique_and_never_stores_plaintext(monkeypatch) -> None:
    store, engine, users, credentials = _store(monkeypatch)
    password = "never store this plaintext"
    password_hash = "$argon2id$v=19$m=65536,t=3,p=4$offline$safehash"

    subject = store.create_account(
        issuer="https://licenceiq.test",
        normalized_username="new.user",
        password_hash=password_hash,
        created_at=NOW,
    )

    account = store.find_account(
        issuer="https://licenceiq.test",
        normalized_username="new.user",
    )
    assert account is not None
    assert account.subject == subject
    assert account.subject != "new.user"
    assert account.password_hash == password_hash
    with engine.connect() as connection:
        row = connection.execute(sa.select(credentials)).one()
        assert row.password_hash == password_hash
        assert password not in row.password_hash
        assert connection.execute(sa.select(sa.func.count()).select_from(users)).scalar_one() == 1

    with pytest.raises(AccountAlreadyExistsError):
        store.create_account(
            issuer="https://licenceiq.test",
            normalized_username="new.user",
            password_hash=password_hash,
            created_at=NOW,
        )
    with engine.connect() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(users)).scalar_one() == 1

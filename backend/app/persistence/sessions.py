"""PostgreSQL-backed principals and revocable JWT sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.persistence.models import app_users, auth_sessions, local_credentials


class AccountAlreadyExistsError(Exception):
    """Internal uniqueness result that carries no submitted credential data."""


@dataclass(frozen=True, slots=True)
class LocalAccount:
    """Minimum durable credential record required for local authentication."""

    subject: str
    password_hash: str


class AccountStore(Protocol):
    """Durable local-account boundary used by the authentication service."""

    def create_account(
        self,
        *,
        issuer: str,
        normalized_username: str,
        password_hash: str,
        created_at: datetime,
    ) -> str: ...

    def find_account(self, *, issuer: str, normalized_username: str) -> LocalAccount | None: ...


class SessionStore(Protocol):
    """Persistence boundary used by the JWT service without exposing database details."""

    def create_session(
        self,
        *,
        issuer: str,
        subject: str,
        jti: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> UUID: ...

    def session_is_active(
        self,
        *,
        issuer: str,
        subject: str,
        sid: UUID,
        jti: str,
        now: datetime,
    ) -> bool: ...

    def revoke_session(
        self,
        *,
        issuer: str,
        subject: str,
        sid: UUID,
        jti: str,
        now: datetime,
    ) -> bool: ...


class PostgresSessionStore:
    """Persist opaque local principals, credentials, and revocable sessions."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_account(
        self,
        *,
        issuer: str,
        normalized_username: str,
        password_hash: str,
        created_at: datetime,
    ) -> str:
        """Atomically create one opaque principal and its Argon2 credential."""
        user_id = uuid4()
        subject = f"local:{uuid4().hex}"
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    sa.insert(app_users).values(
                        id=user_id,
                        issuer=issuer,
                        subject=subject,
                        status="ACTIVE",
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                connection.execute(
                    sa.insert(local_credentials).values(
                        user_id=user_id,
                        normalized_username=normalized_username,
                        password_hash=password_hash,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
        except IntegrityError as exc:
            raise AccountAlreadyExistsError from exc
        return subject

    def find_account(self, *, issuer: str, normalized_username: str) -> LocalAccount | None:
        """Load an active local account without exposing its database identifier."""
        statement = (
            sa.select(app_users.c.subject, local_credentials.c.password_hash)
            .select_from(
                local_credentials.join(app_users, local_credentials.c.user_id == app_users.c.id)
            )
            .where(
                app_users.c.issuer == issuer,
                app_users.c.status == "ACTIVE",
                local_credentials.c.normalized_username == normalized_username,
            )
        )
        with self._engine.connect() as connection:
            row = connection.execute(statement).one_or_none()
        if row is None:
            return None
        return LocalAccount(subject=row.subject, password_hash=row.password_hash)

    def create_session(
        self,
        *,
        issuer: str,
        subject: str,
        jti: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> UUID:
        """Upsert the principal and create one independently revocable session."""
        with self._engine.begin() as connection:
            user_id = self._active_user_id(connection, issuer=issuer, subject=subject)
            if user_id is None:
                user_id = uuid4()
                try:
                    # Keep the outer session transaction usable after a uniqueness race.
                    with connection.begin_nested():
                        connection.execute(
                            sa.insert(app_users).values(
                                id=user_id,
                                issuer=issuer,
                                subject=subject,
                                status="ACTIVE",
                                created_at=issued_at,
                                updated_at=issued_at,
                            )
                        )
                except IntegrityError:
                    # A concurrent sign-in may have created this principal first.
                    user_id = self._active_user_id(connection, issuer=issuer, subject=subject)
                    if user_id is None:
                        raise
            sid = uuid4()
            connection.execute(
                sa.insert(auth_sessions).values(
                    sid=sid,
                    user_id=user_id,
                    jti=jti,
                    issued_at=issued_at,
                    expires_at=expires_at,
                )
            )
            return sid

    def session_is_active(
        self,
        *,
        issuer: str,
        subject: str,
        sid: UUID,
        jti: str,
        now: datetime,
    ) -> bool:
        """Require a matching active principal and non-revoked, non-expired session."""
        statement = (
            sa.select(auth_sessions.c.sid)
            .select_from(auth_sessions.join(app_users, auth_sessions.c.user_id == app_users.c.id))
            .where(
                auth_sessions.c.sid == sid,
                auth_sessions.c.jti == jti,
                auth_sessions.c.expires_at > now,
                auth_sessions.c.revoked_at.is_(None),
                app_users.c.issuer == issuer,
                app_users.c.subject == subject,
                app_users.c.status == "ACTIVE",
            )
        )
        with self._engine.connect() as connection:
            return connection.execute(statement).scalar_one_or_none() is not None

    def revoke_session(
        self,
        *,
        issuer: str,
        subject: str,
        sid: UUID,
        jti: str,
        now: datetime,
    ) -> bool:
        """Revoke only the caller's exact active session."""
        statement = (
            sa.update(auth_sessions)
            .where(
                auth_sessions.c.sid == sid,
                auth_sessions.c.jti == jti,
                auth_sessions.c.revoked_at.is_(None),
                auth_sessions.c.expires_at > now,
                auth_sessions.c.user_id.in_(
                    sa.select(app_users.c.id).where(
                        app_users.c.issuer == issuer,
                        app_users.c.subject == subject,
                        app_users.c.status == "ACTIVE",
                    )
                ),
            )
            .values(revoked_at=now)
        )
        with self._engine.begin() as connection:
            return connection.execute(statement).rowcount == 1

    @staticmethod
    def _active_user_id(
        connection: sa.Connection,
        *,
        issuer: str,
        subject: str,
    ) -> UUID | None:
        statement = sa.select(app_users.c.id).where(
            app_users.c.issuer == issuer,
            app_users.c.subject == subject,
            app_users.c.status == "ACTIVE",
        )
        return connection.execute(statement).scalar_one_or_none()

"""Focused offline checks for opt-in durable local account registration."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pwdlib import PasswordHash
from pydantic import SecretStr

from app.api.auth import router
from app.core.auth import AuthConfig, AuthService
from app.persistence.sessions import AccountAlreadyExistsError, LocalAccount

NOW = datetime.now(UTC).replace(microsecond=0)
SIGNING_KEY = "offline-registration-signing-key-that-is-at-least-sixty-four-bytes-long"
BOOTSTRAP_PASSWORD = "bootstrap password phrase"
LOCAL_PASSWORD = "local password phrase"
MINIMUM_PASSWORD = "seven77"


class MemoryIdentityStore:
    """Durable identity/session stand-in that retains hashes for security assertions."""

    def __init__(self) -> None:
        self.accounts: dict[str, LocalAccount] = {}
        self.sessions: dict[UUID, tuple[str, str, str, datetime, bool]] = {}

    def create_account(
        self,
        *,
        issuer: str,
        normalized_username: str,
        password_hash: str,
        created_at: datetime,
    ) -> str:
        del issuer, created_at
        if normalized_username in self.accounts:
            raise AccountAlreadyExistsError
        subject = f"local:{uuid4().hex}"
        self.accounts[normalized_username] = LocalAccount(
            subject=subject,
            password_hash=password_hash,
        )
        return subject

    def find_account(self, *, issuer: str, normalized_username: str) -> LocalAccount | None:
        del issuer
        return self.accounts.get(normalized_username)

    def create_session(
        self,
        *,
        issuer: str,
        subject: str,
        jti: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> UUID:
        del issued_at
        sid = uuid4()
        self.sessions[sid] = (issuer, subject, jti, expires_at, False)
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
        saved = self.sessions.get(sid)
        return bool(
            saved and saved[:3] == (issuer, subject, jti) and saved[3] > now and not saved[4]
        )

    def revoke_session(
        self,
        *,
        issuer: str,
        subject: str,
        sid: UUID,
        jti: str,
        now: datetime,
    ) -> bool:
        saved = self.sessions.get(sid)
        if not saved or not self.session_is_active(
            issuer=issuer,
            subject=subject,
            sid=sid,
            jti=jti,
            now=now,
        ):
            return False
        self.sessions[sid] = (*saved[:4], True)
        return True


def _service(
    *, enabled: bool = True, with_bootstrap: bool = True
) -> tuple[AuthService, MemoryIdentityStore]:
    password_hash = PasswordHash.recommended()
    store = MemoryIdentityStore()
    if with_bootstrap:
        config = AuthConfig(
            signing_key=SecretStr(SIGNING_KEY),
            issuer="https://licenceiq.test",
            audience="licenceiq-browser",
            bootstrap_username="candidate",
            bootstrap_password_hash=SecretStr(password_hash.hash(BOOTSTRAP_PASSWORD)),
            bootstrap_subject="bootstrap-subject",
            self_registration_enabled=enabled,
        )
    else:
        config = AuthConfig(
            signing_key=SecretStr(SIGNING_KEY),
            issuer="https://licenceiq.test",
            audience="licenceiq-browser",
            self_registration_enabled=enabled,
        )
    service = AuthService(
        config,
        now_provider=lambda: NOW,
        session_store=store if enabled else None,
        account_store=store if enabled else None,
    )
    return service, store


def _client(service: AuthService) -> TestClient:
    app = FastAPI()
    app.state.auth_service = service
    app.include_router(router)
    return TestClient(app)


def test_signup_creates_opaque_account_session_and_supports_normalized_login() -> None:
    service, store = _service()
    client = _client(service)

    signup = client.post(
        "/api/auth/signup",
        json={"username": " New.User ", "password": LOCAL_PASSWORD},
    )

    assert signup.status_code == 201
    assert signup.headers["cache-control"] == "no-store"
    assert signup.headers["pragma"] == "no-cache"
    token = signup.json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert claims["sub"].startswith("local:")
    assert claims["sub"] != "new.user"
    assert UUID(claims["sid"]) in store.sessions
    assert service.authenticate_token(token).subject == claims["sub"]

    login = client.post(
        "/api/auth/login",
        json={"username": "NEW.USER", "password": LOCAL_PASSWORD},
    )
    assert login.status_code == 200
    login_claims = jwt.decode(login.json()["access_token"], options={"verify_signature": False})
    assert login_claims["sub"] == claims["sub"]


def test_signup_rejects_duplicate_bootstrap_collision_and_invalid_inputs_generically() -> None:
    service, _ = _service()
    client = _client(service)
    expected = {"detail": "Registration failed."}
    maximum_password = "x" * 256
    overlong_password = "x" * 257

    first = client.post(
        "/api/auth/signup",
        json={"username": "new-user", "password": MINIMUM_PASSWORD},
    )
    duplicate = client.post(
        "/api/auth/signup",
        json={"username": "NEW-USER", "password": "another password phrase"},
    )
    bootstrap_collision = client.post(
        "/api/auth/signup",
        json={"username": "Candidate", "password": LOCAL_PASSWORD},
    )
    weak_password = client.post(
        "/api/auth/signup",
        json={"username": "valid-account", "password": "six666"},
    )
    maximum = client.post(
        "/api/auth/signup",
        json={"username": "max-account", "password": maximum_password},
    )
    overlong = client.post(
        "/api/auth/signup",
        json={"username": "overlong-account", "password": overlong_password},
    )
    invalid = client.post(
        "/api/auth/signup",
        json={"username": "x", "password": "short"},
    )

    assert first.status_code == 201
    assert maximum.status_code == 201
    assert (
        duplicate.status_code
        == bootstrap_collision.status_code
        == weak_password.status_code
        == overlong.status_code
        == invalid.status_code
        == 400
    )
    assert (
        duplicate.json()
        == bootstrap_collision.json()
        == weak_password.json()
        == overlong.json()
        == invalid.json()
        == expected
    )
    responses = (
        duplicate.text
        + bootstrap_collision.text
        + weak_password.text
        + overlong.text
        + invalid.text
    )
    assert LOCAL_PASSWORD not in responses
    assert "six666" not in responses
    assert overlong_password not in responses


def test_signup_disabled_is_rejected_without_a_durable_store() -> None:
    service, _ = _service(enabled=False)

    response = _client(service).post(
        "/api/auth/signup",
        json={"username": "new-user", "password": LOCAL_PASSWORD},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Registration is unavailable."}


def test_registration_can_run_without_a_bootstrap_account() -> None:
    service, _ = _service(with_bootstrap=False)
    client = _client(service)

    signup = client.post(
        "/api/auth/signup",
        json={"username": "account-only", "password": LOCAL_PASSWORD},
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "account-only", "password": LOCAL_PASSWORD},
    )

    assert signup.status_code == 201
    assert login.status_code == 200


def test_only_argon2_hash_is_retained_for_local_password() -> None:
    service, store = _service()

    response = _client(service).post(
        "/api/auth/signup",
        json={"username": "hash-check", "password": LOCAL_PASSWORD},
    )

    assert response.status_code == 201
    stored_hash = store.accounts["hash-check"].password_hash
    assert stored_hash.startswith("$argon2")
    assert LOCAL_PASSWORD not in stored_hash
    assert LOCAL_PASSWORD not in response.text

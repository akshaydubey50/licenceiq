"""Offline security-boundary checks for bootstrap login and JWT validation."""

from datetime import UTC, datetime, timedelta

import pytest

jwt = pytest.importorskip("jwt", reason="Phase 9 requires PyJWT dependency integration")
pwdlib = pytest.importorskip("pwdlib", reason="Phase 9 requires pwdlib[argon2] integration")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app.api.auth import router  # noqa: E402
from app.core.auth import AuthConfig, AuthenticationError, AuthService  # noqa: E402
from app.schemas.auth import LoginRequest  # noqa: E402

NOW = datetime.now(UTC).replace(microsecond=0)
SIGNING_KEY = "offline-test-signing-key-that-is-at-least-sixty-four-bytes-for-hs512-coverage"
PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="module")
def password_hash() -> str:
    return str(pwdlib.PasswordHash.recommended().hash(PASSWORD))


@pytest.fixture
def config(password_hash: str) -> AuthConfig:
    return AuthConfig(
        signing_key=SecretStr(SIGNING_KEY),
        issuer="https://licenceiq.test",
        audience="licenceiq-api",
        bootstrap_username="candidate",
        bootstrap_password_hash=SecretStr(password_hash),
        bootstrap_subject="user-001",
        access_token_ttl_seconds=900,
    )


@pytest.fixture
def service(config: AuthConfig) -> AuthService:
    return AuthService(config, now_provider=lambda: NOW)


def test_valid_credentials_issue_a_strictly_scoped_token(service: AuthService) -> None:
    response = service.login(LoginRequest(username="candidate", password=PASSWORD))

    assert response.token_type == "bearer"
    assert response.expires_in == 900
    assert service.authenticate_token(response.access_token).subject == "user-001"


@pytest.mark.parametrize(
    ("username", "password"),
    [("unknown", PASSWORD), ("candidate", "wrong password")],
)
def test_wrong_credentials_have_one_generic_failure(
    service: AuthService, username: str, password: str
) -> None:
    with pytest.raises(AuthenticationError, match="^Authentication failed\\.$"):
        service.login(LoginRequest(username=username, password=password))


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Basic abc", "Bearer", "Bearer ", "Bearer one two", "Bearer\ttoken"],
)
def test_missing_or_malformed_authorization_is_rejected(
    service: AuthService, authorization: str | None
) -> None:
    with pytest.raises(AuthenticationError, match="^Authentication failed\\.$"):
        service.authenticate_authorization(authorization)


def _token(config: AuthConfig, **overrides: object) -> str:
    claims: dict[str, object] = {
        "iss": config.issuer,
        "aud": config.audience,
        "sub": "user-001",
        "iat": datetime.now(UTC) - timedelta(seconds=2),
        "nbf": datetime.now(UTC) - timedelta(seconds=2),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "jti": "offline-test-id",
    }
    claims.update(overrides)
    return str(
        jwt.encode(
            claims,
            config.signing_key.get_secret_value(),
            algorithm=config.signing_algorithm,
        )
    )


def test_expired_token_is_rejected(service: AuthService, config: AuthConfig) -> None:
    token = _token(config, exp=datetime.now(UTC) - timedelta(seconds=1))

    with pytest.raises(AuthenticationError):
        service.authenticate_token(token)


def test_wrong_signature_is_rejected(service: AuthService, config: AuthConfig) -> None:
    claims = jwt.decode(_token(config), options={"verify_signature": False})
    token = jwt.encode(
        claims,
        "different-offline-signing-key-that-is-at-least-32-bytes",
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        service.authenticate_token(str(token))


@pytest.mark.parametrize(
    ("claim", "value"),
    [("iss", "https://other.test"), ("aud", "other-api")],
)
def test_issuer_and_audience_are_fixed(
    service: AuthService, config: AuthConfig, claim: str, value: str
) -> None:
    with pytest.raises(AuthenticationError):
        service.authenticate_token(_token(config, **{claim: value}))


def test_non_allowlisted_token_algorithm_is_rejected(
    service: AuthService, config: AuthConfig
) -> None:
    claims = jwt.decode(_token(config), options={"verify_signature": False})
    token = jwt.encode(claims, SIGNING_KEY, algorithm="HS512")

    with pytest.raises(AuthenticationError):
        service.authenticate_token(str(token))


@pytest.mark.parametrize("subject", ["", "   ", 123])
def test_invalid_subject_is_rejected(
    service: AuthService, config: AuthConfig, subject: object
) -> None:
    with pytest.raises(AuthenticationError):
        service.authenticate_token(_token(config, sub=subject))


def test_login_http_response_is_private_and_generic(service: AuthService) -> None:
    app = FastAPI()
    app.state.auth_service = service
    app.include_router(router)
    client = TestClient(app)

    success = client.post(
        "/api/auth/login",
        json={"username": "candidate", "password": PASSWORD},
    )
    failure = client.post(
        "/api/auth/login",
        json={"username": "candidate", "password": "wrong password"},
    )

    assert success.status_code == 200
    assert set(success.json()) == {"access_token", "token_type", "expires_in"}
    assert success.headers["cache-control"] == "no-store"
    assert success.headers["pragma"] == "no-cache"
    assert PASSWORD not in success.text
    assert failure.status_code == 401
    assert failure.json() == {"detail": "Authentication failed."}
    assert failure.headers["www-authenticate"] == "Bearer"
    assert PASSWORD not in failure.text

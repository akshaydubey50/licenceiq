"""Bootstrap credential verification and strict JWT access-token handling."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import SecretStr

from app.schemas.auth import AccessTokenResponse, AuthenticatedUser, LoginRequest

AUTHENTICATION_FAILED: Final = "Authentication failed."
_SUPPORTED_SIGNING_ALGORITHMS: Final = frozenset({"HS256", "HS384", "HS512"})
_REQUIRED_CLAIMS: Final = ("iss", "aud", "sub", "iat", "nbf", "exp", "jti")


class AuthenticationError(Exception):
    """Internal generic failure that never contains credentials or token details."""

    def __init__(self) -> None:
        super().__init__(AUTHENTICATION_FAILED)


class PasswordVerifier(Protocol):
    """Narrow password-hash boundary so tests and composition remain explicit."""

    def verify(self, password: str, password_hash: str) -> bool:
        """Return whether a plaintext candidate matches a stored modern hash."""


class PwdlibPasswordVerifier:
    """Verify bootstrap credentials using pwdlib's recommended password hasher."""

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()

    def verify(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Validated, explicitly injected authentication settings."""

    signing_key: SecretStr
    issuer: str
    audience: str
    bootstrap_username: str
    bootstrap_password_hash: SecretStr
    bootstrap_subject: str
    access_token_ttl_seconds: int = 15 * 60
    signing_algorithm: str = "HS256"

    def __post_init__(self) -> None:
        text_fields = {
            "issuer": self.issuer,
            "audience": self.audience,
            "bootstrap_username": self.bootstrap_username,
            "bootstrap_subject": self.bootstrap_subject,
        }
        if any(not value.strip() for value in text_fields.values()):
            raise ValueError("Authentication identifiers must not be empty.")
        if len(self.bootstrap_subject) > 200:
            raise ValueError("The authentication subject is too long.")
        if not self.bootstrap_password_hash.get_secret_value():
            raise ValueError("A bootstrap password hash is required.")
        if len(self.signing_key.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("The JWT signing key must contain at least 32 bytes.")
        if self.access_token_ttl_seconds <= 0:
            raise ValueError("The access-token lifetime must be positive.")
        if self.signing_algorithm not in _SUPPORTED_SIGNING_ALGORITHMS:
            raise ValueError("The configured JWT signing algorithm is not allowed.")


class AuthService:
    """Authenticate the bootstrap account and issue or validate access tokens."""

    def __init__(
        self,
        config: AuthConfig,
        password_verifier: PasswordVerifier | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self._password_verifier = password_verifier or PwdlibPasswordVerifier()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def login(self, credentials: LoginRequest) -> AccessTokenResponse:
        """Verify credentials without revealing which value was incorrect."""
        password = credentials.password.get_secret_value()
        try:
            password_matches = self._password_verifier.verify(
                password,
                self.config.bootstrap_password_hash.get_secret_value(),
            )
        except Exception:
            # Invalid/mismatched configured hashes remain a generic public failure.
            password_matches = False

        username_matches = secrets.compare_digest(
            credentials.username.encode("utf-8"),
            self.config.bootstrap_username.encode("utf-8"),
        )
        if not (username_matches and password_matches):
            raise AuthenticationError
        return self.issue_access_token(self.config.bootstrap_subject)

    def issue_access_token(self, subject: str) -> AccessTokenResponse:
        """Create a signed, short-lived token for a non-empty stable subject."""
        normalized_subject = subject.strip()
        if not normalized_subject or len(normalized_subject) > 200:
            raise ValueError("A valid token subject is required.")

        issued_at = self._utc_now()
        expires_at = issued_at + timedelta(seconds=self.config.access_token_ttl_seconds)
        claims = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": normalized_subject,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            "jti": secrets.token_urlsafe(24),
        }
        token = jwt.encode(
            claims,
            self.config.signing_key.get_secret_value(),
            algorithm=self.config.signing_algorithm,
        )
        return AccessTokenResponse(
            access_token=token,
            expires_in=self.config.access_token_ttl_seconds,
        )

    def authenticate_authorization(self, authorization: str | None) -> AuthenticatedUser:
        """Validate a complete Authorization header and return its token subject."""
        token = self._bearer_token(authorization)
        if token is None:
            raise AuthenticationError
        return self.authenticate_token(token)

    def authenticate_token(self, token: str) -> AuthenticatedUser:
        """Validate signature, algorithm, issuer, audience, lifetime, and subject."""
        try:
            claims = jwt.decode(
                token,
                self.config.signing_key.get_secret_value(),
                algorithms=[self.config.signing_algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={
                    "require": list(_REQUIRED_CLAIMS),
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "verify_sub": True,
                },
            )
            subject = claims.get("sub")
            if not isinstance(subject, str):
                raise AuthenticationError
            normalized_subject = subject.strip()
            if not normalized_subject or len(normalized_subject) > 200:
                raise AuthenticationError
            return AuthenticatedUser(subject=normalized_subject)
        except (InvalidTokenError, AuthenticationError, ValueError, TypeError):
            raise AuthenticationError from None

    def _utc_now(self) -> datetime:
        current = self._now_provider()
        if current.tzinfo is None:
            raise ValueError("The authentication clock must return a timezone-aware datetime.")
        return current.astimezone(UTC)

    @staticmethod
    def _bearer_token(authorization: str | None) -> str | None:
        if authorization is None:
            return None
        scheme, separator, token = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token
            or token.strip() != token
            or any(character.isspace() for character in token)
        ):
            return None
        return token

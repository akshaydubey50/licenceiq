"""Bootstrap/local credential verification and strict JWT access-token handling."""

import re
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import SecretStr

from app.persistence.sessions import (
    AccountAlreadyExistsError,
    AccountStore,
    SessionStore,
)
from app.schemas.auth import AccessTokenResponse, AuthenticatedUser, LoginRequest, SignupRequest

AUTHENTICATION_FAILED: Final = "Authentication failed."
REGISTRATION_FAILED: Final = "Registration failed."
REGISTRATION_UNAVAILABLE: Final = "Registration is unavailable."
_SUPPORTED_SIGNING_ALGORITHMS: Final = frozenset({"HS256", "HS384", "HS512"})
_REQUIRED_CLAIMS: Final = ("iss", "aud", "sub", "iat", "nbf", "exp", "jti")
_LOCAL_USERNAME_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_MIN_PASSWORD_LENGTH: Final = 7
_MAX_PASSWORD_LENGTH: Final = 256


class AuthenticationError(Exception):
    """Internal generic failure that never contains credentials or token details."""

    def __init__(self) -> None:
        super().__init__(AUTHENTICATION_FAILED)


class RegistrationError(Exception):
    """Generic public registration failure without submitted credential details."""

    def __init__(self) -> None:
        super().__init__(REGISTRATION_FAILED)


class RegistrationUnavailableError(Exception):
    """Raised when local account creation is disabled by server policy."""

    def __init__(self) -> None:
        super().__init__(REGISTRATION_UNAVAILABLE)


class PasswordVerifier(Protocol):
    """Narrow password-hash boundary so tests and composition remain explicit."""

    def verify(self, password: str, password_hash: str) -> bool:
        """Return whether a plaintext candidate matches a stored modern hash."""


class PasswordHasher(PasswordVerifier, Protocol):
    """Hash and verify local passwords behind a testable Argon2 boundary."""

    def hash(self, password: str) -> str:
        """Return a password hash suitable for durable storage."""


class PwdlibPasswordHasher:
    """Hash and verify credentials using pwdlib's recommended Argon2 settings."""

    def __init__(self, password_hash: PasswordHash | None = None) -> None:
        self._password_hash = password_hash or PasswordHash.recommended()

    def verify(self, password: str, password_hash: str) -> bool:
        return self._password_hash.verify(password, password_hash)

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """Validated, explicitly injected authentication settings."""

    signing_key: SecretStr
    issuer: str
    audience: str
    bootstrap_username: str = ""
    bootstrap_password_hash: SecretStr = field(default_factory=lambda: SecretStr(""))
    bootstrap_subject: str = ""
    access_token_ttl_seconds: int = 15 * 60
    signing_algorithm: str = "HS256"
    self_registration_enabled: bool = False

    def __post_init__(self) -> None:
        required_identifiers = {
            "issuer": self.issuer,
            "audience": self.audience,
        }
        if any(not value.strip() for value in required_identifiers.values()):
            raise ValueError("Authentication identifiers must not be empty.")
        bootstrap_identifiers = (self.bootstrap_username, self.bootstrap_subject)
        bootstrap_values = (*bootstrap_identifiers, self.bootstrap_password_hash.get_secret_value())
        bootstrap_is_configured = all(value.strip() for value in bootstrap_values)
        if any(value.strip() for value in bootstrap_values) and not bootstrap_is_configured:
            raise ValueError("Bootstrap account settings must be complete when configured.")
        if not self.self_registration_enabled and not bootstrap_is_configured:
            raise ValueError("A bootstrap account is required when registration is disabled.")
        if self.bootstrap_subject and len(self.bootstrap_subject) > 200:
            raise ValueError("The authentication subject is too long.")
        if len(self.signing_key.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("The JWT signing key must contain at least 32 bytes.")
        if self.access_token_ttl_seconds <= 0:
            raise ValueError("The access-token lifetime must be positive.")
        if self.signing_algorithm not in _SUPPORTED_SIGNING_ALGORITHMS:
            raise ValueError("The configured JWT signing algorithm is not allowed.")


class AuthService:
    """Authenticate bootstrap/local accounts and issue or validate access tokens."""

    def __init__(
        self,
        config: AuthConfig,
        password_verifier: PasswordVerifier | None = None,
        password_hasher: PasswordHasher | None = None,
        now_provider: Callable[[], datetime] | None = None,
        session_store: SessionStore | None = None,
        account_store: AccountStore | None = None,
    ) -> None:
        self.config = config
        default_password_hasher = PwdlibPasswordHasher()
        self._password_verifier = password_verifier or default_password_hasher
        self._password_hasher = password_hasher or default_password_hasher
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._session_store = session_store
        self._account_store = account_store
        if config.self_registration_enabled and (
            self._session_store is None or self._account_store is None
        ):
            raise ValueError("Self-registration requires durable account and session stores.")

    def login(self, credentials: LoginRequest) -> AccessTokenResponse:
        """Verify credentials without revealing which value was incorrect."""
        username = self._canonical_username(credentials.username)
        local_username = self._normalized_local_username(credentials.username)
        password = credentials.password.get_secret_value()
        bootstrap_username = self._canonical_username(self.config.bootstrap_username)
        bootstrap_is_configured = bool(
            bootstrap_username
            and self.config.bootstrap_subject.strip()
            and self.config.bootstrap_password_hash.get_secret_value()
        )
        bootstrap_matches = bootstrap_is_configured and self._constant_time_text_matches(
            username, bootstrap_username
        )

        account = None
        if not bootstrap_matches and local_username and self._account_store is not None:
            try:
                account = self._account_store.find_account(
                    issuer=self.config.issuer,
                    normalized_username=local_username,
                )
            except Exception:
                raise AuthenticationError from None

        candidate_hash = account.password_hash if account is not None else None
        if candidate_hash is None and bootstrap_is_configured:
            candidate_hash = self.config.bootstrap_password_hash.get_secret_value()
        try:
            password_matches = (
                self._password_verifier.verify(password, candidate_hash)
                if candidate_hash is not None
                else False
            )
        except Exception:
            # Invalid/mismatched configured hashes remain a generic public failure.
            password_matches = False

        if bootstrap_matches and password_matches:
            return self.issue_access_token(self.config.bootstrap_subject)
        if account is not None and password_matches:
            return self.issue_access_token(account.subject)
        raise AuthenticationError

    def signup(self, credentials: SignupRequest) -> AccessTokenResponse:
        """Create one durable local account and immediately issue its revocable session."""
        if (
            not self.config.self_registration_enabled
            or self._account_store is None
            or self._session_store is None
        ):
            raise RegistrationUnavailableError

        normalized_username = self._normalized_local_username(credentials.username)
        password = credentials.password.get_secret_value()
        if (
            normalized_username is None
            or not _MIN_PASSWORD_LENGTH <= len(password) <= _MAX_PASSWORD_LENGTH
            or self._constant_time_text_matches(
                normalized_username,
                self._canonical_username(self.config.bootstrap_username),
            )
        ):
            raise RegistrationError

        try:
            password_hash = self._password_hasher.hash(password)
            if not password_hash.startswith("$argon2"):
                raise ValueError("The configured password hasher did not produce Argon2.")
            subject = self._account_store.create_account(
                issuer=self.config.issuer,
                normalized_username=normalized_username,
                password_hash=password_hash,
                created_at=self._utc_now(),
            )
        except AccountAlreadyExistsError:
            raise RegistrationError from None
        except Exception:
            raise RegistrationError from None

        try:
            return self.issue_access_token(subject)
        except AuthenticationError:
            # The account remains usable for a later login if session issuance was transiently down.
            raise RegistrationError from None

    @staticmethod
    def _canonical_username(username: str) -> str:
        """Apply one stable Unicode normalization and case-folding policy."""
        return unicodedata.normalize("NFKC", username).strip().casefold()

    @classmethod
    def _normalized_local_username(cls, username: str) -> str | None:
        normalized = cls._canonical_username(username)
        if _LOCAL_USERNAME_PATTERN.fullmatch(normalized) is None:
            return None
        return normalized

    @staticmethod
    def _constant_time_text_matches(candidate: str, expected: str) -> bool:
        if not candidate or not expected:
            return False
        return secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))

    def issue_access_token(self, subject: str) -> AccessTokenResponse:
        """Create a signed, short-lived token for a non-empty stable subject."""
        normalized_subject = subject.strip()
        if not normalized_subject or len(normalized_subject) > 200:
            raise ValueError("A valid token subject is required.")

        issued_at = self._utc_now()
        expires_at = issued_at + timedelta(seconds=self.config.access_token_ttl_seconds)
        jti = secrets.token_urlsafe(24)
        claims: dict[str, Any] = {
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": normalized_subject,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            "jti": jti,
        }
        if self._session_store is not None:
            try:
                sid = self._session_store.create_session(
                    issuer=self.config.issuer,
                    subject=normalized_subject,
                    jti=jti,
                    issued_at=issued_at,
                    expires_at=expires_at,
                )
            except Exception as exc:
                raise AuthenticationError from exc
            claims["sid"] = str(sid)
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
        required_claims = [*_REQUIRED_CLAIMS]
        if self._session_store is not None:
            required_claims.append("sid")
        try:
            claims = jwt.decode(
                token,
                self.config.signing_key.get_secret_value(),
                algorithms=[self.config.signing_algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={
                    "require": required_claims,
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
            if self._session_store is None:
                return AuthenticatedUser(subject=normalized_subject)
            sid = UUID(str(claims.get("sid")))
            jti = claims.get("jti")
            if not isinstance(jti, str) or not self._session_store.session_is_active(
                issuer=self.config.issuer,
                subject=normalized_subject,
                sid=sid,
                jti=jti,
                now=self._utc_now(),
            ):
                raise AuthenticationError
            return AuthenticatedUser(subject=normalized_subject, session_id=str(sid))
        except (InvalidTokenError, AuthenticationError, ValueError, TypeError):
            raise AuthenticationError from None

    def logout(self, authorization: str | None) -> None:
        """Revoke the caller's durable session; stateless modes have no logout record."""
        if self._session_store is None:
            raise AuthenticationError
        token = self._bearer_token(authorization)
        if token is None:
            raise AuthenticationError
        try:
            claims = jwt.decode(
                token,
                self.config.signing_key.get_secret_value(),
                algorithms=[self.config.signing_algorithm],
                issuer=self.config.issuer,
                audience=self.config.audience,
                options={"require": [*_REQUIRED_CLAIMS, "sid"]},
            )
            subject = str(claims["sub"]).strip()
            sid = UUID(str(claims["sid"]))
            jti = claims["jti"]
            if (
                not subject
                or not isinstance(jti, str)
                or not self._session_store.revoke_session(
                    issuer=self.config.issuer,
                    subject=subject,
                    sid=sid,
                    jti=jti,
                    now=self._utc_now(),
                )
            ):
                raise AuthenticationError
        except (InvalidTokenError, AuthenticationError, KeyError, TypeError, ValueError):
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

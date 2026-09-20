"""Load backend settings independently of the command's working directory."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Load prefixed app settings and the standard server-side OpenAI credential."""

    model_config = SettingsConfigDict(
        env_prefix="LICENCEIQ_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "LicenceIQ API"
    environment: Literal["development", "test", "production"] = "development"
    auth_mode: Literal["capability", "jwt", "hybrid"] = "capability"
    jwt_signing_key: SecretStr = Field(default=SecretStr(""))
    jwt_issuer: str = "licenceiq-api"
    jwt_audience: str = "licenceiq-browser"
    jwt_access_token_ttl_seconds: int = Field(default=15 * 60, ge=60, le=60 * 60)
    bootstrap_username: str = ""
    bootstrap_password_hash: SecretStr = Field(default=SecretStr(""))
    bootstrap_subject: str = ""
    self_registration_enabled: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    document_storage_backend: Literal["filesystem", "minio"] = "filesystem"
    document_metadata_backend: Literal["object_store", "postgres"] = "object_store"
    database_url: SecretStr = Field(default=SecretStr(""))
    document_storage_dir: Path = PROJECT_ROOT / "backend" / ".data" / "documents"
    minio_endpoint: str = ""
    minio_access_key: SecretStr = Field(default=SecretStr(""))
    minio_secret_key: SecretStr = Field(default=SecretStr(""))
    minio_bucket: str = "licenceiq-private"
    minio_prefix: str = "documents"
    minio_secure: bool = True
    max_upload_file_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    max_upload_request_bytes: int = Field(default=11 * 1024 * 1024, ge=1)
    document_retention_seconds: int = Field(default=24 * 60 * 60, ge=1)
    max_pdf_pages: int = Field(default=20, ge=1)
    max_image_dimension: int = Field(default=12_000, ge=1)
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    openai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="OPENAI_API_KEY")
    langfuse_tracing_enabled: bool = Field(
        default=False,
        validation_alias="LANGFUSE_TRACING_ENABLED",
    )
    langfuse_public_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="LANGFUSE_PUBLIC_KEY",
    )
    langfuse_secret_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias="LANGFUSE_SECRET_KEY",
    )
    langfuse_base_url: str = Field(default="", validation_alias="LANGFUSE_BASE_URL")
    # Licence contents are too sensitive for prompt/completion capture. This invariant
    # intentionally rejects attempts to enable it through environment configuration.
    langfuse_capture_io: bool = Field(
        default=False,
        validation_alias="LANGFUSE_CAPTURE_IO",
    )
    ocr_model: str = Field(default="gpt-4.1-mini", min_length=1)
    ocr_timeout_seconds: float = Field(default=45, ge=1, le=120)
    reading_timeout_seconds: float = Field(default=120, ge=1, le=120)
    ocr_max_image_dimension: int = Field(default=2400, ge=64, le=4000)
    ocr_max_image_pixels: int = Field(default=4_000_000, ge=4096, le=16_000_000)
    max_reading_characters: int = Field(default=200_000, ge=1, le=1_000_000)
    extraction_model: str = Field(default="gpt-4.1-mini", min_length=1)
    extraction_timeout_seconds: float = Field(default=60, ge=1, le=120)
    extraction_max_input_characters: int = Field(default=200_000, ge=1, le=1_000_000)
    extraction_max_output_tokens: int = Field(default=4000, ge=1, le=16_000)
    question_model: str = Field(default="gpt-4.1-mini", min_length=1)
    # Semantic retrieval can require two bounded embedding calls before the answer request.
    question_timeout_seconds: float = Field(default=60, ge=1, le=120)
    question_max_input_characters: int = Field(default=50_000, ge=1000, le=250_000)
    question_max_output_tokens: int = Field(default=1000, ge=1, le=4000)
    question_max_selected_blocks: int = Field(default=8, ge=1, le=20)
    question_max_selected_characters: int = Field(default=16_000, ge=1, le=50_000)
    question_embedding_model: str = Field(default="text-embedding-3-small", min_length=1)
    question_embedding_dimensions: int = Field(default=256, ge=1, le=3072)
    question_embedding_timeout_seconds: float = Field(default=15, ge=1, le=120)
    question_embedding_max_blocks: int = Field(default=256, ge=1, le=2000)
    question_embedding_max_characters: int = Field(default=100_000, ge=1, le=200_000)
    question_rewrite_model: str = Field(default="gpt-4.1-mini", min_length=1)
    question_rewrite_timeout_seconds: float = Field(default=8, ge=1, le=30)
    question_rewrite_max_input_characters: int = Field(default=2500, ge=500, le=5000)
    question_rewrite_max_output_tokens: int = Field(default=200, ge=1, le=1000)
    question_guardrails_enabled: bool = True
    question_guardrail_timeout_seconds: float = Field(default=2, ge=0.1, le=10)
    max_concurrent_questions: int = Field(default=4, ge=1, le=32)

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        """Require explicit browser origins instead of wildcard or path-based access."""
        normalized: list[str] = []
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("CORS entries must be explicit HTTP(S) origins without paths.")
            # Accessing port also rejects malformed port values during settings validation.
            _ = parsed.port
            normalized.append(origin.rstrip("/"))
        return normalized

    @field_validator("max_upload_request_bytes")
    @classmethod
    def validate_request_limit(cls, limit: int, info: ValidationInfo) -> int:
        """Leave enough multipart overhead to accept a file at the advertised limit."""
        file_limit = info.data.get("max_upload_file_bytes", 10 * 1024 * 1024)
        if limit <= file_limit:
            raise ValueError("The request limit must be larger than the file limit.")
        return limit

    @field_validator("langfuse_base_url")
    @classmethod
    def validate_langfuse_base_url(cls, value: str) -> str:
        """Accept an explicit HTTP(S) Langfuse root without embedded credentials."""
        normalized = value.strip().rstrip("/")
        if not normalized:
            return ""
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Langfuse base URL must be an HTTP(S) URL without credentials.")
        _ = parsed.port
        return normalized

    @field_validator("langfuse_capture_io")
    @classmethod
    def validate_langfuse_capture_io(cls, value: bool) -> bool:
        """Accept normal environment boolean syntax while permanently forbidding capture."""
        if value:
            raise ValueError("Langfuse input/output capture must remain disabled.")
        return False

    @model_validator(mode="after")
    def validate_private_deployment_settings(self) -> "Settings":
        """Require complete, non-local safeguards before enabling protected modes."""
        if self.document_storage_backend == "minio":
            endpoint = self.minio_endpoint.strip()
            if not endpoint or "://" in endpoint or "/" in endpoint:
                raise ValueError(
                    "MinIO endpoint must be a host with an optional port, without a URL path."
                )
            if (
                not self.minio_access_key.get_secret_value()
                or not self.minio_secret_key.get_secret_value()
            ):
                raise ValueError("MinIO access and secret keys are required for MinIO storage.")

        if self.document_metadata_backend == "postgres":
            if self.document_storage_backend != "minio":
                raise ValueError(
                    "PostgreSQL document metadata requires MinIO document storage "
                    "for original bytes."
                )
            if not self.database_url.get_secret_value():
                raise ValueError("PostgreSQL document metadata requires LICENCEIQ_DATABASE_URL.")
            if self.question_embedding_dimensions != 256:
                raise ValueError(
                    "PostgreSQL vector persistence requires question embedding dimensions of 256."
                )

        if self.auth_mode in {"jwt", "hybrid"}:
            signing_key = self.jwt_signing_key.get_secret_value()
            if len(signing_key.encode("utf-8")) < 32:
                raise ValueError("JWT signing key must contain at least 32 bytes.")
            bootstrap_values = (
                self.bootstrap_username,
                self.bootstrap_subject,
                self.bootstrap_password_hash.get_secret_value(),
            )
            bootstrap_is_configured = all(value.strip() for value in bootstrap_values)
            if any(value.strip() for value in bootstrap_values) and not bootstrap_is_configured:
                raise ValueError("Bootstrap account settings must be complete when configured.")
            if not self.self_registration_enabled and not bootstrap_is_configured:
                raise ValueError(
                    "JWT and hybrid modes require a complete bootstrap account unless "
                    "self-registration is enabled."
                )

        if self.self_registration_enabled:
            if self.environment == "production":
                raise ValueError("Self-registration is not available in production.")
            if self.auth_mode not in {"jwt", "hybrid"}:
                raise ValueError("Self-registration requires JWT authentication.")
            if self.document_metadata_backend != "postgres":
                raise ValueError("Self-registration requires durable PostgreSQL identity storage.")

        if self.environment == "production":
            # Public guest access needs additional abuse controls and operational safeguards
            # that are outside this assessment, so production remains authenticated-only.
            if self.auth_mode != "jwt":
                raise ValueError("Production requires JWT authentication.")
            if self.document_storage_backend != "minio":
                raise ValueError("Production requires MinIO document storage.")
            if self.document_metadata_backend != "postgres":
                raise ValueError("Production requires PostgreSQL document metadata.")
            if not self.database_url.get_secret_value():
                raise ValueError("Production requires LICENCEIQ_DATABASE_URL.")
            if not self.minio_secure:
                raise ValueError("Production requires secure MinIO transport.")
            if any(urlsplit(origin).scheme != "https" for origin in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS.")
            if self.langfuse_ready and urlsplit(self.langfuse_base_url).scheme != "https":
                raise ValueError("Production Langfuse telemetry requires HTTPS.")
        return self

    @property
    def langfuse_ready(self) -> bool:
        """Enable export only when explicitly requested with a complete key pair and host."""
        return self.langfuse_tracing_enabled and all(
            (
                self.langfuse_public_key.get_secret_value().strip(),
                self.langfuse_secret_key.get_secret_value().strip(),
                self.langfuse_base_url,
            )
        )


@lru_cache
def get_settings() -> Settings:
    """Read process settings once; tests can instead inject a Settings instance."""
    return Settings()

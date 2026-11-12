"""Application settings loaded from environment variables and the repository .env file.

Environment variables always win over values in .env, which lets tests and Docker
override any setting without editing files.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

# backend/app/core/config.py -> parents[3] is the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]

# The placeholder shipped in .env.example. Allowed for local development only.
PLACEHOLDER_JWT_SECRET = "replace-with-a-long-random-value"  # noqa: S105 - known placeholder


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "SyncForge API"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    postgres_user: str = "syncforge"
    postgres_password: SecretStr = SecretStr("change-me-local-only")
    postgres_db: str = "syncforge"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    # Optional full URL (e.g. from a managed database); takes precedence when set.
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    cors_origins: list[str] = ["http://localhost:4200"]

    # ---- Authentication (JWT access tokens) -------------------------------------
    jwt_secret_key: SecretStr = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_issuer: str = "syncforge"
    jwt_audience: str = "syncforge-api"
    access_token_expire_minutes: int = Field(default=30, ge=1, le=24 * 60)

    # ---- Connectors (external applications) -------------------------------------
    # Fernet key(s) that encrypt connector credentials at rest. Comma-separated to
    # rotate keys: the first key encrypts, every key can decrypt.
    connector_encryption_key: SecretStr | None = None
    # Hosts that connectors may call. Guards against server-side request forgery
    # (an admin pointing a connector at an internal service).
    connector_allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    connector_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=60)
    connector_read_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # Wall-clock limit for one whole operation, across all the requests it makes.
    connector_operation_timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    # Default endpoints: the local mock services in mock-services/. 127.0.0.1 rather
    # than "localhost": on Windows, localhost tries IPv6 (::1) first, and a refused
    # loopback connection is retried for ~2s before falling back to IPv4.
    slack_base_url: str = "http://127.0.0.1:9101"
    google_workspace_base_url: str = "http://127.0.0.1:9102"
    payroll_base_url: str = "http://127.0.0.1:9103"

    # ---- Background processing (Redis + Celery workers + outbox relay) ------------
    redis_url: str = "redis://localhost:6379/0"
    # How long a worker owns an event it claimed. Renewed before every step; if a worker
    # dies, the relay re-dispatches the event once the lease has expired.
    worker_lease_seconds: int = Field(default=300, ge=10, le=3600)
    # Outbox relay: rows published per poll, and the pause between polls.
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)

    # ---- Retries (exponential backoff with jitter; see app/reliability/retry.py) ------
    retry_max_attempts: int = Field(default=5, ge=1, le=20)  # first attempt included
    retry_base_delay_seconds: float = Field(default=2.0, gt=0, le=300)
    retry_max_delay_seconds: float = Field(default=300.0, gt=0, le=86400)
    retry_jitter_ratio: float = Field(default=0.2, ge=0, le=1)

    # ---- Circuit breaker per connector (app/reliability/circuit_breaker.py) ----------
    # Consecutive outage-type failures (server error, timeout, network) that open it.
    circuit_failure_threshold: int = Field(default=5, ge=1, le=100)
    # How long it stays open before one trial call is let through (half-open).
    circuit_open_seconds: float = Field(default=60.0, gt=0, le=3600)

    # ---- Idempotency keys on create requests (app/reliability/idempotency.py) --------
    # How long a stored response can be replayed for the same Idempotency-Key.
    idempotency_ttl_hours: int = Field(default=24, ge=1, le=720)

    @field_validator("connector_encryption_key", mode="before")
    @classmethod
    def _blank_key_means_unset(cls, value: object) -> object:
        # `CONNECTOR_ENCRYPTION_KEY=` (as shipped in .env.example) means "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _reject_placeholder_secrets_in_production(self) -> Self:
        if self.app_env == "production":
            if self.jwt_secret_key.get_secret_value() == PLACEHOLDER_JWT_SECRET:
                raise ValueError("JWT_SECRET_KEY must be changed from the placeholder value.")
            if self.postgres_password.get_secret_value() == "change-me-local-only":
                raise ValueError("POSTGRES_PASSWORD must be changed from the placeholder value.")
            if self.connector_encryption_key is None:
                raise ValueError("CONNECTOR_ENCRYPTION_KEY is required in production.")
        return self

    @property
    def database_url(self) -> URL | str:
        if self.database_url_override:
            return self.database_url_override
        # URL.create escapes special characters in the password safely.
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()

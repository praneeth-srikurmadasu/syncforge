"""Application settings loaded from environment variables and the repository .env file.

Environment variables always win over values in .env, which lets tests and Docker
override any setting without editing files.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
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

    @model_validator(mode="after")
    def _reject_placeholder_secrets_in_production(self) -> Self:
        if self.app_env == "production":
            if self.jwt_secret_key.get_secret_value() == PLACEHOLDER_JWT_SECRET:
                raise ValueError("JWT_SECRET_KEY must be changed from the placeholder value.")
            if self.postgres_password.get_secret_value() == "change-me-local-only":
                raise ValueError("POSTGRES_PASSWORD must be changed from the placeholder value.")
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

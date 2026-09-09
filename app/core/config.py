from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Cestos Operations"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    database_url: str
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_expire_days: int = Field(default=30, ge=1, le=90)
    redis_url: str | None = None
    cors_origins: list[str] = []
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    initial_admin_email: str | None = None
    initial_admin_password: SecretStr | None = None
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = Field(default=60, ge=10, le=3600)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_use_ssl: bool = False
    public_base_url: str = "http://localhost:8000/test-ui"
    storage_dir: str = "storage"
    max_upload_size_mb: int = Field(default=10, ge=1, le=100)

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if make_url(value).drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if len(secret) < 32 or secret.startswith("replace-with"):
            raise ValueError("Set a random JWT_SECRET_KEY of at least 32 characters")
        return value

    @model_validator(mode="after")
    def production_settings(self) -> "Settings":
        if self.app_env == "production" and (self.debug or "*" in self.cors_origins):
            raise ValueError("Production must disable DEBUG and wildcard CORS")
        if self.app_env == "production" and self.smtp_host:
            if not (self.smtp_starttls or self.smtp_use_ssl) or not self.public_base_url.startswith(
                "https://"
            ):
                raise ValueError("Production SMTP requires STARTTLS and an HTTPS PUBLIC_BASE_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

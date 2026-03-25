from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str | None = None
    secret_key: str = "development-only-secret-key-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    cors_allowed_origins: str = "http://localhost:5173,http://localhost:8080"
    spreadsheet_max_size_mb: int = 10
    spreadsheet_allowed_content_types: str = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/octet-stream"
    )
    batch_worker_enabled: bool = True
    batch_worker_poll_interval_seconds: int = 5
    batch_worker_lease_seconds: int = 300

    legal_one_base_url: str | None = None
    legal_one_client_id: str | None = None
    legal_one_client_secret: str | None = None

    smtp_server: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def spreadsheet_max_size_bytes(self) -> int:
        return self.spreadsheet_max_size_mb * 1024 * 1024

    @property
    def allowed_spreadsheet_content_types(self) -> set[str]:
        return {
            content_type.strip().lower()
            for content_type in self.spreadsheet_allowed_content_types.split(",")
            if content_type.strip()
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

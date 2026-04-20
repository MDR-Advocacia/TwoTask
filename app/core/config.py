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
    legal_one_position_fix_status_file: str | None = None
    legal_one_web_username: str | None = None
    legal_one_web_password: str | None = None
    legal_one_web_key_label: str | None = None
    publication_treatment_output_dir: str | None = None
    publication_treatment_runner_script: str | None = None
    publication_treatment_batch_size: int = 20
    publication_treatment_pause_seconds: int = 5
    publication_treatment_max_attempts: int = 3
    publication_treatment_monitor_poll_seconds: int = 5

    smtp_server: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str | None = None
    email_to: str | None = None

    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"
    datajud_api_key: str | None = None
    datajud_timeout_seconds: int = 30
    datajud_default_page_size: int = 100

    comunica_base_url: str = "https://comunicaapi.pje.jus.br"
    comunica_timeout_seconds: int = 30
    djen_default_meio: str = "D"

    process_monitoring_idle_window_days: int = 15
    process_monitoring_recency_window_days: int = 10

    # ── Publication Capture (Legal One /Updates) ──────────────────────
    # Quando um escritório é capturado pela primeira vez (nenhum cursor
    # prévio), a rodagem inicial olha para trás este número de dias.
    publication_initial_lookback_days: int = 3
    # Overlap defensivo aplicado em todas as rodagens seguintes
    # (date_from = last_success − overlap). Mantém a janela fechada
    # mesmo se houver atraso de processamento/indexação no L1.
    publication_overlap_hours: int = 1
    # Campo do Legal One usado para filtrar a busca:
    # "creationDate" = data em que o L1 disponibilizou a publicação (recomendado)
    # "date"         = data efetiva da publicação no diário (pode perder entradas tardias)
    publication_capture_date_field: str = "creationDate"

    # Classifier Engine
    anthropic_api_key: str | None = None
    classifier_model: str = "claude-haiku-4-5-20251001"
    classifier_max_concurrent: int = 5
    classifier_max_tokens: int = 4096

    # ── Prazos Iniciais ───────────────────────────────────────────────
    # Chave(s) que autenticam a automação externa no endpoint de intake.
    # Aceita múltiplas chaves separadas por vírgula (rotação sem downtime).
    prazos_iniciais_api_key: str | None = None
    # Pasta raiz (dentro do volume persistente) onde os PDFs da habilitação
    # são guardados até o upload no GED do L1.
    prazos_iniciais_storage_path: str = "/app/data/prazos_iniciais"
    prazos_iniciais_max_pdf_mb: int = 20
    # Quantos dias manter o PDF local após confirmação de upload no GED.
    prazos_iniciais_retention_days: int = 7
    # Parâmetros do agregador (janela antes de submeter batch pra Anthropic).
    prazos_iniciais_batch_window_seconds: int = 600
    prazos_iniciais_batch_min_size: int = 5
    prazos_iniciais_batch_max_size: int = 100
    # typeId usado no L1 para o documento de habilitação (Documento/Habilitação).
    prazos_iniciais_ged_type_id: str = "2-48"
    # Modelo Anthropic usado na classificação (Sonnet — mais sensível).
    prazos_iniciais_classifier_model: str = "claude-sonnet-4-6"
    prazos_iniciais_classifier_max_tokens: int = 4096

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

    @property
    def prazos_iniciais_api_keys(self) -> set[str]:
        """Chaves válidas para autenticar a automação externa (aceita rotação)."""
        raw = self.prazos_iniciais_api_key or ""
        return {key.strip() for key in raw.split(",") if key.strip()}

    @property
    def prazos_iniciais_max_pdf_bytes(self) -> int:
        return self.prazos_iniciais_max_pdf_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

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
    # Worker periódico: agrega intakes PRONTO_PARA_CLASSIFICAR e dispara
    # batch + faz polling/apply dos batches pendentes.
    # Desligado por padrão em dev pra evitar gasto involuntário com Anthropic.
    prazos_iniciais_auto_classification_enabled: bool = False
    # Intervalo entre execuções do worker (segundos).
    prazos_iniciais_auto_classification_interval_seconds: int = 300
    # Fila de cancelamento da task legada "Agendar Prazos". Só consome
    # itens que já foram explicitamente enfileirados ao final do fluxo de
    # confirmação, então pode ficar ligada por padrão sem efeitos colaterais.
    prazos_iniciais_legacy_task_cancellation_enabled: bool = True
    prazos_iniciais_legacy_task_cancellation_interval_seconds: int = 60
    prazos_iniciais_legacy_task_cancellation_batch_size: int = 10
    # Rate limit entre items consecutivos na fila (evita martelar o Legal One
    # quando há muitos itens pendentes). Aceita fracionário.
    prazos_iniciais_legacy_task_cancel_rate_limit_seconds: float = 2.0
    # Circuit breaker: após N falhas de infraestrutura (auth/timeout/exception)
    # consecutivas, o worker pula ticks por cooldown_minutes minutos. Sucesso
    # zera o contador; falhas de negócio (task_not_found, layout_drift) não
    # contam porque sinalizam problemas de dado, não de conexão.
    prazos_iniciais_legacy_task_circuit_breaker_threshold: int = 3
    prazos_iniciais_legacy_task_circuit_breaker_cooldown_minutes: int = 10

    # ── Disparo periódico do tratamento web (Onda 3 #6) ─────────────────
    # Worker que varre intakes com `dispatch_pending=True` e dispara
    # GED upload + enqueue cancel da legada em ordem cronológica.
    # Desligado por padrão até a TI validar — operador pode disparar
    # manualmente pelo botão "Disparar próximos 10".
    prazos_iniciais_dispatch_enabled: bool = False
    prazos_iniciais_dispatch_interval_seconds: int = 300
    prazos_iniciais_dispatch_batch_limit: int = 10

    # ── Batch Tasks (OneSid, OneRequest, etc.) ────────────────────────
    # Chave(s) que autenticam as automações externas no endpoint
    # /api/v1/tasks/batch-create. Separado do JWT do operador pq o
    # OneSid chama direto via HTTP sem ter usuário/senha no sistema.
    # Aceita múltiplas separadas por vírgula pra rotação sem downtime.
    batch_tasks_api_key: str | None = None

    # ── AJUS (sistema do cliente — POST /inserir-prazos) ──────────────
    # Credenciais lidas do env (Coolify). NÃO fica em tabela porque é
    # uma conta única por instalação MDR. Se um dia precisar de conta
    # por escritório, evolui pra tabela. Ver app/services/ajus/.
    ajus_base_url: str = "https://sistema.ajus.com.br/webservices/api"
    ajus_bearer_token: str | None = None
    ajus_cliente: str | None = None
    ajus_login: str | None = None
    ajus_senha: str | None = None
    # Storage local de cópias do PDF da habilitação que foram pra fila
    # AJUS. Sobrevive à rotina de cleanup do prazos_iniciais. Apagado
    # automaticamente após inserção bem-sucedida (sucesso da AJUS).
    ajus_storage_path: str = "/app/data/ajus_pdfs"

    # ── Classificação AJUS via RPA Playwright (Chunk 2) ───────────────
    # Selectors XPath, paths do portal e domínio do cliente NÃO ficam
    # aqui — viraram constantes em `app/services/ajus/portal_constants.py`
    # porque são fixos do portal AJUS / cliente MDR e não variam por
    # instância. Aqui sobra só o que é confidencial ou operacional.
    #
    # Volume persistente onde cada conta AJUS guarda seu storage_state.
    # Layout: <root>/<account_id>/storage_state.json. Volume é
    # compartilhado entre o container API e o `ajus-runner` (que roda
    # o Playwright). Em prod (Coolify) montar `/data/ajus-session/`.
    ajus_session_path: str = "/app/data/ajus-session"
    # Key Fernet pra criptografar a senha das contas AJUS na tabela
    # `ajus_session_accounts`. Gerar com Fernet.generate_key() — nunca
    # commitar valor real. Sem essa key configurada, o módulo de
    # classificação fica desabilitado (não loga, não dispara).
    ajus_fernet_key: str | None = None
    # Timeout do flow de login (ms) — usado em wait_for_login_outcome.
    # Ajustável via env se o portal estiver lento.
    ajus_login_outcome_timeout_ms: int = 30_000
    # Timeout do polling do IP-code (segundos). Operador tem esse tempo
    # pra submeter o código pela UI antes do runner desistir.
    ajus_ip_code_wait_seconds: int = 300
    # Worker do ajus-runner: intervalo entre polls e tamanho do batch
    # por conta em cada ciclo. 5 itens × 45s ≈ 4min/batch, então com
    # poll de 30s o worker fica idle a maior parte do tempo quando a
    # fila é pequena. Em backlog grande, sobe `ajus_runner_batch_per_account`.
    ajus_runner_poll_interval_seconds: int = 30
    ajus_runner_batch_per_account: int = 5


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

    @property
    def batch_tasks_api_keys(self) -> set[str]:
        """
        Chaves válidas pra autenticar automações externas que chamam
        /api/v1/tasks/batch-create (OneSid, OneRequest etc.). Aceita
        múltiplas separadas por vírgula.
        """
        raw = self.batch_tasks_api_key or ""
        return {key.strip() for key in raw.split(",") if key.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

"""
Modelos do fluxo "Agendar Prazos Iniciais".

Recebe processos novos vindos de uma automação externa (JSON + PDF da
habilitação), classifica via Claude Sonnet (Batches API), e agenda as
tarefas resultantes no Legal One após revisão humana.

Tabelas
-------
prazo_inicial_intake     → 1 linha por POST recebido na API externa
prazo_inicial_sugestao   → N sugestões por intake (saída da IA)
prazo_inicial_batch      → lotes enviados à Anthropic (rastreabilidade)
"""

from sqlalchemy import (
    Numeric,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ─── Status do intake ─────────────────────────────────────────────────
# Ciclo de vida do registro principal. Ordem típica (feliz):
#   RECEBIDO → PRONTO_PARA_CLASSIFICAR → EM_CLASSIFICACAO → CLASSIFICADO
#          → EM_REVISAO → AGENDADO → GED_ENVIADO → CONCLUIDO
#
# Ramo "sem template cadastrado":
#   EM_CLASSIFICACAO → AGUARDANDO_CONFIG_TEMPLATE (fica travado até que o
#                     operador cadastre template para o (tipo_prazo, subtipo,
#                     office) daquela sugestão, ou agende manualmente pela
#                     tela de revisão — ver `template_matching_service`).

INTAKE_STATUS_RECEIVED = "RECEBIDO"
INTAKE_STATUS_LAWSUIT_NOT_FOUND = "PROCESSO_NAO_ENCONTRADO"
INTAKE_STATUS_READY_TO_CLASSIFY = "PRONTO_PARA_CLASSIFICAR"
INTAKE_STATUS_IN_CLASSIFICATION = "EM_CLASSIFICACAO"
INTAKE_STATUS_CLASSIFIED = "CLASSIFICADO"
INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG = "AGUARDANDO_CONFIG_TEMPLATE"
INTAKE_STATUS_IN_REVIEW = "EM_REVISAO"
INTAKE_STATUS_SCHEDULED = "AGENDADO"
# Fluxo "Finalizar sem providência" (Caminho A): operador confirma
# que o caso não exige tarefa nova — só empurra habilitação pro GED e
# cancela a legada. Distinto de AGENDADO pra não poluir relatórios
# operacionais que contam "tasks criadas".
INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE = "CONCLUIDO_SEM_PROVIDENCIA"
INTAKE_STATUS_GED_SENT = "GED_ENVIADO"
INTAKE_STATUS_COMPLETED = "CONCLUIDO"
INTAKE_STATUS_CLASSIFICATION_ERROR = "ERRO_CLASSIFICACAO"
INTAKE_STATUS_SCHEDULE_ERROR = "ERRO_AGENDAMENTO"
INTAKE_STATUS_GED_ERROR = "ERRO_GED"
INTAKE_STATUS_CANCELLED = "CANCELADO"

# ─── Status do batch (Anthropic Messages Batches API) ─────────────────

PIN_BATCH_STATUS_SUBMITTED = "ENVIADO"
PIN_BATCH_STATUS_IN_PROGRESS = "EM_PROCESSAMENTO"
PIN_BATCH_STATUS_READY = "PRONTO"
PIN_BATCH_STATUS_APPLIED = "APLICADO"
PIN_BATCH_STATUS_FAILED = "FALHA"
PIN_BATCH_STATUS_CANCELLED = "CANCELADO"

# ─── Status da revisão de sugestão ────────────────────────────────────

SUGESTAO_REVIEW_PENDING = "pendente"
SUGESTAO_REVIEW_APPROVED = "aprovado"
SUGESTAO_REVIEW_REJECTED = "rejeitado"
SUGESTAO_REVIEW_EDITED = "editado"

# ─── Origem do intake (pin016) ────────────────────────────────────────
# EXTERNAL_API: provedor externo via X-Intake-Api-Key (modo histórico).
# USER_UPLOAD:  operador subiu PDF do processo na íntegra pela UI;
#               capa/integra montadas mecanicamente pelo motor de
#               extração (pdfplumber + extractor PJe TJBA).

INTAKE_SOURCE_EXTERNAL_API = "EXTERNAL_API"
INTAKE_SOURCE_USER_UPLOAD = "USER_UPLOAD"

# ─── Confiança da extração mecânica (pin016) ──────────────────────────
# high:    template detectado, capa+timeline extraídas (PJe TJBA OK).
# partial: capa parcialmente preenchida ou timeline não-segmentada.
# low:     fallback texto cru — capa vazia, integra como blob.

EXTRACTION_CONFIDENCE_HIGH = "high"
EXTRACTION_CONFIDENCE_PARTIAL = "partial"
EXTRACTION_CONFIDENCE_LOW = "low"


class PrazoInicialIntake(Base):
    """
    Registro principal — 1 linha por processo recebido pela API externa.
    """

    __tablename__ = "prazo_inicial_intakes"

    id = Column(Integer, primary_key=True, index=True)

    # Chave de idempotência enviada pela automação externa.
    external_id = Column(String(255), nullable=False, unique=True, index=True)

    # Número CNJ do processo (normalizado: apenas dígitos).
    cnj_number = Column(String(32), nullable=False, index=True)

    # ID do processo no Legal One (preenchido após resolução).
    lawsuit_id = Column(Integer, nullable=True, index=True)

    # Escritório responsável pelo processo no L1 (derivado do lawsuit).
    office_id = Column(Integer, nullable=True, index=True)

    # Dados da capa do processo (recebidos pela API externa).
    capa_json = Column(JSON, nullable=False)

    # Íntegra do processo em blocos com data (recebida pela API externa).
    integra_json = Column(JSON, nullable=False)

    # Metadata livre enviada pela automação externa (ex.: source, versão).
    metadata_json = Column(JSON, nullable=True)

    # Caminho relativo do PDF dentro do volume persistente
    # (ex.: "2026/04/20/uuid.pdf"). None após cleanup pós-upload GED.
    pdf_path = Column(String(512), nullable=True)
    pdf_sha256 = Column(String(64), nullable=True)
    pdf_bytes = Column(BigInteger, nullable=True)
    pdf_filename_original = Column(String(255), nullable=True)

    # Estado do intake — ver constantes no topo.
    status = Column(
        String,
        nullable=False,
        default=INTAKE_STATUS_RECEIVED,
        index=True,
    )

    # Referência ao batch de classificação (quando aplicável).
    classification_batch_id = Column(
        Integer,
        ForeignKey("prazo_inicial_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Resultado do upload no GED do L1.
    ged_document_id = Column(Integer, nullable=True)
    ged_uploaded_at = Column(DateTime(timezone=True), nullable=True)

    # Última mensagem de erro (pra exibir na UI quando em estado ERRO_*).
    error_message = Column(Text, nullable=True)

    # Classificação preliminar feita pela IA (Fase 3c).
    # natureza_processo: COMUM | JUIZADO | AGRAVO_INSTRUMENTO | OUTRO.
    # Roteia o conjunto de perguntas aplicáveis e entra como filtro no
    # template matching (ver template_matching_service).
    natureza_processo = Column(String(64), nullable=True, index=True)
    # produto: SUPERENDIVIDAMENTO | CREDCESTA | ... | OUTRO. INFORMATIVO
    # apenas — não afeta classificação nem matching de templates. Usado
    # em relatórios e filtros da UI.
    produto = Column(String(64), nullable=True, index=True)

    # Preenchidos apenas quando natureza_processo = AGRAVO_INSTRUMENTO.
    # Extraídos pela IA da petição inicial pra ligar o agravo ao
    # processo de 1º grau (origem) sem o operador precisar abrir o PDF.
    agravo_processo_origem_cnj = Column(String(32), nullable=True)
    agravo_decisao_agravada_resumo = Column(Text, nullable=True)

    # Agregados calculados a partir de prazo_inicial_pedidos (Bloco E).
    # Ficam NULL até a primeira classificação; recalculados em cada
    # reprocessamento e em cada PATCH de pedido.
    #
    # Regra "menos favorável ao banco" em probabilidade_exito_global:
    # se QUALQUER pedido tem prob_perda=provavel → exito=remota.
    # Se a pior prob_perda entre pedidos é possivel → exito=possivel.
    # Se todos remota → exito=provavel.
    valor_total_pedido = Column(Numeric(14, 2), nullable=True)
    valor_total_estimado = Column(Numeric(14, 2), nullable=True)
    aprovisionamento_sugerido = Column(Numeric(14, 2), nullable=True)
    probabilidade_exito_global = Column(String(16), nullable=True)
    analise_estrategica = Column(Text, nullable=True)

    # Quem tratou finalisticamente o intake — preenchido quando o operador
    # confirma agendamentos OU finaliza sem providência (pin011). NULL
    # enquanto o intake estiver em fluxo. Usado pra "Tratado por: <nome>"
    # na listagem do HITL e pra filtro por operador.
    treated_by_user_id = Column(Integer, nullable=True, index=True)
    treated_by_email = Column(String(255), nullable=True)
    treated_by_name = Column(String(255), nullable=True)
    treated_at = Column(DateTime(timezone=True), nullable=True)

    # Disparo desacoplado de GED + cancel da legacy task (pin012, Onda 3 #5).
    # Após confirmar/finalizar, o intake fica AGENDADO ou
    # CONCLUIDO_SEM_PROVIDENCIA com `dispatch_pending=True`. O disparo
    # acontece via botão manual ("Disparar agora") na Tratamento Web ou
    # via worker periódico configurável. Quando GED+enqueue cancel
    # completam com sucesso, vira False + dispatched_at preenchido.
    dispatch_pending = Column(
        Boolean, nullable=False, server_default=text("false"), index=True,
    )
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    dispatch_error_message = Column(Text, nullable=True)

    # Origem do intake (pin016) — EXTERNAL_API ou USER_UPLOAD. NOT NULL
    # com default no servidor; backfill da migration coloca todos os
    # registros antigos como EXTERNAL_API.
    source = Column(
        String(32),
        nullable=False,
        server_default=INTAKE_SOURCE_EXTERNAL_API,
        index=True,
    )
    # Nome livre do provedor externo (quando aplicável). Útil quando
    # tivermos múltiplos provedores de API com chaves distintas.
    source_provider_name = Column(String(255), nullable=True)

    # Quem submeteu (USER_UPLOAD only — NULL pra EXTERNAL_API). Filtro
    # "Minha fila" usa submitted_by_user_id. NÃO confundir com
    # treated_by_* (PIN011) — quem TRATOU é quem confirmou no HITL.
    submitted_by_user_id = Column(Integer, nullable=True, index=True)
    submitted_by_email = Column(String(255), nullable=True)
    submitted_by_name = Column(String(255), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)

    # Status da extração mecânica do PDF (USER_UPLOAD only). Quando
    # pdf_extraction_failed=True a UI exibe badge "Sem texto extraível —
    # classificar manualmente"; o operador preenche capa/sugestões à mão
    # no HITL. Pra USER_UPLOAD bem-sucedido: extractor_used identifica
    # qual extractor rodou (ex.: "pje_tjba_v1"), extraction_confidence
    # é "high"/"partial"/"low".
    pdf_extraction_failed = Column(
        Boolean, nullable=False, server_default=text("false"),
    )
    extractor_used = Column(String(64), nullable=True)
    extraction_confidence = Column(String(16), nullable=True)

    # Habilitação MDR (procuração + carta de preposição) — preservada
    # mesmo após extração do processo bem-sucedida porque vai pro GED L1
    # e AJUS (memory project_pin_habilitacao_ajus.md). Distinta do
    # pdf_path (processo na íntegra), que é descartado após extração ok.
    habilitacao_pdf_path = Column(String(512), nullable=True)
    habilitacao_pdf_sha256 = Column(String(64), nullable=True)
    habilitacao_pdf_bytes = Column(BigInteger, nullable=True)
    habilitacao_pdf_filename_original = Column(String(255), nullable=True)

    received_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relacionamentos
    sugestoes = relationship(
        "PrazoInicialSugestao",
        back_populates="intake",
        cascade="all, delete-orphan",
    )
    pedidos = relationship(
        "PrazoInicialPedido",
        back_populates="intake",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    classification_batch = relationship(
        "PrazoInicialBatch",
        back_populates="intakes",
        foreign_keys=[classification_batch_id],
    )


class PrazoInicialSugestao(Base):
    """
    Sugestão de agendamento gerada pela IA — N por intake (um processo
    pode ter contestação + audiência + manifestação avulsa simultâneas).
    """

    __tablename__ = "prazo_inicial_sugestoes"

    id = Column(Integer, primary_key=True, index=True)

    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Tipo alto nível do prazo/evento identificado pela IA.
    # Valores permitidos serão definidos em prazos_iniciais_taxonomy.py
    # (sessão dedicada). Deliberadamente string, não enum de coluna.
    tipo_prazo = Column(String(64), nullable=False, index=True)
    subtipo = Column(String(128), nullable=True)

    # Dados de prazo (quando aplicável).
    data_base = Column(Date, nullable=True)
    prazo_dias = Column(Integer, nullable=True)
    prazo_tipo = Column(String(16), nullable=True)  # "util" | "corrido"
    data_final_calculada = Column(Date, nullable=True)

    # Prazo fatal (o mais restritivo conhecido, considerando PI + últimas
    # decisões). `fundamentacao` traz o artigo do CPC / súmula / trecho
    # da decisão. `base_decisao` resume a movimentação que originou.
    prazo_fatal_data = Column(Date, nullable=True)
    prazo_fatal_fundamentacao = Column(Text, nullable=True)
    prazo_base_decisao = Column(Text, nullable=True)

    # Dados de audiência (quando aplicável).
    audiencia_data = Column(Date, nullable=True)
    audiencia_hora = Column(Time, nullable=True)
    audiencia_link = Column(Text, nullable=True)

    # Rastreabilidade da decisão da IA.
    confianca = Column(String(16), nullable=True)  # alta | media | baixa
    justificativa = Column(Text, nullable=True)

    # Sugestão de responsável (L1 user id) — pode ser preenchido pela IA
    # ou derivado de regras de negócio.
    responsavel_sugerido_id = Column(Integer, nullable=True)

    # Mapeamento Legal One — preenchido pelo suggestion_service com base
    # na taxonomia.
    task_type_id = Column(Integer, nullable=True)
    task_subtype_id = Column(Integer, nullable=True)

    # Payload pronto para enviar ao L1 (editável pelo operador antes
    # da confirmação).
    payload_proposto = Column(JSON, nullable=True)

    # Revisão humana.
    review_status = Column(
        String(16),
        nullable=False,
        default=SUGESTAO_REVIEW_PENDING,
        index=True,
    )
    reviewed_by_email = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # Referência à tarefa criada no L1 após agendamento confirmado.
    created_task_id = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    intake = relationship("PrazoInicialIntake", back_populates="sugestoes")


class PrazoInicialBatch(Base):
    """
    Lote enviado à Anthropic Messages Batches API para classificação.
    Espelha o modelo de publicações (PublicationBatchClassification).
    """

    __tablename__ = "prazo_inicial_batches"

    id = Column(Integer, primary_key=True, index=True)

    # ID do lote na Anthropic (ex: "msgbatch_...").
    anthropic_batch_id = Column(String, nullable=True, index=True)

    # Estado interno.
    status = Column(
        String,
        nullable=False,
        default=PIN_BATCH_STATUS_SUBMITTED,
        index=True,
    )
    anthropic_status = Column(String, nullable=True)

    # Contadores (atualizados em cada polling).
    total_records = Column(Integer, nullable=False, default=0)
    succeeded_count = Column(Integer, default=0)
    errored_count = Column(Integer, default=0)
    expired_count = Column(Integer, default=0)
    canceled_count = Column(Integer, default=0)

    # IDs dos intakes incluídos neste batch (JSON array).
    intake_ids = Column(JSON, nullable=True)

    # Mapeamento custom_id → intake_id (útil no apply).
    batch_metadata = Column(JSON, nullable=True)

    model_used = Column(String, nullable=True)
    requested_by_email = Column(String, nullable=True, index=True)

    # URL de download dos resultados (presente quando ended).
    results_url = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    intakes = relationship(
        "PrazoInicialIntake",
        back_populates="classification_batch",
        foreign_keys="PrazoInicialIntake.classification_batch_id",
    )

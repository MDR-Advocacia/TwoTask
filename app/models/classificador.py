"""Models do modulo Classificador (diagnostico de carteira).

Modulo paralelo a Prazos Iniciais — recebe carteira inteira (xlsx / API /
import dos intakes de prazos_iniciais), refresca capa via L1, classifica
com prompt proprio (taxonomy v2 + PCOND + prob_exito + analise estrategica)
e gera relatorios pra cliente final (XLSX multi-aba, PDF executivo, painel).

Tabelas:
- ClassificadorLote: cabecalho do diagnostico
- ClassificadorProcesso: snapshot por processo (com FK opcional pro
  intake original em prazo_inicial_intakes — rastreabilidade)
- ClassificadorPedido: 1:N por processo (espelho de prazo_inicial_pedidos)
- ClassificadorRelatorio: relatorios gerados (XLSX, PDF) — segue padrao
  de base_processual_export (async com status PENDENTE/PROCESSANDO/...)

Snapshot: relatorio e' documento historico imutavel. Dados sao copiados
no momento da captura, NAO linkados via JOIN. Refresh L1 acontece antes
do snapshot pra garantir "extremamente atualizado no momento da captura".

Ver memory project_classificador.md pra decisoes-chave.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ─── Status do lote ───────────────────────────────────────────────────
LOTE_STATUS_RASCUNHO = "RASCUNHO"
LOTE_STATUS_CAPTURANDO_L1 = "CAPTURANDO_L1"
LOTE_STATUS_READY = "PRONTO_PARA_CLASSIFICAR"
LOTE_STATUS_CLASSIFYING = "CLASSIFICANDO"
LOTE_STATUS_CLASSIFIED = "CLASSIFICADO"
LOTE_STATUS_ERROR = "ERRO"
LOTE_STATUS_CANCELLED = "CANCELADO"

LOTE_STATUSES_VALID = frozenset({
    LOTE_STATUS_RASCUNHO,
    LOTE_STATUS_CAPTURANDO_L1,
    LOTE_STATUS_READY,
    LOTE_STATUS_CLASSIFYING,
    LOTE_STATUS_CLASSIFIED,
    LOTE_STATUS_ERROR,
    LOTE_STATUS_CANCELLED,
})

# ─── Status do processo individual ────────────────────────────────────
PROC_STATUS_PENDENTE = "PENDENTE"
PROC_STATUS_CAPTURANDO_L1 = "CAPTURANDO_L1"
PROC_STATUS_READY = "PRONTO_PARA_CLASSIFICAR"
PROC_STATUS_CLASSIFIED = "CLASSIFICADO"
PROC_STATUS_ERROR_CAPTURE = "ERRO_CAPTURA"
PROC_STATUS_ERROR_CLASSIFICATION = "ERRO_CLASSIFICACAO"

PROC_STATUSES_VALID = frozenset({
    PROC_STATUS_PENDENTE,
    PROC_STATUS_CAPTURANDO_L1,
    PROC_STATUS_READY,
    PROC_STATUS_CLASSIFIED,
    PROC_STATUS_ERROR_CAPTURE,
    PROC_STATUS_ERROR_CLASSIFICATION,
})

# ─── Source por processo ──────────────────────────────────────────────
SOURCE_PRAZOS_INICIAIS = "PRAZOS_INICIAIS"
SOURCE_UPLOAD_XLSX = "UPLOAD_XLSX"
SOURCE_API_JSON = "API_JSON"

SOURCES_VALID = frozenset({
    SOURCE_PRAZOS_INICIAIS,
    SOURCE_UPLOAD_XLSX,
    SOURCE_API_JSON,
})

# ─── Polo ─────────────────────────────────────────────────────────────
POLO_AUTOR = "autor"
POLO_REU = "reu"
POLO_AMBOS = "ambos"

# ─── Relatorio ────────────────────────────────────────────────────────
REL_FORMAT_XLSX = "XLSX"
REL_FORMAT_PDF = "PDF"

REL_FORMATS_VALID = frozenset({REL_FORMAT_XLSX, REL_FORMAT_PDF})

REL_STATUS_PENDENTE = "PENDENTE"
REL_STATUS_PROCESSANDO = "PROCESSANDO"
REL_STATUS_PRONTO = "PRONTO"
REL_STATUS_FALHOU = "FALHOU"

REL_STATUSES_VALID = frozenset({
    REL_STATUS_PENDENTE,
    REL_STATUS_PROCESSANDO,
    REL_STATUS_PRONTO,
    REL_STATUS_FALHOU,
})

# ─── Status do batch Anthropic (espelhado do PI) ──────────────────────
BATCH_STATUS_SUBMITTED = "ENVIADO"
BATCH_STATUS_IN_PROGRESS = "EM_PROCESSAMENTO"
BATCH_STATUS_READY = "PRONTO"
BATCH_STATUS_APPLIED = "APLICADO"
BATCH_STATUS_FAILED = "FALHA"
BATCH_STATUS_CANCELLED = "CANCELADO"

BATCH_STATUSES_VALID = frozenset({
    BATCH_STATUS_SUBMITTED,
    BATCH_STATUS_IN_PROGRESS,
    BATCH_STATUS_READY,
    BATCH_STATUS_APPLIED,
    BATCH_STATUS_FAILED,
    BATCH_STATUS_CANCELLED,
})

# ─── Confianca da extracao mecanica (espelhado do PI) ─────────────────
EXTRACTION_CONFIDENCE_HIGH = "high"
EXTRACTION_CONFIDENCE_PARTIAL = "partial"
EXTRACTION_CONFIDENCE_LOW = "low"


class ClassificadorLote(Base):
    """Cabecalho de 1 "diagnostico" de carteira.

    snapshot_at = momento em que o operador clicou "criar lote". A partir
    desse instante, todo dado do lote e' frozen (apesar do refresh L1
    poder demorar minutos depois).
    """

    __tablename__ = "classificador_lote"

    id = Column(Integer, primary_key=True, index=True)

    nome = Column(String(255), nullable=False)
    cliente_nome = Column(String(255), nullable=True)
    descricao = Column(Text, nullable=True)

    status = Column(
        String(32),
        nullable=False,
        default=LOTE_STATUS_RASCUNHO,
        server_default=LOTE_STATUS_RASCUNHO,
    )

    # Composicao do lote por fonte: {"PRAZOS_INICIAIS": 300, "UPLOAD_XLSX": 100}
    source_summary = Column(JSON, nullable=True)
    # Filtros aplicados no /from-prazos-iniciais (auditavel)
    filtros_aplicados = Column(JSON, nullable=True)

    # Agregados desnormalizados (atualizados quando classificacao termina)
    total_processos = Column(Integer, nullable=False, default=0, server_default="0")
    total_processos_capturados = Column(Integer, nullable=False, default=0, server_default="0")
    total_processos_classificados = Column(Integer, nullable=False, default=0, server_default="0")
    total_processos_com_erro = Column(Integer, nullable=False, default=0, server_default="0")
    valor_total_causa = Column(Numeric(18, 2), nullable=True)
    valor_total_estimado = Column(Numeric(18, 2), nullable=True)
    pcond_total = Column(Numeric(18, 2), nullable=True)
    prob_exito_medio = Column(Numeric(5, 4), nullable=True)

    # Analise estrategica agregada da carteira (gerada pela IA no fim)
    analise_estrategica_carteira = Column(Text, nullable=True)

    # Timestamps por fase
    snapshot_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    captura_l1_started_at = Column(DateTime(timezone=True), nullable=True)
    captura_l1_finished_at = Column(DateTime(timezone=True), nullable=True)
    classificacao_started_at = Column(DateTime(timezone=True), nullable=True)
    classificacao_finished_at = Column(DateTime(timezone=True), nullable=True)

    error_message = Column(Text, nullable=True)

    created_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relacionamentos
    processos = relationship(
        "ClassificadorProcesso",
        back_populates="lote",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relatorios = relationship(
        "ClassificadorRelatorio",
        back_populates="lote",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClassificadorProcesso(Base):
    """Snapshot por processo dentro de um lote.

    data_captura_l1 = quando a capa foi puxada da L1 (pode ser diferente
    de snapshot_at do lote em ate' alguns minutos). Vai pra capa do PDF
    pra cliente saber a frescor do dado.

    source_intake_id e' FK opcional pra rastreabilidade (se o processo
    veio do fluxo de Prazos Iniciais). Mesmo que o intake seja deletado,
    o snapshot continua valido (ON DELETE SET NULL).
    """

    __tablename__ = "classificador_processo"

    id = Column(Integer, primary_key=True, index=True)

    lote_id = Column(
        Integer,
        ForeignKey("classificador_lote.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Fonte do dado (por processo, nao por lote — mistura ok)
    source = Column(String(32), nullable=False)
    # Rastreabilidade pro intake original. SET NULL preserva snapshot.
    source_intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Identificacao
    cnj_number = Column(String(64), nullable=True, index=True)
    lawsuit_id = Column(Integer, nullable=True)
    external_id = Column(String(128), nullable=True)

    # Capa (snapshot da L1)
    capa_json = Column(JSON, nullable=True)
    polo_ativo = Column(JSON, nullable=True)
    polo_passivo = Column(JSON, nullable=True)
    natureza_processo = Column(String(32), nullable=True)
    produto = Column(String(128), nullable=True)

    # Patrocinio (snapshot do calculo de _materialize_patrocinio)
    patrocinio_json = Column(JSON, nullable=True)

    # ─── PDF storage + extracao mecanica (cla002) ────────────────────
    # PDF original do robo (ou upload manual). pdf_sha256 e' o
    # identificador estavel pra cache/dedup.
    pdf_path = Column(String(512), nullable=True)
    pdf_sha256 = Column(String(64), nullable=True, index=True)
    pdf_bytes = Column(BigInteger, nullable=True)
    pdf_filename_original = Column(String(255), nullable=True)

    # Resultado da extracao mecanica (espelho do PI ExtractionResult)
    integra_json = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    pdf_extraction_failed = Column(
        Boolean, nullable=False, default=False, server_default="false",
    )
    extractor_used = Column(String(64), nullable=True)
    extraction_confidence = Column(String(16), nullable=True)

    # FK pro batch corrente (NULL ate' classificar). cla002.
    classification_batch_id = Column(
        Integer,
        ForeignKey("classificador_batch.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Resposta CRUA da IA — guardada inteira pra auditoria + permite
    # rerodar materializacao sem chamar batch de novo se mudar schema
    classificacao_response_json = Column(JSON, nullable=True)

    # Contestacao existente — espelho do bloco do PI, materializado
    # pra query rapida no relatorio (quem contestou pelo Master, etc.)
    contestacao_existente_json = Column(JSON, nullable=True)

    # Resultado da classificacao (Classificador, taxonomy v2)
    categoria_id = Column(
        Integer,
        ForeignKey("classification_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    subcategoria_id = Column(
        Integer,
        ForeignKey("classification_subcategories.id", ondelete="SET NULL"),
        nullable=True,
    )
    polo = Column(String(16), nullable=True)

    valor_estimado = Column(Numeric(18, 2), nullable=True)
    pcond_sugerido = Column(Numeric(18, 2), nullable=True)
    # 0.0 a 1.0
    prob_exito = Column(Numeric(5, 4), nullable=True)
    justificativa = Column(Text, nullable=True)
    analise_estrategica = Column(Text, nullable=True)
    # 0.0 a 1.0
    confianca = Column(Numeric(5, 4), nullable=True)

    # Status + erros
    status = Column(
        String(32),
        nullable=False,
        default=PROC_STATUS_PENDENTE,
        server_default=PROC_STATUS_PENDENTE,
    )
    error_message = Column(Text, nullable=True)

    # Timestamps
    data_captura_l1 = Column(DateTime(timezone=True), nullable=True)
    data_classificacao = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relacionamentos
    lote = relationship("ClassificadorLote", back_populates="processos")
    pedidos = relationship(
        "ClassificadorPedido",
        back_populates="processo",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClassificadorPedido(Base):
    """1:N por processo. Estrutura espelho de prazo_inicial_pedidos.

    Aprovisionamento segue CPC 25 / IAS 37 (remota=0, possivel=0, provavel=valor_estimado).
    """

    __tablename__ = "classificador_pedido"

    __table_args__ = (
        CheckConstraint(
            "probabilidade_perda IS NULL OR probabilidade_perda IN ('remota', 'possivel', 'provavel')",
            name="ck_classificador_pedido_prob_perda",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    processo_id = Column(
        Integer,
        ForeignKey("classificador_processo.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    tipo_pedido = Column(String(64), nullable=False, index=True)
    natureza = Column(String(64), nullable=True)
    valor_indicado = Column(Numeric(14, 2), nullable=True)
    valor_estimado = Column(Numeric(14, 2), nullable=True)
    fundamentacao_valor = Column(Text, nullable=True)
    probabilidade_perda = Column(String(16), nullable=True)
    aprovisionamento = Column(Numeric(14, 2), nullable=True)
    fundamentacao_risco = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    processo = relationship("ClassificadorProcesso", back_populates="pedidos")


class ClassificadorRelatorio(Base):
    """Relatorios gerados (XLSX, PDF). Async, padrao base_processual_export.

    Multiplos relatorios podem ser gerados pro mesmo lote (XLSX + PDF +
    variantes futuras). file_path aponta pra volume persistente.
    """

    __tablename__ = "classificador_relatorio"

    __table_args__ = (
        CheckConstraint(
            "formato IN ('XLSX', 'PDF')",
            name="ck_classificador_relatorio_formato",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    lote_id = Column(
        Integer,
        ForeignKey("classificador_lote.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    formato = Column(String(16), nullable=False)
    status = Column(
        String(32),
        nullable=False,
        default=REL_STATUS_PENDENTE,
        server_default=REL_STATUS_PENDENTE,
    )

    file_path = Column(String(512), nullable=True)
    file_bytes = Column(Integer, nullable=True)
    file_sha256 = Column(String(64), nullable=True)

    params_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    requested_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    lote = relationship("ClassificadorLote", back_populates="relatorios")


class ClassificadorBatch(Base):
    """Rastreabilidade do batch Anthropic Messages Batches API.

    Espelho de PrazoInicialBatch, adaptado pro modulo Classificador.
    1 row por submit (multiplos por lote — re-run, retry).
    """

    __tablename__ = "classificador_batch"

    id = Column(Integer, primary_key=True, index=True)

    lote_id = Column(
        Integer,
        ForeignKey("classificador_lote.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # IDs externos (Anthropic) + status retornado pela API
    anthropic_batch_id = Column(String(128), nullable=True, index=True)
    anthropic_status = Column(String(32), nullable=True)

    # Status local — controle do nosso lado (espelho do PI)
    status = Column(
        String(32),
        nullable=False,
        default=BATCH_STATUS_SUBMITTED,
        server_default=BATCH_STATUS_SUBMITTED,
        index=True,
    )

    # Lista de processo_ids do lote incluidos no batch + mapping custom_id
    processo_ids = Column(JSON, nullable=True)
    batch_metadata = Column(JSON, nullable=True)

    # Contadores espelhados de request_counts da Anthropic
    total_records = Column(Integer, nullable=False, default=0, server_default="0")
    succeeded_count = Column(Integer, nullable=False, default=0, server_default="0")
    errored_count = Column(Integer, nullable=False, default=0, server_default="0")
    expired_count = Column(Integer, nullable=False, default=0, server_default="0")
    canceled_count = Column(Integer, nullable=False, default=0, server_default="0")

    model_used = Column(String(128), nullable=True)
    results_url = Column(String(1024), nullable=True)
    error_message = Column(Text, nullable=True)

    requested_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    requested_by_email = Column(String(255), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

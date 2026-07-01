"""
Modelos do módulo "Análise Recursal" (dentro de Prazos Processuais).

O operador sobe o PDF de um processo na íntegra (nomeado pelo número do
processo). Reusamos o motor de extração mecânica de Prazos Iniciais
(`pdf_extractor.extract`) — determinístico, sem IA — para obter
`capa_json` + `integra_json`, e então UMA chamada Sonnet (via Batches API)
emite o veredito de viabilidade recursal. O custo do preparo é calculado
de forma DETERMINÍSTICA por lookup na tabela de custas por estado
(`recursal_custas`), nunca pela IA.

Tabelas
-------
analise_recursal         → 1 linha por PDF de processo subido
analise_recursal_batches → lotes enviados à Anthropic (rastreabilidade)
recursal_custas          → tabela de custas por UF × tipo de recurso
                           (preparo = % do valor da causa + fixo, com
                           piso/teto, + porte) — alimentada pelo operador.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
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


# ─── Status da análise ────────────────────────────────────────────────
# Ciclo de vida (feliz): RECEBIDO → EM_ANALISE → ANALISADO
#   RECEBIDO    → PDF subido + extração mecânica OK, aguardando lote
#   EM_ANALISE  → incluído num batch Anthropic em processamento
#   ANALISADO   → veredito aplicado (+ custo calculado)
#   ERRO_ANALISE→ falha ao processar/parsear o resultado da IA
#   SEM_TEXTO   → PDF escaneado/sem texto extraível (pdfplumber < 50 chars):
#                 não dá pra analisar automaticamente; operador trata fora.
RCR_STATUS_RECEBIDO = "RECEBIDO"
RCR_STATUS_EM_ANALISE = "EM_ANALISE"
RCR_STATUS_ANALISADO = "ANALISADO"
RCR_STATUS_ERRO = "ERRO_ANALISE"
RCR_STATUS_SEM_TEXTO = "SEM_TEXTO"

# ─── Status do batch (espelha PrazoInicialBatch) ──────────────────────
RCR_BATCH_STATUS_SUBMITTED = "ENVIADO"
RCR_BATCH_STATUS_IN_PROGRESS = "EM_PROCESSAMENTO"
RCR_BATCH_STATUS_READY = "PRONTO"
RCR_BATCH_STATUS_APPLIED = "APLICADO"
RCR_BATCH_STATUS_FAILED = "FALHA"

# ─── Domínios do veredito (espelham o schema Pydantic) ────────────────
RESULTADO_DECISAO_VALIDOS = {"PROCEDENTE", "IMPROCEDENTE", "PARCIAL", "EXTINTO"}
TIPO_DECISAO_VALIDOS = {"SENTENCA", "ACORDAO", "DECISAO_INTERLOCUTORIA"}
PROBABILIDADE_REVERSAO_VALIDOS = {"REMOTA", "POSSIVEL", "PROVAVEL"}
RECORRER_VALIDOS = {"SIM", "NAO", "LIMITROFE"}
TIPO_RECURSO_VALIDOS = {"APELACAO", "RECURSO_INOMINADO", "AGRAVO", "RESP", "RE"}
CONFIANCA_VALIDOS = {"ALTA", "MEDIA", "BAIXA"}


class AnaliseRecursal(Base):
    """Uma análise de viabilidade recursal de um processo subido pelo operador."""

    __tablename__ = "analise_recursal"

    id = Column(Integer, primary_key=True, index=True)

    # Número do processo — vem do NOME do arquivo (operador nomeia o PDF
    # com o número do processo). `cnj_number` é o CNJ que o extractor
    # achou na capa (pode divergir/faltar; usado pra derivar UF).
    processo_numero = Column(String, nullable=False, index=True)
    cnj_number = Column(String, nullable=True, index=True)
    # UF do tribunal (derivada do CNJ estadual ou setada pelo operador) —
    # chave do lookup de custas.
    uf = Column(String, nullable=True, index=True)

    # Extração mecânica reusada de Prazos Iniciais.
    capa_json = Column(JSON, nullable=True)
    integra_json = Column(JSON, nullable=True)
    extractor_used = Column(String, nullable=True)
    extraction_confidence = Column(String, nullable=True)  # high|partial|low
    extraction_failed = Column(Boolean, nullable=False, default=False)

    pdf_sha256 = Column(String, nullable=True, index=True)
    pdf_filename_original = Column(String, nullable=True)
    pdf_bytes = Column(Integer, nullable=True)

    status = Column(
        String, nullable=False, default=RCR_STATUS_RECEBIDO, index=True
    )
    analysis_batch_id = Column(
        Integer, ForeignKey("analise_recursal_batches.id"), nullable=True, index=True
    )
    error_message = Column(Text, nullable=True)

    # ─── Identificação (cabeçalho/assunto do parecer) ─────────────────
    nome_autor = Column(String, nullable=True)
    cpf = Column(String, nullable=True)
    objeto = Column(String, nullable=True)        # ex.: "Negativa de Contratação"
    produto = Column(String, nullable=True)       # ex.: "Credcesta"
    tribunal = Column(String, nullable=True)      # ex.: "TJPE"

    # ─── Veredito + conteúdo do parecer (preenchido após o batch) ─────
    resultado_decisao = Column(String, nullable=True)       # PROCEDENTE|...
    tipo_decisao = Column(String, nullable=True)            # SENTENCA|ACORDAO|...
    resumo_topicos = Column(JSON, nullable=True)            # list[str] (determinações)
    destaque = Column(Text, nullable=True)                  # ex.: "não houve dano moral"
    fundamentacao_juiz = Column(Text, nullable=True)        # síntese do juízo
    # Contestação juntada COM documentos? (presença, não qualidade) — positivo.
    contestacao_com_documentos = Column(Boolean, nullable=True)
    pontos_analise = Column(JSON, nullable=True)            # list[str] ("observa-se que")
    probabilidade_reversao = Column(String, nullable=True)  # REMOTA|POSSIVEL|PROVAVEL
    recorrer = Column(String, nullable=True)                # SIM|NAO|LIMITROFE
    tipo_recurso = Column(String, nullable=True)            # APELACAO|AGRAVO|...
    fundamentacao = Column(Text, nullable=True)             # justificativa da conclusão
    valor_causa = Column(Numeric(14, 2), nullable=True)
    valor_condenacao = Column(String, nullable=True)        # texto ou "Ilíquido"
    data_intimacao = Column(Date, nullable=True)            # intimação/publicação da decisão
    prazo_fatal = Column(Date, nullable=True)               # +N dias úteis (computado)
    # Custo do preparo — DETERMINÍSTICO (lookup na tabela), não da IA.
    custo_estimado = Column(Numeric(14, 2), nullable=True)
    custo_detalhe = Column(JSON, nullable=True)             # breakdown do cálculo
    confianca = Column(String, nullable=True)               # ALTA|MEDIA|BAIXA

    # Auditoria.
    uploaded_by_user_id = Column(Integer, nullable=True)
    uploaded_by_email = Column(String, nullable=True, index=True)
    uploaded_by_name = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    analyzed_at = Column(DateTime(timezone=True), nullable=True)

    analysis_batch = relationship(
        "AnaliseRecursalBatch",
        back_populates="analises",
        foreign_keys=[analysis_batch_id],
    )


class AnaliseRecursalBatch(Base):
    """Lote enviado à Anthropic Messages Batches API (espelha PrazoInicialBatch)."""

    __tablename__ = "analise_recursal_batches"

    id = Column(Integer, primary_key=True, index=True)

    anthropic_batch_id = Column(String, nullable=True, index=True)

    status = Column(
        String, nullable=False, default=RCR_BATCH_STATUS_SUBMITTED, index=True
    )
    anthropic_status = Column(String, nullable=True)

    total_records = Column(Integer, nullable=False, default=0)
    succeeded_count = Column(Integer, default=0)
    errored_count = Column(Integer, default=0)
    expired_count = Column(Integer, default=0)
    canceled_count = Column(Integer, default=0)

    # IDs das análises incluídas neste batch (JSON array).
    analise_ids = Column(JSON, nullable=True)
    # Mapeamento custom_id → analise_id (útil no apply).
    batch_metadata = Column(JSON, nullable=True)

    model_used = Column(String, nullable=True)
    requested_by_email = Column(String, nullable=True, index=True)

    results_url = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)

    analises = relationship(
        "AnaliseRecursal",
        back_populates="analysis_batch",
        foreign_keys="AnaliseRecursal.analysis_batch_id",
    )


class RecursalCustaTabela(Base):
    """
    Tabela de custas do preparo recursal por UF × tipo de recurso.

    Preparo = clamp(valor_causa * percentual% + valor_fixo,
                    valor_minimo, valor_maximo) + porte_remessa_retorno.

    Alimentada pelo operador (a planilha de custas de cada estado).
    Enquanto vazia, `custo_estimado` da análise fica NULL.
    """

    __tablename__ = "recursal_custas"

    id = Column(Integer, primary_key=True, index=True)

    uf = Column(String, nullable=False, index=True)          # "BA", "SP", ...
    tribunal = Column(String, nullable=True)                 # "TJBA"
    tipo_recurso = Column(String, nullable=False, index=True)  # APELACAO|AGRAVO|...

    percentual = Column(Numeric(7, 4), nullable=False, default=0)  # % do valor da causa
    valor_fixo = Column(Numeric(14, 2), nullable=False, default=0)
    valor_minimo = Column(Numeric(14, 2), nullable=True)
    valor_maximo = Column(Numeric(14, 2), nullable=True)
    porte_remessa_retorno = Column(Numeric(14, 2), nullable=False, default=0)

    vigencia = Column(String, nullable=True)                 # ano ("2026")
    fundamentacao = Column(Text, nullable=True)              # base legal
    ativo = Column(Boolean, nullable=False, default=True, index=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

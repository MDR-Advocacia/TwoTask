"""
Análise de Patrocínio do intake — 1:1 com PrazoInicialIntake.

Disparada pelo classifier APENAS quando o polo passivo bate com alguma
vinculada Master. Não interfere em tasks (não cria PrazoInicialSugestao).
Existe pra rastrear a decisão de quem patrocina o caso (MDR / outro
escritório / condução interna) e a fila de devolução.

Fluxo:
1. IA preenche todos os campos exceto `review_status`/`reviewed_*`.
2. `review_status='pendente'`. Operador revisa no HITL.
3. PATCH /intakes/{id}/patrocinio:
   - aprovado: aceita decisão da IA sem alterar campos
   - editado:  operador alterou um ou mais campos da decisão
   - rejeitado: operador discordou — limpa decisão e flag pra reanálise
"""

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# ─── Decisão de patrocínio ────────────────────────────────────────
PATROCINIO_DECISAO_MDR = "MDR_ADVOCACIA"
PATROCINIO_DECISAO_OUTRO = "OUTRO_ESCRITORIO"
PATROCINIO_DECISAO_CONDUCAO_INTERNA = "CONDUCAO_INTERNA"

PATROCINIO_DECISOES_VALIDAS = frozenset({
    PATROCINIO_DECISAO_MDR,
    PATROCINIO_DECISAO_OUTRO,
    PATROCINIO_DECISAO_CONDUCAO_INTERNA,
})

PATROCINIO_DECISAO_LABELS = {
    PATROCINIO_DECISAO_MDR: "MDR Advocacia",
    PATROCINIO_DECISAO_OUTRO: "Outro escritório",
    PATROCINIO_DECISAO_CONDUCAO_INTERNA: "Condução interna",
}


# ─── Natureza da ação ─────────────────────────────────────────────
PATROCINIO_NATUREZA_CONSUMERISTA = "CONSUMERISTA"
PATROCINIO_NATUREZA_CIVIL_PUBLICA = "CIVIL_PUBLICA"
PATROCINIO_NATUREZA_INQUERITO_ADMINISTRATIVO = "INQUERITO_ADMINISTRATIVO"
PATROCINIO_NATUREZA_TRABALHISTA = "TRABALHISTA"
PATROCINIO_NATUREZA_OUTRO = "OUTRO"

PATROCINIO_NATUREZAS_VALIDAS = frozenset({
    PATROCINIO_NATUREZA_CONSUMERISTA,
    PATROCINIO_NATUREZA_CIVIL_PUBLICA,
    PATROCINIO_NATUREZA_INQUERITO_ADMINISTRATIVO,
    PATROCINIO_NATUREZA_TRABALHISTA,
    PATROCINIO_NATUREZA_OUTRO,
})


# ─── Status de revisão ────────────────────────────────────────────
PATROCINIO_REVIEW_PENDING = "pendente"
PATROCINIO_REVIEW_APPROVED = "aprovado"
PATROCINIO_REVIEW_EDITED = "editado"
PATROCINIO_REVIEW_REJECTED = "rejeitado"

PATROCINIO_REVIEW_STATUSES_VALIDOS = frozenset({
    PATROCINIO_REVIEW_PENDING,
    PATROCINIO_REVIEW_APPROVED,
    PATROCINIO_REVIEW_EDITED,
    PATROCINIO_REVIEW_REJECTED,
})


class PrazoInicialPatrocinio(Base):
    __tablename__ = "prazo_inicial_patrocinio"

    id = Column(Integer, primary_key=True, index=True)
    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    decisao = Column(String(32), nullable=False)
    outro_escritorio_nome = Column(String(255), nullable=True)
    outro_advogado_nome = Column(String(255), nullable=True)
    outro_advogado_oab = Column(String(32), nullable=True)
    outro_advogado_data_habilitacao = Column(Date, nullable=True)

    suspeita_devolucao = Column(
        Boolean, nullable=False, server_default=text("false"), index=True,
    )
    motivo_suspeita = Column(Text, nullable=True)
    natureza_acao = Column(String(32), nullable=True)

    polo_passivo_confirmado = Column(
        Boolean, nullable=False, server_default=text("true"),
    )
    polo_passivo_observacao = Column(Text, nullable=True)

    confianca = Column(String(16), nullable=True)  # alta | media | baixa
    fundamentacao = Column(Text, nullable=True)

    review_status = Column(
        String(16),
        nullable=False,
        server_default=PATROCINIO_REVIEW_PENDING,
        index=True,
    )
    reviewed_by_user_id = Column(Integer, nullable=True)
    reviewed_by_email = Column(String(255), nullable=True)
    reviewed_by_name = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    intake = relationship("PrazoInicialIntake", back_populates="patrocinio")

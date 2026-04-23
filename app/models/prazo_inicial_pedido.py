"""
Pedidos extraídos da petição inicial (N:1 com intake).

Cada pedido é uma "pretensão" da parte autora (ex.: danos morais,
repetição de indébito, obrigação de fazer, etc.). Para cada um, a IA
(Sonnet) preenche:

- `tipo_pedido`: código canônico da tabela `prazo_inicial_tipos_pedido`
  (ex.: "DANOS_MORAIS", "REPETICAO_INDEBITO_SIMPLES").
- `valor_indicado`: valor em reais que a PI pede (pode ser NULL em
  pedidos declaratórios ou quando a PI não especifica).
- `valor_estimado`: valor REALISTA de eventual condenação, baseado em
  jurisprudência do tema (não é o valor pedido — é a projeção da IA
  do que a corte provavelmente arbitraria se o banco perder).
- `probabilidade_perda`: (remota | possivel | provavel) da ótica do
  banco-réu. Segue CPC 25 / IAS 37.
- `aprovisionamento`: valor a provisionar segundo CPC 25:
    * remota   → 0
    * possivel → 0 (divulga em nota)
    * provavel → valor_estimado integral

As fundamentações são texto livre em português para auditoria pelo
operador no HITL.

Essa tabela nasce vazia. Só é populada quando um intake passa pela
classificação Sonnet (Bloco D2) ou quando o operador aciona
"Reanalisar" (Bloco F, pendente).
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


# Constantes da escala de probabilidade (CPC 25 / IAS 37).
PROB_PERDA_REMOTA = "remota"
PROB_PERDA_POSSIVEL = "possivel"
PROB_PERDA_PROVAVEL = "provavel"

PROB_PERDA_VALIDAS = frozenset({
    PROB_PERDA_REMOTA,
    PROB_PERDA_POSSIVEL,
    PROB_PERDA_PROVAVEL,
})

PROB_PERDA_LABELS = {
    PROB_PERDA_REMOTA: "Remota",
    PROB_PERDA_POSSIVEL: "Possível",
    PROB_PERDA_PROVAVEL: "Provável",
}

# Ranking pra decidir "menos favorável ao banco" quando compondo a
# classificação global do intake (Bloco E). Provável > Possível > Remota.
PROB_PERDA_RANK = {
    PROB_PERDA_REMOTA: 0,
    PROB_PERDA_POSSIVEL: 1,
    PROB_PERDA_PROVAVEL: 2,
}


class PrazoInicialPedido(Base):
    __tablename__ = "prazo_inicial_pedidos"

    __table_args__ = (
        CheckConstraint(
            f"probabilidade_perda IN ('{PROB_PERDA_REMOTA}', "
            f"'{PROB_PERDA_POSSIVEL}', '{PROB_PERDA_PROVAVEL}')",
            name="ck_prazo_inicial_pedidos_prob_perda",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    intake_id = Column(
        Integer,
        ForeignKey("prazo_inicial_intakes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Código canônico do tipo (não FK SQL — validamos por app porque os
    # tipos podem ser desativados via is_active=false sem apagar pedidos
    # históricos que já apontam pra eles).
    tipo_pedido = Column(String(64), nullable=False, index=True)

    # Natureza específica do pedido (redundante mas conveniente pra
    # filtros — copiada de `prazo_inicial_tipos_pedido.naturezas` no
    # momento da extração).  Pode ser NULL se a IA não conseguir inferir.
    natureza = Column(String(64), nullable=True)

    # Valores em reais, precisão de 2 casas decimais (padrão monetário).
    # Numeric(14, 2) suporta até R$ 999.999.999.999,99 — mais que suficiente.
    valor_indicado = Column(Numeric(14, 2), nullable=True)
    valor_estimado = Column(Numeric(14, 2), nullable=True)

    # Fundamentação textual — obrigatório pela IA, preenchido SEMPRE.
    fundamentacao_valor = Column(Text, nullable=True)

    probabilidade_perda = Column(String(16), nullable=True, index=True)

    # Calculado pela IA aplicando CPC 25 no valor_estimado + prob.
    aprovisionamento = Column(Numeric(14, 2), nullable=True)

    fundamentacao_risco = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    intake = relationship("PrazoInicialIntake", back_populates="pedidos")

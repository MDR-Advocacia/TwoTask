"""
Tipos de pedido para análise estratégica da petição inicial.

Semeada via migration com 46 tipos cobrindo as principais naturezas
(Cível, Consumidor, Trabalhista, Previdenciária, Tributária, etc.).
A IA (Sonnet) extrai da petição inicial quais pedidos estão presentes,
e para cada um associa valor indicado, valor estimado realista,
probabilidade de perda (remota/possível/provável) e aprovisionamento
sugerido segundo CPC 25 / IAS 37.

A tabela é admin-editável (is_active toggle) para que o escritório
possa desativar tipos que não usa sem deploy. O campo `naturezas` é
string com ";" como separador — não normalizamos em tabela N:N porque
naturezas são enum fixo e pequenas (8 valores) — SQL LIKE resolve.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.session import Base


class PrazoInicialTipoPedido(Base):
    __tablename__ = "prazo_inicial_tipos_pedido"

    id = Column(Integer, primary_key=True, index=True)

    # Chave estável (snake_case MAIÚSCULO) usada no banco e no prompt.
    # A humanização para UI fica no campo `nome` abaixo, para NÃO depender
    # de dicionário de labels externo (aqui é ponto de extensão do cliente).
    codigo = Column(String, nullable=False, unique=True, index=True)

    # Nome humanizado exibido na UI e no prompt do Sonnet.
    nome = Column(String, nullable=False)

    # Naturezas aplicáveis (string separada por ";"). Vazio = aplica a
    # qualquer natureza. Valores canônicos: "Cível", "Consumidor",
    # "Trabalhista", "Previdenciária", "Tributária", "Administrativa",
    # "Constitucional", "Ambiental", "Penal".
    naturezas = Column(String, nullable=True)

    # Ordem de apresentação / triagem. Menor = aparece primeiro.
    display_order = Column(Integer, nullable=False, default=100)

    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

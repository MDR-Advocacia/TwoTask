"""
Cadastro das empresas vinculadas ao Banco Master.

Quando o polo passivo de um intake contém o CNPJ de uma vinculada ATIVA,
o motor de classificação executa a análise de Patrocínio (decisão entre
MDR Advocacia / Outro escritório / Condução interna), em paralelo às
sugestões de prazo.

Editável por admin. Seed inicial em pin018.
"""

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.db.session import Base


class MasterVinculada(Base):
    __tablename__ = "master_vinculadas"

    id = Column(Integer, primary_key=True, index=True)
    cnpj = Column(String(18), nullable=False, unique=True, index=True)
    nome = Column(String(255), nullable=False)
    estado = Column(String(2), nullable=True)
    ativo = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

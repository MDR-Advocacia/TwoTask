"""
Overrides de classificação por escritório.

Permite que cada escritório:
  - Exclua classificações que não se aplicam ao seu contexto
  - Adicione classificações customizadas (categoria + subcategoria)

Quando presentes, estes overrides são usados para:
  1. Filtrar a taxonomia no prompt do classificador IA
  2. Validar resultados de classificação
  3. Gerar templates de tarefa específicos
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class OfficeClassificationOverride(Base):
    """
    Cada registro representa uma regra de override para um escritório:
      - action='exclude': exclui a categoria/subcategoria da taxonomia do escritório
      - action='include_custom': adiciona uma classificação customizada
    """
    __tablename__ = "office_classification_overrides"
    __table_args__ = (
        UniqueConstraint(
            "office_external_id", "category", "subcategory", "action",
            name="uq_office_clf_override",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    office_external_id = Column(
        Integer,
        ForeignKey("legal_one_offices.external_id"),
        nullable=False,
        index=True,
    )

    # Classificação alvo
    category = Column(String, nullable=False)
    subcategory = Column(String, nullable=True)  # None = aplica a toda a categoria

    # Tipo de override
    action = Column(
        String, nullable=False, default="exclude"
    )  # "exclude" | "include_custom"

    # Para custom: descrição opcional de quando usar esta classificação
    custom_description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Relationships
    office = relationship(
        "LegalOneOffice",
        primaryjoin="OfficeClassificationOverride.office_external_id == LegalOneOffice.external_id",
        foreign_keys=[office_external_id],
    )

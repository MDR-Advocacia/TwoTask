"""Taxonomia de classificações — antes hardcoded em
`app/services/classifier/taxonomy.py:CLASSIFICATION_TREE`, agora persistida
em DB pra que o admin gerencie pela UI.

Cada categoria/subcategoria tem campos opcionais que enriquecem o prompt
da IA (description, default_polo, default_prazo_*, exemplo) — gerados via
Sonnet helper quando admin cadastra novo item, ou preenchidos manualmente.

Fallback de seguranca: quando DB esta vazio (migration nova ou reset),
o `taxonomy_service` cai pro CLASSIFICATION_TREE hardcoded — preserva
comportamento. Migration tax001 faz o seed inicial.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.session import Base


class ClassificationCategory(Base):
    __tablename__ = "classification_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False, unique=True, index=True)
    # Texto livre que descreve quando aplicar essa categoria. Usado pela
    # IA via build_taxonomy_text — quanto mais especifico, melhor.
    description = Column(Text, nullable=True)
    # Quando categoria nao tem subcategorias, esses campos ficam aqui
    # (ex.: "Provas", "Manifestacao das Partes"). Quando tem subs, ficam
    # vazios aqui e cada sub tem os seus.
    default_polo = Column(String(16), nullable=True)
    default_prazo_dias = Column(Integer, nullable=True)
    default_prazo_tipo = Column(String(16), nullable=True)  # 'util'|'corrido'
    default_prazo_fundamentacao = Column(Text, nullable=True)
    example_publication = Column(Text, nullable=True)
    example_response_json = Column(Text, nullable=True)  # JSON string

    display_order = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(
        Boolean, nullable=False, default=True, server_default="true",
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    subcategories = relationship(
        "ClassificationSubcategory",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="ClassificationSubcategory.display_order, ClassificationSubcategory.name",
    )


class ClassificationSubcategory(Base):
    __tablename__ = "classification_subcategories"
    __table_args__ = (
        UniqueConstraint("category_id", "name", name="uq_subcat_per_category"),
    )

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(
        Integer,
        ForeignKey("classification_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(160), nullable=False)

    description = Column(Text, nullable=True)
    default_polo = Column(String(16), nullable=True)
    default_prazo_dias = Column(Integer, nullable=True)
    default_prazo_tipo = Column(String(16), nullable=True)
    default_prazo_fundamentacao = Column(Text, nullable=True)
    example_publication = Column(Text, nullable=True)
    example_response_json = Column(Text, nullable=True)

    display_order = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(
        Boolean, nullable=False, default=True, server_default="true",
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    category = relationship("ClassificationCategory", back_populates="subcategories")

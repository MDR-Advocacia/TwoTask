"""
Feedback de classificação para melhoria contínua do classificador de publicações.

Dois tipos de feedback:
  - implicit: capturado automaticamente quando o operador reclassifica manualmente
  - explicit: operador clica no thumbs-down e informa a correção + nota

Os feedbacks são injetados como exemplos (few-shot) no prompt do classificador,
melhorando a assertividade ao longo do tempo.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class ClassificationFeedback(Base):
    __tablename__ = "classification_feedbacks"

    id = Column(Integer, primary_key=True, index=True)

    # Publicação de referência (para rastreabilidade e extração de texto)
    record_id = Column(
        Integer,
        ForeignKey("publicacao_registros.id"),
        nullable=False,
        index=True,
    )

    # Tipo de feedback
    feedback_type = Column(
        String, nullable=False, index=True,
    )  # "implicit" | "explicit"

    # O que o agente classificou (errado)
    original_category = Column(String, nullable=True)
    original_subcategory = Column(String, nullable=True)
    original_polo = Column(String, nullable=True)
    original_natureza = Column(String, nullable=True)

    # O que o operador corrigiu (certo)
    corrected_category = Column(String, nullable=False)
    corrected_subcategory = Column(String, nullable=True)
    corrected_polo = Column(String, nullable=True)
    corrected_natureza = Column(String, nullable=True)

    # Campos do feedback explícito
    error_type = Column(String, nullable=True)  # "category" | "subcategory" | "polo" | "natureza" | "multiple"
    user_note = Column(Text, nullable=True)  # Nota do operador (ex: "quando menciona embargante, sempre é Embargos")

    # Trecho representativo do texto da publicação (para injetar no prompt)
    text_excerpt = Column(Text, nullable=True)

    # Escritório (para feedback por escritório, se aplicável)
    office_external_id = Column(Integer, nullable=True, index=True)

    # Metadados
    created_by_email = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

"""
Feedback livre dos usuarios pra equipe (botao flutuante presente em
toda pagina autenticada). Categorizado pra agrupar bug/sugestao/duvida/
elogio/outro, com captura automatica de page_url e user_agent pra
ajudar reproducao.

O ciclo de vida e' simples:
- "novo": acabou de chegar, ainda nao tratado
- "lido": admin marcou que viu/leu
- "arquivado": admin terminou, esconde da listagem padrao

Nao deletamos feedbacks — historico e' valioso pra entender padroes ao
longo do tempo. Pra apagar de vez (LGPD/usuario removido), o ON DELETE
CASCADE da FK user_id se encarrega quando o LegalOneUser e' apagado.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.sql import func

from app.db.session import Base


# Categorias livres da UI. String em vez de enum SQL pra evitar migration
# toda vez que a equipe quiser adicionar uma nova. A UI valida o set.
FEEDBACK_CATEGORY_BUG = "bug"
FEEDBACK_CATEGORY_SUGGESTION = "sugestao"
FEEDBACK_CATEGORY_QUESTION = "duvida"
FEEDBACK_CATEGORY_PRAISE = "elogio"
FEEDBACK_CATEGORY_OTHER = "outro"

FEEDBACK_CATEGORIES_VALIDAS = frozenset({
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_SUGGESTION,
    FEEDBACK_CATEGORY_QUESTION,
    FEEDBACK_CATEGORY_PRAISE,
    FEEDBACK_CATEGORY_OTHER,
})

FEEDBACK_STATUS_NEW = "novo"
FEEDBACK_STATUS_READ = "lido"
FEEDBACK_STATUS_ARCHIVED = "arquivado"

FEEDBACK_STATUSES_VALIDOS = frozenset({
    FEEDBACK_STATUS_NEW,
    FEEDBACK_STATUS_READ,
    FEEDBACK_STATUS_ARCHIVED,
})


class UserFeedback(Base):
    __tablename__ = "user_feedbacks"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="CASCADE"),
        nullable=False,
    )

    category = Column(String(32), nullable=False)
    message = Column(Text, nullable=False)

    page_url = Column(String(500), nullable=True)
    user_agent = Column(String(500), nullable=True)

    status = Column(
        String(16), nullable=False, server_default=FEEDBACK_STATUS_NEW,
    )
    admin_note = Column(Text, nullable=True)
    reviewed_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )
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

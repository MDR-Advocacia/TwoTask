"""
Avisos broadcast emitidos pelo admin pra usuarios online (banner no
topo da app). Persistidos em duas tabelas:

- AdminNotice: o aviso em si (titulo + mensagem + janela starts/ends +
  severidade).
- AdminNoticeDismissal: marca quem ja fechou — combinacao de notice_id +
  user_id eh PK, garantindo idempotencia ("so aparece uma vez por user").

Aviso eh "ativo" quando starts_at <= now <= ends_at E nao existe linha
em dismissals pro (notice_id, user_id) atual. Polling de 30s no
frontend (componente AdminNoticeBar) chama GET /admin/notices/active
pra puxar a lista relevante pro usuario logado.
"""

from sqlalchemy import (
    Boolean,
    Column,
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


# Severidades validas — espelha o que a UI sabe estilizar (info/warning/danger).
NOTICE_SEVERITY_INFO = "info"
NOTICE_SEVERITY_WARNING = "warning"
NOTICE_SEVERITY_DANGER = "danger"

NOTICE_SEVERITIES_VALIDAS = frozenset({
    NOTICE_SEVERITY_INFO,
    NOTICE_SEVERITY_WARNING,
    NOTICE_SEVERITY_DANGER,
})


class AdminNotice(Base):
    __tablename__ = "admin_notices"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    severity = Column(String(16), nullable=False, server_default=NOTICE_SEVERITY_INFO)

    # require_ack=True -> aviso aparece como POP-UP bloqueante (modal) e so
    # some quando o usuario clica "Ciente". False (default) mantem o
    # comportamento de banner discreto no topo da app.
    require_ack = Column(Boolean, nullable=False, server_default=text("false"))

    starts_at = Column(DateTime(timezone=True), nullable=False)
    ends_at = Column(DateTime(timezone=True), nullable=False)

    created_by_user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    dismissals = relationship(
        "AdminNoticeDismissal",
        back_populates="notice",
        cascade="all, delete-orphan",
    )
    views = relationship(
        "AdminNoticeView",
        back_populates="notice",
        cascade="all, delete-orphan",
    )


class AdminNoticeDismissal(Base):
    __tablename__ = "admin_notice_dismissals"

    notice_id = Column(
        Integer,
        ForeignKey("admin_notices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dismissed_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

    notice = relationship("AdminNotice", back_populates="dismissals")


class AdminNoticeView(Base):
    """
    Registra IMPRESSAO: quem teve o aviso renderizado na tela (banner ou
    pop-up), independente de ter clicado "Ciente"/X. Diferente de
    AdminNoticeDismissal, que so marca quem fechou/confirmou.

    Assim "Visto por N" >= "Confirmado por M": pode haver quem viu o aviso
    mas nunca confirmou (fechou a aba, deixou o banner aberto, etc.).

    first_seen_at: primeira vez que o front reportou a impressao.
    last_seen_at:  ultima vez (atualizado quando o front reexibe).
    """

    __tablename__ = "admin_notice_views"

    notice_id = Column(
        Integer,
        ForeignKey("admin_notices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("legal_one_users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    first_seen_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    last_seen_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    notice = relationship("AdminNotice", back_populates="views")

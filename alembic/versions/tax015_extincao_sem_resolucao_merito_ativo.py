"""Polo ATIVO: adiciona 'Sentença de extinção sem resolução do mérito' em
'Decisão, Sentença e Extinção' e INATIVA a antiga 'Extinção por prescrição /
abandono / ausência de pressupostos'.

Decisao com operador 2026-06-05: o autor nao tinha uma sub limpa pra sentenca
de extincao SEM resolucao do merito (art. 485 CPC), que o passivo ja tem
('Sentença Extinção sem Resolução de Mérito'). A sub que existia no ativo
('Extinção por prescrição / abandono / ausência de pressupostos') embaralhava
naturezas diferentes — prescricao e extincao COM merito (art. 487 II),
abandono/pressupostos sao SEM merito (art. 485). Operador decidiu:
  - CRIAR 'Sentença de extinção sem resolução do mérito' (art. 485 geral).
  - INATIVAR a antiga (is_active=false) — fica dormente; registros antigos
    seguem visiveis, mas a IA nao usa mais. Se houver template amarrado nela
    em prod, recriar/remapear pro novo nome.

Idempotente. So vale pras classificacoes FUTURAS.

Revision ID: tax015
Revises: tax014
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax015"
down_revision: Union[str, None] = "tax014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAT_NAME = "Decisão, Sentença e Extinção"
_NEW_SUB = "Sentença de extinção sem resolução do mérito"
_OLD_SUB = "Extinção por prescrição / abandono / ausência de pressupostos"
# Subs sao alfabeticas na UI (2026-06-04), display_order e' so cosmetico.
_NEW_SUB_DISPLAY_ORDER = 7


def _cat_id(conn, cat_table):
    return conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _CAT_NAME)
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    cat_table = sa.table(
        "classification_categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
    )
    sub_table = sa.table(
        "classification_subcategories",
        sa.column("category_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("taxonomy_version", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )

    cat_id = _cat_id(conn, cat_table)
    if cat_id is None:
        raise RuntimeError(
            f"Categoria '{_CAT_NAME}' nao existe — tax006 (seed v2) precisa ter rodado antes."
        )

    # 1) Cria a sub nova (idempotente).
    already = conn.execute(
        sa.select(sub_table.c.category_id)
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _NEW_SUB)
    ).first()
    if already is None:
        conn.execute(
            sub_table.insert().values(
                category_id=cat_id,
                name=_NEW_SUB,
                taxonomy_version="v2",
                display_order=_NEW_SUB_DISPLAY_ORDER,
                is_active=True,
            )
        )

    # 2) Inativa a antiga (dormente; nao deleta pra preservar historico).
    conn.execute(
        sub_table.update()
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _OLD_SUB)
        .values(is_active=False)
    )

    try:
        from app.services.classifier.taxonomy import invalidate_taxonomy_cache
        invalidate_taxonomy_cache()
    except Exception:
        pass


def downgrade() -> None:
    conn = op.get_bind()
    cat_table = sa.table(
        "classification_categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
    )
    sub_table = sa.table(
        "classification_subcategories",
        sa.column("category_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    cat_id = _cat_id(conn, cat_table)
    if cat_id is None:
        return

    # Reverte: remove a nova e reativa a antiga.
    conn.execute(
        sub_table.delete()
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _NEW_SUB)
    )
    conn.execute(
        sub_table.update()
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _OLD_SUB)
        .values(is_active=True)
    )

    try:
        from app.services.classifier.taxonomy import invalidate_taxonomy_cache
        invalidate_taxonomy_cache()
    except Exception:
        pass

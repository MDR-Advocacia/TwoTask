"""Adiciona sub 'Distribuir Carta Precatória' em 'Manifestação do Credor /
Exequente' (polo ATIVO).

Decisao com operador 2026-06: BB Autor recebe intimacao recorrente pra
retirar / distribuir / comprovar Carta Precatoria (acompanhar diligencia no
juizo deprecado, recolher custas la) em cumprimento/execucao. A precatoria so
existia no lado PASSIVO ('Custas, Alvaras, Mandados e Atos Cartorarios /
Carta Precatoria / Rogatoria'); o ATIVO nao tinha cobertura, entao essas
publicacoes ficavam sem classificacao/template pro exequente.

Idempotente: rerun nao duplica (checa por nome antes de inserir; unique
constraint (category_id, name)).

Revision ID: tax012
Revises: pub003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax012"
down_revision: Union[str, None] = "pub003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAT_NAME = "Manifestação do Credor / Exequente"
_SUB_NAME = "Distribuir Carta Precatória"
# Subs existentes vao 0..7 + 'Petição de Provas — Autor'=99 (tax011).
# 8 deixa a nova logo apos as de diligencia, antes da Petição de Provas.
_SUB_DISPLAY_ORDER = 8


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

    cat_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _CAT_NAME)
    ).scalar()
    if cat_id is None:
        raise RuntimeError(
            f"Categoria '{_CAT_NAME}' nao existe — tax006 (seed v2) precisa ter rodado antes."
        )

    already = conn.execute(
        sa.select(sub_table.c.category_id)
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _SUB_NAME)
    ).first()
    if already is None:
        conn.execute(
            sub_table.insert().values(
                category_id=cat_id,
                name=_SUB_NAME,
                taxonomy_version="v2",
                display_order=_SUB_DISPLAY_ORDER,
                is_active=True,
            )
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
    )

    cat_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _CAT_NAME)
    ).scalar()
    if cat_id is not None:
        conn.execute(
            sub_table.delete()
            .where(sub_table.c.category_id == cat_id)
            .where(sub_table.c.name == _SUB_NAME)
        )

    try:
        from app.services.classifier.taxonomy import invalidate_taxonomy_cache
        invalidate_taxonomy_cache()
    except Exception:
        pass

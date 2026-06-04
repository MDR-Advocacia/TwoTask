"""Desmembra custas no polo ATIVO: adiciona sub 'Recolher custas iniciais' em
'Manifestação do Credor / Exequente'.

Decisao com operador 2026-06-04: a sub 'Recolher custas / diligencias' (polo
ativo, BB Autor) misturava custas INICIAIS (preparo/distribuicao — art. 290
CPC, 2% inicial sob pena de extincao/cancelamento da distribuicao) com custas
INTERMEDIARIAS (diligencia do oficial, buscas online, codigo 1007/1008,
precatoria, edital). Sao atos diferentes, com prazo/urgencia/risco distintos.
Desmembramos:

  - 'Recolher custas iniciais'      -> NOVA (este migration): preparo/inicio.
  - 'Recolher custas / diligencias' -> MANTIDA: todo o resto nao-inicial.

Mantemos o nome da existente de proposito, pra nao quebrar o template e os
feedbacks ja amarrados a ela (o match e' por string). O roteamento
inicial x intermediaria fica no ATIVO_SCHEME_ADDENDUM (prompts.py). Vale so
pras classificacoes FUTURAS — nao mexe em registro passado.

Idempotente: rerun nao duplica (checa por nome antes de inserir; unique
constraint (category_id, name)).

Revision ID: tax013
Revises: tax012
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax013"
down_revision: Union[str, None] = "tax012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CAT_NAME = "Manifestação do Credor / Exequente"
_SUB_NAME = "Recolher custas iniciais"
# Subs existentes vao 0..7 + 'Petição de Provas — Autor'=99 (tax011) +
# 'Distribuir Carta Precatória'=8 (tax012). 9 deixa a nova logo em seguida.
_SUB_DISPLAY_ORDER = 9


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

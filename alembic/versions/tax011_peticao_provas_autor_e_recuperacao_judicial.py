"""Adiciona sub 'Petição de Provas — Autor' em 'Manifestação do Credor / Exequente'
e cria cat nova 'Recuperação Judicial' polo='ambos' com 4 subs minimalistas.

Decisao com operador 2026-05-11 (continuacao da tax010): operador da
carteira ativa pediu cobertura de:

  1) Pet. de provas pelo lado do autor (especificacao/requerimento de
     provas a produzir). Cat alvo 'Manifestação do Credor / Exequente'
     ja existe (polo ativo, criada na tax006) com 8 subs. Adicionamos
     uma sub explicita 'Petição de Provas — Autor' (sufixo '— Autor'
     deixa claro o lado, evitando confusao se um dia criarmos sub
     analoga pro lado reu).

  2) Recuperacao Judicial. Cat nova polo='ambos' (credor habilita
     credito; devedor administra a RJ). 4 subs minimalistas:
       - Habilitação de Crédito
       - Impugnação de Crédito
       - Plano de Recuperação
       - Para análise

Idempotente: rerun nao duplica (checa por nome antes de inserir;
sub insert sob unique constraint (category_id, name)).

Revision ID: tax011
Revises: bp002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax011"
down_revision: Union[str, None] = "bp002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MANIFESTACAO_CREDOR_NAME = "Manifestação do Credor / Exequente"
_PETICAO_PROVAS_SUB_NAME = "Petição de Provas — Autor"

_RECUPERACAO_JUDICIAL_NAME = "Recuperação Judicial"
_RECUPERACAO_JUDICIAL_SUBS = [
    "Habilitação de Crédito",
    "Impugnação de Crédito",
    "Plano de Recuperação",
    "Para análise",
]
# display_order=21: agrupa com Assembleia de Credores (=20 na tax010)
# no final da arvore. Cats novas de RJ/falencia ficam juntas no fim.
_RECUPERACAO_JUDICIAL_DISPLAY_ORDER = 21


def upgrade() -> None:
    conn = op.get_bind()

    cat_table = sa.table(
        "classification_categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("polo_scope", sa.String),
        sa.column("taxonomy_version", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )
    sub_table = sa.table(
        "classification_subcategories",
        sa.column("category_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("taxonomy_version", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
    )

    # 1) Sub nova em 'Manifestação do Credor / Exequente'.
    # Encontra a cat existente (criada na tax006). Insere a sub no
    # display_order=99 pra ir pro final dela sem disputar posicao com
    # subs existentes (que vao 0..7).
    cat_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _MANIFESTACAO_CREDOR_NAME)
    ).scalar()
    if cat_id is None:
        # Defensivo: se tax006 nao rodou, nao criamos sub orfa.
        raise RuntimeError(
            f"Categoria '{_MANIFESTACAO_CREDOR_NAME}' nao existe — "
            "tax006 (seed v2) precisa ter rodado antes."
        )

    already_pet = conn.execute(
        sa.select(sub_table.c.category_id)
        .where(sub_table.c.category_id == cat_id)
        .where(sub_table.c.name == _PETICAO_PROVAS_SUB_NAME)
    ).first()
    if already_pet is None:
        conn.execute(
            sub_table.insert().values(
                category_id=cat_id,
                name=_PETICAO_PROVAS_SUB_NAME,
                taxonomy_version="v2",
                display_order=99,
                is_active=True,
            )
        )

    # 2) Cat nova 'Recuperação Judicial'.
    existing_rj = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _RECUPERACAO_JUDICIAL_NAME)
    ).scalar()
    if existing_rj is None:
        result = conn.execute(
            cat_table.insert()
            .values(
                name=_RECUPERACAO_JUDICIAL_NAME,
                polo_scope="ambos",
                taxonomy_version="v2",
                display_order=_RECUPERACAO_JUDICIAL_DISPLAY_ORDER,
                is_active=True,
            )
            .returning(cat_table.c.id)
        )
        rj_id = result.scalar()
    else:
        rj_id = existing_rj
        conn.execute(
            cat_table.update()
            .where(cat_table.c.id == rj_id)
            .values(
                polo_scope="ambos",
                taxonomy_version="v2",
                is_active=True,
            )
        )

    # 3) Subs da RJ (idempotente — checa antes de inserir).
    for idx, sub_name in enumerate(_RECUPERACAO_JUDICIAL_SUBS):
        already = conn.execute(
            sa.select(sub_table.c.category_id)
            .where(sub_table.c.category_id == rj_id)
            .where(sub_table.c.name == sub_name)
        ).first()
        if already is None:
            conn.execute(
                sub_table.insert().values(
                    category_id=rj_id,
                    name=sub_name,
                    taxonomy_version="v2",
                    display_order=idx,
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

    # 1) Remove sub 'Petição de Provas — Autor' da cat existente.
    cat_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _MANIFESTACAO_CREDOR_NAME)
    ).scalar()
    if cat_id is not None:
        conn.execute(
            sub_table.delete()
            .where(sub_table.c.category_id == cat_id)
            .where(sub_table.c.name == _PETICAO_PROVAS_SUB_NAME)
        )

    # 2) Remove cat 'Recuperação Judicial' + subs.
    rj_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _RECUPERACAO_JUDICIAL_NAME)
    ).scalar()
    if rj_id is not None:
        conn.execute(
            sub_table.delete().where(sub_table.c.category_id == rj_id)
        )
        conn.execute(
            cat_table.delete().where(cat_table.c.id == rj_id)
        )

    try:
        from app.services.classifier.taxonomy import invalidate_taxonomy_cache
        invalidate_taxonomy_cache()
    except Exception:
        pass

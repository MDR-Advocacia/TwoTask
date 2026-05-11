"""Audiências vira polo='ambos' e cria nova cat 'Assembleia de Credores' polo='ambos'.

Decisao com operador 2026-05-11: o escritorio de polo ativo (credor /
exequente) tambem precisa classificar audiencias e assembleias de
credores na carteira. A cat 'Audiências' ja existia em polo='passivo'
com 8 subs neutras (Conciliação, Instrução, Audiência Una, Mediação,
Adiamento/Redesignação, Cancelamento, Não Especificada, Para Análise)
— suficiente pra cobrir o ativo tambem, basta abrir o polo. Templates
ja cadastrados (56) continuam funcionando.

'Assembleia de Credores' nao existia em nenhum polo. Cat nova com 3
subs minimalistas (Designada, Realizada, Para análise). Suficiente
pra operacao classificar AGC sem granularidade desnecessaria.

Idempotente: rerun nao duplica (checa existencia por nome antes de
inserir cat nova; sub insert sob unique constraint (category_id, name)).

Revision ID: tax010
Revises: bp001
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax010"
down_revision: Union[str, None] = "bp001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Cat alvo da abertura de polo.
_AUDIENCIAS_NAME = "Audiências"

# Cat nova. Subs minimalistas (decisao operador).
_ASSEMBLEIA_NAME = "Assembleia de Credores"
_ASSEMBLEIA_SUBS = [
    "Designada",
    "Realizada",
    "Para análise",
]
# display_order alto (20): vai pro final em qualquer polo, sem disputar
# posicao com cats existentes. Operador pode mover via UI futura sem
# precisar de migration nova.
_ASSEMBLEIA_DISPLAY_ORDER = 20


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

    # 1) Audiências: polo passivo -> ambos. Mantem display_order, subs e
    # is_active. So abre o polo pra cobrir o ativo tambem.
    conn.execute(
        cat_table.update()
        .where(cat_table.c.name == _AUDIENCIAS_NAME)
        .values(polo_scope="ambos")
    )

    # 2) Assembleia de Credores: cria cat nova se ainda nao existe.
    # Idempotente: rerun nao duplica.
    existing = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _ASSEMBLEIA_NAME)
    ).scalar()
    if existing is None:
        result = conn.execute(
            cat_table.insert()
            .values(
                name=_ASSEMBLEIA_NAME,
                polo_scope="ambos",
                taxonomy_version="v2",
                display_order=_ASSEMBLEIA_DISPLAY_ORDER,
                is_active=True,
            )
            .returning(cat_table.c.id)
        )
        cat_id = result.scalar()
    else:
        # Caso ja exista (rerun parcial), garante polo='ambos' e v2.
        cat_id = existing
        conn.execute(
            cat_table.update()
            .where(cat_table.c.id == cat_id)
            .values(
                polo_scope="ambos",
                taxonomy_version="v2",
                is_active=True,
            )
        )

    # 3) Subs da Assembleia. Insere uma a uma pulando duplicatas (via
    # check explicito — evita IntegrityError do unique).
    for idx, sub_name in enumerate(_ASSEMBLEIA_SUBS):
        already = conn.execute(
            sa.select(sub_table.c.category_id)
            .where(sub_table.c.category_id == cat_id)
            .where(sub_table.c.name == sub_name)
        ).first()
        if already is None:
            conn.execute(
                sub_table.insert().values(
                    category_id=cat_id,
                    name=sub_name,
                    taxonomy_version="v2",
                    display_order=idx,
                    is_active=True,
                )
            )

    # Invalida o cache de taxonomia em memoria pra que a proxima
    # request veja as mudancas sem esperar o TTL (60s). Best-effort —
    # se a app nao estiver online ainda (boot Coolify), silenciosamente
    # ignora.
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
        sa.column("polo_scope", sa.String),
    )
    sub_table = sa.table(
        "classification_subcategories",
        sa.column("category_id", sa.Integer),
        sa.column("name", sa.String),
    )

    # 1) Reverte Audiências pra polo='passivo'.
    conn.execute(
        cat_table.update()
        .where(cat_table.c.name == _AUDIENCIAS_NAME)
        .values(polo_scope="passivo")
    )

    # 2) Remove subs + cat Assembleia. Templates apontando pra essa cat
    # ficariam orfaos — mas downgrade so e' usado em rollback de dev,
    # nao em producao. CASCADE FK na pratica (subcategories ON DELETE
    # CASCADE em category_id).
    cat_id = conn.execute(
        sa.select(cat_table.c.id).where(cat_table.c.name == _ASSEMBLEIA_NAME)
    ).scalar()
    if cat_id is not None:
        conn.execute(
            sub_table.delete().where(sub_table.c.category_id == cat_id)
        )
        conn.execute(
            cat_table.delete().where(cat_table.c.id == cat_id)
        )

    try:
        from app.services.classifier.taxonomy import invalidate_taxonomy_cache
        invalidate_taxonomy_cache()
    except Exception:
        pass

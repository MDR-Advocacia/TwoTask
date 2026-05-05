"""classification_categories + classification_subcategories + seed inicial

Move o `CLASSIFICATION_TREE` que estava hardcoded em
`app/services/classifier/taxonomy.py` pra duas tabelas no DB. Permite que
o admin gerencie taxonomia pela UI (e que a IA respeite mudancas em runtime
via cache curto), em vez de exigir deploy pra cada nova categoria.

O seed reproduz o estado atual da CLASSIFICATION_TREE (sem `description`,
`default_polo`, `default_prazo_*` ou exemplos — esses campos ficam vazios
e podem ser preenchidos depois pelo admin via UI/Sonnet helper).

Decisao tomada com user em 2026-05-04: cache TTL=60s, fallback hardcoded
quando DB vazio, categoria-only mantem campos default na propria categoria
(em vez de criar subcategoria sintetica).

Revision ID: tax001
Revises: sqd004
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax001"
down_revision: Union[str, None] = "sqd004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Snapshot da CLASSIFICATION_TREE no momento da migration. Mantido aqui
# pra reproducibilidade — se taxonomy.py for editado depois, a migration
# antiga continua seedeando o estado original (intencional).
SEED_TREE = {
    "1° Grau - Cível / Execução": [
        "Apresentação de Contestação",
        "Cumprimento de Sentença",
        "Embargos à Execução",
        "Determinação de Penhora",
        "Suspensão da Execução",
        "Expedição de Mandado ou Alvará",
        "Sentença Execução | Obrigação Satisfeita",
        "Extinção Total da Dívida",
        "Renúncia do Crédito",
        "Indeferimento da Inicial",
        "Prescrição Intercorrente",
        "Execução - Para Análise",
    ],
    "2° Grau - Cível": [
        "Abertura De Prazo - Contrarrazões",
        "Agravo De Instrumento",
        "Inclusão Em Pauta De Julgamento",
        "Suspensão / Sobrestamento",
        "Acordão - Provido",
        "Acordão - Não Provido",
        "Acordão - Provido Em Parte",
        "Acordão Não Definido",
        "Decisão Monocrática",
        "Para Análise 2º Grau",
    ],
    "Tutela": [
        "Tutela Pendente de Decisão",
        "Tutela Concedida",
        "Tutela Mantida",
        "Tutela Revogada",
        "Tutela Modificada",
        "Tutela Não Concedida",
    ],
    "Audiência Agendada": [
        "Conciliação",
        "Instrução",
        "Audiência Una",
        "Não especificada",
    ],
    "Citação": [
        "Citação para Contestar",
        "Citação para Apresentação de Documentos",
        "Citação - Para Análise",
    ],
    "Complementar Custas": [],
    "Manifestação das Partes": [],
    "Provas": [],
    "Embargos de Declaração": [
        "Contrarrazões",
        "Decisão Monocrática",
        "Embargos de Declaração - Para Análise",
    ],
    "Recurso Inominado": [
        "Contrarrazões",
        "Abertura de Prazo",
        "Recurso Inominado - Para Análise",
    ],
    "Saneamento e Organização do Processo": [],
    "Sentença": [
        "Sentença Parcialmente procedente",
        "Sentença Procedente",
        "Sentença Improcedente",
        "Sentença Homologação de transação",
        "Sentença Homologação de renúncia à pretensão",
        "Sentença Homologação Decisão por Juiz Leigo",
        "Sentença Embargos de Declaração",
        "Sentença Indeferimento da inicial",
        "Sentença Ausência de movimento",
        "Sentença Abandono do autor",
        "Sentença Ausência de pressupostos",
        "Sentença Ausência de legitimidade",
        "Sentença Homologação desistência da ação",
        "Sentença de Extinção sem Resolução",
        "Sentença Não definida",
    ],
    "Trânsito em Julgado": [],
    "Execução": [],
    "Arquivamento Definitivo": [],
    "Para análise": [],
}


def upgrade() -> None:
    op.create_table(
        "classification_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_polo", sa.String(length=16), nullable=True),
        sa.Column("default_prazo_dias", sa.Integer(), nullable=True),
        sa.Column("default_prazo_tipo", sa.String(length=16), nullable=True),
        sa.Column("default_prazo_fundamentacao", sa.Text(), nullable=True),
        sa.Column("example_publication", sa.Text(), nullable=True),
        sa.Column("example_response_json", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_classification_categories_name", "classification_categories", ["name"])

    op.create_table(
        "classification_subcategories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(),
                  sa.ForeignKey("classification_categories.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_polo", sa.String(length=16), nullable=True),
        sa.Column("default_prazo_dias", sa.Integer(), nullable=True),
        sa.Column("default_prazo_tipo", sa.String(length=16), nullable=True),
        sa.Column("default_prazo_fundamentacao", sa.Text(), nullable=True),
        sa.Column("example_publication", sa.Text(), nullable=True),
        sa.Column("example_response_json", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("category_id", "name", name="uq_subcat_per_category"),
    )
    op.create_index("ix_classification_subcategories_category_id", "classification_subcategories", ["category_id"])

    # Seed inicial — preserva o estado da CLASSIFICATION_TREE atual.
    conn = op.get_bind()
    cat_table = sa.table(
        "classification_categories",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("display_order", sa.Integer),
    )
    sub_table = sa.table(
        "classification_subcategories",
        sa.column("category_id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("display_order", sa.Integer),
    )
    for cat_idx, (cat_name, subs) in enumerate(SEED_TREE.items()):
        result = conn.execute(
            cat_table.insert()
            .values(name=cat_name, display_order=cat_idx)
            .returning(cat_table.c.id)
        )
        cat_id = result.scalar()
        for sub_idx, sub_name in enumerate(subs):
            conn.execute(
                sub_table.insert().values(
                    category_id=cat_id,
                    name=sub_name,
                    display_order=sub_idx,
                )
            )


def downgrade() -> None:
    op.drop_index("ix_classification_subcategories_category_id", table_name="classification_subcategories")
    op.drop_table("classification_subcategories")
    op.drop_index("ix_classification_categories_name", table_name="classification_categories")
    op.drop_table("classification_categories")

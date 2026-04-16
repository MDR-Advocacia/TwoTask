"""Adiciona coluna `uf` materializada em publicacao_registros

Revision ID: perf002_uf_column
Revises: perf001_pub_record_indexes
Create Date: 2026-04-16

Motivação
---------
O filtro de UF antes era aplicado em memória (Python) após carregar TODOS
os registros. Com a coluna materializada + índice, o filtro vai pro SQL
e a paginação funciona no banco.

A data migration popula a coluna para registros existentes usando a mesma
lógica de ``uf_from_cnj`` (extrai J e TR do CNJ de 20 dígitos).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "perf002_uf_column"
down_revision: Union[str, Sequence[str], None] = "perf001_pub_record_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mapa idêntico ao _UF_ESTADUAL do publication_search_service.py
_UF_ESTADUAL = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA", "06": "CE",
    "07": "DF", "08": "ES", "09": "GO", "10": "MA", "11": "MT", "12": "MS",
    "13": "MG", "14": "PA", "15": "PB", "16": "PR", "17": "PE", "18": "PI",
    "19": "RJ", "20": "RN", "21": "RS", "22": "RO", "23": "RR", "24": "SC",
    "25": "SP", "26": "SE", "27": "TO",
}


def _build_case_sql() -> str:
    """
    Gera SQL CASE WHEN para derivar a UF a partir de linked_lawsuit_cnj.

    A expressão regexp_replace extrai somente dígitos do CNJ.
    Depois, substring(... from 14 for 1) = J (ramo da justiça)
    e substring(... from 15 for 2) = TR (tribunal/região).
    """
    when_clauses: list[str] = []

    # J=8 → Justiça Estadual
    for code, uf in _UF_ESTADUAL.items():
        when_clauses.append(
            f"WHEN j = '8' AND tr = '{code}' THEN '{uf}'"
        )

    # J=4 → TRF
    when_clauses.append("WHEN j = '4' THEN 'TRF' || CAST(CAST(tr AS INTEGER) AS TEXT)")

    # J=7 → TRT
    when_clauses.append("WHEN j = '7' THEN 'TRT' || CAST(CAST(tr AS INTEGER) AS TEXT)")

    # J=5 → Justiça Militar Estadual
    when_clauses.append("WHEN j = '5' THEN 'JME' || CAST(CAST(tr AS INTEGER) AS TEXT)")

    # J=6 → TRE (usa UF estadual quando possível)
    for code, uf in _UF_ESTADUAL.items():
        when_clauses.append(
            f"WHEN j = '6' AND tr = '{code}' THEN 'TRE-{uf}'"
        )
    when_clauses.append("WHEN j = '6' THEN 'TRE-' || tr")

    joined = "\n            ".join(when_clauses)

    return f"""
        UPDATE publicacao_registros
        SET uf = derived.uf_value
        FROM (
            SELECT
                id,
                CASE
                    {joined}
                    ELSE NULL
                END AS uf_value
            FROM (
                SELECT
                    id,
                    substring(digits FROM 14 FOR 1) AS j,
                    substring(digits FROM 15 FOR 2) AS tr
                FROM (
                    SELECT
                        id,
                        regexp_replace(linked_lawsuit_cnj, '[^0-9]', '', 'g') AS digits
                    FROM publicacao_registros
                    WHERE linked_lawsuit_cnj IS NOT NULL
                      AND length(regexp_replace(linked_lawsuit_cnj, '[^0-9]', '', 'g')) = 20
                ) raw
            ) parsed
        ) derived
        WHERE publicacao_registros.id = derived.id
          AND derived.uf_value IS NOT NULL
    """


def upgrade() -> None:
    # 1) Adiciona coluna
    op.add_column(
        "publicacao_registros",
        sa.Column("uf", sa.String(length=10), nullable=True),
    )

    # 2) Índice
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_publicacao_registros_uf "
        "ON publicacao_registros (uf)"
    )

    # 3) Data migration: popula a partir do CNJ existente
    op.execute(_build_case_sql())


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_publicacao_registros_uf")
    op.drop_column("publicacao_registros", "uf")

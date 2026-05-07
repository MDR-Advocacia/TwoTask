"""ajus_classification_blocklist — bloqueia envio AJUS por classificacao pendente

Tabela que armazena CNJs de processos com classificacao pendente no
Legal One. Cada upload da planilha XLSX (operador faz manual quando
sentir necessidade) substitui o conteudo dessa tabela atomicamente.

Quando o operador dispara o lote (`dispatch_pending_batch`,
`dispatch_one`, `dispatch_selected`), o queue_service consulta essa
tabela por CNJ — se bater, o item e' pulado (NAO marcado enviando)
com log explicito. Item permanece em `pendente`/`erro`, voltando a
ser candidato no proximo dispatch SE o operador subir uma nova
planilha onde o CNJ ja' nao aparece (= classificacao concluida).

Campos extras (cod_ajus, materia) vem da planilha pra debug — nao
sao usados pelo dispatch, so' visiveis na UI/log.

Revision ID: ajus009
Revises: tax006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "ajus009"
down_revision: Union[str, None] = "tax006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ajus_classification_blocklist",
        sa.Column("id", sa.Integer(), nullable=False),
        # CNJ so' digitos (20). UNIQUE garante idempotencia do replace.
        sa.Column("cnj_number", sa.String(length=20), nullable=False),
        # Metadados opcionais vindos da planilha — debug/UI, nao usado
        # no dispatch.
        sa.Column("cod_ajus", sa.String(length=32), nullable=True),
        sa.Column("materia", sa.String(length=255), nullable=True),
        # Quando o CNJ apareceu pela primeira vez no blocklist, e
        # quando foi visto por ultimo (ultimo upload). Util pra
        # detectar processos que ja' estao ha muito tempo pendentes.
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cnj_number", name="uq_ajus_blocklist_cnj"),
    )
    op.create_index(
        "ix_ajus_blocklist_cnj",
        "ajus_classification_blocklist",
        ["cnj_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ajus_blocklist_cnj",
        table_name="ajus_classification_blocklist",
    )
    op.drop_table("ajus_classification_blocklist")

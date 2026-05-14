"""cla004: coluna audiencias_json em classificador_processo.

Revision ID: cla004
Revises: cla003
Create Date: 2026-05-14

Adiciona coluna JSON `audiencias_json` em classificador_processo pra
armazenar lista de audiencias detectadas no processo (passadas e
futuras), com comparecimentos e dados.

Estrutura esperada (lista de objetos):
[
  {
    "data": "2026-06-15",
    "hora": "14:00",
    "tipo": "conciliacao",        // conciliacao|instrucao|una|outra
    "local_ou_link": "https://...",
    "status": "agendada",         // agendada|realizada|cancelada|redesignada
    "comparecimentos": [
      {
        "polo": "reu",            // autor|reu
        "advogado_nome": "...",
        "advogado_oab": "...",
        "e_mdr_ou_vinculada": true,
        "parte_representada": "Banco Master S.A."
      }
    ],
    "resultado": "Sem acordo.",
    "fonte": "trecho que comprova"
  }
]

Coluna nullable. Indice JSON (Postgres) nao adicionado nessa fase —
filtragem por audiencias_proximas usa scan + filter no Python.
Se virar gargalo, adicionar GIN index depois.
"""

from alembic import op
import sqlalchemy as sa


revision = "cla004"
down_revision = "cla003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "classificador_processo",
        sa.Column("audiencias_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("classificador_processo", "audiencias_json")

"""adiciona squad_members.is_assistant + target_role em ambos os templates

Squads agora reconhecem 2 papeis paralelos a `is_leader`:
- `is_leader` (ja existe) — responsavel principal das tarefas da squad
- `is_assistant` (novo) — recebe tarefas marcadas como `target_role='assistente'`

Templates de prazos iniciais (`prazo_inicial_task_templates`) e
publicacoes (`task_templates`) ganham coluna `target_role` que decide
pra quem vai a tarefa criada no L1:
- `'principal'` (default) — usa o `responsible_user_external_id` do
  template/operador
- `'assistente'` — resolve via `Squad.is_assistant` da squad do
  responsavel (ver `app/services/squad_assistant_resolver.py`)

Pre-mapeamento aplicado a 18 subtipos com palavra "Subsidio" no nome
(escolhidos com o user em 2026-05-04). Os demais subtipos ficam
`'principal'` ate revisao manual via UI de templates.

Revision ID: sqd001
Revises: pin015
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "sqd001"
down_revision: Union[str, None] = "pin015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Subtipos pre-mapeados como 'assistente'. Lista decidida em conversa
# com o user — todos com palavra "Subsidio" no nome (claros). Outros
# candidatos ("Acompanhar Cálculo", "Trânsito", etc.) ficam pra revisao
# manual na UI de templates.
ASSISTANT_PREMAPPED_SUBTYPE_IDS = (
    843,   # Workflow / Solicitar Subsídio
    856,   # BB Defesa / Solicitar Subsídio - BB Defesa
    857,   # BB Defesa / Acompanhar Subsidio - BB Defesa
    958,   # Ativos e BB / Acompanhar Subsídio - BB Autor
    1002,  # BB Recurso / Solicitar Subsídio - BB Recurso
    1003,  # BB Recurso / Acompanhar Subsídio - BB Recurso
    1071,  # Bradesco / Analisar Subsídios - Bradesco
    1104,  # Bradesco / Reiterar Subsídios - Bradesco
    1118,  # BB Defesa / Analisar Subsídios Recebidos - BB Defesa
    1132,  # TwoTask / Subsidio Atendido - ONESID
    1142,  # BB Execução e Encerramento / Acompanhar subsídio Complexo
    1143,  # BB Execução e Encerramento / Acompanhar subsídio Simples
    1150,  # Ativos Réu / Aguardando Subsídios para Cumprimento
    1156,  # Banese Réu / Aguardando Subsídios
    1162,  # BB Defesa / Acompanhar Subsídio - Indicação de Assistente Técnico
    1184,  # Trabalhista / Trabalhista - Solicitar Subsídio
    1248,  # Banco Master / Solicitar Subsídio - Banco Master
    1300,  # OneSid / Retorno de Subsídios
)


def upgrade() -> None:
    # 1) is_assistant em squad_members (espelho de is_leader)
    op.add_column(
        "squad_members",
        sa.Column(
            "is_assistant",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # 2) target_role em ambas as tabelas de template
    for table in ("prazo_inicial_task_templates", "task_templates"):
        op.add_column(
            table,
            sa.Column(
                "target_role",
                sa.String(length=16),
                nullable=False,
                server_default="principal",
            ),
        )
        op.create_check_constraint(
            f"ck_{table}_target_role",
            table,
            "target_role IN ('principal', 'assistente')",
        )

    # 3) Pre-mapeamento — marca templates dos subtipos "Subsidio" como
    # 'assistente'. Idempotente (pode rodar varias vezes sem dano).
    if ASSISTANT_PREMAPPED_SUBTYPE_IDS:
        ids_csv = ",".join(str(i) for i in ASSISTANT_PREMAPPED_SUBTYPE_IDS)
        for table in ("prazo_inicial_task_templates", "task_templates"):
            op.execute(
                f"UPDATE {table} SET target_role = 'assistente' "
                f"WHERE task_subtype_external_id IN ({ids_csv})"
            )


def downgrade() -> None:
    for table in ("prazo_inicial_task_templates", "task_templates"):
        op.drop_constraint(f"ck_{table}_target_role", table, type_="check")
        op.drop_column(table, "target_role")
    op.drop_column("squad_members", "is_assistant")

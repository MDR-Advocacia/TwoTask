"""relax prazo_inicial_task_templates constraints

Fase 4a.2 — duas mudanças complementares:

1. **Remove a UniqueConstraint** em
   (tipo_prazo, subtipo, natureza_aplicavel, office_external_id).

   Motivação: o padrão de publicações (task_templates) já permite múltiplos
   templates por (category, subcategory, office) — cada um gera uma tarefa
   no agendamento (ex: "abrir prazo" + "pedir cópia ao correspondente").
   A docstring do PrazoInicialTaskTemplate já declarava essa intenção
   ("Múltiplos templates ativos dentro da MESMA combinação geram múltiplas
   sugestões"), mas a UNIQUE contradizia. Removendo, o modelo passa a bater
   com o matching_service (que já devolvia N templates sem filtro adicional
   além da regra específico>global).

2. **Permite `due_business_days` negativo** (novo range: -365..+30, novo
   default: -3).

   Motivação: em prazos iniciais, a tarefa no L1 tipicamente precisa ser
   agendada ANTES do fatal (D-N), não depois. Convenção de sinal (igual à
   usada em publication_search_service.py): a soma é `base + timedelta(
   days=due_business_days)`, logo:
     - negativo = antes da referência (D-N, caso típico de prazos iniciais)
     - 0        = no dia da referência
     - positivo = depois (mantido pro caso de reuniões pós-audiência etc.)

   O teto de 30 dias no positivo é arbitrário pra evitar typos catastróficos
   (nada impede alargar depois). Range armazenado como CheckConstraint para
   que o banco rejeite valores fora da faixa em qualquer caminho (não só via
   API).

Dados existentes: o usuário informou que vai re-editar manualmente os
templates ativos (não há migração de dados aqui). O default server_side
passa a ser '-3' pra novos INSERTs que omitam o campo.

Revision ID: pin005
Revises: pin004
Create Date: 2026-04-20
"""

from alembic import op
import sqlalchemy as sa


revision = "pin005"
down_revision = "pin004"
branch_labels = None
depends_on = None


TABLE = "prazo_inicial_task_templates"
UQ_NAME = "uq_pin_task_templates_tipo_subtipo_natureza_office"
CK_NAME = "ck_pin_task_templates_due_business_days_range"


def _has_unique(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(
        uq["name"] == name for uq in inspector.get_unique_constraints(table)
    )


def _has_check(table: str, name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        return any(
            ck.get("name") == name for ck in inspector.get_check_constraints(table)
        )
    except NotImplementedError:
        # Alguns dialetos (SQLite antigo) não expõem get_check_constraints.
        # Nesse caso, a create_check_constraint dentro do batch garante que a
        # constraint é aplicada — o downgrade só tenta dropar se existir.
        return False


def upgrade() -> None:
    # 1) DROP UniqueConstraint + ALTER default + ADD CheckConstraint num único
    # batch_alter_table. Idempotente: se a UNIQUE já foi removida ou a CHECK
    # já existe, pula sem erro (útil pra re-aplicar em dev após rollback
    # manual).
    with op.batch_alter_table(TABLE) as batch:
        if _has_unique(TABLE, UQ_NAME):
            batch.drop_constraint(UQ_NAME, type_="unique")

        batch.alter_column(
            "due_business_days",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="-3",
        )

        if not _has_check(TABLE, CK_NAME):
            batch.create_check_constraint(
                CK_NAME,
                "due_business_days >= -365 AND due_business_days <= 30",
            )


def downgrade() -> None:
    # Reverte pra forma anterior: recoloca UNIQUE, volta default=3, remove CHECK.
    # NÃO valida se existem linhas duplicadas antes — downgrade em dev
    # assume dados saudáveis. Em prod, isso é responsabilidade do operador.
    with op.batch_alter_table(TABLE) as batch:
        if _has_check(TABLE, CK_NAME):
            batch.drop_constraint(CK_NAME, type_="check")

        batch.alter_column(
            "due_business_days",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="3",
        )

        if not _has_unique(TABLE, UQ_NAME):
            batch.create_unique_constraint(
                UQ_NAME,
                [
                    "tipo_prazo",
                    "subtipo",
                    "natureza_aplicavel",
                    "office_external_id",
                ],
            )

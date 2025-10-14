"""data: insere regras de co-ocorrência para tarefas BB e Ativos

Revision ID: 3d256a322f0c
Revises: c001_adiciona_tabela
Create Date: 2025-10-14 15:01:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3d256a322f0c'
down_revision: Union[str, None] = 'c001_adiciona_tabela'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# --- DEFINIÇÃO DAS REGRAS DE NEGÓCIO ---
TASK_RULES = [
    {"principal": "Audiência de Conciliação - BB Réu", "obrigatorias": ["Solicitar preposto - BB Réu", "Juntar ata de audiência - BB Réu"]},
    {"principal": "Audiência de Instrução - BB Réu", "obrigatorias": ["Solicitar preposto - BB Réu", "Juntar ata de audiência - BB Réu"]},
    {"principal": "Audiência UNA - BB Réu", "obrigatorias": ["Solicitar preposto - BB Réu", "Juntar ata de audiência - BB Réu"]},
    {"principal": "Contestação - BB Réu", "obrigatorias": ["Solicitar Subsídio - BB Réu"]},
    {"principal": "Inclusão de Resultado - BB Réu", "obrigatorias": ["Análise/Acompanhar Trânsito - 1 Grau - BB Encerramento"]},
    {"principal": "Inclusão de Resultado de Improcedência - BB Réu", "obrigatorias": ["Análise/Acompanhar Trânsito - 1 Grau - BB Encerramento"]},
    {"principal": "Inclusão de Resultado 2° GRAU Réu - BB Réu", "obrigatorias": ["Análise/Acompanhar Trânsito - 2 Grau - BB Encerramento"]},
    {"principal": "Audiência de Conciliação - Ativos Réu", "obrigatorias": ["Juntar ata de audiência - Ativos Réu"]},
    {"principal": "Audiência de Instrução - Ativos Réu", "obrigatorias": ["Juntar ata de audiência - Ativos Réu"]}
]

def upgrade() -> None:
    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    # Define as tabelas para que o SQLAlchemy possa construir a consulta de forma segura
    task_subtypes_table = sa.Table('legal_one_task_subtypes', sa.MetaData(),
                                   sa.Column('id', sa.Integer, primary_key=True),
                                   sa.Column('name', sa.String))

    task_rules_table = sa.Table('task_corequisite_rules', sa.MetaData(),
                                sa.Column('id', sa.Integer, primary_key=True),
                                sa.Column('primary_subtype_id', sa.Integer),
                                sa.Column('secondary_subtype_id', sa.Integer),
                                sa.Column('description', sa.String))

    try:
        print("Iniciando a inserção de regras de co-ocorrência de tarefas...")
        
        all_subtype_names = set()
        for rule in TASK_RULES:
            all_subtype_names.add(rule['principal'])
            for o in rule['obrigatorias']:
                all_subtype_names.add(o)

        # Constrói a consulta de forma compatível com todos os bancos de dados
        query = sa.select(task_subtypes_table.c.name, task_subtypes_table.c.id).where(task_subtypes_table.c.name.in_(all_subtype_names))
        
        result = session.execute(query)
        subtype_id_map = {name: id for name, id in result}

        # Prepara uma lista de todas as regras a serem inseridas
        rules_to_insert = []
        for rule in TASK_RULES:
            principal_name = rule['principal']
            if principal_name not in subtype_id_map:
                print(f"AVISO: Subtipo principal '{principal_name}' não encontrado. Pulando regra.")
                continue
            
            principal_id = subtype_id_map[principal_name]

            for obrigatoria_name in rule['obrigatorias']:
                if obrigatoria_name not in subtype_id_map:
                    print(f"AVISO: Subtipo obrigatório '{obrigatoria_name}' para a regra '{principal_name}' não foi encontrado. Pulando inserção.")
                    continue
                
                obrigatoria_id = subtype_id_map[obrigatoria_name]
                description = f"Regra: '{principal_name}' requer '{obrigatoria_name}'."
                rules_to_insert.append({
                    "primary_subtype_id": principal_id,
                    "secondary_subtype_id": obrigatoria_id,
                    "description": description
                })
                print(f"  -> Preparando regra: '{principal_name}' -> '{obrigatoria_name}'")

        # Insere todas as regras de uma vez (mais eficiente)
        if rules_to_insert:
            op.bulk_insert(task_rules_table, rules_to_insert)
            print(f"{len(rules_to_insert)} regras inseridas com sucesso.")

    finally:
        session.close()


def downgrade() -> None:
    print("Removendo todas as regras de co-ocorrência de tarefas...")
    op.execute("DELETE FROM task_corequisite_rules")
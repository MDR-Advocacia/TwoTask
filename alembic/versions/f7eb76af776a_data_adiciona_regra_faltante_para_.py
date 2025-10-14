"""data: adiciona regra faltante para resultado de 2 grau

Revision ID: f7eb76af776a
Revises: 3d256a322f0c
Create Date: <data_e_hora>
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7eb76af776a' # Substitua pelo ID gerado no nome do arquivo
down_revision: Union[str, None] = '3d256a322f0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    session = sa.orm.Session(bind=bind)

    # Define as tabelas para a consulta
    task_subtypes_table = sa.Table('legal_one_task_subtypes', sa.MetaData(),
                                   sa.Column('id', sa.Integer, primary_key=True),
                                   sa.Column('name', sa.String))
    
    task_rules_table = sa.Table('task_corequisite_rules', sa.MetaData(),
                                sa.Column('id', sa.Integer, primary_key=True),
                                sa.Column('primary_subtype_id', sa.Integer),
                                sa.Column('secondary_subtype_id', sa.Integer),
                                sa.Column('description', sa.String))

    try:
        print("Inserindo regra de co-ocorrência para 'Inclusão de Resultado 2º GRAU Réu - BB Recurso'...")

        # Nomes exatos das tarefas
        principal_name = 'Inclusão de Resultado 2º GRAU Réu - BB Recurso'
        obrigatoria_name = 'Análise/Acompanhar Trânsito - 2 Grau - BB Encerramento'

        # Busca os IDs
        query = sa.select(task_subtypes_table.c.name, task_subtypes_table.c.id).where(
            task_subtypes_table.c.name.in_([principal_name, obrigatoria_name])
        )
        result = session.execute(query)
        subtype_id_map = {name: id for name, id in result}

        # Verifica se ambos foram encontrados
        if principal_name in subtype_id_map and obrigatoria_name in subtype_id_map:
            principal_id = subtype_id_map[principal_name]
            obrigatoria_id = subtype_id_map[obrigatoria_name]

            # Prepara e insere a regra
            rule_to_insert = {
                "primary_subtype_id": principal_id,
                "secondary_subtype_id": obrigatoria_id,
                "description": f"Regra: '{principal_name}' requer '{obrigatoria_name}'."
            }
            op.bulk_insert(task_rules_table, [rule_to_insert])
            print("  -> Regra inserida com sucesso.")
        else:
            print("AVISO: Não foi possível encontrar um dos subtipos necessários. A regra não foi inserida.")

    finally:
        session.close()


def downgrade() -> None:
    # Este downgrade é mais complexo, pois precisaríamos saber o ID exato.
    # Para simplicidade, vamos deixar em branco, mas em um cenário real,
    # poderíamos buscar os IDs e deletar a linha específica.
    print("O downgrade desta migração de dados não removerá a regra específica. Se necessário, remova manualmente.")
    pass
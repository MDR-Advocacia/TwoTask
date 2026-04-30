"""Adiciona status `nao_encontrado` na fila de classificacao AJUS.

Quando o AJUS responde a busca rapida com "Desculpe, mas nenhuma acao
foi encontrada com os termos pesquisados!", o item NAO eh um erro
tecnico — eh um caso legitimo de "esse processo nao esta cadastrado
no AJUS desse cliente". Antes era marcado como `erro` generico, o
que poluia a fila de erros tecnicos. Agora vai pra status proprio,
permitindo:
  - filtrar separadamente os erros tecnicos vs nao-cadastrados
  - exportar a lista de nao-cadastrados pro time de implantacao
  - retentar erros tecnicos sem retentar nao-cadastrados (que vao
    falhar do mesmo jeito ate o time cadastrar no AJUS).

Revision ID: ajus005
Revises: ajus004
"""

from typing import Sequence, Union

from alembic import op


revision: str = "ajus005"
down_revision: Union[str, None] = "ajus004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres nao permite ALTER CHECK CONSTRAINT — precisa drop + recreate.
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "DROP CONSTRAINT IF EXISTS ck_ajus_classif_queue_status"
    )
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "ADD CONSTRAINT ck_ajus_classif_queue_status "
        "CHECK (status IN ("
        "'pendente','processando','sucesso','erro','cancelado','nao_encontrado'"
        "))"
    )


def downgrade() -> None:
    # Antes de reverter o CHECK, normaliza qualquer item em
    # nao_encontrado pra erro (senao o constraint trava com violacao)
    op.execute(
        "UPDATE ajus_classificacao_queue "
        "SET status = 'erro' "
        "WHERE status = 'nao_encontrado'"
    )
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "DROP CONSTRAINT IF EXISTS ck_ajus_classif_queue_status"
    )
    op.execute(
        "ALTER TABLE ajus_classificacao_queue "
        "ADD CONSTRAINT ck_ajus_classif_queue_status "
        "CHECK (status IN ("
        "'pendente','processando','sucesso','erro','cancelado'"
        "))"
    )

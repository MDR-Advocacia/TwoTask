"""Seed da taxonomia v2 (polo ativo + polo passivo).

Insere as 10 cats do polo ATIVO e as 12 cats do polo PASSIVO com suas
subcategorias, marcando taxonomy_version='v2' e polo_scope correto.

A taxonomia v1 (seedada pela tax001) e mantida intacta com
taxonomy_version='v1' e polo_scope='ambos' (default herdado da tax002).
Registros antigos (publicacoes ja classificadas, templates, overrides)
continuam casando contra a v1 ate o switch global do toggle.

Idempotente: se uma categoria com mesmo nome ja existe (rerun da
migration ou seed parcial), atualiza polo_scope/taxonomy_version
em vez de criar duplicata. Subcategorias idem via UniqueConstraint
(category_id, name).

Decisoes de produto consolidadas com user em 2026-05-07 (ver historico
da feature taxonomy/v2). Nomenclatura genericamente neutra — sem
referencias a clientes especificos. Categorias residuais "Para Analise"
ficam em ultimo lugar do display_order de cada arvore.

Revision ID: tax006
Revises: tax005
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "tax006"
down_revision: Union[str, None] = "tax005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Snapshot da taxonomia v2 polo ATIVO. Ordem dos dicts = display_order
# (1 a 10). Categorias residuais sem subs = lista vazia.
ATIVO_TREE: dict[str, list[str]] = {
    "Citação, Intimação e Localização": [
        "Citação positiva",
        "Citação negativa",
        "Intimação positiva",
        "Intimação negativa",
        "Endereço / localização do devedor",
        "Mandado cumprido / não cumprido",
        "Para análise",
    ],
    "Manifestação do Credor / Exequente": [
        "Manifestar sobre certidão / diligência",
        "Apresentar cálculo / atualizar débito",
        "Indicar bens ou endereço",
        "Requerer prosseguimento",
        "Juntar documentos",
        "Recolher custas / diligências",
        "Manifestar sobre defesa do devedor",
        "Para análise",
    ],
    "Manifestação do Devedor / Executado": [
        "Pagar débito",
        "Apresentar defesa",
        "Manifestar sobre penhora / bloqueio",
        "Manifestar sobre cálculo",
        "Regularizar representação",
        "Para análise",
    ],
    "Pesquisa Patrimonial e Bloqueio": [
        "Pesquisa patrimonial deferida",
        "Pesquisa patrimonial indeferida",
        "Resultado positivo",
        "Resultado negativo",
        "Bloqueio realizado",
        "Desbloqueio / levantamento da constrição",
        "Para análise",
    ],
    "Penhora, Garantia e Expropriação": [
        "Penhora deferida / realizada",
        "Penhora indeferida",
        "Avaliação de bem",
        "Leilão / praça",
        "Arrematação / adjudicação",
        "Garantia insuficiente / substituição de garantia",
        "Para análise",
    ],
    "Acordo, Pagamento e Depósito": [
        "Proposta de acordo",
        "Acordo homologado",
        "Pagamento parcial",
        "Pagamento integral",
        "Depósito judicial",
        "Expedição de alvará / levantamento",
        "Inadimplemento de acordo",
        "Para análise",
    ],
    "Defesa do Devedor e Incidentes": [
        "Contestação",
        "Embargos à execução / monitórios",
        "Impugnação ao cumprimento de sentença",
        "Exceção de pré-executividade",
        "Pedido de desbloqueio / substituição de penhora",
        "Alegação de pagamento, prescrição ou excesso",
        "Para análise",
    ],
    # Decisao 2(a): "Sentenca Homologacao de transacao" NAO entra aqui.
    # Homologacao de acordo (mesmo via sentenca) cai em "Acordo, Pagamento
    # e Deposito" (cat 6 ativo).
    "Decisão, Sentença e Extinção": [
        "Decisão favorável ao credor",
        "Decisão desfavorável ao credor",
        "Sentença procedente / favorável",
        "Sentença improcedente / desfavorável",
        "Suspensão",
        "Arquivamento",
        "Extinção por pagamento",
        "Extinção por prescrição / abandono / ausência de pressupostos",
        "Para análise",
    ],
    "Recursos": [
        "Abertura de prazo para contrarrazões",
        "Agravo",
        "Apelação",
        "Recurso inominado",
        "Embargos de declaração",
        "Acórdão favorável",
        "Acórdão desfavorável",
        "Acórdão parcial / não definido",
        "Para análise",
    ],
    # Categoria residual sem subs — usa subcategoria '-' no schema da IA.
    "Para Análise — Recuperação de Crédito": [],
}


# Snapshot da taxonomia v2 polo PASSIVO. Ordem dos dicts = display_order
# (1 a 12).
PASSIVO_TREE: dict[str, list[str]] = {
    "Citação e Intimação Inicial": [
        "Citação para Contestar",
        "Citação para Apresentação de Documentos",
        "Citação por Edital",
        "Intimação Inicial (não-citatória)",
        "Para Análise",
    ],
    # Decisao (c): "Manifestar sobre Laudo" NAO entra aqui — fica
    # exclusivamente em cat 5 (Provas, Pericia e Saneamento).
    "Manifestações, Prazos e Providências": [
        "Manifestar sobre Documentos Juntados",
        "Cumprir Determinação Específica",
        "Regularizar Representação Processual",
        "Manifestar sobre Defesa / Réplica",
        "Para Análise",
    ],
    "Tutelas, Liminares e Medidas Urgentes": [
        "Tutela / Liminar Deferida",
        "Tutela / Liminar Indeferida",
        "Tutela Mantida",
        "Tutela Revogada",
        "Tutela Modificada",
        "Pedido de Tutela Pendente",
        "Para Análise",
    ],
    "Audiências": [
        "Conciliação",
        "Instrução",
        "Audiência Una",
        "Mediação",
        "Adiamento / Redesignação",
        "Cancelamento",
        "Não Especificada",
        "Para Análise",
    ],
    "Provas, Perícia e Saneamento": [
        "Despacho Saneador",
        "Perícia Deferida / Nomeação de Perito",
        "Perícia Indeferida",
        "Apresentação de Quesitos / Assistente Técnico",
        "Laudo Pericial Juntado — intimação para manifestar",
        "Outras Provas Deferidas / Indeferidas",
        "Para Análise",
    ],
    "Decisões Interlocutórias e Despachos Relevantes": [
        "Decisão Interlocutória — substantiva",
        "Despacho de Mero Expediente",
        "Suspensão / Sobrestamento",
        "Determinação Genérica",
        "Para Análise",
    ],
    "Sentença e Extinção": [
        "Sentença Procedente",
        "Sentença Parcialmente Procedente",
        "Sentença Improcedente",
        "Sentença Homologação de Transação",
        "Sentença Homologação de Desistência / Renúncia",
        "Sentença Indeferimento da Inicial",
        "Sentença Extinção sem Resolução de Mérito",
        "Sentença Não Definida",
        "Para Análise",
    ],
    "Recursos e Julgamentos em 2º Grau": [
        "Abertura de Prazo para Contrarrazões",
        "Agravo de Instrumento",
        "Apelação",
        "Recurso Inominado",
        "Embargos de Declaração",
        "Inclusão em Pauta de Julgamento",
        "Acórdão / Decisão Monocrática — Provido",
        "Acórdão / Decisão Monocrática — Não Provido",
        "Acórdão / Decisão Monocrática — Provido em Parte",
        "Acórdão Não Definido",
        "Para Análise",
    ],
    "Cumprimento de Sentença / Execução": [
        "Intimação para Pagamento Voluntário (15 dias úteis)",
        "Intimação para Impugnação ao Cumprimento de Sentença",
        "Determinação de Penhora",
        "Bloqueio Efetivado contra o Cliente",
        "Pesquisa Patrimonial Deferida",
        "Liberação / Levantamento de Constrição",
        "Embargos à Execução",
        "Apresentação de Garantia / Caução",
        "Sentença de Extinção da Execução",
        "Suspensão da Execução",
        "Prescrição Intercorrente",
        "Para Análise",
    ],
    "Custas, Alvarás, Mandados e Atos Cartorários": [
        "Recolhimento de Custas / Preparo",
        "Expedição de Mandado",
        "Expedição de Alvará",
        "Carta Precatória / Rogatória",
        "Devolução de Mandado / Diligência",
        "Para Análise",
    ],
    "Trânsito em Julgado e Arquivamento": [
        "Trânsito em Julgado Certificado",
        "Arquivamento Definitivo",
        "Arquivamento Provisório / Suspenso",
        "Baixa em Distribuição",
        "Para Análise",
    ],
    # Categoria residual sem subs.
    "Para Análise": [],
}


def _seed_tree(conn, tree: dict[str, list[str]], polo: str) -> None:
    """Insere as cats e subs de uma arvore (ativo ou passivo).

    Idempotente: pula categorias com mesmo nome (so atualiza polo_scope/
    taxonomy_version pra garantir o estado desejado mesmo em rerun).
    """
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

    for cat_idx, (cat_name, subs) in enumerate(tree.items()):
        # Categoria pode ja existir (nome com unique constraint global).
        # Se sim, atualiza polo_scope/version pra garantir estado v2.
        existing = conn.execute(
            sa.select(cat_table.c.id).where(cat_table.c.name == cat_name)
        ).scalar()

        if existing is None:
            result = conn.execute(
                cat_table.insert()
                .values(
                    name=cat_name,
                    polo_scope=polo,
                    taxonomy_version="v2",
                    display_order=cat_idx,
                    is_active=True,
                )
                .returning(cat_table.c.id)
            )
            cat_id = result.scalar()
        else:
            cat_id = existing
            conn.execute(
                cat_table.update()
                .where(cat_table.c.id == cat_id)
                .values(
                    polo_scope=polo,
                    taxonomy_version="v2",
                    display_order=cat_idx,
                    is_active=True,
                )
            )
            # Limpa subs antigas dessa cat pra evitar mistura de v1+v2.
            # So executa quando a cat ja existia, pra preservar tax001.
            # Nao deveria acontecer na pratica (nomes nao colidem), mas
            # mantem o seed tolerante a edicoes manuais previas.
            conn.execute(
                sa.text("DELETE FROM classification_subcategories WHERE category_id = :cid"),
                {"cid": cat_id},
            )

        for sub_idx, sub_name in enumerate(subs):
            conn.execute(
                sub_table.insert().values(
                    category_id=cat_id,
                    name=sub_name,
                    taxonomy_version="v2",
                    display_order=sub_idx,
                    is_active=True,
                )
            )


def upgrade() -> None:
    conn = op.get_bind()
    _seed_tree(conn, ATIVO_TREE, polo="ativo")
    _seed_tree(conn, PASSIVO_TREE, polo="passivo")


def downgrade() -> None:
    """Remove apenas registros v2 — mantem v1 (legacy) intacta."""
    conn = op.get_bind()
    conn.execute(sa.text(
        "DELETE FROM classification_subcategories WHERE taxonomy_version = 'v2'"
    ))
    conn.execute(sa.text(
        "DELETE FROM classification_categories WHERE taxonomy_version = 'v2'"
    ))

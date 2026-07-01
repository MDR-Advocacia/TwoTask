"""
Catálogo de PRODUTOS do Banco Master (vocabulário controlado) + normalização.

Mapeia a "família crua" que aparece nos processos para um produto canônico
e sua CATEGORIA ("Cai em"). Distingue PRODUTO de OBJETO: Superendividamento,
Negativação, Cobrança Indevida e Fraude são OBJETOS (causa de pedir), não
produtos — quando a IA colocar um desses em `produto`, zeramos (vai pro
campo `objeto`).
"""

from __future__ import annotations

import unicodedata
from typing import Optional, Tuple

# Produto canônico → (categoria "Cai em", aliases de match).
# ORDEM IMPORTA: do mais específico pro mais genérico. "Cartão de Crédito
# Consignado" e "Cartão de Crédito" vêm antes de "Empréstimo Consignado"
# (cujo alias "consignado" senão capturaria o cartão consignado), e o
# cartão consignado vem antes do cartão simples (cujo nome é substring).
PRODUTOS_CATALOGO = [
    {
        "nome": "CREDCESTA",
        "categoria": "Conta/Pacotes",
        "aliases": ["credcesta", "cred cesta", "cesta", "conta cesta", "pacote"],
    },
    {
        "nome": "Cartão de Crédito Consignado",
        "categoria": "Consignado",
        # RMC = Reserva de Margem Consignável; RCC = Reserva de Cartão Consignado.
        "aliases": [
            "cartao de credito consignado", "cartao consignado", "rmc", "rcc",
            "reserva de margem", "reserva de cartao",
        ],
    },
    {
        "nome": "Cartão de Crédito",
        "categoria": "Cartão",
        "aliases": ["cartao de credito", "cartao"],
    },
    {
        "nome": "Empréstimo Consignado",
        "categoria": "Consignado",
        "aliases": ["emprestimo consignado", "consignado", "emprestimo"],
    },
]

# Termos que são OBJETO (causa de pedir), nunca produto.
OBJETOS_TERMS = [
    "superendividamento", "negativacao", "cobranca indevida", "fraude",
]

# Lista de produtos canônicos (pra exibir no prompt/UI).
PRODUTOS_NOMES = [p["nome"] for p in PRODUTOS_CATALOGO]


def _norm(text: str) -> str:
    txt = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(txt.lower().split())


def normalize_produto(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Normaliza o produto cru → (nome canônico, categoria).

    - É um OBJETO (superendividamento/negativação/...) → (None, None).
    - Casa um produto do catálogo → (nome canônico, categoria).
    - Desconhecido → (raw original, "Outros").
    - Vazio → (None, None).
    """
    if not raw or not str(raw).strip():
        return None, None
    n = _norm(str(raw))

    # É objeto, não produto.
    for obj in OBJETOS_TERMS:
        if obj in n:
            return None, None

    # Match no catálogo (mais específico primeiro: o catálogo já está em
    # ordem de especificidade — consignado antes de cartão genérico).
    for prod in PRODUTOS_CATALOGO:
        if _norm(prod["nome"]) in n:
            return prod["nome"], prod["categoria"]
        for alias in prod["aliases"]:
            if alias in n:
                return prod["nome"], prod["categoria"]

    return str(raw).strip(), "Outros"


def categoria_de(produto: Optional[str]) -> Optional[str]:
    """Categoria ('Cai em') de um produto já canônico (ou cru)."""
    _, cat = normalize_produto(produto)
    return cat

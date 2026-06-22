"""Tipos de coluna compartilhados.

`jsonb()` — JSONB no Postgres (produção), degradando para JSON no SQLite.

Necessário porque a suíte de testes monta o schema via
`Base.metadata.create_all` contra um SQLite em memória (ver tests/conftest.py),
e o compilador do SQLite não renderiza o tipo `JSONB` do dialeto Postgres
(`CompileError: can't render element of type JSONB`) — o que fazia TODOS os
testes que dependem do fixture `db_session` falharem no setup, mascarando
regressões reais.

`with_variant` troca o tipo INTEIRO (DDL + serialização bind/result) por
`JSON` APENAS no dialeto SQLite. Em Postgres o DDL continua idêntico (JSONB),
então NÃO exige migration. Use `jsonb()` no lugar de `JSONB` em qualquer
coluna nova para manter os testes rodando.
"""
from __future__ import annotations

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB


def jsonb():
    """Coluna JSONB (Postgres) com fallback JSON (SQLite/testes)."""
    return JSONB().with_variant(JSON(), "sqlite")

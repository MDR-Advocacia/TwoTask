#!/usr/bin/env python3
"""Seed de onr_solicitacoes a partir do SQLite do OneRequest legado.

Lê a tabela `solicitacoes` de um arquivo `solicitacoes.db` (exportado da máquina
do escritório onde roda o OneRequest) e insere/atualiza em `onr_solicitacoes`,
mapeando os campos e resolvendo o responsável por NOME -> LegalOneUser.

Uso (dentro do container da API, onde DATABASE_URL aponta pro Postgres certo):

    # dry-run (não grava nada, só relata):
    python scripts/seed_onerequest_from_sqlite.py /tmp/solicitacoes.db

    # grava de fato:
    python scripts/seed_onerequest_from_sqlite.py /tmp/solicitacoes.db --commit

    # grava e também atualiza detalhes das DMIs que já existem:
    python scripts/seed_onerequest_from_sqlite.py /tmp/solicitacoes.db --commit --update

Idempotente: por padrão pula DMIs cujo numero_solicitacao já existe. NUNCA
deleta nada. status_tratamento entra sempre como NOVO (o operador trata/agenda
no Flow). status_sistema é mapeado de 'Aberto'/'Respondido' do OneRequest.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

# Permite importar o app tanto no container (/app) quanto rodando localmente.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal  # noqa: E402
from app.models.legal_one import LegalOneUser  # noqa: E402
from app.models.onerequest import (  # noqa: E402
    OnerequestSolicitacao,
    STATUS_SISTEMA_ABERTO,
    STATUS_SISTEMA_RESPONDIDO,
    STATUS_TRATAMENTO_NOVO,
)

# Campos de detalhe (capturados pela RPA) que o --update refresca.
DETAIL_FIELDS = (
    "titulo",
    "npj_direcionador",
    "prazo",
    "texto_dmi",
    "numero_processo",
    "polo",
)


def _norm(value) -> str:
    return (value or "").strip() if isinstance(value, str) else (value and str(value).strip() or "")


def _clean_opt(value):
    """Normaliza string opcional; 'N/A' e vazio viram None."""
    s = _norm(value)
    if not s or s.upper() == "N/A":
        return None
    return s


def _map_status_sistema(value) -> str:
    s = _norm(value).lower()
    return STATUS_SISTEMA_RESPONDIDO if s.startswith("respond") else STATUS_SISTEMA_ABERTO


def _parse_recebido(value):
    s = _norm(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed onr_solicitacoes do SQLite do OneRequest.")
    ap.add_argument("db_path", help="Caminho do solicitacoes.db do OneRequest.")
    ap.add_argument("--commit", action="store_true", help="Grava de fato (senão é dry-run).")
    ap.add_argument("--update", action="store_true", help="Atualiza detalhes de DMIs já existentes.")
    args = ap.parse_args()

    if not os.path.exists(args.db_path):
        print(f"ERRO: arquivo não encontrado: {args.db_path}")
        sys.exit(1)

    conn = sqlite3.connect(args.db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM solicitacoes")]
    finally:
        conn.close()
    print(f"SQLite: {len(rows)} linhas em 'solicitacoes'.")

    db = SessionLocal()
    try:
        # nome (normalizado) -> id do LegalOneUser
        name_to_id: dict[str, int] = {}
        for uid, uname in db.query(LegalOneUser.id, LegalOneUser.name).all():
            if uname:
                name_to_id.setdefault(uname.strip().lower(), uid)

        existentes = {
            num for (num,) in db.query(OnerequestSolicitacao.numero_solicitacao).all()
        }

        inseridos = atualizados = pulados = 0
        resp_ok = resp_naomatch = 0
        nomes_naomatch: set[str] = set()
        st_count = {STATUS_SISTEMA_ABERTO: 0, STATUS_SISTEMA_RESPONDIDO: 0}

        for r in rows:
            numero = _norm(r.get("numero_solicitacao"))
            if not numero:
                continue

            resp_nome = _clean_opt(r.get("responsavel"))
            resp_id = None
            if resp_nome:
                resp_id = name_to_id.get(resp_nome.lower())
                if resp_id:
                    resp_ok += 1
                else:
                    resp_naomatch += 1
                    nomes_naomatch.add(resp_nome)

            status_sistema = _map_status_sistema(r.get("status_sistema"))
            st_count[status_sistema] += 1

            if numero in existentes:
                if args.update:
                    row = (
                        db.query(OnerequestSolicitacao)
                        .filter(OnerequestSolicitacao.numero_solicitacao == numero)
                        .first()
                    )
                    for f in DETAIL_FIELDS:
                        novo = r.get(f)
                        if novo:
                            setattr(row, f, novo)
                    row.status_sistema = status_sistema
                    atualizados += 1
                else:
                    pulados += 1
                continue

            db.add(
                OnerequestSolicitacao(
                    numero_solicitacao=numero,
                    titulo=_clean_opt(r.get("titulo")),
                    npj_direcionador=_clean_opt(r.get("npj_direcionador")),
                    prazo=_clean_opt(r.get("prazo")),
                    texto_dmi=r.get("texto_dmi") or None,
                    numero_processo=_clean_opt(r.get("numero_processo")),
                    polo=_clean_opt(r.get("polo")),
                    recebido_em=_parse_recebido(r.get("recebido_em")),
                    status_sistema=status_sistema,
                    status_tratamento=STATUS_TRATAMENTO_NOVO,
                    responsavel_user_id=resp_id,
                    setor=_clean_opt(r.get("setor")),
                    data_agendamento=_clean_opt(r.get("data_agendamento")),
                    anotacao=r.get("anotacao") or None,
                )
            )
            inseridos += 1

        print("\n=== RESUMO ===")
        print(f"  inserir:            {inseridos}")
        print(f"  atualizar:          {atualizados}  (--update={'on' if args.update else 'off'})")
        print(f"  pular (ja existem): {pulados}")
        print(
            f"  status_sistema:     ABERTO={st_count[STATUS_SISTEMA_ABERTO]}  "
            f"RESPONDIDO={st_count[STATUS_SISTEMA_RESPONDIDO]}"
        )
        print(f"  responsavel:        resolvido={resp_ok}  sem_match={resp_naomatch}")
        if nomes_naomatch:
            amostra = ", ".join(sorted(nomes_naomatch)[:20])
            reticencias = " ..." if len(nomes_naomatch) > 20 else ""
            print(f"  nomes sem match no LegalOneUser ({len(nomes_naomatch)}): {amostra}{reticencias}")

        if args.commit:
            db.commit()
            print("\n>>> COMMIT aplicado.")
        else:
            db.rollback()
            print("\n>>> DRY-RUN (nada gravado). Rode com --commit pra aplicar.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""Backfill historico da Base Banco Master.

Le todos os arquivos XLSX em uma pasta, ordena por timestamp do filename,
e posta um a um na API de /admin/base-processual/uploads/backfill:

- 'Primeira Tranche de Processos a Distribuir - DD.MM.YYYY.xlsx': vai como
  mode=snapshot (pipeline normal, cria processos reais com timestamp historico).
- 'PLANILHA_MIGRACAO_COMPLETA - YYYY-MM-DD HH-MM-SS.xlsx': vai como
  mode=lote_historico (so' conta linhas, nao cria processos individuais — pq
  esse schema nao tem cod_ajus).
- 'testeworkflow*': pulado (provavel teste do operador).

Uso:
  Variaveis de ambiente:
    BASE_PROCESSUAL_API_URL    Default 'http://localhost:8112'
    BASE_PROCESSUAL_ADMIN_EMAIL    Email do admin pra login JWT
    BASE_PROCESSUAL_ADMIN_PASSWORD    Senha
    BASE_PROCESSUAL_HISTORICO_DIR    Pasta com os XLSX (default
        'C:/Users/jonil/OneDrive/Desktop/Banco Master/Histórico Bases')

  Exemplo:
    python scripts/backfill_base_processual_historico.py

Dry-run (lista o que faria sem postar):
    python scripts/backfill_base_processual_historico.py --dry-run

Idempotencia: lotes historicos sao append-only (subir 2x cria 2 rows). Pra
re-rodar limpando antes, faca TRUNCATE das tabelas base_processual_* primeiro
(ou descarte revogadas via UI).
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("backfill")

# --- Defaults ---
DEFAULT_API_URL = os.environ.get("BASE_PROCESSUAL_API_URL", "http://localhost:8112")
DEFAULT_HISTORICO_DIR = os.environ.get(
    "BASE_PROCESSUAL_HISTORICO_DIR",
    r"C:\Users\jonil\OneDrive\Desktop\Banco Master\Histórico Bases",
)

# Regex pros 2 padroes de nome
_RE_PRIMEIRA_TRANCHE = re.compile(
    r"^Primeira Tranche.*?(\d{2})\.(\d{2})\.(\d{4})\.xlsx$",
    re.IGNORECASE,
)
_RE_PLANILHA_MIGRACAO = re.compile(
    r"^PLANILHA_MIGRACAO_COMPLETA\s*-\s*"
    r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2})-(\d{2})-(\d{2})\.xlsx$",
    re.IGNORECASE,
)
_RE_TESTE = re.compile(r"^testeworkflow", re.IGNORECASE)


def parse_filename(filename: str) -> Optional[tuple[datetime, str]]:
    """Devolve (timestamp, mode) ou None se filename for pra pular.

    mode: 'snapshot' pra Primeira Tranche, 'lote_historico' pra MIGRACAO.
    Filename "2025" e' tratado como 2026 (typo conhecido).
    """
    if _RE_TESTE.match(filename):
        return None  # skip

    m = _RE_PRIMEIRA_TRANCHE.match(filename)
    if m:
        dd, mm, yyyy = m.groups()
        year = int(yyyy)
        if year == 2025:
            year = 2026  # typo conhecido confirmado pelo operador
        ts = datetime(year, int(mm), int(dd), 0, 0, 0)
        return (ts, "snapshot")

    m = _RE_PLANILHA_MIGRACAO.match(filename)
    if m:
        y, mo, d, h, mi, s = m.groups()
        ts = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
        return (ts, "lote_historico")

    return None  # padrao desconhecido — pular


def login(api_url: str, email: str, password: str) -> str:
    """Login JWT — retorna o access_token."""
    url = f"{api_url}/api/v1/auth/token"
    log.info("Login em %s como %s...", url, email)
    r = requests.post(
        url,
        data={"username": email, "password": password},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"Login OK mas sem access_token na resposta: {r.text}")
    log.info("Login OK, token recebido.")
    return token


def post_backfill(
    api_url: str,
    token: str,
    file_path: Path,
    uploaded_at: datetime,
    mode: str,
    timeout_seconds: int = 300,
) -> dict:
    """Posta o arquivo no endpoint /uploads/backfill. Retorna JSON da resposta."""
    url = f"{api_url}/api/v1/admin/base-processual/uploads/backfill"
    iso_ts = uploaded_at.isoformat()
    with open(file_path, "rb") as f:
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            files={"file": (file_path.name, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"uploaded_at": iso_ts, "mode": mode},
            timeout=timeout_seconds,
        )
    if not r.ok:
        try:
            err = r.json()
        except Exception:
            err = r.text
        raise RuntimeError(f"HTTP {r.status_code}: {err}")
    return r.json()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        default=DEFAULT_HISTORICO_DIR,
        help="Pasta com os XLSX historicos.",
    )
    ap.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help="URL base da API (sem /api/v1).",
    )
    ap.add_argument(
        "--email",
        default=os.environ.get("BASE_PROCESSUAL_ADMIN_EMAIL"),
        help="Email do admin pro login.",
    )
    ap.add_argument(
        "--password",
        default=os.environ.get("BASE_PROCESSUAL_ADMIN_PASSWORD"),
        help="Senha do admin.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista o que faria sem postar.",
    )
    ap.add_argument(
        "--token",
        default=None,
        help="JWT direto (alternativo a email/password — copie do browser).",
    )
    args = ap.parse_args()

    pasta = Path(args.dir)
    if not pasta.is_dir():
        log.error("Pasta nao existe: %s", pasta)
        return 1

    # Lista + parseia + ordena
    files = sorted(pasta.glob("*.xlsx"))
    plan: list[tuple[Path, datetime, str]] = []
    skipped: list[str] = []
    for p in files:
        parsed = parse_filename(p.name)
        if parsed is None:
            skipped.append(p.name)
            continue
        ts, mode = parsed
        plan.append((p, ts, mode))

    plan.sort(key=lambda x: x[1])

    log.info("=" * 60)
    log.info("Pasta: %s", pasta)
    log.info("Plano (%d arquivos, ordenados por timestamp):", len(plan))
    for p, ts, mode in plan:
        log.info("  %s  [%s]  %s", ts.isoformat(), mode, p.name)
    if skipped:
        log.info("Pulados (%d): %s", len(skipped), ", ".join(skipped))
    log.info("=" * 60)

    if args.dry_run:
        log.info("DRY-RUN — nada postado. Use sem --dry-run pra executar.")
        return 0

    # Autenticacao
    if args.token:
        token = args.token
    else:
        if not args.email or not args.password:
            log.error(
                "Email/senha obrigatorios (ou use --token). Defina via flags "
                "ou env BASE_PROCESSUAL_ADMIN_EMAIL/PASSWORD."
            )
            return 1
        try:
            token = login(args.api_url, args.email, args.password)
        except Exception as exc:
            log.error("Login falhou: %s", exc)
            return 1

    # Execucao
    total_processos_snap = 0
    total_lotes = 0
    erros = []
    for i, (path, ts, mode) in enumerate(plan, start=1):
        prefix = f"[{i:02d}/{len(plan):02d}]"
        log.info("%s POST %s mode=%s -> %s", prefix, ts.isoformat(), mode, path.name)
        try:
            result = post_backfill(args.api_url, token, path, ts, mode)
            novos = result.get("summary_novos", 0)
            log.info("%s   OK upload_id=%s novos=%s status=%s",
                     prefix, result.get("upload_id"), novos, result.get("status"))
            if mode == "snapshot":
                total_processos_snap += novos
            else:
                total_lotes += novos
        except Exception as exc:
            log.error("%s   FALHOU: %s", prefix, exc)
            erros.append((path.name, str(exc)))

    log.info("=" * 60)
    log.info("Resumo:")
    log.info("  Snapshot total (Primeira Tranche): %d processos", total_processos_snap)
    log.info("  Lotes historicos total: %d processos (somatorio)", total_lotes)
    log.info("  TOTAL entradas backfilladas: %d", total_processos_snap + total_lotes)
    if erros:
        log.error("  Falhas: %d", len(erros))
        for fname, err in erros:
            log.error("    - %s: %s", fname, err)
        return 2
    log.info("=" * 60)
    log.info("Backfill concluido. Confira o dashboard 'Visão Geral' -> grafico de 90d.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

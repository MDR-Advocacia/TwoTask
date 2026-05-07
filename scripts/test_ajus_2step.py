"""
Teste manual da hipotese de fluxo 2-step do AJUS, em DUAS PARTES.

Roda chamadas REAIS contra a producao do AJUS. Le credenciais do .env
na raiz do projeto. NAO depende do FastAPI/DB (so requests + dotenv).

Subcomandos:

    create    POST /inserir-prazos com situacao=A + arquivo.
              Imprime o codInformacaoJudicial pra usar no conclude.

    conclude  POST /agenda-concluir-prazos com [codInformacaoJudicial]
              recebido do create.

Uso (PowerShell, do checkout principal):

    cd "C:\\Users\\jonil\\OneDrive\\Desktop\\Projetos HUB\\OneTask - Solo\\onetask"

    # Parte 1 — cria em ABERTO com o arquivo
    python scripts/test_ajus_2step.py create `
      --pdf "C:\\temp\\habilitacao.pdf" `
      --cnj "8021090-02.2026.8.05.0001" `
      --cod 84

    # >>> CONFERIR NA UI DO AJUS QUE O ANDAMENTO APARECEU <<<
    # >>> ANOTAR O codInformacaoJudicial QUE O SCRIPT IMPRIMIU <<<

    # Parte 2 — conclui o que foi criado
    python scripts/test_ajus_2step.py conclude --cod-info 6519
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _load_creds() -> dict:
    if not ENV_PATH.exists():
        sys.exit(f"ERRO: {ENV_PATH} nao existe. Crie um .env na raiz "
                 f"com as 4 vars AJUS_*.")
    load_dotenv(ENV_PATH)
    creds = {
        "base_url": (os.getenv("AJUS_BASE_URL") or
                     "https://sistema.ajus.com.br/webservices/api").rstrip("/"),
        "bearer": os.getenv("AJUS_BEARER_TOKEN") or "",
        "cliente": os.getenv("AJUS_CLIENTE") or "",
        "login": os.getenv("AJUS_LOGIN") or "",
        "senha": os.getenv("AJUS_SENHA") or "",
    }
    missing = [k for k in ("bearer", "cliente", "login", "senha")
               if not creds[k]]
    if missing:
        sys.exit(f"ERRO: faltam no .env: "
                 f"{', '.join('AJUS_' + k.upper() for k in missing)}")
    return creds


def _headers(creds: dict) -> dict:
    return {
        "Authorization": f"Bearer {creds['bearer']}",
        "cliente": creds["cliente"],
        "Content-Type": "application/json",
    }


def _print_body_resumido(body: dict) -> None:
    safe = json.loads(json.dumps(body))
    if "login" in safe:
        safe["login"] = "***"
    if "senha" in safe:
        safe["senha"] = "***"
    for prazo in safe.get("prazos", []) or []:
        if isinstance(prazo, dict):
            for arq in prazo.get("arquivos", []) or []:
                if isinstance(arq, dict) and isinstance(arq.get("base64"), str):
                    b64 = arq["base64"]
                    arq["base64"] = (
                        f"<{len(b64)} chars, first24={b64[:24]!r}>"
                    )
    print(json.dumps(safe, indent=2, ensure_ascii=False))


def _post(creds: dict, path: str, body: dict, label: str):
    url = f"{creds['base_url']}/{path.lstrip('/')}"
    print(f"\n{BOLD}{CYAN}── {label}: POST {url} ──{RESET}")
    print(f"{BOLD}Body enviado:{RESET}")
    _print_body_resumido(body)
    try:
        r = requests.post(url, json=body, headers=_headers(creds), timeout=120)
    except requests.RequestException as exc:
        print(f"{RED}FALHA DE REDE: {exc}{RESET}")
        return None
    color = GREEN if r.status_code == 200 else RED
    print(f"\n{BOLD}Resposta:{RESET} {color}HTTP {r.status_code}{RESET} "
          f"content-type={r.headers.get('Content-Type')}")
    print(r.text)
    try:
        return r.json()
    except ValueError:
        return None


def _today_brl() -> str:
    return date.today().strftime("%d/%m/%Y")


def cmd_create(args, creds) -> int:
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"ERRO: PDF nao existe: {pdf_path}")
    pdf_bytes = pdf_path.read_bytes()
    if not pdf_bytes.startswith(b"%PDF"):
        sys.exit(f"ERRO: arquivo nao tem magic bytes de PDF (%PDF). "
                 f"Recebido: {pdf_bytes[:8]!r}")
    if len(pdf_bytes) > 10 * 1024 * 1024:
        sys.exit(f"ERRO: PDF tem {len(pdf_bytes)} bytes (>10MB, limite AJUS).")
    b64 = base64.b64encode(pdf_bytes).decode("ascii")

    print(f"{BOLD}Setup CREATE:{RESET}")
    print(f"  base_url = {creds['base_url']}")
    print(f"  cliente  = {creds['cliente']}")
    print(f"  cnj      = {args.cnj}")
    print(f"  cod      = {args.cod}")
    print(f"  pdf      = {pdf_path} ({len(pdf_bytes)} bytes, "
          f"base64 {len(b64)} chars)")
    print(f"  data     = {_today_brl()}")

    today = _today_brl()
    body = {
        "login": creds["login"],
        "senha": creds["senha"],
        "prazos": [{
            "identificadorAcao": {"numeroProcesso": args.cnj},
            "codAndamento": args.cod,
            "situacao": "A",
            "dataEvento": today,
            "dataAgendamento": today,
            "dataFatal": today,
            "informacao": (
                f"[TESTE 2-STEP] passo 1 (A) — habilitacao via API "
                f"cod={args.cod}"
            ),
            "arquivos": [{"nome": "habilitacao.pdf", "base64": b64}],
        }],
    }
    resp = _post(creds, "inserir-prazos", body,
                 "PASSO 1: inserir-prazos (situacao=A + arquivo)")
    if not (resp and isinstance(resp, list) and resp):
        print(f"\n{RED}Resposta inesperada — abortando.{RESET}")
        return 1
    item = resp[0]
    inserido = bool(item.get("inserido"))
    cod_info = item.get("codInformacaoJudicial")
    msg = item.get("msg")

    print()
    if inserido and cod_info:
        print(f"{BOLD}{GREEN}╔══════════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}{GREEN}║  PASSO 1 OK — andamento criado em ABERTO    ║{RESET}")
        print(f"{BOLD}{GREEN}║                                              ║{RESET}")
        print(f"{BOLD}{GREEN}║  codInformacaoJudicial = {cod_info:<20s}║{RESET}")
        print(f"{BOLD}{GREEN}╚══════════════════════════════════════════════╝{RESET}")
        print(f"\n{BOLD}Proximos passos:{RESET}")
        print(f"  1. Confere na UI do AJUS que o andamento aparece "
              f"no processo {args.cnj}")
        print(f"  2. Confere que o PDF da habilitacao esta anexado nele")
        print(f"  3. Quando estiver tudo OK, roda o passo 2:")
        print(f"\n     {CYAN}python scripts/test_ajus_2step.py "
              f"conclude --cod-info {cod_info}{RESET}\n")
        return 0
    else:
        print(f"{BOLD}{RED}PASSO 1 FALHOU{RESET}")
        print(f"  inserido = {inserido}")
        print(f"  cod      = {cod_info!r}")
        print(f"  msg      = {msg!r}")
        return 1


def cmd_conclude(args, creds) -> int:
    try:
        cod_int = int(args.cod_info)
    except (TypeError, ValueError):
        sys.exit(f"ERRO: --cod-info deve ser inteiro. "
                 f"Recebido: {args.cod_info!r}")

    print(f"{BOLD}Setup CONCLUDE:{RESET}")
    print(f"  base_url = {creds['base_url']}")
    print(f"  cliente  = {creds['cliente']}")
    print(f"  cod_info = {cod_int}")

    body = {
        "login": creds["login"],
        "senha": creds["senha"],
        "prazos": [cod_int],
    }
    resp = _post(creds, "agenda-concluir-prazos", body,
                 "PASSO 2: agenda-concluir-prazos")
    if not (resp and isinstance(resp, dict)):
        print(f"\n{RED}Resposta inesperada — abortando.{RESET}")
        return 1

    concluidos = [str(c) for c in (resp.get("concluidos") or [])]
    nao_loc = [str(c) for c in (resp.get("nao-localizados") or [])]
    erros = resp.get("erros") or []
    cod_str = str(cod_int)

    print()
    if cod_str in concluidos:
        print(f"{BOLD}{GREEN}╔══════════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}{GREEN}║  PASSO 2 OK — andamento concluido            ║{RESET}")
        print(f"{BOLD}{GREEN}║  cod={cod_int:<10d}                            ║{RESET}")
        print(f"{BOLD}{GREEN}║                                              ║{RESET}")
        print(f"{BOLD}{GREEN}║  >>> FLUXO 2-STEP CONFIRMADO <<<             ║{RESET}")
        print(f"{BOLD}{GREEN}╚══════════════════════════════════════════════╝{RESET}")
        return 0
    if cod_str in nao_loc:
        print(f"{BOLD}{RED}PASSO 2 FALHOU — cod {cod_str} em "
              f"`nao-localizados`. Estranho — ele foi criado agora.{RESET}")
        return 1
    if erros:
        print(f"{BOLD}{RED}PASSO 2 FALHOU — cod {cod_str} em `erros`:{RESET}")
        print(json.dumps(erros, indent=2, ensure_ascii=False))
        return 1
    print(f"{BOLD}{YELLOW}PASSO 2: cod {cod_str} nao apareceu em "
          f"nenhuma das 3 listas. Ver body acima.{RESET}")
    return 1


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Teste manual do fluxo 2-step da AJUS (create -> conclude)."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("create", help="Passo 1: cria em A com arquivo.")
    pc.add_argument("--pdf", required=True, help="Caminho pro PDF.")
    pc.add_argument("--cnj", required=True,
                    help="CNJ mascarado do processo.")
    pc.add_argument("--cod", default="84",
                    help="codAndamento (default: 84 HABILITACAO).")

    pk = sub.add_parser("conclude", help="Passo 2: conclui o cod do passo 1.")
    pk.add_argument("--cod-info", required=True,
                    help="codInformacaoJudicial retornado pelo create.")

    args = p.parse_args()
    creds = _load_creds()

    if args.cmd == "create":
        return cmd_create(args, creds)
    if args.cmd == "conclude":
        return cmd_conclude(args, creds)
    return 2


if __name__ == "__main__":
    sys.exit(main())

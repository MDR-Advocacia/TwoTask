"""Ingestão diária do Minha Equipe via DOWNLOAD do relatório "Agenda Analytics".

O L1 gera esse relatório (denormalizado — mesmo formato do seed) todo dia de
manhã. Em vez de remontar via API, baixamos o arquivo pronto e ingerimos:

  sessão web (reuso do login .ASPXAUTH, filelock) →
  GET /agenda/reportagenda/Search → acha o "Agenda Analytics" mais recente →
  GET /shared/ReportShared/GetFile/{id} → parser do seed (replace) + classify.

O roster (perf_pessoa) NÃO é tocado — só as tarefas. Validado 2026-06-26:
relatório do dia = ~365k linhas, header idêntico ao parser.
"""

import datetime
import json
import logging
import re

import requests

logger = logging.getLogger(__name__)

_REPORT_PATH = "/tmp/perf_agenda_latest.xlsx"
_LIST_URL = "/agenda/reportagenda/Search"
SETTING_LAST_SYNC = "perf_minha_equipe_last_sync"

# Linha do relatório na lista: id do GetFile + título + 1ª data (dd/mm/aaaa) logo após.
_ROW_RE = re.compile(
    r'GetFile/(\d+)">([^<]*Agenda Analytics[^<]*)</a>.{0,200}?(\d{2}/\d{2}/\d{4})',
    re.DOTALL,
)

try:
    from zoneinfo import ZoneInfo

    _BRT = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    _BRT = None


def _now():
    return datetime.datetime.now(tz=_BRT) if _BRT else datetime.datetime.now()


def _hoje_str() -> str:
    return _now().strftime("%d/%m/%Y")


def _session() -> requests.Session:
    """Sessão HTTP autenticada reusando o login .ASPXAUTH existente (filelock/TTL)."""
    from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
        LegacyTaskHttpCancellationService,
    )

    cookies = LegacyTaskHttpCancellationService()._ensure_session()
    s = requests.Session()
    for k, v in cookies.items():
        s.cookies.set(k, v)
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    return s


def _find_latest(session: requests.Session, base: str):
    html = session.get(base + _LIST_URL, timeout=60).text
    m = _ROW_RE.search(html)
    if not m:
        return None
    return {"id": m.group(1), "title": m.group(2).strip(), "data": m.group(3)}


def baixar_e_ingerir(db, *, force: bool = False) -> dict:
    """Baixa o relatório do dia e ingere. force=True ingere o mais recente mesmo
    que não seja de hoje (ex.: botão "Atualizar agora")."""
    from app.services.prazos_iniciais.legacy_task_helpers import web_base_url

    base = web_base_url()
    session = _session()
    rel = _find_latest(session, base)
    if not rel:
        return {"ok": False, "motivo": "relatorio_nao_encontrado"}

    hoje = _hoje_str()
    if rel["data"] != hoje and not force:
        return {
            "ok": False,
            "motivo": "relatorio_do_dia_ainda_nao_gerado",
            "ultima_data": rel["data"],
            "hoje": hoje,
        }

    resp = session.get(f"{base}/shared/ReportShared/GetFile/{rel['id']}", timeout=300)
    resp.raise_for_status()
    with open(_REPORT_PATH, "wb") as f:
        f.write(resp.content)

    # Parser do seed (replace total) + classify, mantendo o roster intacto.
    from app.models.performance import PerfPessoa
    from app.services.performance.seed import classify_subtipos, seed_tarefas

    name_to_id = {p.nome_norm: p.id for p in db.query(PerfPessoa).all()}
    n = seed_tarefas(db, name_to_id, agenda_path=_REPORT_PATH)
    classify_subtipos(db)

    info = {
        "ok": True,
        "tarefas": n,
        "relatorio": rel["title"],
        "data": rel["data"],
        "bytes": len(resp.content),
        "em": _now().isoformat(),
    }
    _set_last_sync(info)
    logger.info("Minha Equipe ingest: %s tarefas do relatório '%s' (%s).", n, rel["title"], rel["data"])
    return info


def _set_last_sync(info: dict) -> None:
    from app.services.app_settings import set_setting

    set_setting(SETTING_LAST_SYNC, json.dumps(info, ensure_ascii=False))


def get_last_sync():
    from app.services.app_settings import get_setting

    raw = get_setting(SETTING_LAST_SYNC, default=None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def ja_sincronizou_hoje() -> bool:
    ls = get_last_sync()
    return bool(ls and ls.get("ok") and ls.get("data") == _hoje_str())

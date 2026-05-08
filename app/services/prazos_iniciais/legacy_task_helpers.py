"""
Helpers compartilhados para resolucao de "legacy task" no Legal One.

Substitui `legacy_task_cancellation_service.py` (versao Playwright clickflow,
deprecada em 2026-05-08) — mantem apenas a parte de **resolucao** (CNJ ->
lawsuit_id -> task selection via API L1) + paths/credenciais que o
LegacyTaskHttpCancellationService precisa.

O cancelamento real agora e' 100% HTTP (POST direto no endpoint
`/processos/CompromissoTarefa/ModalEnvolvimentoEmLote`); o subprocess
Node/Playwright sobrevive APENAS pra fazer o login OnePass inicial e
exportar cookie `.ASPXAUTH` (modo `--login-only` no `cancel-legacy-task.js`).
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from app.core.config import settings
from app.services.legal_one_client import LegalOneApiClient

logger = logging.getLogger(__name__)


# ── Constantes ────────────────────────────────────────────────────────

# Tipo/subtipo da legacy task que vamos cancelar (configurado pelo
# operador no L1 — pode mudar caso a casa migre para outro template).
DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID = 33
DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID = 1283
# Status da task no L1 que ainda permitem cancelar (0 = Pendente,
# 3 = Cancelada — repetir cancel em ja-cancelada e' no-op).
DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS = (0,)
# Status alvo (3 = Cancelada).
DEFAULT_CANCELLED_STATUS_ID = 3
DEFAULT_CANCELLED_STATUS_TEXT = "Cancelado"
# Base URL do L1 web (Novajus/Thomson Reuters).
DEFAULT_LEGAL_ONE_WEB_BASE_URL = "https://mdradvocacia.novajus.com.br"


# ── Helpers stateless ─────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_cnj(cnj_number: Optional[str]) -> Optional[str]:
    if cnj_number is None:
        return None
    cleaned = str(cnj_number).strip()
    return cleaned or None


# ── Resolver de paths e credenciais (subprocess Node) ─────────────────


def resolve_project_root() -> Path:
    """
    Raiz do projeto — quatro niveis acima desse arquivo
    (app/services/prazos_iniciais/legacy_task_helpers.py -> repo root).
    """
    return Path(__file__).resolve().parents[3]


def resolve_output_root() -> Path:
    return (
        resolve_project_root()
        / "output"
        / "playwright"
        / "legalone"
        / "prazos-iniciais"
        / "legacy-task-cancellation"
    )


def resolve_runner_script() -> Path:
    """Caminho do `cancel-legacy-task.js` (modo `--login-only` apenas)."""
    return (
        resolve_project_root()
        / "app"
        / "runners"
        / "legalone"
        / "cancel-legacy-task.js"
    )


def resolve_node_binary() -> str:
    candidate = shutil.which("node") or shutil.which("node.exe")
    if not candidate:
        raise RuntimeError(
            "Node.js nao encontrado no PATH. Instale o Node para executar "
            "o runner Playwright (modo --login-only)."
        )
    return candidate


def resolve_web_credentials() -> dict[str, str]:
    """
    Credenciais OnePass do L1 web. Lidas via settings (env vars no Coolify).
    Aceita os dois formatos LEGAL_ONE_* e LEGALONE_* por compat com runners
    antigos.
    """
    username = (
        settings.legal_one_web_username
        or os.getenv("LEGAL_ONE_WEB_USERNAME")
        or os.getenv("LEGALONE_WEB_USERNAME")
    )
    password = (
        settings.legal_one_web_password
        or os.getenv("LEGAL_ONE_WEB_PASSWORD")
        or os.getenv("LEGALONE_WEB_PASSWORD")
    )
    key_label = (
        settings.legal_one_web_key_label
        or os.getenv("LEGAL_ONE_WEB_KEY_LABEL")
        or os.getenv("LEGALONE_WEB_KEY_LABEL")
    )
    missing = [
        name
        for name, value in {
            "LEGAL_ONE_WEB_USERNAME": username,
            "LEGAL_ONE_WEB_PASSWORD": password,
            "LEGAL_ONE_WEB_KEY_LABEL": key_label,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Credenciais web do Legal One ausentes para login: "
            + ", ".join(missing)
        )
    return {
        "LEGAL_ONE_WEB_USERNAME": username,
        "LEGAL_ONE_WEB_PASSWORD": password,
        "LEGAL_ONE_WEB_KEY_LABEL": key_label,
        "LEGALONE_WEB_USERNAME": username,
        "LEGALONE_WEB_PASSWORD": password,
        "LEGALONE_WEB_KEY_LABEL": key_label,
    }


def web_base_url() -> str:
    return (
        os.getenv("LEGAL_ONE_WEB_URL")
        or os.getenv("LEGALONE_WEB_URL")
        or DEFAULT_LEGAL_ONE_WEB_BASE_URL
    ).rstrip("/")


def build_task_urls(
    task_id: int,
    lawsuit_id: Optional[int] = None,
) -> dict[str, str]:
    """
    URLs do L1 web pra task. Usado pra retornar links uteis no payload de
    cancelamento (exibidos na UI/painel pra abrir a tarefa direto no L1).
    """
    base = web_base_url()
    if lawsuit_id is not None:
        details_relative = (
            f"/processos/processos/DetailsCompromissosTarefas/{lawsuit_id}"
            "?renderOnlySection=True"
        )
        details_url = f"{base}{details_relative}"
        edit_url = (
            f"{base}/processos/tarefas/edittarefa/{task_id}"
            f"?parentId={lawsuit_id}&tipoContexto=1"
            f"&returnUrl={quote(details_relative, safe='')}"
        )
        return {"edit_url": edit_url, "details_url": details_url}

    details_relative = (
        f"/agenda/tarefas/DetailsCompromissoTarefa/{task_id}"
        "?currentPage=1&hasNavigation=True"
    )
    details_url = f"{base}{details_relative}"
    edit_url = (
        f"{base}/agenda/Tarefas/EditCompromissoTarefa/"
        f"{task_id}?returnUrl={quote(details_relative, safe='')}"
    )
    return {"edit_url": edit_url, "details_url": details_url}


# ── Resolver de target task via API L1 ────────────────────────────────


class LegacyTaskResolver:
    """
    Resolve a "legacy task" alvo (Verificar Prazos e Habilitacao) no L1
    a partir de identificadores parciais — cnj_number e/ou lawsuit_id
    e/ou task_id. Usa a API REST do L1 (LegalOneApiClient).

    Saidas possiveis (campo `reason` no dict de retorno):
      - "task_selected": achou; segue pro cancelamento.
      - "task_not_found": existem tasks vinculadas, mas nenhuma com tipo/
        subtipo/status configurados — terminal silencioso.
      - "lawsuit_not_found": cnj_number invalido / processo nao cadastrado.
    """

    def __init__(self, *, client: Optional[LegalOneApiClient] = None):
        self.client = client or LegalOneApiClient()
        self.logger = logging.getLogger(__name__)

    def extract_lawsuit_id_from_relationships(
        self, task_id: int
    ) -> Optional[int]:
        try:
            relationships = self.client.get_task_relationships(task_id)
        except Exception:
            self.logger.exception(
                "Falha ao buscar relacionamentos da tarefa %s.", task_id
            )
            return None
        for rel in relationships:
            if rel.get("linkType") != "Litigation":
                continue
            lawsuit_id = _to_int(rel.get("linkId"))
            if lawsuit_id is not None:
                return lawsuit_id
        return None

    @staticmethod
    def select_task_candidate(
        tasks: list[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        """Mais recente vence (creationDate desc, taskId desc como tiebreak)."""
        if not tasks:
            return None

        def _key(task: dict[str, Any]) -> tuple[str, int]:
            creation_date = str(task.get("creationDate") or "")
            tid = _to_int(task.get("id")) or 0
            return creation_date, tid

        return sorted(tasks, key=_key, reverse=True)[0]

    def resolve_target_task(
        self,
        *,
        cnj_number: Optional[str],
        lawsuit_id: Optional[int],
        task_id: Optional[int],
        task_type_external_id: int,
        task_subtype_external_id: int,
        candidate_status_ids: list[int],
    ) -> dict[str, Any]:
        normalized_cnj = _normalize_cnj(cnj_number)
        resolved_lawsuit_id = _to_int(lawsuit_id)

        # Caminho rapido: ja temos task_id
        if task_id is not None:
            try:
                task = self.client.get_task_by_id(task_id)
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    return {
                        "reason": "task_not_found",
                        "success": False,
                        "cnj_number": normalized_cnj,
                        "lawsuit_id": resolved_lawsuit_id,
                        "task_id": task_id,
                        "candidate_count": 0,
                        "selected_task": None,
                    }
                raise

            if resolved_lawsuit_id is None:
                resolved_lawsuit_id = self.extract_lawsuit_id_from_relationships(
                    task_id
                )
            return {
                "reason": "task_selected",
                "success": True,
                "cnj_number": normalized_cnj,
                "lawsuit_id": resolved_lawsuit_id,
                "task_id": task_id,
                "candidate_count": 1,
                "selected_task": task,
            }

        # Sem task_id: precisamos de lawsuit_id (ou cnj_number pra resolver)
        if resolved_lawsuit_id is None:
            if not normalized_cnj:
                raise ValueError(
                    "Informe ao menos um identificador: cnj_number, "
                    "lawsuit_id ou task_id."
                )
            lawsuit = self.client.search_lawsuit_by_cnj(normalized_cnj)
            if not lawsuit:
                return {
                    "reason": "lawsuit_not_found",
                    "success": False,
                    "cnj_number": normalized_cnj,
                    "lawsuit_id": None,
                    "task_id": None,
                    "candidate_count": 0,
                    "selected_task": None,
                }
            resolved_lawsuit_id = _to_int(lawsuit.get("id"))
            normalized_cnj = (
                _normalize_cnj(lawsuit.get("identifierNumber")) or normalized_cnj
            )

        matching_tasks = self.client.find_tasks_for_lawsuit(
            resolved_lawsuit_id,
            type_id=task_type_external_id,
            subtype_id=task_subtype_external_id,
            status_ids=candidate_status_ids,
            top=25,
        )
        selected_task = self.select_task_candidate(matching_tasks)
        if selected_task is None:
            return {
                "reason": "task_not_found",
                "success": False,
                "cnj_number": normalized_cnj,
                "lawsuit_id": resolved_lawsuit_id,
                "task_id": None,
                "candidate_count": len(matching_tasks),
                "selected_task": None,
            }

        return {
            "reason": "task_selected",
            "success": True,
            "cnj_number": normalized_cnj,
            "lawsuit_id": resolved_lawsuit_id,
            "task_id": _to_int(selected_task.get("id")),
            "candidate_count": len(matching_tasks),
            "selected_task": selected_task,
        }

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

from app.core.config import settings
from app.services.legal_one_client import LegalOneApiClient

logger = logging.getLogger(__name__)


DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID = 33
DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID = 1283
DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS = (0,)
DEFAULT_CANCELLED_STATUS_ID = 3
DEFAULT_CANCELLED_STATUS_TEXT = "Cancelado"
DEFAULT_LEGAL_ONE_WEB_BASE_URL = "https://mdradvocacia.novajus.com.br"

RUNNER_SUCCESS_STATUSES = {"cancelled", "already_cancelled"}

# Substrings (lowercase) que classificam falhas do runner para alimentar
# o circuit breaker e a UI:
#  - layout_drift     → tela do L1 mudou (campo/seletor não encontrado)
#  - auth_failure     → não autenticou (signon/login/senha/redirecionado)
#  - timeout          → playwright/HTTP estourou timeout
#  - verification_failed → POST passou mas o status final não bateu com o alvo
# Falhas de dado (task_not_found, lawsuit_not_found) já vêm com `reason`
# explícito do _resolve_target_task e não passam por aqui.
LAYOUT_DRIFT_HINTS = (
    "selector",
    "selectorerror",
    "locator",
    "waiting for selector",
    "no element found",
    "element is not attached",
    "element is not visible",
    "element is not enabled",
    "expected to find",
    "form not found",
    "not visible",
    "not editable",
    "cannot click",
    "is not clickable",
    "campo não encontrado",
    "campo nao encontrado",
)
AUTH_FAILURE_HINTS = (
    "signon",
    "sign-on",
    "/login",
    "logon",
    "credenciais",
    "credentials",
    "invalid credentials",
    "unauthorized",
    "401",
    "403",
    "redirected to login",
    "redirected to /login",
    "password",
    "senha",
    "autenticacao",
    "autenticação",
)
TIMEOUT_HINTS = (
    "timeout",
    "timed out",
    "etimedout",
    "page.waitfor",
    "navigation timeout",
)
VERIFICATION_HINTS = (
    "verifiedstatus",
    "status verification",
    "verifica status",
    "expected status",
    "status esperado",
    "status final diferente",
)


@dataclass(frozen=True)
class LegacyTaskRunnerPaths:
    run_dir: Path
    input: Path
    status: Path
    log: Path
    error_log: Path
    artifacts: Path


class LegacyTaskCancellationService:
    """
    Cancela a task legado de "Agendar Prazos" no Legal One.

    Fluxo:
      1. Resolve o processo (CNJ -> lawsuit_id), quando necessario.
      2. Busca a task vinculada ao processo por tipo/subtipo/status.
      3. Executa o runner Playwright que abre a tela de edicao da task e
         altera o status para cancelado.
    """

    def __init__(self, *, client: Optional[LegalOneApiClient] = None):
        self.client = client or LegalOneApiClient()
        self.logger = logging.getLogger(__name__)

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _read_json_file(file_path: Path, fallback: Any = None) -> Any:
        try:
            raw = file_path.read_text(encoding="utf-8").replace("\ufeff", "")
            return json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            return fallback

    @staticmethod
    def _classify_runner_error(
        *,
        runner_state: Optional[str],
        runner_item_status: Optional[str],
        runner_error: Optional[str],
    ) -> str:
        """
        Resolve uma categoria estável a partir do erro do runner Playwright.

        Uso a jusante: alimentar o circuit breaker (auth_failure/timeout
        contam, layout_drift/verification_failed não) e a UI (badge por
        categoria em vez de stack trace cru).

        Categorias:
          - auth_failure        → infra (login OnePass falhou/redirecionou)
          - timeout             → infra (Playwright/HTTP estourou)
          - layout_drift        → dado/L1 mudou (seletor/elemento sumiu)
          - verification_failed → dado (status final não bateu com o alvo)
          - runner_error        → fallback genérico
        """
        if runner_item_status in {"cancelled", "already_cancelled"}:
            return runner_item_status

        text = " ".join(
            part.lower()
            for part in (runner_state or "", runner_item_status or "", runner_error or "")
            if part
        )
        if not text.strip():
            return "runner_error"

        if any(hint in text for hint in AUTH_FAILURE_HINTS):
            return "auth_failure"
        if any(hint in text for hint in TIMEOUT_HINTS):
            return "timeout"
        if any(hint in text for hint in LAYOUT_DRIFT_HINTS):
            return "layout_drift"
        if any(hint in text for hint in VERIFICATION_HINTS):
            return "verification_failed"
        return "runner_error"

    @staticmethod
    def _normalize_cnj(cnj_number: Optional[str]) -> Optional[str]:
        if cnj_number is None:
            return None
        cleaned = str(cnj_number).strip()
        return cleaned or None

    def _resolve_project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _resolve_output_root(self) -> Path:
        return (
            self._resolve_project_root()
            / "output"
            / "playwright"
            / "legalone"
            / "prazos-iniciais"
            / "legacy-task-cancellation"
        )

    def _resolve_runner_script(self) -> Path:
        return (
            self._resolve_project_root()
            / "app"
            / "runners"
            / "legalone"
            / "cancel-legacy-task.js"
        )

    def _resolve_node_binary(self) -> str:
        candidate = shutil.which("node") or shutil.which("node.exe")
        if not candidate:
            raise RuntimeError(
                "Node.js nao encontrado no PATH. Instale o Node para executar o runner Playwright."
            )
        return candidate

    def _resolve_credentials(self) -> dict[str, str]:
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
                "Credenciais web do Legal One ausentes para cancelar a task legado: "
                + ", ".join(missing)
            )

        return {
            # Mantemos os dois formatos por compatibilidade com runners antigos
            # e com o carregamento do Pydantic via .env.
            "LEGAL_ONE_WEB_USERNAME": username,
            "LEGAL_ONE_WEB_PASSWORD": password,
            "LEGAL_ONE_WEB_KEY_LABEL": key_label,
            "LEGALONE_WEB_USERNAME": username,
            "LEGALONE_WEB_PASSWORD": password,
            "LEGALONE_WEB_KEY_LABEL": key_label,
        }

    def _build_run_paths(self, task_id: int) -> LegacyTaskRunnerPaths:
        stamp = self._utcnow().strftime("%Y%m%d-%H%M%S-%f")
        run_dir = self._resolve_output_root() / f"task-{task_id}-{stamp}"
        return LegacyTaskRunnerPaths(
            run_dir=run_dir,
            input=run_dir / "input.json",
            status=run_dir / "status.json",
            log=run_dir / "runner.log",
            error_log=run_dir / "runner.err.log",
            artifacts=run_dir / "artifacts",
        )

    def _build_task_urls(self, task_id: int) -> dict[str, str]:
        web_base_url = (
            os.getenv("LEGAL_ONE_WEB_URL")
            or os.getenv("LEGALONE_WEB_URL")
            or DEFAULT_LEGAL_ONE_WEB_BASE_URL
        ).rstrip("/")
        details_relative = (
            f"/agenda/tarefas/DetailsCompromissoTarefa/{task_id}"
            "?currentPage=1&hasNavigation=True"
        )
        details_url = f"{web_base_url}{details_relative}"
        edit_url = (
            f"{web_base_url}/agenda/Tarefas/EditCompromissoTarefa/"
            f"{task_id}?returnUrl={quote(details_relative, safe='')}"
        )
        return {
            "edit_url": edit_url,
            "details_url": details_url,
        }

    def _extract_lawsuit_id_from_relationships(self, task_id: int) -> Optional[int]:
        try:
            relationships = self.client.get_task_relationships(task_id)
        except Exception:
            self.logger.exception(
                "Falha ao buscar relacionamentos da tarefa %s.", task_id
            )
            return None

        for relationship in relationships:
            if relationship.get("linkType") != "Litigation":
                continue
            lawsuit_id = self._to_int(relationship.get("linkId"))
            if lawsuit_id is not None:
                return lawsuit_id
        return None

    def _select_task_candidate(self, tasks: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not tasks:
            return None

        def _sort_key(task: dict[str, Any]) -> tuple[str, int]:
            creation_date = str(task.get("creationDate") or "")
            task_id = self._to_int(task.get("id")) or 0
            return creation_date, task_id

        return sorted(tasks, key=_sort_key, reverse=True)[0]

    def _resolve_target_task(
        self,
        *,
        cnj_number: Optional[str],
        lawsuit_id: Optional[int],
        task_id: Optional[int],
        task_type_external_id: int,
        task_subtype_external_id: int,
        candidate_status_ids: list[int],
    ) -> dict[str, Any]:
        normalized_cnj = self._normalize_cnj(cnj_number)
        resolved_lawsuit_id = self._to_int(lawsuit_id)

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
                resolved_lawsuit_id = self._extract_lawsuit_id_from_relationships(task_id)

            return {
                "reason": "task_selected",
                "success": True,
                "cnj_number": normalized_cnj,
                "lawsuit_id": resolved_lawsuit_id,
                "task_id": task_id,
                "candidate_count": 1,
                "selected_task": task,
            }

        if resolved_lawsuit_id is None:
            if not normalized_cnj:
                raise ValueError(
                    "Informe ao menos um identificador: cnj_number, lawsuit_id ou task_id."
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
            resolved_lawsuit_id = self._to_int(lawsuit.get("id"))
            normalized_cnj = (
                self._normalize_cnj(lawsuit.get("identifierNumber")) or normalized_cnj
            )

        matching_tasks = self.client.find_tasks_for_lawsuit(
            resolved_lawsuit_id,
            type_id=task_type_external_id,
            subtype_id=task_subtype_external_id,
            status_ids=candidate_status_ids,
            top=25,
        )
        selected_task = self._select_task_candidate(matching_tasks)
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
            "task_id": self._to_int(selected_task.get("id")),
            "candidate_count": len(matching_tasks),
            "selected_task": selected_task,
        }

    def _build_runner_items(
        self,
        *,
        cnj_number: Optional[str],
        lawsuit_id: Optional[int],
        task: dict[str, Any],
        target_status_id: int,
        target_status_text: str,
    ) -> list[dict[str, Any]]:
        task_id = self._to_int(task.get("id"))
        if task_id is None:
            raise ValueError("A tarefa selecionada nao possui ID valido.")

        urls = self._build_task_urls(task_id)
        return [
            {
                "index": 1,
                "sequenceNumber": "0001",
                "cnj": cnj_number,
                "lawsuitId": lawsuit_id,
                "taskId": task_id,
                "description": task.get("description"),
                "currentStatusId": self._to_int(task.get("statusId")),
                "targetStatusId": int(target_status_id),
                "targetStatusText": target_status_text,
                "editUrl": urls["edit_url"],
                "detailsUrl": urls["details_url"],
            }
        ]

    def _run_runner(
        self,
        *,
        paths: LegacyTaskRunnerPaths,
        runner_items: list[dict[str, Any]],
        max_attempts: int,
    ) -> dict[str, Any]:
        runner_script = self._resolve_runner_script()
        if not runner_script.exists():
            raise RuntimeError(f"Runner Playwright nao encontrado em {runner_script}")

        node_binary = self._resolve_node_binary()
        credentials = self._resolve_credentials()

        paths.run_dir.mkdir(parents=True, exist_ok=True)
        paths.artifacts.mkdir(parents=True, exist_ok=True)
        paths.log.touch(exist_ok=True)
        paths.error_log.touch(exist_ok=True)
        paths.input.write_text(
            json.dumps(runner_items, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        command = [
            node_binary,
            str(runner_script),
            "--input",
            str(paths.input),
            "--output",
            str(paths.status),
            "--artifacts-dir",
            str(paths.artifacts),
            "--max-attempts",
            str(max(1, int(max_attempts))),
        ]

        env = {**os.environ, **credentials}
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with paths.log.open("ab") as stdout, paths.error_log.open("ab") as stderr:
            completed = subprocess.run(  # noqa: S603
                command,
                cwd=str(runner_script.parent),
                env=env,
                stdout=stdout,
                stderr=stderr,
                creationflags=creation_flags,
                check=False,
            )

        payload = self._read_json_file(paths.status, fallback=None)
        if not isinstance(payload, dict):
            error_preview = ""
            try:
                error_preview = paths.error_log.read_text(
                    encoding="utf-8", errors="ignore"
                )[-2000:]
            except OSError:
                error_preview = ""
            raise RuntimeError(
                "Runner de cancelamento nao gerou status valido "
                f"(exit_code={completed.returncode}). {error_preview}".strip()
            )

        payload["process_exit_code"] = completed.returncode
        return payload

    def cancel_task(
        self,
        *,
        cnj_number: Optional[str] = None,
        lawsuit_id: Optional[int] = None,
        task_id: Optional[int] = None,
        task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        candidate_status_ids: Optional[list[int]] = None,
        target_status_id: int = DEFAULT_CANCELLED_STATUS_ID,
        target_status_text: str = DEFAULT_CANCELLED_STATUS_TEXT,
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        candidate_status_ids = list(
            candidate_status_ids or DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS
        )
        resolution = self._resolve_target_task(
            cnj_number=cnj_number,
            lawsuit_id=lawsuit_id,
            task_id=task_id,
            task_type_external_id=task_type_external_id,
            task_subtype_external_id=task_subtype_external_id,
            candidate_status_ids=candidate_status_ids,
        )

        selected_task = resolution.get("selected_task")
        resolved_task_id = resolution.get("task_id")
        resolved_lawsuit_id = resolution.get("lawsuit_id")
        normalized_cnj = resolution.get("cnj_number")

        urls = (
            self._build_task_urls(resolved_task_id)
            if resolved_task_id is not None
            else {"edit_url": None, "details_url": None}
        )

        if not resolution.get("success"):
            return {
                "success": False,
                "reason": resolution["reason"],
                "cnj_number": normalized_cnj,
                "lawsuit_id": resolved_lawsuit_id,
                "task_id": resolved_task_id,
                "candidate_count": resolution.get("candidate_count"),
                "selected_task": None,
                "current_status_id": None,
                "target_status_id": int(target_status_id),
                "target_status_text": target_status_text,
                "runner_state": None,
                "runner_item_status": None,
                "runner_response": None,
                "runner_error": None,
                "process_exit_code": None,
                "status_file_path": None,
                "log_file_path": None,
                "error_log_file_path": None,
                "artifacts_dir": None,
                "edit_url": urls["edit_url"],
                "details_url": urls["details_url"],
            }

        current_status_id = self._to_int(selected_task.get("statusId"))
        if current_status_id == int(target_status_id):
            return {
                "success": True,
                "reason": "already_in_target_status",
                "cnj_number": normalized_cnj,
                "lawsuit_id": resolved_lawsuit_id,
                "task_id": resolved_task_id,
                "candidate_count": resolution.get("candidate_count"),
                "selected_task": selected_task,
                "current_status_id": current_status_id,
                "target_status_id": int(target_status_id),
                "target_status_text": target_status_text,
                "runner_state": "completed",
                "runner_item_status": "already_cancelled",
                "runner_response": {
                    "verifiedStatusId": current_status_id,
                    "verifiedStatusText": target_status_text,
                },
                "runner_error": None,
                "process_exit_code": 0,
                "status_file_path": None,
                "log_file_path": None,
                "error_log_file_path": None,
                "artifacts_dir": None,
                "edit_url": urls["edit_url"],
                "details_url": urls["details_url"],
            }

        runner_items = self._build_runner_items(
            cnj_number=normalized_cnj,
            lawsuit_id=resolved_lawsuit_id,
            task=selected_task,
            target_status_id=target_status_id,
            target_status_text=target_status_text,
        )
        paths = self._build_run_paths(resolved_task_id)
        payload = self._run_runner(
            paths=paths,
            runner_items=runner_items,
            max_attempts=max_attempts,
        )

        items = payload.get("items") or []
        item_payload = items[0] if items else {}
        runner_item_status = item_payload.get("status")
        runner_state = payload.get("state")
        runner_error = item_payload.get("error") or payload.get("error")

        success = (
            runner_state == "completed"
            and runner_item_status in RUNNER_SUCCESS_STATUSES
        )

        # Em sucesso mantemos o status do runner como reason (cancelled/
        # already_cancelled — entram em QUEUE_SUCCESS_REASONS). Em falha,
        # classificamos a categoria do erro pra alimentar o circuit breaker
        # (auth_failure/timeout contam, layout_drift/verification_failed não)
        # e pra UI exibir um badge estável.
        if success:
            reason = runner_item_status
        else:
            reason = self._classify_runner_error(
                runner_state=runner_state,
                runner_item_status=runner_item_status,
                runner_error=runner_error,
            )

        return {
            "success": success,
            "reason": reason,
            "cnj_number": normalized_cnj,
            "lawsuit_id": resolved_lawsuit_id,
            "task_id": resolved_task_id,
            "candidate_count": resolution.get("candidate_count"),
            "selected_task": selected_task,
            "current_status_id": current_status_id,
            "target_status_id": int(target_status_id),
            "target_status_text": target_status_text,
            "runner_state": runner_state,
            "runner_item_status": runner_item_status,
            "runner_response": item_payload.get("response"),
            "runner_error": runner_error,
            "process_exit_code": payload.get("process_exit_code"),
            "status_file_path": str(paths.status),
            "log_file_path": str(paths.log),
            "error_log_file_path": str(paths.error_log),
            "artifacts_dir": str(paths.artifacts),
            "edit_url": urls["edit_url"],
            "details_url": urls["details_url"],
        }

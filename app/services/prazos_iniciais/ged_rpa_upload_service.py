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

from app.core.config import settings
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGAL_ONE_WEB_BASE_URL,
    _mirror_runner_log_to_stdout,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GedRpaRunnerPaths:
    run_dir: Path
    input: Path
    status: Path
    log: Path
    error_log: Path
    artifacts: Path


class GedRpaUploadService:
    """
    Upload de documento GED via interface web do Legal One.

    Esse caminho existe como fallback operacional para o upload ECM API, que
    retorna "File not found in Storage" mesmo apos PUT do blob com HTTP 201.
    """

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _resolve_project_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _resolve_output_root(self) -> Path:
        return (
            self._resolve_project_root()
            / "output"
            / "playwright"
            / "legalone"
            / "prazos-iniciais"
            / "ged-upload"
        )

    def _resolve_runner_script(self) -> Path:
        return (
            self._resolve_project_root()
            / "app"
            / "runners"
            / "legalone"
            / "upload-ged-document.js"
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
        web_url = (
            os.getenv("LEGAL_ONE_WEB_URL")
            or os.getenv("LEGALONE_WEB_URL")
            or DEFAULT_LEGAL_ONE_WEB_BASE_URL
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
                "Credenciais web do Legal One ausentes para upload GED via RPA: "
                + ", ".join(missing)
            )

        return {
            "LEGAL_ONE_WEB_USERNAME": username,
            "LEGAL_ONE_WEB_PASSWORD": password,
            "LEGAL_ONE_WEB_KEY_LABEL": key_label,
            "LEGALONE_WEB_USERNAME": username,
            "LEGALONE_WEB_PASSWORD": password,
            "LEGALONE_WEB_KEY_LABEL": key_label,
            "LEGAL_ONE_WEB_URL": web_url,
            "LEGALONE_WEB_URL": web_url,
        }

    def _build_run_paths(self, intake_id: int) -> GedRpaRunnerPaths:
        stamp = self._utcnow().strftime("%Y%m%d-%H%M%S-%f")
        run_dir = self._resolve_output_root() / f"intake-{intake_id}-{stamp}"
        return GedRpaRunnerPaths(
            run_dir=run_dir,
            input=run_dir / "input.json",
            status=run_dir / "status.json",
            log=run_dir / "runner.log",
            error_log=run_dir / "runner.err.log",
            artifacts=run_dir / "artifacts",
        )

    @staticmethod
    def _read_json_file(file_path: Path, fallback: Any = None) -> Any:
        try:
            raw = file_path.read_text(encoding="utf-8").replace("\ufeff", "")
            return json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError):
            return fallback

    def upload_document(
        self,
        *,
        intake_id: int,
        lawsuit_id: int,
        cnj_number: Optional[str],
        pdf_path: Path,
        archive_name: str,
        description: str,
        type_id: str,
    ) -> dict[str, Any]:
        runner_script = self._resolve_runner_script()
        if not runner_script.exists():
            raise RuntimeError(f"Runner Playwright nao encontrado em {runner_script}")
        if not pdf_path.exists():
            raise RuntimeError(f"PDF nao encontrado para upload GED via RPA: {pdf_path}")

        paths = self._build_run_paths(intake_id)
        paths.run_dir.mkdir(parents=True, exist_ok=True)
        paths.artifacts.mkdir(parents=True, exist_ok=True)
        paths.log.touch(exist_ok=True)
        paths.error_log.touch(exist_ok=True)

        item = {
            "intakeId": int(intake_id),
            "lawsuitId": int(lawsuit_id),
            "cnj": cnj_number,
            "pdfPath": str(pdf_path),
            "archive": archive_name,
            "description": description,
            "typeId": type_id,
        }
        paths.input.write_text(
            json.dumps(item, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        command = [
            self._resolve_node_binary(),
            str(runner_script),
            "--input",
            str(paths.input),
            "--output",
            str(paths.status),
            "--artifacts-dir",
            str(paths.artifacts),
        ]

        env = {**os.environ, **self._resolve_credentials()}
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

        run_label = f"ged-rpa run={paths.run_dir.name}"
        logger.info("%s: runner Node finalizou (exit_code=%s).", run_label, completed.returncode)
        try:
            _mirror_runner_log_to_stdout(
                log_path=paths.log,
                error_log_path=paths.error_log,
                run_label=run_label,
                exit_code=completed.returncode,
            )
        except Exception:  # noqa: BLE001
            logger.exception("%s: falha ao espelhar logs do runner pro stdout.", run_label)

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
                "Runner GED RPA nao gerou status valido "
                f"(exit_code={completed.returncode}). stderr={error_preview}"
            )

        if completed.returncode != 0 or payload.get("state") != "completed":
            raise RuntimeError(
                "Runner GED RPA falhou: "
                f"state={payload.get('state')} status={payload.get('status')} "
                f"error={payload.get('error')} artifacts={payload.get('diagnosticJsonPath')}"
            )

        response = payload.get("response") or {}
        document_id = response.get("documentId")
        return {
            "document_id": int(document_id) if document_id else -abs(int(intake_id)),
            "runner_status": payload,
            "run_dir": str(paths.run_dir),
        }

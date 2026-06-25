"""HTML → PDF reusando o Chromium do Playwright já instalado na imagem da API.

Não adiciona dependência nova: o Dockerfile já roda
`npx playwright install --with-deps chromium` (para o RPA Node), e o stage
`api` herda isso. Aqui só invocamos um pequeno script Node que renderiza o
HTML em PDF A4. Mesmo idioma de subprocess do publication_treatment_service.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# pdf.py vive em app/services/publications_report/ → parents[2] já é o pacote `app`.
_RUNNER = Path(__file__).resolve().parents[2] / "runners" / "legalone" / "render-report-pdf.js"


def _resolve_node() -> str:
    candidate = shutil.which("node") or shutil.which("node.exe")
    if not candidate:
        raise RuntimeError("Node.js não encontrado no PATH — necessário para renderizar o PDF.")
    return candidate


def html_to_pdf(html: str, timeout: int = 120) -> bytes:
    """Renderiza o HTML do relatório em bytes de PDF. Levanta em caso de falha."""
    runner = _RUNNER
    if not runner.exists():
        raise RuntimeError(f"Script de renderização ausente: {runner}")

    with tempfile.TemporaryDirectory(prefix="perf-report-") as tmp:
        html_path = Path(tmp) / "report.html"
        pdf_path = Path(tmp) / "report.pdf"
        html_path.write_text(html, encoding="utf-8")

        command = [_resolve_node(), str(runner), str(html_path), str(pdf_path)]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.run(  # noqa: S603
                command,
                cwd=str(runner.parent),
                env={**os.environ},
                capture_output=True,
                timeout=timeout,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Tempo esgotado ao renderizar o PDF do relatório.") from exc

        if proc.returncode != 0 or not pdf_path.exists():
            err = (proc.stderr or b"").decode("utf-8", "replace")[:600]
            logger.error("render-report-pdf falhou rc=%s: %s", proc.returncode, err)
            raise RuntimeError(f"Falha ao renderizar o PDF (rc={proc.returncode}). {err}")

        return pdf_path.read_bytes()

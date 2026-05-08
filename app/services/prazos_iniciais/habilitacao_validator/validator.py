"""
Orquestracao dos checks heuristicos sobre o PDF da habilitacao.

Status agregado:
  - Algum CRITICO em FALHA           → FALHA
  - Algum (qualquer) em ALERTA       → ALERTA
  - Tudo OK ou PULADO                → OK
  - Falha de IO/extracao             → ERRO_EXTRACAO

`run_validation` NUNCA levanta — toda excecao vira ERRO_EXTRACAO. O
intake_service chama isso de forma sincrona (PDF de 6 paginas roda em
<1s no pdfplumber) e nao bloqueia o avanco do intake quando falha.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from app.models.prazo_inicial import (
    HABILITACAO_CHECK_STATUS_EXTRACTION_ERROR,
    HABILITACAO_CHECK_STATUS_FAILED,
    HABILITACAO_CHECK_STATUS_NOT_VERIFIED,
    HABILITACAO_CHECK_STATUS_OK,
    HABILITACAO_CHECK_STATUS_WARNING,
    PrazoInicialIntake,
)
from app.services.prazos_iniciais.habilitacao_validator import checks
from app.services.prazos_iniciais.habilitacao_validator.text import (
    extract_pages,
    join_pages,
    normalize,
)
from app.services.prazos_iniciais.storage import resolve_pdf_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HabilitacaoCheckOutcome:
    """Resultado da rodada de validacao."""

    status: str
    checks: List[dict]
    checked_at: datetime


def _aggregate_status(check_results: List[dict]) -> str:
    has_critical_failure = any(
        c["status"] == checks.CHECK_FAILED
        and c["criticidade"] == checks.CRIT_CRITICAL
        for c in check_results
    )
    if has_critical_failure:
        return HABILITACAO_CHECK_STATUS_FAILED

    has_warning = any(
        c["status"] in (checks.CHECK_WARNING, checks.CHECK_FAILED)
        for c in check_results
    )
    if has_warning:
        return HABILITACAO_CHECK_STATUS_WARNING

    return HABILITACAO_CHECK_STATUS_OK


def _io_error_outcome(check_id: str, label: str, detalhe: str) -> HabilitacaoCheckOutcome:
    return HabilitacaoCheckOutcome(
        status=HABILITACAO_CHECK_STATUS_EXTRACTION_ERROR,
        checks=[{
            "id": check_id,
            "label": label,
            "criticidade": checks.CRIT_CRITICAL,
            "status": checks.CHECK_FAILED,
            "detalhe": detalhe,
        }],
        checked_at=datetime.now(timezone.utc),
    )


def run_validation(intake: PrazoInicialIntake) -> HabilitacaoCheckOutcome:
    """
    Roda os checks heuristicos sobre o PDF de habilitacao do intake.
    NUNCA levanta — falhas viram outcomes com status ERRO_EXTRACAO.
    """
    pdf_path = getattr(intake, "habilitacao_pdf_path", None)
    if not pdf_path:
        return HabilitacaoCheckOutcome(
            status=HABILITACAO_CHECK_STATUS_NOT_VERIFIED,
            checks=[],
            checked_at=datetime.now(timezone.utc),
        )

    try:
        absolute = resolve_pdf_path(pdf_path)
        pdf_bytes = absolute.read_bytes()
    except FileNotFoundError:
        logger.warning(
            "PDF de habilitacao do intake %d nao existe no disco: %s",
            intake.id, pdf_path,
        )
        return _io_error_outcome(
            "IO", "Leitura do PDF",
            "Arquivo da habilitacao nao encontrado no volume "
            "(pode ter sido removido por limpeza manual).",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Falha ao abrir PDF de habilitacao do intake %d", intake.id,
        )
        return _io_error_outcome(
            "IO", "Leitura do PDF",
            f"Nao foi possivel abrir o PDF: {exc}",
        )

    try:
        pages = extract_pages(pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Falha ao extrair texto do PDF do intake %d", intake.id,
        )
        return _io_error_outcome(
            "EXTRACT", "Extracao de texto",
            f"PDF nao pode ser lido com pdfplumber: {exc}",
        )

    text_full = join_pages(pages)
    if not text_full or len(text_full) < 100:
        return _io_error_outcome(
            "EXTRACT", "Extracao de texto",
            "PDF aberto mas sem texto extraivel (provavelmente "
            "escaneado/imagem). Operador precisa revisar manualmente.",
        )

    text_norm = normalize(text_full)

    results = [
        checks.check_peticao_habilitacao(text_norm),
        checks.check_pedido_exclusivamente(text_norm),
        checks.check_assinatura_titular(text_norm),
        checks.check_procuracao(text_norm),
        checks.check_substabelecimento(text_norm),
        checks.check_cnj_match(text_norm, intake.cnj_number),
        checks.check_cliente_match(text_norm, intake),
        checks.check_oab_escritorio(text_norm),
        checks.check_data_assinatura(text_norm, intake),
    ]

    return HabilitacaoCheckOutcome(
        status=_aggregate_status(results),
        checks=results,
        checked_at=datetime.now(timezone.utc),
    )


def persist_outcome(
    intake: PrazoInicialIntake,
    outcome: HabilitacaoCheckOutcome,
) -> None:
    """Atualiza os 3 campos do intake a partir do outcome (sem commit)."""
    intake.habilitacao_check_status = outcome.status
    intake.habilitacao_check_result = {"checks": outcome.checks}
    intake.habilitacao_check_at = outcome.checked_at

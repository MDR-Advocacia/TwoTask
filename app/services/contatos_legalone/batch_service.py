"""Orquestracao dos lotes de Atualizacao de Contatos.

O endpoint so' valida HTTP e delega aqui. O enriquecimento em si (achar
contato + POST nas navigation properties) NAO acontece aqui — quem faz e' o
worker (enrich_worker.py), item a item, respeitando o rate limiter do L1.

Responsabilidades:
- preview_csv: parseia sem gravar (resumo + amostra pra UI).
- create_batch_from_csv: parseia, cria batch + itens (PENDENTE).
- recompute_counters / finalize / progress.
- retry_failed / cancel_batch / delete_batch.
- serializers pra UI.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.contato_update import (
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_DONE_WITH_ERRORS,
    BATCH_STATUS_PROCESSING,
    BATCH_TERMINAL_STATUSES,
    ITEM_RETRYABLE_STATUSES,
    ITEM_STATUS_DUPLICADO,
    ITEM_STATUS_ERRO,
    ITEM_STATUS_NAO_ENCONTRADO,
    ITEM_STATUS_PENDENTE,
    ITEM_STATUS_PROCESSANDO,
    ITEM_STATUS_SUCESSO,
    ContatoAtualizacaoBatch,
    ContatoAtualizacaoItem,
)
from app.services.contatos_legalone import csv_parser

logger = logging.getLogger(__name__)


class ContatoValidationError(Exception):
    """CSV tem celulas bloqueantes — nao cria o lote. Carrega os issues."""

    def __init__(self, issues: list, summary: dict):
        self.issues = issues
        self.summary = summary
        super().__init__("Planilha com celulas fora do padrao (bloqueantes).")


def cap_issues(issues: list, limit: int = 1000) -> list:
    """Erros primeiro, alertas depois; limita pra nao estourar o payload."""
    errs = [i for i in issues if i.get("severity") == "error"]
    warns = [i for i in issues if i.get("severity") != "error"]
    return (errs + warns)[:limit]


# ─── Contadores + status ─────────────────────────────────────────────────


def recompute_counters(db: Session, batch: ContatoAtualizacaoBatch) -> None:
    """Recomputa os contadores denormalizados a partir dos itens."""
    counts: dict[str, int] = {}
    rows = (
        db.query(ContatoAtualizacaoItem.status, sa_func.count(ContatoAtualizacaoItem.id))
        .filter(ContatoAtualizacaoItem.batch_id == batch.id)
        .group_by(ContatoAtualizacaoItem.status)
        .all()
    )
    for status, n in rows:
        counts[status] = n

    sucesso = counts.get(ITEM_STATUS_SUCESSO, 0)
    erro = (
        counts.get(ITEM_STATUS_ERRO, 0)
        + counts.get(ITEM_STATUS_NAO_ENCONTRADO, 0)
        + counts.get(ITEM_STATUS_DUPLICADO, 0)
    )
    pendente = counts.get(ITEM_STATUS_PENDENTE, 0) + counts.get(ITEM_STATUS_PROCESSANDO, 0)

    batch.total_itens = sucesso + erro + pendente
    batch.total_sucesso = sucesso
    batch.total_erro = erro
    batch.total_pendente = pendente


def _finalize_status(batch: ContatoAtualizacaoBatch) -> None:
    """Define status terminal (DONE / DONE_WITH_ERRORS) quando nada pende."""
    if batch.total_erro > 0:
        batch.status = BATCH_STATUS_DONE_WITH_ERRORS
    else:
        batch.status = BATCH_STATUS_DONE
    if batch.finished_at is None:
        batch.finished_at = datetime.now(timezone.utc)


def progress_pct(batch: ContatoAtualizacaoBatch) -> int:
    total = batch.total_itens or 0
    if total <= 0:
        return 100 if batch.status in BATCH_TERMINAL_STATUSES else 0
    done = (batch.total_sucesso or 0) + (batch.total_erro or 0)
    return int(round(100 * done / total))


# ─── Preview (sem gravar) ─────────────────────────────────────────────────


def preview_csv(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Parseia o CSV e devolve resumo + amostra, SEM tocar no banco."""
    parsed = csv_parser.parse_csv(file_bytes)
    sample = [
        {
            "row_number": r["row_number"],
            "doc_number": r["doc_number"],
            "doc_kind": r["doc_kind"],
            "name": r["name"],
            "nome_abreviado": r["nome_abreviado"],
            "phones": r["phones"],
            "email": r["email"],
            "address": r["address"],
        }
        for r in parsed["rows"][:20]
    ]
    return {
        "filename": filename,
        "headers": parsed["headers"],
        "summary": parsed["summary"],
        "sample": sample,
        "invalid": parsed["invalid"][:50],
        "issues": cap_issues(parsed["issues"]),
        "has_blocking": parsed["has_blocking"],
    }


# ─── Criacao de lote ──────────────────────────────────────────────────────


def create_batch_from_csv(
    db: Session,
    *,
    nome: str,
    description: Optional[str],
    dry_run: bool,
    file_bytes: bytes,
    original_filename: str,
    created_by_user_id: Optional[int],
) -> tuple[ContatoAtualizacaoBatch, dict[str, Any]]:
    """Parseia o CSV e cria o lote + itens (PENDENTE). Nao escreve no L1 —
    o worker processa depois (em dry-run se `dry_run=True`)."""
    parsed = csv_parser.parse_csv(file_bytes)
    # Trava server-side: nao cria lote com celulas bloqueantes (ex.: CPF/CNPJ
    # invalido). E' a rede de seguranca do bloqueio feito na UI.
    if parsed.get("has_blocking"):
        raise ContatoValidationError(cap_issues(parsed["issues"]), parsed["summary"])
    rows = parsed["rows"]
    if not rows:
        raise ValueError(
            "Nenhuma linha valida no CSV (cada linha precisa de um CPF/CNPJ valido)."
        )

    sha256 = hashlib.sha256(file_bytes).hexdigest()

    batch = ContatoAtualizacaoBatch(
        nome=nome.strip(),
        description=(description or None),
        dry_run=bool(dry_run),
        status=BATCH_STATUS_PROCESSING,
        source_filename=original_filename,
        source_sha256=sha256,
        created_by_user_id=created_by_user_id,
        processing_started_at=datetime.now(timezone.utc),
    )
    db.add(batch)
    db.flush()

    for r in rows:
        db.add(
            ContatoAtualizacaoItem(
                batch_id=batch.id,
                row_number=r["row_number"],
                doc_number=r["doc_number"],
                doc_digits=r["doc_digits"],
                doc_kind=r["doc_kind"],
                nome_abreviado=r["nome_abreviado"],
                payload_json={
                    "name": r["name"],
                    "phones": r["phones"],
                    "email": r["email"],
                    "address": r["address"],
                },
                status=ITEM_STATUS_PENDENTE,
            )
        )
    db.flush()
    recompute_counters(db, batch)
    db.commit()
    db.refresh(batch)

    summary = {
        **parsed["summary"],
        "invalid": parsed["invalid"][:50],
        "dry_run": batch.dry_run,
    }
    return batch, summary


# ─── Acoes (retry / cancel / delete) ─────────────────────────────────────


def retry_failed(db: Session, batch: ContatoAtualizacaoBatch) -> dict[str, Any]:
    """Re-enfileira itens ERRO + NAO_ENCONTRADO (volta a PENDENTE)."""
    if batch.status == BATCH_STATUS_CANCELLED:
        raise ValueError("Lote cancelado nao pode ser reprocessado.")

    re_enqueued = 0
    for it in batch.itens:
        if it.status in ITEM_RETRYABLE_STATUSES:
            it.status = ITEM_STATUS_PENDENTE
            it.error_message = None
            it.processed_at = None
            re_enqueued += 1

    if re_enqueued:
        batch.status = BATCH_STATUS_PROCESSING
        batch.finished_at = None
        if batch.processing_started_at is None:
            batch.processing_started_at = datetime.now(timezone.utc)
    db.flush()
    recompute_counters(db, batch)
    db.commit()
    db.refresh(batch)
    return {"re_enqueued": re_enqueued}


def cancel_batch(db: Session, batch: ContatoAtualizacaoBatch) -> ContatoAtualizacaoBatch:
    """Cancela o lote — worker para de pegar os PENDENTE (filtra PROCESSING)."""
    if batch.status in BATCH_TERMINAL_STATUSES:
        return batch
    batch.status = BATCH_STATUS_CANCELLED
    batch.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(batch)
    return batch


def delete_batch(db: Session, batch: ContatoAtualizacaoBatch) -> None:
    """Apaga o lote (cascade nos itens). Sem arquivo no volume — o CSV nunca
    e' persistido (PII/LGPD)."""
    db.delete(batch)
    db.commit()


# ─── Serializers ─────────────────────────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def serialize_item(it: ContatoAtualizacaoItem) -> dict[str, Any]:
    payload = it.payload_json or {}
    return {
        "id": it.id,
        "batch_id": it.batch_id,
        "row_number": it.row_number,
        "doc_number": it.doc_number,
        "doc_kind": it.doc_kind,
        "name": payload.get("name"),
        "nome_abreviado": it.nome_abreviado,
        "contact_id": it.contact_id,
        "status": it.status,
        "phones": payload.get("phones") or [],
        "email": payload.get("email"),
        "address": payload.get("address"),
        "result": it.result_json,
        "error_message": it.error_message,
        "attempts": it.attempts,
        "created_at": _iso(it.created_at),
        "processed_at": _iso(it.processed_at),
    }


def serialize_batch(batch: ContatoAtualizacaoBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "nome": batch.nome,
        "description": batch.description,
        "dry_run": batch.dry_run,
        "status": batch.status,
        "is_terminal": batch.status in BATCH_TERMINAL_STATUSES,
        "progress_pct": progress_pct(batch),
        "total_itens": batch.total_itens,
        "total_sucesso": batch.total_sucesso,
        "total_erro": batch.total_erro,
        "total_pendente": batch.total_pendente,
        "source_filename": batch.source_filename,
        "error_message": batch.error_message,
        "created_by_user_id": batch.created_by_user_id,
        "created_at": _iso(batch.created_at),
        "updated_at": _iso(batch.updated_at),
        "finished_at": _iso(batch.finished_at),
    }


def status_payload(batch: ContatoAtualizacaoBatch) -> dict[str, Any]:
    """Payload barato pro polling de progresso (sem listar itens)."""
    return {
        "id": batch.id,
        "status": batch.status,
        "dry_run": batch.dry_run,
        "is_terminal": batch.status in BATCH_TERMINAL_STATUSES,
        "progress_pct": progress_pct(batch),
        "total_itens": batch.total_itens,
        "total_sucesso": batch.total_sucesso,
        "total_erro": batch.total_erro,
        "total_pendente": batch.total_pendente,
        "finished_at": _iso(batch.finished_at),
        "updated_at": _iso(batch.updated_at),
    }

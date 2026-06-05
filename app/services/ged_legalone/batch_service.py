"""Orquestracao dos lotes de envio ao GED do Legal One.

Responsabilidades (o endpoint so' valida HTTP e delega aqui):
- create_batch_single: 1 arquivo -> N CNJs (modo SINGLE_FILE).
- create_batch_multi: N arquivos -> N CNJs (modo MULTI_FILE).
- resolve_cnjs: resolve CNJ -> lawsuit_id no L1 (idempotente / retry-safe).
- retry_failed: re-enfileira itens ERRO + CNJ_NAO_ENCONTRADO.
- cancel_batch / delete_batch (cleanup do arquivo compartilhado incluso).
- recompute_counters + serializers pra UI.

O upload em si NAO acontece aqui — quem sobe pro GED e' o worker
(upload_worker.py), que pega itens PENDENTE com lawsuit_id resolvido.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.ged_legalone import (
    BATCH_MODE_MULTI_FILE,
    BATCH_MODE_SINGLE_FILE,
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_DONE,
    BATCH_STATUS_DONE_WITH_ERRORS,
    BATCH_STATUS_PROCESSING,
    BATCH_STATUS_RESOLVING,
    BATCH_TERMINAL_STATUSES,
    ITEM_RETRYABLE_STATUSES,
    ITEM_STATUS_CNJ_NAO_ENCONTRADO,
    ITEM_STATUS_ERRO,
    ITEM_STATUS_PENDENTE,
    ITEM_STATUS_PROCESSANDO,
    ITEM_STATUS_SUCESSO,
    GedUploadBatch,
    GedUploadItem,
)
from app.services.ged_legalone import storage

logger = logging.getLogger(__name__)


# ─── Helpers de CNJ (espelham app/services/ajus/queue_service.py) ────────
# Copia local proposital pra manter o modulo GED auto-contido (importar
# queue_service traz ajus_client/prazo_calculator junto, peso desnecessario).
_CNJ_REGEX = re.compile(
    r"(\d{7})[-.\s]?(\d{2})[-.\s]?(\d{4})[-.\s]?(\d{1})[-.\s]?(\d{2})[-.\s]?(\d{4})",
)


def extract_cnj_from_filename(filename: str) -> Optional[str]:
    """Extrai CNJ (20 digitos) do nome do arquivo, ou None se nao bater."""
    if not filename:
        return None
    base = filename.rsplit(".", 1)[0] if "." in filename else filename
    match = _CNJ_REGEX.search(base)
    if not match:
        return None
    return "".join(match.groups())


def normalize_cnj_basic(raw: str) -> Optional[str]:
    """Normaliza CNJ pra 20 digitos (sem mascara). None se != 20 digitos."""
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    return digits if len(digits) == 20 else None


def mask_cnj(digits: str) -> str:
    """Formata 20 digitos como NNNNNNN-DD.AAAA.J.TR.OOOO (ou devolve cru)."""
    d = "".join(c for c in str(digits or "") if c.isdigit())
    if len(d) != 20:
        return digits or ""
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13:14]}.{d[14:16]}.{d[16:20]}"


def parse_cnj_list(raw: str) -> dict[str, Any]:
    """
    Parseia uma lista de CNJs colada (quebra por \\n , ;). Retorna
    {valid: [20digits...], invalid: [tokens crus...], duplicates_removed: n}.
    Dedup preserva a 1a ocorrencia.
    """
    tokens = [t.strip() for t in re.split(r"[\n,;]+", raw or "") if t.strip()]
    valid: list[str] = []
    invalid: list[str] = []
    seen: set[str] = set()
    duplicates = 0
    for tok in tokens:
        norm = normalize_cnj_basic(tok)
        if not norm:
            invalid.append(tok)
            continue
        if norm in seen:
            duplicates += 1
            continue
        seen.add(norm)
        valid.append(norm)
    return {"valid": valid, "invalid": invalid, "duplicates_removed": duplicates}


# ─── Resolucao CNJ -> lawsuit_id ─────────────────────────────────────────


def _only_digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def resolve_cnjs(db: Session, batch: GedUploadBatch) -> dict[str, Any]:
    """
    Resolve CNJ -> lawsuit_id pros itens que ainda precisam (lawsuit_id
    NULL e status PENDENTE/CNJ_NAO_ENCONTRADO). Idempotente e retry-safe:
    itens SUCESSO / ERRO-com-lawsuit nao sao tocados.

    Ao fim, recomputa contadores e move o batch pra PROCESSING (tem item
    pendente com lawsuit) ou DONE_WITH_ERRORS (nada a processar).

    Retorna resumo {resolved, nao_encontrado, total}.
    """
    batch.status = BATCH_STATUS_RESOLVING
    if batch.resolving_started_at is None:
        batch.resolving_started_at = datetime.now(timezone.utc)
    db.flush()

    pending = [
        it
        for it in batch.itens
        if it.lawsuit_id is None
        and it.status in (ITEM_STATUS_PENDENTE, ITEM_STATUS_CNJ_NAO_ENCONTRADO)
    ]
    distinct_cnjs = sorted({it.cnj_number for it in pending if it.cnj_number})

    by_digits: dict[str, dict] = {}
    if distinct_cnjs:
        try:
            from app.services.legal_one_client import LegalOneApiClient

            matches = LegalOneApiClient().search_lawsuits_by_cnj_numbers(distinct_cnjs)
        except Exception:  # noqa: BLE001
            logger.exception(
                "GED LegalOne: falha ao resolver CNJs do lote %s (segue, itens "
                "ficam CNJ_NAO_ENCONTRADO e podem ser reprocessados).",
                batch.id,
            )
            matches = {}
        # Indexa por digitos puros pra casar com it.cnj_number (20 digitos),
        # robusto a como o L1 formata a chave de retorno.
        for key, val in (matches or {}).items():
            by_digits[_only_digits(key)] = val
            idn = (val or {}).get("identifierNumber")
            if idn:
                by_digits[_only_digits(idn)] = val

    now = datetime.now(timezone.utc)
    for it in pending:
        if not it.cnj_number:
            it.status = ITEM_STATUS_CNJ_NAO_ENCONTRADO
            it.error_message = "Item sem CNJ (nome do arquivo sem CNJ e sem correcao manual)."
            it.processed_at = now
            continue
        match = by_digits.get(it.cnj_number)
        lawsuit_id = (match or {}).get("id")
        if match and lawsuit_id:
            it.lawsuit_id = int(lawsuit_id)
            it.status = ITEM_STATUS_PENDENTE
            it.error_message = None
            it.processed_at = None
        else:
            it.status = ITEM_STATUS_CNJ_NAO_ENCONTRADO
            it.error_message = f"CNJ {mask_cnj(it.cnj_number)} nao encontrado no Legal One."
            it.processed_at = now

    db.flush()
    recompute_counters(db, batch)

    has_work = any(
        it.status == ITEM_STATUS_PENDENTE and it.lawsuit_id is not None
        for it in batch.itens
    )
    if has_work:
        batch.status = BATCH_STATUS_PROCESSING
        if batch.processing_started_at is None:
            batch.processing_started_at = datetime.now(timezone.utc)
        batch.finished_at = None
    else:
        # Nada pra subir — tudo CNJ_NAO_ENCONTRADO (ou ja' terminou).
        _finalize_status(batch)
    db.flush()

    resolved = sum(1 for it in batch.itens if it.lawsuit_id is not None)
    nao_encontrado = sum(
        1 for it in batch.itens if it.status == ITEM_STATUS_CNJ_NAO_ENCONTRADO
    )
    return {
        "resolved": resolved,
        "nao_encontrado": nao_encontrado,
        "total": len(batch.itens),
    }


# ─── Contadores + status ─────────────────────────────────────────────────


def recompute_counters(db: Session, batch: GedUploadBatch) -> None:
    """Recomputa os contadores denormalizados a partir dos itens."""
    counts: dict[str, int] = {}
    rows = (
        db.query(GedUploadItem.status, sa_func.count(GedUploadItem.id))
        .filter(GedUploadItem.batch_id == batch.id)
        .group_by(GedUploadItem.status)
        .all()
    )
    for status, n in rows:
        counts[status] = n

    sucesso = counts.get(ITEM_STATUS_SUCESSO, 0)
    erro = counts.get(ITEM_STATUS_ERRO, 0) + counts.get(ITEM_STATUS_CNJ_NAO_ENCONTRADO, 0)
    pendente = counts.get(ITEM_STATUS_PENDENTE, 0) + counts.get(ITEM_STATUS_PROCESSANDO, 0)

    batch.total_itens = sucesso + erro + pendente
    batch.total_sucesso = sucesso
    batch.total_erro = erro
    batch.total_pendente = pendente


def _finalize_status(batch: GedUploadBatch) -> None:
    """Define status terminal (DONE / DONE_WITH_ERRORS) quando nada pende."""
    if batch.total_erro > 0:
        batch.status = BATCH_STATUS_DONE_WITH_ERRORS
    else:
        batch.status = BATCH_STATUS_DONE
    if batch.finished_at is None:
        batch.finished_at = datetime.now(timezone.utc)


def progress_pct(batch: GedUploadBatch) -> int:
    total = batch.total_itens or 0
    if total <= 0:
        return 100 if batch.status in BATCH_TERMINAL_STATUSES else 0
    done = (batch.total_sucesso or 0) + (batch.total_erro or 0)
    return int(round(100 * done / total))


# ─── Criacao de lotes ────────────────────────────────────────────────────


def create_batch_single(
    db: Session,
    *,
    nome: str,
    type_id: Optional[str],
    description: Optional[str],
    cnj_raw: str,
    file_bytes: bytes,
    original_filename: str,
    created_by_user_id: Optional[int],
) -> tuple[GedUploadBatch, dict[str, Any]]:
    """Modo SINGLE_FILE: 1 arquivo guardado 1x -> N itens (1 por CNJ)."""
    parsed = parse_cnj_list(cnj_raw)
    valid = parsed["valid"]
    if not valid:
        raise ValueError(
            "Nenhum CNJ valido na lista (cada CNJ precisa ter 20 digitos)."
        )

    ext = storage.normalize_ext(original_filename)
    stored = storage.save_file(file_bytes, ext=ext)

    batch = GedUploadBatch(
        nome=nome.strip(),
        mode=BATCH_MODE_SINGLE_FILE,
        type_id=(type_id or None),
        description=(description or None),
        status=BATCH_STATUS_RESOLVING,
        shared_file_path=stored.relative_path,
        shared_file_sha256=stored.sha256,
        shared_original_filename=original_filename,
        created_by_user_id=created_by_user_id,
    )
    db.add(batch)
    db.flush()

    for cnj in valid:
        db.add(
            GedUploadItem(
                batch_id=batch.id,
                cnj_number=cnj,
                file_path=stored.relative_path,
                original_filename=original_filename,
                file_ext=ext,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                status=ITEM_STATUS_PENDENTE,
            )
        )
    db.flush()

    resolve_summary = resolve_cnjs(db, batch)
    db.commit()
    db.refresh(batch)

    summary = {
        **resolve_summary,
        "invalid_cnjs": parsed["invalid"],
        "duplicates_removed": parsed["duplicates_removed"],
    }
    return batch, summary


def create_batch_multi(
    db: Session,
    *,
    nome: str,
    type_id: Optional[str],
    description: Optional[str],
    files: list[dict[str, Any]],
    cnj_overrides: dict[str, str],
    created_by_user_id: Optional[int],
) -> tuple[GedUploadBatch, dict[str, Any]]:
    """
    Modo MULTI_FILE: cada arquivo vira 1 item, com CNJ vindo do override
    (correcao manual na UI) ou extraido do nome do arquivo.

    `files`: lista de {"filename": str, "bytes": bytes}.
    `cnj_overrides`: {filename -> cnj cru} (opcional por arquivo).
    """
    if not files:
        raise ValueError("Nenhum arquivo recebido.")

    batch = GedUploadBatch(
        nome=nome.strip(),
        mode=BATCH_MODE_MULTI_FILE,
        type_id=(type_id or None),
        description=(description or None),
        status=BATCH_STATUS_RESOLVING,
        created_by_user_id=created_by_user_id,
    )
    db.add(batch)
    db.flush()

    files_sem_cnj: list[str] = []
    for f in files:
        filename = f["filename"]
        data = f["bytes"]
        ext = storage.normalize_ext(filename)
        stored = storage.save_file(data, ext=ext)

        override = cnj_overrides.get(filename)
        cnj = normalize_cnj_basic(override) if override else extract_cnj_from_filename(filename)
        if not cnj:
            files_sem_cnj.append(filename)

        db.add(
            GedUploadItem(
                batch_id=batch.id,
                cnj_number=cnj,
                file_path=stored.relative_path,
                original_filename=filename,
                file_ext=ext,
                size_bytes=stored.size_bytes,
                sha256=stored.sha256,
                status=ITEM_STATUS_PENDENTE,
            )
        )
    db.flush()

    resolve_summary = resolve_cnjs(db, batch)
    db.commit()
    db.refresh(batch)

    summary = {
        **resolve_summary,
        "files_sem_cnj": files_sem_cnj,
    }
    return batch, summary


# ─── Acoes (retry / cancel / delete) ─────────────────────────────────────


def retry_failed(db: Session, batch: GedUploadBatch) -> dict[str, Any]:
    """Re-enfileira itens ERRO + CNJ_NAO_ENCONTRADO (volta a PENDENTE)."""
    if batch.status == BATCH_STATUS_CANCELLED:
        raise ValueError("Lote cancelado nao pode ser reprocessado.")

    re_enqueued = 0
    for it in batch.itens:
        if it.status in ITEM_RETRYABLE_STATUSES:
            it.status = ITEM_STATUS_PENDENTE
            it.error_message = None
            it.processed_at = None
            # CNJ_NAO_ENCONTRADO nunca teve lawsuit_id; sera' re-resolvido.
            # ERRO mantem lawsuit_id e re-sobe direto. Em ambos, attempts
            # acumula no worker (nao zera) pra rastrear historico.
            re_enqueued += 1
    db.flush()

    resolve_summary = resolve_cnjs(db, batch)
    db.commit()
    db.refresh(batch)
    return {"re_enqueued": re_enqueued, **resolve_summary}


def cancel_batch(db: Session, batch: GedUploadBatch) -> GedUploadBatch:
    """Cancela o lote — worker para de pegar os PENDENTE (filtra PROCESSING)."""
    if batch.status in BATCH_TERMINAL_STATUSES:
        return batch
    batch.status = BATCH_STATUS_CANCELLED
    batch.finished_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(batch)
    return batch


def delete_batch(db: Session, batch: GedUploadBatch) -> None:
    """
    Apaga o lote (cascade nos itens) + os arquivos do volume.

    Modo SINGLE_FILE: o mesmo path e' referenciado por N itens — deleta o
    conjunto DISTINTO de paths (1x cada), unindo o shared_file_path.
    """
    distinct_paths: set[str] = set()
    if batch.shared_file_path:
        distinct_paths.add(batch.shared_file_path)
    for it in batch.itens:
        if it.file_path:
            distinct_paths.add(it.file_path)

    for path in distinct_paths:
        try:
            storage.delete_file(path)
        except Exception:  # noqa: BLE001
            logger.warning("GED LegalOne: falha ao apagar arquivo %s (segue).", path)

    db.delete(batch)
    db.commit()


# ─── Serializers ─────────────────────────────────────────────────────────


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def serialize_item(it: GedUploadItem) -> dict[str, Any]:
    return {
        "id": it.id,
        "batch_id": it.batch_id,
        "cnj_number": it.cnj_number,
        "cnj_masked": mask_cnj(it.cnj_number) if it.cnj_number else None,
        "lawsuit_id": it.lawsuit_id,
        "original_filename": it.original_filename,
        "file_ext": it.file_ext,
        "size_bytes": it.size_bytes,
        "status": it.status,
        "ged_document_id": it.ged_document_id,
        "error_message": it.error_message,
        "attempts": it.attempts,
        "created_at": _iso(it.created_at),
        "processed_at": _iso(it.processed_at),
    }


def serialize_batch(batch: GedUploadBatch) -> dict[str, Any]:
    return {
        "id": batch.id,
        "nome": batch.nome,
        "mode": batch.mode,
        "type_id": batch.type_id,
        "description": batch.description,
        "status": batch.status,
        "is_terminal": batch.status in BATCH_TERMINAL_STATUSES,
        "progress_pct": progress_pct(batch),
        "total_itens": batch.total_itens,
        "total_sucesso": batch.total_sucesso,
        "total_erro": batch.total_erro,
        "total_pendente": batch.total_pendente,
        "shared_original_filename": batch.shared_original_filename,
        "error_message": batch.error_message,
        "created_by_user_id": batch.created_by_user_id,
        "created_at": _iso(batch.created_at),
        "updated_at": _iso(batch.updated_at),
        "finished_at": _iso(batch.finished_at),
    }


def status_payload(batch: GedUploadBatch) -> dict[str, Any]:
    """Payload barato pro polling de progresso (sem listar itens)."""
    return {
        "id": batch.id,
        "status": batch.status,
        "mode": batch.mode,
        "is_terminal": batch.status in BATCH_TERMINAL_STATUSES,
        "progress_pct": progress_pct(batch),
        "total_itens": batch.total_itens,
        "total_sucesso": batch.total_sucesso,
        "total_erro": batch.total_erro,
        "total_pendente": batch.total_pendente,
        "finished_at": _iso(batch.finished_at),
        "updated_at": _iso(batch.updated_at),
    }

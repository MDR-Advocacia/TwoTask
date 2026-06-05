"""Worker periodico do GED LegalOne — sobe os arquivos dos lotes pro GED.

CORE do modulo (nao dormente): pega itens PENDENTE com lawsuit_id resolvido
de lotes em PROCESSING e chama legal_one_client.upload_document_to_ged item
a item.

Garantias:
- Idempotencia: item com `ged_document_id` setado NUNCA re-sobe (short-circuit).
- Claim-then-process: marca PROCESSANDO + commit ANTES da chamada L1; crash
  no meio deixa o item em PROCESSANDO (nao re-sobe sozinho). Um reaper reseta
  PROCESSANDO travado (sem ged_document_id) de volta pra PENDENTE.
- Concorrencia 1 (max_instances=1, coalesce): o _rate_limiter global do L1
  ja' serializa o throughput; paralelizar nao ganharia nada e tirava o guard
  natural de nao re-pegar o mesmo item.

Gatilho: settings.ged_legalone_worker_enabled (default True).
Registrado no startup do FastAPI (main.py lifespan).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.ged_legalone import (
    BATCH_STATUS_PROCESSING,
    ITEM_STATUS_ERRO,
    ITEM_STATUS_PENDENTE,
    ITEM_STATUS_PROCESSANDO,
    ITEM_STATUS_SUCESSO,
    GedUploadBatch,
    GedUploadItem,
)
from app.services.ged_legalone import batch_service, storage

logger = logging.getLogger(__name__)

JOB_ID = "ged_legalone_upload"


def _reap_stuck(db) -> int:
    """Reseta itens PROCESSANDO travados (sem ged_document_id) -> PENDENTE."""
    stuck_minutes = max(1, settings.ged_legalone_stuck_minutes)
    threshold = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
    stuck = (
        db.query(GedUploadItem)
        .join(GedUploadBatch, GedUploadItem.batch_id == GedUploadBatch.id)
        .filter(
            GedUploadItem.status == ITEM_STATUS_PROCESSANDO,
            GedUploadItem.ged_document_id.is_(None),
            GedUploadItem.updated_at < threshold,
            GedUploadBatch.status == BATCH_STATUS_PROCESSING,
        )
        .all()
    )
    for it in stuck:
        it.status = ITEM_STATUS_PENDENTE
        it.error_message = "Reprocessado (item travou em PROCESSANDO — possivel crash do worker)."
    if stuck:
        db.commit()
        logger.warning("GED LegalOne: %d item(ns) travado(s) resetado(s) pra PENDENTE.", len(stuck))
    return len(stuck)


def _process_one_item(db, item_id: int) -> None:
    """Sobe 1 item pro GED. Tolerante a falha — vira ERRO com a msg do L1."""
    from app.services.legal_one_client import (
        LegalOneApiClient,
        LegalOneGedUploadError,
    )

    item = db.get(GedUploadItem, item_id)
    # Guards de idempotencia / corrida: so' processa PENDENTE sem documento.
    if item is None:
        return
    if item.status != ITEM_STATUS_PENDENTE or item.ged_document_id is not None:
        return
    if item.lawsuit_id is None:
        return

    # Claim ANTES da chamada L1 (commit) — evita re-pegar em outro tick.
    item.status = ITEM_STATUS_PROCESSANDO
    item.attempts = (item.attempts or 0) + 1
    db.commit()

    now = datetime.now(timezone.utc)
    try:
        absolute = storage.resolve_file_path(item.file_path)
        if not absolute.exists():
            raise LegalOneGedUploadError(
                f"Arquivo fisico nao encontrado no volume: {item.file_path}"
            )
        file_bytes = absolute.read_bytes()
        if not file_bytes:
            raise LegalOneGedUploadError(f"Arquivo vazio: {item.file_path}")

        batch = item.batch
        archive_name = item.original_filename or f"documento.{item.file_ext or 'bin'}"
        description = batch.description or f"GED LegalOne — lote #{batch.id} ({batch.nome})"

        document_id = LegalOneApiClient().upload_document_to_ged(
            file_bytes=file_bytes,
            file_name=item.original_filename or archive_name,
            litigation_id=int(item.lawsuit_id),
            type_id=(batch.type_id or None),
            archive_name=archive_name,
            description=description,
            file_extension=(item.file_ext or None),
        )

        item.ged_document_id = int(document_id)
        item.status = ITEM_STATUS_SUCESSO
        item.error_message = None
        item.processed_at = now
        db.commit()
        logger.info(
            "GED LegalOne OK: item=%s lote=%s lawsuit=%s document_id=%s",
            item.id, item.batch_id, item.lawsuit_id, document_id,
        )
    except LegalOneGedUploadError as exc:
        item.status = ITEM_STATUS_ERRO
        item.error_message = str(exc)[:1000]
        item.processed_at = now
        db.commit()
        logger.warning("GED LegalOne ERRO: item=%s lote=%s: %s", item.id, item.batch_id, exc)
    except Exception as exc:  # noqa: BLE001
        item.status = ITEM_STATUS_ERRO
        item.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        item.processed_at = now
        db.commit()
        logger.exception("GED LegalOne ERRO inesperado: item=%s lote=%s", item.id, item.batch_id)


def _finalize_batch_if_done(db, batch_id: int) -> None:
    """Recomputa contadores; se nada pende, fecha o lote (DONE / DONE_WITH_ERRORS)."""
    batch = db.get(GedUploadBatch, batch_id)
    if batch is None or batch.status != BATCH_STATUS_PROCESSING:
        return
    batch_service.recompute_counters(db, batch)
    if batch.total_pendente == 0:
        batch_service._finalize_status(batch)
    db.commit()


def _tick() -> None:
    """Uma execucao do worker. Nao levanta — apenas loga falhas."""
    db = SessionLocal()
    try:
        _reap_stuck(db)

        per_tick = max(1, settings.ged_legalone_worker_batch_size)
        items = (
            db.query(GedUploadItem)
            .join(GedUploadBatch, GedUploadItem.batch_id == GedUploadBatch.id)
            .filter(
                GedUploadItem.status == ITEM_STATUS_PENDENTE,
                GedUploadItem.lawsuit_id.isnot(None),
                GedUploadBatch.status == BATCH_STATUS_PROCESSING,
            )
            .order_by(GedUploadItem.created_at.asc())
            .limit(per_tick)
            .all()
        )
        if not items:
            return

        item_ids = [it.id for it in items]
        affected = {it.batch_id for it in items}
        logger.info("GED LegalOne: processando %d item(ns) neste tick.", len(item_ids))

        for iid in item_ids:
            _process_one_item(db, iid)

        for bid in affected:
            _finalize_batch_if_done(db, bid)
    finally:
        db.close()


def _run_tick() -> None:
    """Adapter sincrono pro APScheduler."""
    try:
        _tick()
    except Exception:  # noqa: BLE001
        logger.exception("GED LegalOne: erro inesperado no tick.")


def register_ged_legalone_job(scheduler) -> None:
    """Registra o job periodico. No-op se o worker estiver desligado."""
    if not settings.ged_legalone_worker_enabled:
        logger.info(
            "GED LegalOne worker NAO registrado (ged_legalone_worker_enabled=False)."
        )
        return

    interval = max(5, settings.ged_legalone_worker_interval_seconds)
    scheduler.add_job(
        _run_tick,
        trigger="interval",
        seconds=interval,
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "GED LegalOne worker registrado (intervalo=%ds, batch_size=%d).",
        interval, settings.ged_legalone_worker_batch_size,
    )

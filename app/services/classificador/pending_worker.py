"""Worker dormente do Classificador — agrupa PDFs pendentes em batches de
50 por cliente, cria lotes automaticamente e dispara classify.

Pattern:
- A cada tick (default 60s), pra cada cliente_nome distinto na fila:
  - Pega ate BATCH_SIZE (50) PDFs em status=PENDENTE
  - Se count == BATCH_SIZE OU oldest received_at > BATCH_TIMEOUT (30min):
    - Cria lote novo (cliente_nome herdado dos PDFs)
    - Move PDFs pra ALOCADO + amarra lote_id
    - Pra cada PDF: roda ingest_pdf (le bytes do volume + extracao mecanica)
      → marca PROCESSADO + processo_id
    - Se TUDO ok e CLASSIFICADOR_PENDING_AUTO_CLASSIFY=True, dispara
      classify do lote (Anthropic Batches em background).
- Se um PDF falha em ingest, marca ERRO mas nao bloqueia os outros do mesmo lote.
- Se TODOS falham, lote fica com 0 processos OK — operador apaga via UI.

Registrado no startup do main.py via `register_classificador_pending_job`.
Gated por `settings.classificador_pending_worker_enabled`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.classificador import (
    ClassificadorLote,
    ClassificadorPdfPending,
    LOTE_STATUS_RASCUNHO,
    PENDING_STATUS_ALOCADO,
    PENDING_STATUS_ERRO,
    PENDING_STATUS_PENDENTE,
    PENDING_STATUS_PROCESSADO,
)
from app.services.classificador.classifier_runner import (
    ClassificadorBatchClassifier,
)
from app.services.classificador.pdf_intake import (
    SOURCE_PDF_ROBOT_API,
    ingest_pdf,
)
from app.services.prazos_iniciais.storage import delete_pdf, resolve_pdf_path

logger = logging.getLogger(__name__)


def _read_pdf_from_storage(pdf_path: str) -> Optional[bytes]:
    """Le bytes do PDF gravado em pending.pdf_path (caminho relativo)."""
    try:
        abs_path = resolve_pdf_path(pdf_path)
        if not abs_path.exists():
            logger.error("pending_worker: PDF nao encontrado em %s", pdf_path)
            return None
        return abs_path.read_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.exception("pending_worker: falha lendo PDF %s: %s", pdf_path, exc)
        return None


def _should_flush_group(pending_list: list[ClassificadorPdfPending],
                       batch_size: int, timeout_minutes: int) -> bool:
    """Decide se um grupo de PDFs pendentes deve virar lote agora."""
    if not pending_list:
        return False
    if len(pending_list) >= batch_size:
        return True
    oldest = min(p.received_at for p in pending_list if p.received_at)
    age = datetime.now(timezone.utc) - oldest
    return age.total_seconds() >= timeout_minutes * 60


def _process_group(
    db, pending_list: list[ClassificadorPdfPending], batch_size: int,
) -> Optional[int]:
    """Cria 1 lote + processa ate batch_size PDFs do grupo. Retorna lote_id."""
    # Limita ao batch_size
    pending_list = pending_list[:batch_size]
    if not pending_list:
        return None

    # Cliente_nome: usa o primeiro nao-vazio (todos devem ser iguais —
    # agrupamos por cliente). Se todos vazios, vira "Robo — DD/MM HH:MM"
    cliente = next(
        (p.cliente_nome for p in pending_list if p.cliente_nome), None,
    )
    now = datetime.now(timezone.utc)
    nome = f"Robo — {now.strftime('%d/%m %H:%M')} ({len(pending_list)} PDFs)"
    if cliente:
        nome = f"{cliente} — {now.strftime('%d/%m %H:%M')} ({len(pending_list)} PDFs)"

    # 1. Cria lote
    lote = ClassificadorLote(
        nome=nome,
        cliente_nome=cliente,
        descricao=f"Criado automaticamente pelo motor dormente — {len(pending_list)} PDFs",
        status=LOTE_STATUS_RASCUNHO,
        snapshot_at=now,
        source_summary={},
    )
    db.add(lote)
    db.flush()
    logger.info(
        "pending_worker: lote #%s criado (cliente=%r, %d PDFs)",
        lote.id, cliente, len(pending_list),
    )

    # 2. Aloca PDFs ao lote (mesmo se ingest falhar depois)
    for p in pending_list:
        p.status = PENDING_STATUS_ALOCADO
        p.lote_id = lote.id
        p.allocated_at = now
    db.commit()

    # 3. Pra cada PDF: le bytes + ingest_pdf
    sucessos = 0
    for p in pending_list:
        pdf_bytes = _read_pdf_from_storage(p.pdf_path)
        if not pdf_bytes:
            p.status = PENDING_STATUS_ERRO
            p.error_message = f"PDF nao encontrado no volume: {p.pdf_path}"
            p.processed_at = datetime.now(timezone.utc)
            db.commit()
            continue

        try:
            proc = ingest_pdf(
                db,
                lote_id=lote.id,
                pdf_bytes=pdf_bytes,
                pdf_filename=p.pdf_filename_original or "pending.pdf",
                source=SOURCE_PDF_ROBOT_API,
                cnj_hint=p.cnj_hint,
                external_id=p.external_id,
                produto=p.produto,
                metadata={"observacao_operador": p.observacao,
                          "pending_id": p.id,
                          **(p.metadata_json or {})} if p.observacao or p.metadata_json
                else {"pending_id": p.id},
            )
            p.status = PENDING_STATUS_PROCESSADO
            p.processo_id = proc.id
            p.processed_at = datetime.now(timezone.utc)
            sucessos += 1
            # Descarta o PDF do pending storage (ja foi processado +
            # ingest_pdf criou copia propria no volume com seu sha;
            # esse aqui era so' staging temporario).
            try:
                if p.pdf_path:
                    delete_pdf(p.pdf_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "pending_worker: falha deletando pending PDF %s: %s",
                    p.pdf_path, exc,
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("pending_worker: ingest_pdf falhou pra pending=%s", p.id)
            p.status = PENDING_STATUS_ERRO
            p.error_message = f"{type(exc).__name__}: {exc}"
            p.processed_at = datetime.now(timezone.utc)
        db.commit()

    logger.info(
        "pending_worker: lote #%s — %d/%d PDFs processados OK",
        lote.id, sucessos, len(pending_list),
    )

    # 4. Auto-classify se habilitado E houver algo pra classificar
    if settings.classificador_pending_auto_classify and sucessos > 0:
        try:
            runner = ClassificadorBatchClassifier(db)
            processos = runner.collect_pending_processos(lote_id=lote.id)
            if processos:
                asyncio.run(runner.submit_batch(
                    lote_id=lote.id,
                    processos=processos,
                    requested_by_email="motor-dormente@classificador",
                ))
                logger.info(
                    "pending_worker: classify disparado pro lote #%s (%d processos)",
                    lote.id, len(processos),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "pending_worker: falha disparando classify lote=%s: %s",
                lote.id, exc,
            )

    return lote.id


def _tick() -> None:
    """1 iteracao do worker — chamada pelo APScheduler."""
    if not settings.classificador_pending_worker_enabled:
        return

    db = SessionLocal()
    try:
        # Carrega TODOS os PENDENTES
        pending_all = (
            db.query(ClassificadorPdfPending)
            .filter(ClassificadorPdfPending.status == PENDING_STATUS_PENDENTE)
            .order_by(ClassificadorPdfPending.received_at.asc())
            .all()
        )
        if not pending_all:
            return

        # Agrupa por cliente_nome (None vira chave "")
        groups: dict[str, list[ClassificadorPdfPending]] = defaultdict(list)
        for p in pending_all:
            key = p.cliente_nome or ""
            groups[key].append(p)

        batch_size = settings.classificador_batch_size
        timeout = settings.classificador_batch_timeout_minutes

        logger.debug(
            "pending_worker: %d pendentes em %d grupos (cliente)",
            len(pending_all), len(groups),
        )

        for cliente_key, plist in groups.items():
            if not _should_flush_group(plist, batch_size, timeout):
                logger.debug(
                    "pending_worker: cliente=%r tem %d PDFs (aguardando %d ou %dmin)",
                    cliente_key or "(sem cliente)", len(plist), batch_size, timeout,
                )
                continue
            # Pode haver mais que batch_size — _process_group corta no limite,
            # e proxima rodada agarra o resto
            try:
                _process_group(db, plist, batch_size)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "pending_worker: erro processando grupo cliente=%r: %s",
                    cliente_key, exc,
                )
                # Rollback do que estiver pendente nessa transacao
                try:
                    db.rollback()
                except Exception:
                    pass
    finally:
        db.close()


def register_classificador_pending_job(scheduler: BackgroundScheduler) -> None:
    """Registra o tick periodico do motor dormente."""
    if not settings.classificador_pending_worker_enabled:
        logger.info(
            "pending_worker: NAO registrado "
            "(classificador_pending_worker_enabled=False)"
        )
        return
    interval = settings.classificador_pending_worker_interval_seconds
    scheduler.add_job(
        _tick,
        trigger=IntervalTrigger(seconds=interval),
        id="classificador_pending_intake",
        name="Classificador — motor dormente (intake PDFs)",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc),
    )
    logger.info(
        "pending_worker: registrado (interval=%ds, batch_size=%d, timeout=%dmin, auto_classify=%s)",
        interval,
        settings.classificador_batch_size,
        settings.classificador_batch_timeout_minutes,
        settings.classificador_pending_auto_classify,
    )

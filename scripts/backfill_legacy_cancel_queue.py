"""
Backfill da fila de cancelamento da legacy task "Agendar Prazos" para
intakes pre-existentes.

Contexto: ate 2026-05-07 a fila de cancelamento (Pin0XX) so era criada
quando o `lawsuit_id` era resolvido (via `_resolve_intake_target_lawsuit`)
ou no momento do agendamento. A politica nova enfileira na criacao do
intake — mas intakes ja existentes no DB nao receberam item ainda.

Este script cria items PENDENTES na fila para intakes elegiveis:
  - tem `cnj_number` ou `lawsuit_id`
  - nao tem `legacy_task_cancellation_item` ainda
  - nao estao em status de DEVOLUCAO (Pin019: devolucao = exclusao
    manual no L1; nao gera cancel automatico).

Uso:
    # dry-run: lista quantos intakes criariam item, sem persistir
    python scripts/backfill_legacy_cancel_queue.py --dry-run

    # commit em batches de 100 (default)
    python scripts/backfill_legacy_cancel_queue.py --commit

    # commit em batches menores, util pra DB lento ou backlog grande
    python scripts/backfill_legacy_cancel_queue.py --commit --batch-size 50

    # limita pra teste
    python scripts/backfill_legacy_cancel_queue.py --commit --limit 10

Idempotente: re-rodar nao cria duplicatas (filtro pula intakes ja com item).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.prazo_inicial import (  # noqa: E402
    INTAKE_STATUS_DEVOLUCAO_PENDING,
    INTAKE_STATUS_DEVOLUCAO_SENT,
    PrazoInicialIntake,
)
from app.models.prazo_inicial_legacy_task_queue import (  # noqa: E402
    PrazoInicialLegacyTaskCancellationItem,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (  # noqa: E402
    PrazosIniciaisLegacyTaskQueueService,
)


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("backfill_legacy_cancel_queue")


EXCLUDED_INTAKE_STATUSES = {
    INTAKE_STATUS_DEVOLUCAO_PENDING,
    INTAKE_STATUS_DEVOLUCAO_SENT,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Lista quantos itens seriam criados, sem persistir.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Confirma a criacao dos itens (write).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Tamanho do batch entre commits (default 100).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limita o numero de intakes processados (util pra teste).",
    )
    args = parser.parse_args()

    if args.dry_run == args.commit:
        # Forca explicitar — evita ambiguidade ('sem flag' nao define intencao).
        print("Use exatamente um de --dry-run ou --commit.", file=sys.stderr)
        return 2

    db = SessionLocal()
    try:
        return _run(db, args)
    finally:
        db.close()


def _run(db, args) -> int:
    queue_svc = PrazosIniciaisLegacyTaskQueueService(
        db,
        # Backfill nao chama cancel_task — soh cria items. Mocka o
        # cancellation_service pra evitar instanciar o HTTP service
        # (que invocaria login Node por nada).
        cancellation_service=_NoOpCancellationService(),
    )

    # Pega ids dos intakes que JA tem item, pra excluir do candidate set.
    existing_ids = {
        row[0]
        for row in db.query(PrazoInicialLegacyTaskCancellationItem.intake_id).all()
    }
    logger.info("Intakes ja com item na fila: %d", len(existing_ids))

    query = (
        db.query(PrazoInicialIntake)
        .filter(~PrazoInicialIntake.status.in_(EXCLUDED_INTAKE_STATUSES))
        .order_by(PrazoInicialIntake.id.asc())
    )
    if existing_ids:
        query = query.filter(~PrazoInicialIntake.id.in_(existing_ids))
    if args.limit is not None:
        query = query.limit(args.limit)

    candidates = query.all()
    logger.info("Candidatos elegiveis: %d", len(candidates))

    created = 0
    skipped_no_id = 0
    failed = 0
    for index, intake in enumerate(candidates, start=1):
        if not (intake.lawsuit_id or intake.cnj_number):
            skipped_no_id += 1
            continue
        try:
            item = queue_svc.sync_item_from_intake(intake, commit=False)
            if item is not None:
                created += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Falha no intake %d (cnj=%s): %s",
                intake.id, intake.cnj_number, exc,
            )
            failed += 1
            continue
        if args.commit and (index % max(1, args.batch_size) == 0):
            db.commit()
            logger.info(
                "Commit batch (acumulado: criados=%d skipped=%d failed=%d / %d).",
                created, skipped_no_id, failed, index,
            )

    if args.commit:
        db.commit()
        logger.info(
            "DONE — criados=%d skipped_no_id=%d failed=%d.",
            created, skipped_no_id, failed,
        )
    else:
        db.rollback()
        logger.info(
            "DRY RUN — criariam=%d skipped_no_id=%d failed=%d (sem commit).",
            created, skipped_no_id, failed,
        )
    return 0 if failed == 0 else 1


class _NoOpCancellationService:
    """Stub usado pelo backfill — nao precisa do cancellation real."""

    def cancel_task(self, **kwargs):  # noqa: D401
        raise RuntimeError(
            "Backfill nao deve chamar cancel_task — use o worker periodico."
        )


if __name__ == "__main__":
    sys.exit(main())

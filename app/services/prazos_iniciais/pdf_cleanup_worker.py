"""
Cron defensivo de cleanup dos PDFs locais da habilitação.

Critério: intakes com `ged_uploaded_at IS NOT NULL AND pdf_path IS NOT NULL`
já tiveram o documento enviado ao GED do L1 — o arquivo local virou
redundante. O fluxo "feliz" apaga o arquivo imediatamente no
`scheduling_service._cleanup_local_pdf` logo após o upload, mas se
aquela chamada falhar por qualquer motivo (I/O, crash do container
entre o upload e o delete), este worker pega os resíduos.

Também limpa por retenção temporal: mesmo sem confirmação de GED,
arquivos mais antigos que `prazos_iniciais_retention_days` dias são
removidos pra não estourar o volume (cenário de intakes que travaram
em ERRO_CLASSIFICACAO/AGUARDANDO_CONFIG_TEMPLATE por semanas).

Registrado no APScheduler em `main.py` — rodando uma vez por dia de
madrugada (quando o operador não está mexendo).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.prazos_iniciais import storage as pdf_storage

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def cleanup_local_pdfs(db: Session) -> dict[str, int]:
    """
    Executa a limpeza e retorna contadores pra observabilidade:
      - ged_uploaded_cleaned: arquivos removidos por já estarem no GED
      - retention_expired_cleaned: arquivos removidos por retenção
      - failures: falhas ao tentar deletar (log warning mas não levanta)
    """
    stats = {"ged_uploaded_cleaned": 0, "retention_expired_cleaned": 0, "failures": 0}

    # ── Caminho 1: já subiu pro GED, pode apagar imediatamente ──
    ged_orphans = (
        db.query(PrazoInicialIntake)
        .filter(
            PrazoInicialIntake.ged_uploaded_at.isnot(None),
            PrazoInicialIntake.pdf_path.isnot(None),
        )
        .all()
    )
    for intake in ged_orphans:
        try:
            pdf_storage.delete_pdf(intake.pdf_path)
            intake.pdf_path = None
            intake.pdf_bytes = None
            stats["ged_uploaded_cleaned"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cleanup GED-orphan falhou intake=%s path=%s: %s",
                intake.id, intake.pdf_path, exc,
            )
            stats["failures"] += 1

    # ── Caminho 2: retenção temporal (PDFs velhos sem GED) ──
    retention_days = settings.prazos_iniciais_retention_days
    if retention_days > 0:
        cutoff = _utcnow() - timedelta(days=retention_days)
        expired = (
            db.query(PrazoInicialIntake)
            .filter(
                PrazoInicialIntake.pdf_path.isnot(None),
                PrazoInicialIntake.received_at < cutoff,
                # Só estourou retenção se não tá no meio do fluxo crítico
                # (se ainda está RECEBIDO/PRONTO_PARA_CLASSIFICAR/EM_CLASSIFICACAO,
                # mantém pro operador conseguir reprocessar).
                ~PrazoInicialIntake.status.in_([
                    "RECEBIDO",
                    "PRONTO_PARA_CLASSIFICAR",
                    "EM_CLASSIFICACAO",
                ]),
            )
            .all()
        )
        for intake in expired:
            try:
                pdf_storage.delete_pdf(intake.pdf_path)
                intake.pdf_path = None
                intake.pdf_bytes = None
                stats["retention_expired_cleaned"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "cleanup retention-expired falhou intake=%s path=%s: %s",
                    intake.id, intake.pdf_path, exc,
                )
                stats["failures"] += 1

    if any(v > 0 for v in stats.values()):
        db.commit()
    return stats


def _tick() -> None:
    """Wrapper que o APScheduler chama. Cria sessão própria por execução."""
    db: Session = SessionLocal()
    try:
        logger.info("pdf_cleanup.tick.start")
        stats = cleanup_local_pdfs(db)
        logger.info(
            "pdf_cleanup.tick.finish ged_cleaned=%d retention_cleaned=%d failures=%d",
            stats["ged_uploaded_cleaned"],
            stats["retention_expired_cleaned"],
            stats["failures"],
        )
    except Exception:
        logger.exception("pdf_cleanup.tick.error")
    finally:
        db.close()


def register_pdf_cleanup_job(scheduler) -> None:
    """
    Registra o job no APScheduler. Roda 1x por dia às 03:15 UTC
    (horário baixo de uso pra evitar disputar com o operador).
    """
    scheduler.add_job(
        _tick,
        trigger="cron",
        hour=3,
        minute=15,
        id="prazos_iniciais.pdf_cleanup",
        replace_existing=True,
        misfire_grace_time=3600,  # aceita execução atrasada até 1h
    )
    logger.info("pdf_cleanup worker registrado (diário 03:15 UTC).")

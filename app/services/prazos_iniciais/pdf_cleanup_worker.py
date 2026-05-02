"""
Cron defensivo de cleanup dos PDFs locais da habilitação.

Caminho 1 — pós-GED: intakes com `ged_uploaded_at IS NOT NULL AND
pdf_path IS NOT NULL` já tiveram o documento enviado ao GED do L1
— o arquivo local virou redundante. O fluxo "feliz" apaga o arquivo
imediatamente no `scheduling_service._cleanup_local_pdf` logo após
o upload, mas se aquela chamada falhar por qualquer motivo (I/O,
crash do container entre o upload e o delete), este worker pega os
resíduos.

Caminho 2 — retenção temporal de descartes: limpa apenas intakes
em status terminais de descarte (CANCELADO, ERRO_CLASSIFICACAO,
PROCESSO_NAO_ENCONTRADO) onde a habilitação claramente não vai mais
ser usada. Enquanto o tratamento web ainda pode acontecer (intake
em AGENDADO/EM_REVISAO/AGUARDANDO_CONFIG_TEMPLATE/ERRO_GED/
CONCLUIDO_SEM_PROVIDENCIA com dispatch_pending, etc.), o PDF é
preservado indefinidamente — o disparo precisa do arquivo pra subir
no GED do L1 (e futuramente no AJUS), e perder isso forçaria
reenvio manual pelo originador.

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

    # ── Caminho 2: retenção temporal só pra descartes ──
    # Inversão de lógica: em vez de listar status "preserva", listamos
    # explicitamente os terminais de descarte onde dá pra apagar com
    # segurança. Qualquer outro status (incluindo AGENDADO+pending,
    # EM_REVISAO, ERRO_GED, AGUARDANDO_CONFIG_TEMPLATE) preserva o PDF
    # indefinidamente — o tratamento web ainda pode rodar e precisa do
    # arquivo. Os terminais "felizes" (GED_ENVIADO, CONCLUIDO) não
    # caem aqui porque já têm ged_uploaded_at NOT NULL e foram tratados
    # no Caminho 1.
    retention_days = settings.prazos_iniciais_retention_days
    if retention_days > 0:
        cutoff = _utcnow() - timedelta(days=retention_days)
        expired = (
            db.query(PrazoInicialIntake)
            .filter(
                PrazoInicialIntake.pdf_path.isnot(None),
                PrazoInicialIntake.received_at < cutoff,
                PrazoInicialIntake.status.in_([
                    "CANCELADO",
                    "ERRO_CLASSIFICACAO",
                    "PROCESSO_NAO_ENCONTRADO",
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

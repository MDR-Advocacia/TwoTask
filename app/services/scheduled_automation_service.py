"""
Service para gerenciar agendamentos automáticos.

Integra com APScheduler para executar jobs periodicamente.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

from app.models.scheduled_automation import ScheduledAutomation, ScheduledAutomationRun
from app.models.publication_search import PublicationRecord
from app.models.publication_capture import (
    OfficePublicationCursor,
    PublicationFetchAttempt,
    ATTEMPT_STATUS_SUCCESS,
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_DEAD_LETTER,
    CURSOR_STATUS_OK,
    CURSOR_STATUS_FAILED,
    CURSOR_STATUS_DEAD_LETTER,
    RETRY_BACKOFF_MINUTES,
    MAX_CONSECUTIVE_FAILURES_BEFORE_DEAD_LETTER,
)

from app.core.config import settings

logger = logging.getLogger(__name__)


def _overlap_hours() -> int:
    """Overlap defensivo (em horas) aplicado às rodagens recorrentes.

    Configurável via env `PUBLICATION_OVERLAP_HOURS`. Como o filtro usa
    creationDate (disponibilização no L1), 1h já é suficiente.
    """
    return settings.publication_overlap_hours


def _initial_lookback_days() -> int:
    """Dias que a primeira rodagem (sem cursor) olha para trás.

    Configurável via env `PUBLICATION_INITIAL_LOOKBACK_DAYS`.
    """
    return settings.publication_initial_lookback_days


# Aliases para retro-compatibilidade (usados em outros pontos do módulo).
DEFAULT_OVERLAP_HOURS = _overlap_hours()
INITIAL_LOOKBACK_DAYS = _initial_lookback_days()


class ScheduledAutomationService:
    """Manages scheduled automations and APScheduler integration."""

    def __init__(self, db: Session, scheduler: Optional[BackgroundScheduler] = None):
        self.db = db
        self.scheduler = scheduler

    def create_automation(
        self,
        name: str,
        office_ids: List[int],
        steps: List[str],
        cron_expression: Optional[str] = None,
        interval_minutes: Optional[int] = None,
        created_by: Optional[int] = None,
        initial_lookback_days: Optional[int] = None,
        overlap_hours: Optional[int] = None,
    ) -> ScheduledAutomation:
        """Create a new scheduled automation."""
        automation = ScheduledAutomation(
            name=name,
            office_ids=office_ids,
            steps=steps,
            cron_expression=cron_expression,
            interval_minutes=interval_minutes,
            created_by=created_by,
            is_enabled=True,
            initial_lookback_days=initial_lookback_days,
            overlap_hours=overlap_hours,
        )
        self.db.add(automation)
        self.db.commit()
        self.db.refresh(automation)

        # Register with scheduler if enabled
        if self.scheduler:
            self._register_job(automation)

        return automation

    def update_automation(
        self,
        automation_id: int,
        name: Optional[str] = None,
        office_ids: Optional[List[int]] = None,
        steps: Optional[List[str]] = None,
        cron_expression: Optional[str] = None,
        interval_minutes: Optional[int] = None,
        is_enabled: Optional[bool] = None,
        initial_lookback_days: Optional[int] = None,
        overlap_hours: Optional[int] = None,
    ) -> ScheduledAutomation:
        """Update a scheduled automation."""
        automation = self.db.query(ScheduledAutomation).filter(
            ScheduledAutomation.id == automation_id
        ).first()

        if not automation:
            raise ValueError(f"Automation {automation_id} not found")

        if name is not None:
            automation.name = name
        if office_ids is not None:
            automation.office_ids = office_ids
        if steps is not None:
            automation.steps = steps
        if cron_expression is not None:
            automation.cron_expression = cron_expression
        if interval_minutes is not None:
            automation.interval_minutes = interval_minutes
        if is_enabled is not None:
            automation.is_enabled = is_enabled
        if initial_lookback_days is not None:
            automation.initial_lookback_days = initial_lookback_days
        if overlap_hours is not None:
            automation.overlap_hours = overlap_hours

        self.db.commit()
        self.db.refresh(automation)

        # Update job in scheduler
        if self.scheduler:
            job_id = f"automation_{automation_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
            if automation.is_enabled:
                self._register_job(automation)

        return automation

    def delete_automation(self, automation_id: int) -> None:
        """Delete a scheduled automation."""
        automation = self.db.query(ScheduledAutomation).filter(
            ScheduledAutomation.id == automation_id
        ).first()

        if not automation:
            raise ValueError(f"Automation {automation_id} not found")

        # Remove from scheduler
        if self.scheduler:
            job_id = f"automation_{automation_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

        self.db.delete(automation)
        self.db.commit()

    def get_automation(self, automation_id: int) -> Optional[ScheduledAutomation]:
        """Get a scheduled automation by ID."""
        return self.db.query(ScheduledAutomation).filter(
            ScheduledAutomation.id == automation_id
        ).first()

    def list_automations(self, is_enabled: Optional[bool] = None) -> List[ScheduledAutomation]:
        """List scheduled automations."""
        query = self.db.query(ScheduledAutomation)
        if is_enabled is not None:
            query = query.filter(ScheduledAutomation.is_enabled == is_enabled)
        return query.order_by(ScheduledAutomation.created_at.desc()).all()

    def get_runs(self, automation_id: int, limit: int = 50) -> List[ScheduledAutomationRun]:
        """Get runs for a specific automation."""
        return self.db.query(ScheduledAutomationRun).filter(
            ScheduledAutomationRun.automation_id == automation_id
        ).order_by(ScheduledAutomationRun.created_at.desc()).limit(limit).all()

    def _register_job(self, automation: ScheduledAutomation) -> None:
        """Register a job in APScheduler."""
        if not self.scheduler:
            logger.warning("Scheduler not configured, cannot register job for automation %d", automation.id)
            return

        job_id = f"automation_{automation.id}"

        try:
            # Determine trigger
            if automation.cron_expression:
                try:
                    from zoneinfo import ZoneInfo
                    br_tz = ZoneInfo("America/Sao_Paulo")
                except Exception:
                    br_tz = None
                trigger = CronTrigger.from_crontab(automation.cron_expression, timezone=br_tz) if br_tz else CronTrigger.from_crontab(automation.cron_expression)
            elif automation.interval_minutes:
                trigger = IntervalTrigger(minutes=automation.interval_minutes)
            else:
                logger.error("Automation %d has no schedule defined", automation.id)
                return

            # Register job
            self.scheduler.add_job(
                self._execute_automation,
                trigger=trigger,
                id=job_id,
                args=[automation.id],
                name=automation.name,
                replace_existing=True,
            )
            logger.info("Registered job %s for automation %s", job_id, automation.name)
        except Exception as e:
            logger.error("Failed to register job for automation %d: %s", automation.id, e)

    def _update_progress(
        self,
        run_id: int,
        phase: Optional[str] = None,
        current: Optional[int] = None,
        total: Optional[int] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update progress fields on a run, committing immediately so the UI sees it."""
        try:
            run = self.db.query(ScheduledAutomationRun).filter(
                ScheduledAutomationRun.id == run_id
            ).first()
            if not run:
                return
            if phase is not None:
                run.progress_phase = phase
            if current is not None:
                run.progress_current = current
            if total is not None:
                run.progress_total = total
            if message is not None:
                run.progress_message = message
            run.progress_updated_at = datetime.now(timezone.utc)
            self.db.commit()
        except Exception:
            logger.exception("Falha ao atualizar progress de run %s", run_id)
            try:
                self.db.rollback()
            except Exception:
                pass

    def _execute_automation(self, automation_id: int) -> None:
        """Execute an automation (called by scheduler)."""
        logger.info("Executing automation %d", automation_id)

        run = ScheduledAutomationRun(
            automation_id=automation_id,
            status="running",
            progress_phase="starting",
            progress_message="Iniciando execução...",
            progress_updated_at=datetime.now(timezone.utc),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        run_id = run.id

        steps_executed = []
        try:
            automation = self.db.query(ScheduledAutomation).filter(
                ScheduledAutomation.id == automation_id
            ).first()

            if not automation:
                raise ValueError(f"Automation {automation_id} not found")

            total_steps = len(automation.steps)

            # Execute steps
            for step_idx, step in enumerate(automation.steps, start=1):
                try:
                    if step == "pull_publications":
                        self._update_progress(
                            run_id,
                            phase="pull_publications",
                            current=0,
                            total=len(automation.office_ids),
                            message=f"Etapa {step_idx}/{total_steps}: Buscando publicações",
                        )
                        result = self._execute_pull_publications(
                            automation.office_ids,
                            automation_id=automation.id,
                            initial_lookback_days=automation.initial_lookback_days,
                            overlap_hours=automation.overlap_hours,
                            run_id=run_id,
                        )
                        steps_executed.append({
                            "step": "pull_publications",
                            "status": "success",
                            "records_found": result.get("records_found", 0),
                        })
                    elif step == "classify":
                        self._update_progress(
                            run_id,
                            phase="classify",
                            current=0,
                            total=None,
                            message=f"Etapa {step_idx}/{total_steps}: Classificando publicações",
                        )
                        result = self._execute_classify(automation.office_ids, run_id=run_id)
                        steps_executed.append({
                            "step": "classify",
                            "status": "success",
                            "records_classified": result.get("records_classified", 0),
                        })
                    elif step == "treat_publications":
                        self._update_progress(
                            run_id,
                            phase="treat_publications:start",
                            current=0,
                            total=None,
                            message=f"Etapa {step_idx}/{total_steps}: Tratando publicações no Legal One",
                        )
                        result = self._execute_treat_publications(
                            automation.office_ids,
                            automation_id=automation.id,
                            run_id=run_id,
                        )
                        steps_executed.append({
                            "step": "treat_publications",
                            "status": "warning" if result.get("failed_count", 0) else "success",
                            "treated_count": result.get("success_count", 0),
                            "failed_count": result.get("failed_count", 0),
                            "run_id": result.get("run_id"),
                        })
                    else:
                        steps_executed.append({
                            "step": step,
                            "status": "skipped",
                            "reason": f"Unknown step: {step}",
                        })
                except Exception as e:
                    logger.error("Step %s failed: %s", step, e)
                    steps_executed.append({
                        "step": step,
                        "status": "failed",
                        "error": str(e),
                    })

            # Update run and automation
            run.status = "success"
            run.steps_executed = steps_executed
            run.finished_at = datetime.now(timezone.utc)
            run.progress_phase = "done"
            run.progress_message = "Execução concluída"
            run.progress_updated_at = datetime.now(timezone.utc)

            automation.last_run_at = datetime.now(timezone.utc)
            automation.last_status = "success"
            automation.last_error = None

            logger.info("Automation %d completed successfully", automation_id)
        except Exception as e:
            logger.error("Automation %d failed: %s", automation_id, e)
            run.status = "failed"
            run.error_message = str(e)
            run.finished_at = datetime.now(timezone.utc)

            automation = self.db.query(ScheduledAutomation).filter(
                ScheduledAutomation.id == automation_id
            ).first()
            if automation:
                automation.last_run_at = datetime.now(timezone.utc)
                automation.last_status = "failed"
                automation.last_error = str(e)

        finally:
            self.db.commit()

    # ──────────────────────────────────────────────
    # Cursor + retry helpers
    # ──────────────────────────────────────────────

    def _get_or_create_cursor(self, office_id: int) -> OfficePublicationCursor:
        cursor = self.db.query(OfficePublicationCursor).filter(
            OfficePublicationCursor.office_id == office_id
        ).first()
        if cursor is None:
            cursor = OfficePublicationCursor(office_id=office_id, consecutive_failures=0)
            self.db.add(cursor)
            self.db.commit()
            self.db.refresh(cursor)
        return cursor

    def _compute_window(
        self,
        cursor: OfficePublicationCursor,
        now: datetime,
        initial_lookback_days: Optional[int] = None,
        overlap_hours: Optional[int] = None,
    ) -> tuple[datetime, datetime]:
        """Retorna (date_from, date_to) aplicando overlap defensivo.

        A janela é expressa no eixo `creationDate` (data em que o Legal One
        disponibilizou a publicação).

        Se `initial_lookback_days` / `overlap_hours` forem passados (vindos
        da configuração da automação), usa esses valores. Caso contrário,
        cai nos defaults globais.
        """
        effective_overlap = overlap_hours if overlap_hours is not None else _overlap_hours()
        effective_lookback = initial_lookback_days if initial_lookback_days is not None else _initial_lookback_days()

        overlap = timedelta(hours=effective_overlap)
        if cursor.last_successful_date is None:
            date_from = now - timedelta(days=effective_lookback)
        else:
            date_from = cursor.last_successful_date - overlap
        return date_from, now

    def _should_skip_office(self, office_id: int, now: datetime) -> bool:
        """Se há attempt em backoff pendente que ainda não venceu, pula neste run."""
        pending = self.db.query(PublicationFetchAttempt).filter(
            PublicationFetchAttempt.office_id == office_id,
            PublicationFetchAttempt.status == ATTEMPT_STATUS_FAILED,
            PublicationFetchAttempt.next_retry_at > now,
        ).order_by(PublicationFetchAttempt.id.desc()).first()
        return pending is not None

    def _record_attempt_success(
        self,
        office_id: int,
        window_from: datetime,
        window_to: datetime,
        records_found: int,
        automation_id: Optional[int],
    ) -> None:
        attempt = PublicationFetchAttempt(
            office_id=office_id,
            window_from=window_from,
            window_to=window_to,
            status=ATTEMPT_STATUS_SUCCESS,
            attempt_n=1,
            records_found=records_found,
            automation_id=automation_id,
        )
        self.db.add(attempt)

        cursor = self._get_or_create_cursor(office_id)
        cursor.last_successful_date = window_to
        cursor.last_run_at = datetime.now(timezone.utc)
        cursor.last_status = CURSOR_STATUS_OK
        cursor.last_error = None
        cursor.consecutive_failures = 0
        self.db.commit()

    def _record_attempt_failure(
        self,
        office_id: int,
        window_from: datetime,
        window_to: datetime,
        error: str,
        automation_id: Optional[int],
    ) -> None:
        cursor = self._get_or_create_cursor(office_id)
        cursor.consecutive_failures = (cursor.consecutive_failures or 0) + 1
        cursor.last_run_at = datetime.now(timezone.utc)
        cursor.last_error = error[:2000]

        attempt_n = cursor.consecutive_failures
        if attempt_n >= MAX_CONSECUTIVE_FAILURES_BEFORE_DEAD_LETTER:
            status = ATTEMPT_STATUS_DEAD_LETTER
            cursor.last_status = CURSOR_STATUS_DEAD_LETTER
            next_retry = None
            logger.error(
                "Office %s entrou em dead_letter após %d falhas consecutivas",
                office_id, attempt_n,
            )
        else:
            status = ATTEMPT_STATUS_FAILED
            cursor.last_status = CURSOR_STATUS_FAILED
            backoff_min = RETRY_BACKOFF_MINUTES[min(attempt_n - 1, len(RETRY_BACKOFF_MINUTES) - 1)]
            next_retry = datetime.now(timezone.utc) + timedelta(minutes=backoff_min)

        attempt = PublicationFetchAttempt(
            office_id=office_id,
            window_from=window_from,
            window_to=window_to,
            status=status,
            attempt_n=attempt_n,
            next_retry_at=next_retry,
            last_error=error[:2000],
            automation_id=automation_id,
        )
        self.db.add(attempt)
        self.db.commit()

    def _execute_pull_publications(
        self,
        office_ids: List[int],
        automation_id: Optional[int] = None,
        initial_lookback_days: Optional[int] = None,
        overlap_hours: Optional[int] = None,
        run_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executa pull_publications por escritório, usando watermark + overlap defensivo
        e registrando retry/dead-letter em publication_fetch_attempt.
        """
        from app.services.legal_one_client import LegalOneApiClient
        from app.services.publication_search_service import PublicationSearchService

        now = datetime.now(timezone.utc)
        total_found = 0
        skipped: List[int] = []
        failed: List[int] = []
        ok: List[int] = []

        # Cliente L1 + service
        client = LegalOneApiClient()
        search_service = PublicationSearchService(self.db, client)

        # Mapeia office_id interno → external_id (id real no Legal One).
        # O frontend manda sempre o id interno; o filtro de publicações
        # precisa bater com `responsibleOfficeId` dos processos, que é
        # o external_id.
        from app.models.legal_one import LegalOneOffice as _LOOffice
        _rows = (
            self.db.query(_LOOffice.id, _LOOffice.external_id)
            .filter(_LOOffice.id.in_(office_ids))
            .all()
        )
        internal_to_external = {r[0]: r[1] for r in _rows}
        logger.info(
            "Mapeando office_ids internos → external_id (L1): %s",
            internal_to_external,
        )

        total_offices = len(office_ids)
        for idx, office_id in enumerate(office_ids, start=1):
            if run_id is not None:
                ext = internal_to_external.get(office_id, office_id)
                self._update_progress(
                    run_id,
                    phase="pull_publications",
                    current=idx - 1,
                    total=total_offices,
                    message=f"Buscando escritório {idx}/{total_offices} (L1 id={ext})",
                )

            if self._should_skip_office(office_id, now):
                logger.info("Office %s pulado (em backoff).", office_id)
                skipped.append(office_id)
                if run_id is not None:
                    self._update_progress(
                        run_id,
                        current=idx,
                        message=f"Escritório {idx}/{total_offices}: pulado (backoff)",
                    )
                continue

            cursor = self._get_or_create_cursor(office_id)
            date_from, date_to = self._compute_window(
                cursor,
                now,
                initial_lookback_days=initial_lookback_days,
                overlap_hours=overlap_hours,
            )

            try:
                result = search_service.create_and_run_search(
                    # Formato ISO com hora/minuto — se usar só %Y-%m-%d, o
                    # client expande para T00:00:00Z e janelas menores que 1
                    # dia (overlap de horas) ficam ge==le e retornam 0.
                    date_from=date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    date_to=date_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    responsible_office_id=internal_to_external.get(office_id, office_id),
                    auto_classify=False,
                    requested_by="scheduler",
                )
                records_found = int(result.get("total_new", 0) or result.get("total_found", 0) or 0)
                total_found += records_found
                self._record_attempt_success(office_id, date_from, date_to, records_found, automation_id)
                ok.append(office_id)
                if run_id is not None:
                    self._update_progress(
                        run_id,
                        current=idx,
                        total=total_offices,
                        message=f"Escritório {idx}/{total_offices}: +{records_found} publicações (total {total_found})",
                    )
            except Exception as exc:  # noqa: BLE001 — queremos capturar qualquer falha
                logger.exception("Falha ao capturar publicações do escritório %s", office_id)
                self._record_attempt_failure(office_id, date_from, date_to, str(exc), automation_id)
                failed.append(office_id)
                if run_id is not None:
                    self._update_progress(
                        run_id,
                        current=idx,
                        total=total_offices,
                        message=f"Escritório {idx}/{total_offices}: falhou",
                    )

        return {
            "records_found": total_found,
            "offices_ok": ok,
            "offices_failed": failed,
            "offices_skipped": skipped,
        }

    def _execute_classify(self, office_ids: List[int], run_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Classifica publicações NOVO dos escritórios indicados via Anthropic
        Batch API.

        Fluxo:
          1. Mapeia office_id interno → external_id (L1), que é o valor
             salvo em PublicationRecord.linked_office_id.
          2. Coleta registros pendentes (status=NOVO, sem category).
          3. Submete batch à Anthropic.
          4. Faz polling até o batch terminar (timeout defensivo).
          5. Aplica resultados e atualiza os registros.
        """
        import asyncio
        import time
        from app.models.legal_one import LegalOneOffice as _LOOffice
        from app.services.publication_batch_classifier import (
            PublicationBatchClassifier,
            ANTHROPIC_STATUS_ENDED,
        )

        logger.info("Classifying publications for offices (internal ids): %s", office_ids)

        # 1) Mapeia id interno → external_id
        rows = (
            self.db.query(_LOOffice.id, _LOOffice.external_id)
            .filter(_LOOffice.id.in_(office_ids))
            .all()
        )
        internal_to_external = {r[0]: r[1] for r in rows}
        external_office_ids = [
            internal_to_external.get(oid, oid) for oid in office_ids
        ]
        logger.info(
            "Classify: office_ids externos (L1) = %s", external_office_ids
        )

        classifier = PublicationBatchClassifier(db=self.db)

        # 2) Coleta pendentes em todos os escritórios selecionados
        if run_id is not None:
            self._update_progress(run_id, phase="classify:collect", message="Coletando publicações pendentes...")
        all_records = []
        for ext_oid in external_office_ids:
            recs = classifier.collect_pending_records(linked_office_id=ext_oid)
            logger.info(
                "Classify: escritório %s → %d registros pendentes.", ext_oid, len(recs),
            )
            all_records.extend(recs)

        if not all_records:
            logger.info("Classify: nada a classificar.")
            if run_id is not None:
                self._update_progress(run_id, phase="classify:done", current=0, total=0, message="Nada para classificar")
            return {"records_classified": 0, "batch_id": None}

        total_records = len(all_records)
        if run_id is not None:
            self._update_progress(
                run_id,
                phase="classify:submit",
                current=0,
                total=total_records,
                message=f"Submetendo batch à Anthropic ({total_records} registros)...",
            )

        # 3) Submete batch (API async → asyncio.run)
        async def _run_flow():
            batch = await classifier.submit_batch(
                records=all_records, requested_by_email="scheduler"
            )
            logger.info(
                "Classify: batch %s submetido (%d registros).",
                batch.anthropic_batch_id, len(all_records),
            )

            # 4) Polling até terminar (timeout ~30 min)
            poll_interval = 30   # s
            max_wait = 30 * 60   # s
            deadline = time.monotonic() + max_wait

            while time.monotonic() < deadline:
                batch = await classifier.refresh_batch_status(batch)
                if run_id is not None:
                    done = (batch.succeeded_count or 0) + (batch.errored_count or 0)
                    self._update_progress(
                        run_id,
                        phase="classify:poll",
                        current=done,
                        total=total_records,
                        message=f"Anthropic: {done}/{total_records} classificadas (status={batch.anthropic_status})",
                    )
                if batch.anthropic_status == ANTHROPIC_STATUS_ENDED:
                    break
                logger.info(
                    "Classify: batch %s status=%s (succ=%s err=%s) — aguardando...",
                    batch.anthropic_batch_id,
                    batch.anthropic_status,
                    batch.succeeded_count,
                    batch.errored_count,
                )
                await asyncio.sleep(poll_interval)
            else:
                logger.warning(
                    "Classify: batch %s não terminou dentro de %ds; seguindo sem aplicar.",
                    batch.anthropic_batch_id, max_wait,
                )
                return {"records_classified": 0, "batch_id": batch.id, "timeout": True}

            # 5) Apply
            if run_id is not None:
                self._update_progress(
                    run_id,
                    phase="classify:apply",
                    current=total_records,
                    total=total_records,
                    message="Aplicando resultados nos registros...",
                )
            result = await classifier.apply_batch_results(batch)
            logger.info(
                "Classify: batch %s aplicado. Resultado: %s",
                batch.anthropic_batch_id, result,
            )
            return {
                "records_classified": result.get("succeeded", 0),
                "batch_id": batch.id,
                "failed": result.get("failed", 0),
                "skipped": result.get("skipped", 0),
                "total": result.get("total", 0),
            }

        try:
            return asyncio.run(_run_flow())
        except Exception as exc:
            logger.exception("Classify: falha na execução do batch: %s", exc)
            return {"records_classified": 0, "error": str(exc)}

    def _execute_treat_publications(
        self,
        office_ids: List[int],
        automation_id: Optional[int] = None,
        run_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        import time

        from app.models.publication_treatment import (
            RUN_STATUS_COMPLETED,
            RUN_STATUS_COMPLETED_WITH_ERRORS,
        )
        from app.services.publication_treatment_service import PublicationTreatmentService

        treatment_service = PublicationTreatmentService(self.db)
        start_result = treatment_service.start_run(
            office_ids=office_ids,
            trigger_type="AUTOMACAO",
            triggered_by_email="scheduler",
            automation_id=automation_id,
        )

        if not start_result.get("started"):
            existing_run = start_result.get("run") or {}
            if start_result.get("reason") == "already_running" and existing_run.get("id"):
                if run_id is not None:
                    self._update_progress(
                        run_id,
                        phase="treat_publications:wait",
                        message="Tratamento já está em execução; acompanhando run existente...",
                    )
                treatment_run_id = existing_run["id"]
            else:
                if run_id is not None:
                    self._update_progress(
                        run_id,
                        phase="treat_publications:done",
                        current=0,
                        total=0,
                        message="Nenhuma publicação pendente para tratamento.",
                    )
                return {
                    "run_id": existing_run.get("id"),
                    "success_count": existing_run.get("success_count", 0),
                    "failed_count": existing_run.get("failed_count", 0),
                }
        else:
            treatment_run_id = start_result["run"]["id"]
        poll_seconds = max(1, settings.publication_treatment_monitor_poll_seconds)

        while True:
            snapshot = treatment_service.get_run(treatment_run_id, sync_from_file=True)
            if not snapshot:
                raise RuntimeError(f"Run de tratamento #{treatment_run_id} não encontrado.")

            snapshot_payload = treatment_service._run_to_dict(snapshot)  # noqa: SLF001
            if run_id is not None:
                self._update_progress(
                    run_id,
                    phase="treat_publications:wait",
                    current=snapshot_payload.get("processed_items"),
                    total=snapshot_payload.get("total_items"),
                    message=(
                        f"Tratamento L1: {snapshot_payload.get('processed_items', 0)}/"
                        f"{snapshot_payload.get('total_items', 0)} processadas"
                    ),
                )

            if snapshot_payload["is_final"]:
                final_status = snapshot_payload["status"]
                if final_status not in {RUN_STATUS_COMPLETED, RUN_STATUS_COMPLETED_WITH_ERRORS}:
                    raise RuntimeError(
                        f"Tratamento de publicações finalizou com status {final_status}."
                    )

                if run_id is not None:
                    self._update_progress(
                        run_id,
                        phase="treat_publications:done",
                        current=snapshot_payload.get("processed_items"),
                        total=snapshot_payload.get("total_items"),
                        message=(
                            f"Tratamento concluído: {snapshot_payload.get('success_count', 0)} sucesso(s), "
                            f"{snapshot_payload.get('failed_count', 0)} falha(s)."
                        ),
                    )

                return {
                    "run_id": treatment_run_id,
                    "success_count": snapshot_payload.get("success_count", 0),
                    "failed_count": snapshot_payload.get("failed_count", 0),
                }

            time.sleep(poll_seconds)

from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models as _models
from app.api.v1.endpoints import (
    admin,
    auth,
    automations,
    capture_health,
    classifier,
    dashboard,
    offices,
    prazos_iniciais,
    prazos_iniciais_legacy_tasks,
    prazos_iniciais_scheduling,
    publication_treatment,
    publications,
    sectors,
    squads,
    task_templates,
    tasks,
    users,
)
from app.core import auth as auth_security
from app.core.config import settings
from app.core.scheduler import scheduler
from app.services.batch_worker import BatchExecutionWorker

logger = logging.getLogger(__name__)
batch_worker = BatchExecutionWorker()


@asynccontextmanager
async def lifespan(_: FastAPI):
    batch_worker.start()
    scheduler.start()
    logger.info("APScheduler started")

    # Repovoa o scheduler com as automations persistidas e habilitadas.
    try:
        from app.db.session import SessionLocal
        from app.models.scheduled_automation import ScheduledAutomation
        from app.services.scheduled_automation_service import ScheduledAutomationService

        db = SessionLocal()
        try:
            service = ScheduledAutomationService(db=db, scheduler=scheduler)
            enabled = (
                db.query(ScheduledAutomation)
                .filter(ScheduledAutomation.is_enabled == True)  # noqa: E712
                .all()
            )
            for automation in enabled:
                try:
                    service._register_job(automation)
                except Exception:
                    logger.exception(
                        "Falha ao registrar automation %d no scheduler", automation.id
                    )
            if enabled:
                logger.info("Repovoei %d automation(s) no scheduler.", len(enabled))
        finally:
            db.close()
    except Exception:
        logger.exception("Falha ao repopular automations no startup.")

    try:
        from datetime import datetime, timezone

        from app.db.session import SessionLocal
        from app.models.scheduled_automation import ScheduledAutomation, ScheduledAutomationRun

        db = SessionLocal()
        try:
            orphans = (
                db.query(ScheduledAutomationRun)
                .filter(ScheduledAutomationRun.status == "running")
                .all()
            )
            for run in orphans:
                run.status = "failed"
                run.error_message = "API reiniciou durante a execução - polling do batch interrompido."
                run.finished_at = datetime.now(timezone.utc)
                run.progress_phase = "orphaned"
                run.progress_message = "Execução interrompida por reinício da API"
                run.progress_updated_at = datetime.now(timezone.utc)
                automation = (
                    db.query(ScheduledAutomation)
                    .filter(ScheduledAutomation.id == run.automation_id)
                    .first()
                )
                if automation:
                    automation.last_status = "failed"
                    automation.last_error = run.error_message
            if orphans:
                logger.warning("Reapei %d run(s) órfãs de automations.", len(orphans))
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Falha ao reapear runs órfãs no startup.")

    # Reapa syncs de escritório órfãs — thread daemon morre no restart sem rodar o finally
    try:
        from datetime import datetime, timezone

        from app.db.session import SessionLocal
        from app.models.office_lawsuit_index import OfficeLawsuitSync

        db = SessionLocal()
        try:
            stuck = (
                db.query(OfficeLawsuitSync)
                .filter(OfficeLawsuitSync.in_progress == True)  # noqa: E712
                .all()
            )
            for state in stuck:
                state.in_progress = False
                state.last_sync_status = "error"
                state.last_sync_error = (
                    "API reiniciou durante a sincronização - thread interrompida."
                )
                state.finished_at = datetime.now(timezone.utc)
            if stuck:
                logger.warning(
                    "Reapei %d sync(s) órfã(s) de escritório (in_progress=True).",
                    len(stuck),
                )
                db.commit()
        finally:
            db.close()
    except Exception:
        logger.exception("Falha ao reapear syncs órfãs de escritório no startup.")

    # Reapa buscas de publicações presas em EXECUTANDO — o try/except interno
    # do PublicationSearchService não cobre SIGKILL/OOM (caso visto em prod
    # na Busca #2 em 22/04/2026: status ficou EXECUTANDO por 30+ min com
    # total_new=0 na UI, sem error_message). Também registra job periódico
    # no APScheduler pra cobrir casos sem restart de container.
    try:
        from app.services.publication_search_watchdog import (
            reap_orphaned_searches_on_startup,
            register_publication_search_watchdog_job,
        )

        reap_orphaned_searches_on_startup()
        register_publication_search_watchdog_job(scheduler)
    except Exception:
        logger.exception(
            "Falha ao inicializar watchdog de buscas de publicações no startup."
        )

    # Worker periódico do fluxo "Agendar Prazos Iniciais" — gated pela flag
    # prazos_iniciais_auto_classification_enabled (default off).
    try:
        from app.services.prazos_iniciais.auto_worker import (
            register_auto_classification_job,
        )

        register_auto_classification_job(scheduler)
    except Exception:
        logger.exception(
            "Falha ao registrar worker auto de prazos iniciais no startup."
        )

    try:
        from app.services.prazos_iniciais.legacy_task_queue_worker import (
            register_legacy_task_cancellation_job,
        )

        register_legacy_task_cancellation_job(scheduler)
    except Exception:
        logger.exception(
            "Falha ao registrar worker de cancelamento legado de prazos iniciais no startup."
        )

    try:
        yield
    finally:
        batch_worker.stop()
        scheduler.shutdown()
        logger.info("APScheduler stopped")


app = FastAPI(title="OneTask API", version="1.0.0", lifespan=lifespan)

origins = settings.cors_origins
allow_origin_regex = None
allow_credentials = True

if "*" in origins:
    origins = []
    allow_origin_regex = ".*"
    allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

protected_dependencies = [Depends(auth_security.get_current_user)]

app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"], dependencies=protected_dependencies)
app.include_router(capture_health.router, prefix="/api/v1/admin", tags=["Admin"], dependencies=protected_dependencies)
app.include_router(admin.me_router, prefix="/api/v1", tags=["User"], dependencies=protected_dependencies)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"], dependencies=protected_dependencies)
app.include_router(squads.router, prefix="/api/v1/squads", tags=["Squads"], dependencies=protected_dependencies)
app.include_router(sectors.router, prefix="/api/v1/sectors", tags=["Sectors"], dependencies=protected_dependencies)
app.include_router(tasks.router, prefix="/api/v1/tasks", tags=["Tasks"], dependencies=protected_dependencies)
# Router de automação externa (OneSid, OneRequest): autenticado por
# header X-Batch-Api-Key, SEM JWT. Separado pra não herdar o
# protected_dependencies do router de operador.
app.include_router(tasks.batch_router, prefix="/api/v1/tasks")
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"], dependencies=protected_dependencies)
app.include_router(offices.router, prefix="/api/v1", tags=["Offices"], dependencies=protected_dependencies)
app.include_router(classifier.router, prefix="/api/v1/classifier", tags=["Classificador"], dependencies=protected_dependencies)
app.include_router(publications.router, prefix="/api/v1/publications", tags=["Publicações"], dependencies=protected_dependencies)
app.include_router(publication_treatment.router, prefix="/api/v1/publications", tags=["Publicações"], dependencies=protected_dependencies)
# Intake externo: autenticado por API key (header X-Intake-Api-Key), SEM JWT.
app.include_router(prazos_iniciais.intake_router, prefix="/api/v1")
# Endpoints internos de prazos iniciais (UI do operador): JWT obrigatório.
app.include_router(prazos_iniciais.router, prefix="/api/v1", dependencies=protected_dependencies)
app.include_router(
    prazos_iniciais_legacy_tasks.router,
    prefix="/api/v1",
    dependencies=protected_dependencies,
)
app.include_router(
    prazos_iniciais_scheduling.router,
    prefix="/api/v1",
    dependencies=protected_dependencies,
)
app.include_router(task_templates.router, prefix="/api/v1/task-templates", tags=["Templates de Tarefa"], dependencies=protected_dependencies)
app.include_router(automations.router, prefix="/api/v1/automations", tags=["Automações"], dependencies=protected_dependencies)
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Autenticacao"])


@app.get(
    "/api/v1/monitor/legal-one-position-fix/status",
    tags=["Monitor"],
    summary="Acompanhar correcao de posicao do cliente principal (autenticado)",
    dependencies=protected_dependencies,
)
def monitor_legal_one_position_fix_status():
    return tasks.get_legal_one_position_fix_status()


@app.post(
    "/api/v1/monitor/legal-one-position-fix/control",
    tags=["Monitor"],
    summary="Pausar ou retomar a correcao de posicao do cliente principal (autenticado)",
    dependencies=protected_dependencies,
)
def monitor_legal_one_position_fix_control(payload: tasks.LegalOnePositionFixControlRequest):
    return tasks.set_legal_one_position_fix_control(payload.action)


@app.get("/", tags=["Root"])
async def read_root():
    return {"message": "Bem-vindo a API OneTask"}


@app.get("/healthz", tags=["Health"])
async def healthcheck():
    return {
        "status": "ok",
        "batch_worker_enabled": settings.batch_worker_enabled,
    }

import asyncio
import logging
import threading
import time
import uuid

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.batch_task_creation_service import BatchTaskCreationService
from app.services.legal_one_client import LegalOneApiClient


class BatchExecutionWorker:
    def __init__(self):
        self.worker_id = f"worker-{uuid.uuid4()}"
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._poll_interval = max(settings.batch_worker_poll_interval_seconds, 1)

    def start(self) -> None:
        if not settings.batch_worker_enabled:
            logging.info("Batch worker desabilitado por configuracao.")
            return
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(
            target=self._run_loop,
            name="batch-execution-worker",
            daemon=True,
        )
        self._thread.start()
        logging.info("Batch worker iniciado com id %s.", self.worker_id)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _process_execution(self, execution_id: int) -> None:
        db = SessionLocal()
        try:
            service = BatchTaskCreationService(db=db, client=LegalOneApiClient())
            asyncio.run(service.process_claimed_execution(execution_id, self.worker_id))
        except Exception as exc:
            logging.error("Erro ao processar execucao %s no worker: %s", execution_id, exc, exc_info=True)
        finally:
            db.close()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            db = SessionLocal()
            claimed_execution_id = None
            try:
                service = BatchTaskCreationService(db=db, client=None)
                claimed_execution_id = service.claim_next_execution(self.worker_id)
            except Exception as exc:
                logging.error("Erro ao consultar fila de lotes: %s", exc, exc_info=True)
            finally:
                db.close()

            if claimed_execution_id is None:
                time.sleep(self._poll_interval)
                continue

            self._process_execution(claimed_execution_id)

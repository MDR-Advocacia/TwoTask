# app/services/batch_task_creation_service.py
import logging
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest
from app.services.batch_strategies.base_strategy import BaseStrategy
from app.services.batch_strategies.onesid_strategy import OnesidStrategy

class BatchTaskCreationService:
    """
    Orquestrador que seleciona a estratégia correta com base na 'fonte'
    para processar a criação de tarefas em lote.
    """
    def __init__(self, db: Session, client: LegalOneApiClient):
        self.db = db
        self.client = client
        self._strategies: dict[str, type[BaseStrategy]] = {
            "Onesid": OnesidStrategy
        }

    async def process_batch_request(self, request: BatchTaskCreationRequest):
        """
        Ponto de entrada do serviço. Identifica a fonte e executa a estratégia.
        """
        # --- LINHA CORRIGIDA ---
        logging.info(f"Recebida requisição de lote da fonte: '{request.fonte}' com {len(request.processos)} processos.")
        # ---------------------
        
        strategy_class = self._strategies.get(request.fonte)

        if not strategy_class:
            logging.error(f"Nenhuma estratégia encontrada para a fonte: '{request.fonte}'")
            return

        strategy_instance = strategy_class(self.db, self.client)
        result = await strategy_instance.process_batch(request)

        logging.info(f"Processamento do lote da fonte '{request.fonte}' concluído. Resultado: {result}")
# app/services/batch_task_creation_service.py
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest
from app.services.batch_strategies.base_strategy import BaseStrategy
from app.services.batch_strategies.onesid_strategy import OnesidStrategy
from app.models.batch_execution import BatchExecution

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
        Ponto de entrada do serviço. Identifica a fonte, cria o log e executa a estratégia.
        """
        logging.info(f"Recebida requisição de lote da fonte: '{request.fonte}' com {len(request.processos)} processos.")
        
        # PASSO 1: Cria o registro principal da execução do lote no BD
        execution_log = BatchExecution(
            source=request.fonte,
            total_items=len(request.processos)
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)
        
        try:
            strategy_class = self._strategies.get(request.fonte)

            if not strategy_class:
                raise ValueError(f"Nenhuma estratégia encontrada para a fonte: '{request.fonte}'")

            strategy_instance = strategy_class(self.db, self.client)
            
            # PASSO 2: Executa a estratégia, passando o objeto de log para ser preenchido
            result = await strategy_instance.process_batch(request, execution_log)

            # PASSO 3: Atualiza o log principal com os totais retornados pela estratégia
            execution_log.success_count = result.get("sucesso", 0)
            execution_log.failure_count = result.get("falhas", 0)
            logging.info(f"Processamento do lote da fonte '{request.fonte}' concluído. Resultado: {result}")

        except Exception as e:
            logging.error(f"Erro catastrófico ao processar o lote: {e}", exc_info=True)
            # Em caso de erro grave, preenche o restante como falha
            execution_log.failure_count = execution_log.total_items - execution_log.success_count
        
        finally:
            # PASSO 4: Garante que o tempo de finalização e o resultado sejam salvos no BD
            execution_log.end_time = datetime.now(timezone.utc)
            self.db.commit()
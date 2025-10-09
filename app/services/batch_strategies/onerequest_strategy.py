# Conteúdo para: app/services/batch_strategies/onerequest_strategy.py

import logging
import asyncio
from datetime import date, timedelta, datetime, timezone, time
from zoneinfo import ZoneInfo

from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneTaskSubType

# ATENÇÃO: Estes IDs provavelmente serão diferentes para o Onerequest.
# Manteremos os mesmos do Onesid como placeholder por enquanto.
TASK_SUBTYPE_EXTERNAL_ID = 1132
TASK_TYPE_EXTERNAL_ID = 26
DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente

class OnerequestStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir da fonte Onerequest.
    A lógica específica será adaptada conforme as regras de negócio do Onerequest.
    """
    
    def _get_next_business_day(self) -> date:
        """ Calcula o próximo dia útil. """
        today = date.today()
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5: # 5 = Sábado, 6 = Domingo
            next_day += timedelta(days=1)
        return next_day

    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        logging.info(f"Processando lote para a fonte 'Onerequest' com {len(request.processos)} processos.")
        success_count = 0
        failed_items = []

        # A lógica de negócio detalhada virá nos próximos passos.
        # Por enquanto, vamos simular o processamento para garantir que a estrutura funcione.
        
        for processo in request.processos:
            log_item = BatchExecutionItem(
                process_number=processo.numero_processo,
                execution_id=execution_log.id,
                status="FALHA", # Começa como falha
                error_message="Lógica de negócio para Onerequest ainda não implementada."
            )
            failed_items.append({"cnj": processo.numero_processo, "motivo": log_item.error_message})
            execution_log.items.append(log_item)
            await asyncio.sleep(0.05) # Simula uma pequena operação

        logging.warning("Execução da OnerequestStrategy simulada. Nenhuma tarefa foi criada.")

        return {
            "sucesso": success_count,
            "falhas": len(failed_items),
            "detalhes_falhas": failed_items
        }
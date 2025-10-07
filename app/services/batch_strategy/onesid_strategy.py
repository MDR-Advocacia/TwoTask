# app/services/batch_strategies/onesid_strategy.py
import asyncio
import logging
from datetime import date, timedelta
from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.legal_one import LegalOneTaskSubType
# Configurações específicas da estratégia "Onesid"
TASK_SUBTYPE_EXTERNAL_ID = 1132
TASK_TYPE_EXTERNAL_ID = 26 # ID do Pai "PRAZO"

class OnesidStrategy(BaseStrategy):
    """
    Estratégia específica para criar tarefas originadas do sistema Onsid.
    """
    def _get_next_business_day(self) -> date:
        """ Calcula o próximo dia útil. """
        today = date.today()
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5: # 5 = Sábado, 6 = Domingo
            next_day += timedelta(days=1)
        return next_day

    async def process_batch(self, request: BatchTaskCreationRequest) -> dict:
        """ Processa o lote de CNJs vindo do Onsid. """
        success_count = 0
        failed_items = []
        deadline = self._get_next_business_day().strftime("%Y-%m-%d")

        # Valida se o tipo/subtipo de tarefa existem no nosso BD
        sub_type = self.db.query(LegalOneTaskSubType).filter(LegalOneTaskSubType.external_id == TASK_SUBTYPE_EXTERNAL_ID).first()
        if not sub_type or sub_type.parent_type.external_id != TASK_TYPE_EXTERNAL_ID:
            raise ValueError(f"Tipo/Subtipo de tarefa ({TASK_TYPE_EXTERNAL_ID}/{TASK_SUBTYPE_EXTERNAL_ID}) não configurado corretamente no banco de dados.")

        for cnj in request.process_numbers:
            try:
                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")

                task_payload = {
                    "taskTypeId": TASK_TYPE_EXTERNAL_ID,
                    "taskSubTypeId": TASK_SUBTYPE_EXTERNAL_ID,
                    "description": f"Tarefa automática: Subsídio Atendido via Onsid para o processo {cnj}",
                    "deadline": deadline,
                    "relationships": [{"type": "Processo", "id": lawsuit['id']}],
                    "responsibles": [{"id": request.responsible_external_id}]
                }

                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa na API do Legal One.")

                success_count += 1
                logging.info(f"Tarefa para CNJ {cnj} criada com sucesso. ID: {created_task['id']}")
                await asyncio.sleep(0.1) # Pequeno delay para não sobrecarregar a API externa

            except Exception as e:
                logging.error(f"Falha ao processar CNJ {cnj}: {str(e)}")
                failed_items.append({"cnj": cnj, "motivo": str(e)})

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
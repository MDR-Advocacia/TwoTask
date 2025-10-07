# app/services/batch_strategies/onesid_strategy.py
import asyncio
import logging
from datetime import date, timedelta, datetime, timezone
from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.legal_one import LegalOneTaskSubType

# Configurações específicas da estratégia "Onesid"
TASK_SUBTYPE_EXTERNAL_ID = 1132
TASK_TYPE_EXTERNAL_ID = 26
DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente no Legal One

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
        
        # Define o prazo e o formata para o padrão ISO com timezone (UTC)
        deadline_date = self._get_next_business_day()
        deadline_datetime = datetime.combine(deadline_date, datetime.min.time())
        end_datetime_iso = deadline_datetime.isoformat() + "Z"
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Valida se o tipo/subtipo de tarefa existem no nosso BD
        sub_type = self.db.query(LegalOneTaskSubType).filter(LegalOneTaskSubType.external_id == TASK_SUBTYPE_EXTERNAL_ID).first()
        if not sub_type or sub_type.parent_type.external_id != TASK_TYPE_EXTERNAL_ID:
            raise ValueError(f"Tipo/Subtipo de tarefa ({TASK_TYPE_EXTERNAL_ID}/{TASK_SUBTYPE_EXTERNAL_ID}) não configurado corretamente no banco de dados.")

        for cnj in request.process_numbers:
            try:
                # PASSO 1: ENRIQUECIMENTO - Buscar dados do processo
                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')

                if not responsible_office_id:
                    raise Exception("Processo encontrado não possui um Escritório Responsável definido.")

                # PASSO 2: MONTAGEM DO PAYLOAD - Agora completo e correto
                task_payload = {
                    "description": f"Tarefa automática: Subsídio Atendido via Onsid para o processo {cnj}",
                    "priority": "Normal",
                    "startDateTime": start_datetime_iso,
                    "endDateTime": end_datetime_iso,
                    "status": { "id": DEFAULT_TASK_STATUS_ID },
                    "typeId": TASK_TYPE_EXTERNAL_ID,
                    "subTypeId": TASK_SUBTYPE_EXTERNAL_ID,
                    "responsibleOfficeId": responsible_office_id,
                    "originOfficeId": responsible_office_id, # <-- CORREÇÃO 1: Adicionado
                    "participants": [
                        {
                            "contact": {"id": request.responsible_external_id},
                            "isResponsible": True,
                            "isExecuter": True,
                            "isRequester": True # <-- CORREÇÃO 2: Adicionado
                        }
                    ]
                }
                # PASSO 3: CRIAÇÃO E VÍNCULO
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa na API do Legal One (resposta inválida).")
                
                task_id = created_task['id']
                
                link_success = self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})
                if not link_success:
                     # Mesmo que o vínculo falhe, a tarefa foi criada. Consideramos um sucesso parcial.
                    logging.warning(f"Tarefa ID {task_id} criada, mas falha ao vincular ao processo ID {lawsuit_id}.")

                success_count += 1
                logging.info(f"Tarefa para CNJ {cnj} processada com sucesso. Task ID: {task_id}")
                await asyncio.sleep(0.1) 

            except Exception as e:
                logging.error(f"Falha ao processar CNJ {cnj}: {str(e)}")
                failed_items.append({"cnj": cnj, "motivo": str(e)})

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
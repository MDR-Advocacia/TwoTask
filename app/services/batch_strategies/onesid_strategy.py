# app/services/batch_strategies/onesid_strategy.py
import asyncio
import logging
from datetime import date, timedelta, datetime, timezone, time
from zoneinfo import ZoneInfo
from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.legal_one import LegalOneTaskSubType
from app.models.batch_execution import BatchExecution, BatchExecutionItem

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

    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        """ Processa o lote de CNJs vindo do Onsid, registrando cada item no log. """
        success_count = 0
        failed_items = []
        
        # Lógica de data robusta com fuso horário explícito
        local_tz = ZoneInfo("America/Sao_Paulo")
        deadline_date = self._get_next_business_day()
        naive_deadline = datetime.combine(deadline_date, time(23, 59, 59))
        aware_deadline = naive_deadline.replace(tzinfo=local_tz)
        utc_deadline = aware_deadline.astimezone(timezone.utc)
        end_datetime_iso = utc_deadline.isoformat().replace('+00:00', 'Z')
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        # Valida se o tipo/subtipo de tarefa existem no nosso BD
        sub_type = self.db.query(LegalOneTaskSubType).filter(LegalOneTaskSubType.external_id == TASK_SUBTYPE_EXTERNAL_ID).first()
        if not sub_type or sub_type.parent_type.external_id != TASK_TYPE_EXTERNAL_ID:
            raise ValueError(f"Tipo/Subtipo de tarefa ({TASK_TYPE_EXTERNAL_ID}/{TASK_SUBTYPE_EXTERNAL_ID}) não configurado corretamente no banco de dados.")

        for item in request.processos:
            cnj = item.numero_processo
            id_responsavel = item.id_responsavel
            observacao = item.observacao
            
            # Cria o item de log para este CNJ
            log_item = BatchExecutionItem(process_number=cnj, execution_id=execution_log.id)

            try:
                # PASSO 1: ENRIQUECIMENTO - Buscar dados do processo
                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')

                if not responsible_office_id:
                    raise Exception("Processo encontrado não possui um Escritório Responsável definido.")

                # PASSO 2: MONTAGEM DO PAYLOAD
                task_payload = {
                    "description": f"Tarefa automática: Subsídio Atendido via Onsid para o processo {cnj}",
                    "priority": "Normal",
                    "startDateTime": start_datetime_iso,
                    "endDateTime": end_datetime_iso,
                    "status": { "id": DEFAULT_TASK_STATUS_ID },
                    "typeId": TASK_TYPE_EXTERNAL_ID,
                    "subTypeId": TASK_SUBTYPE_EXTERNAL_ID,
                    "responsibleOfficeId": responsible_office_id,
                    "originOfficeId": responsible_office_id,
                    "participants": [
                        {
                            "contact": {"id": id_responsavel},
                            "isResponsible": True,
                            "isExecuter": True,
                            "isRequester": True
                        }
                    ]
                }

                # Adiciona o campo de observação ao payload apenas se ele foi enviado
                if observacao:
                    task_payload['notes'] = observacao

                # PASSO 3: CRIAÇÃO E VÍNCULO
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa na API do Legal One (resposta inválida).")
                
                task_id = created_task['id']
                
                link_success = self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})
                if not link_success:
                    logging.warning(f"Tarefa ID {task_id} criada, mas falha ao vincular ao processo ID {lawsuit_id}.")

                # Log de sucesso
                log_item.status = "SUCESSO"
                log_item.created_task_id = task_id
                
                success_count += 1
                logging.info(f"Tarefa para CNJ {cnj} processada com sucesso. Task ID: {task_id}")
                
            except Exception as e:
                error_msg = str(e)
                # Log de falha
                log_item.status = "FALHA"
                log_item.error_message = error_msg
                
                logging.error(f"Falha ao processar CNJ {cnj}: {error_msg}")
                failed_items.append({"cnj": cnj, "motivo": error_msg})
            
            finally:
                # Adiciona o item (sucesso ou falha) à lista de itens da execução
                execution_log.items.append(log_item)
                await asyncio.sleep(0.1)

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
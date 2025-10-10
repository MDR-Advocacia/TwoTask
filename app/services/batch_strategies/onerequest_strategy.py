# Conteúdo para: app/services/batch_strategies/onerequest_strategy.py

import logging
import asyncio
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest, ProcessoResponsavel
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneTaskSubType

# --- PONTO DE CONFIGURAÇÃO CENTRAL ---
# Dicionário preenchido com as regras de negócio fornecidas.
SECTOR_TASK_MAPPING = {
    "BB Réu": (967, 15),
    "BB Recurso": (968, 19),
    "BB Encerramento": (1058, 20),
    "BB Autor": (969, 18)
}

DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente

class OnerequestStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir da fonte Onerequest.
    Utiliza o campo 'setor' para determinar dinamicamente o tipo de tarefa
    e o escritório responsável.
    """

    def _parse_and_format_deadline(self, date_str: str) -> str:
        """
        Converte uma data de 'dd_mm_aaaa' para o formato ISO 8601 em UTC.
        """
        try:
            # Converte a string de data para um objeto datetime
            local_deadline_date = datetime.strptime(date_str, "%d_%m_%Y")
            
            # Define o fuso horário local e o horário de fim do dia
            local_tz = ZoneInfo("America/Sao_Paulo")
            aware_deadline = datetime.combine(local_deadline_date.date(), time(23, 59, 59)).replace(tzinfo=local_tz)
            
            # Converte para UTC e formata para o padrão ISO
            utc_deadline = aware_deadline.astimezone(timezone.utc)
            return utc_deadline.isoformat().replace('+00:00', 'Z')
        except (ValueError, TypeError):
            logging.error(f"Formato de data inválido recebido: '{date_str}'. Esperado 'dd_mm_aaaa'.")
            raise ValueError(f"Data de agendamento inválida: '{date_str}'")


    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        logging.info(f"Processando lote para a fonte 'Onerequest' com {len(request.processos)} processos.")
        success_count = 0
        failed_items = []
        
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        for processo in request.processos:
            log_item = BatchExecutionItem(process_number=processo.numero_processo, execution_id=execution_log.id)
            
            try:
                # --- LÓGICA DE NEGÓCIO PRINCIPAL ---
                if not processo.setor or processo.setor not in SECTOR_TASK_MAPPING:
                    raise ValueError(f"Setor '{processo.setor}' não é válido ou não está mapeado.")
                
                if not processo.data_agendamento:
                    raise ValueError("A data de agendamento é obrigatória para esta fonte.")

                # Obtém os IDs do mapeamento com base no setor
                task_subtype_id, office_id = SECTOR_TASK_MAPPING[processo.setor]
                
                # Valida o tipo/subtipo no banco de dados
                sub_type = self.db.query(LegalOneTaskSubType).filter(LegalOneTaskSubType.external_id == task_subtype_id).first()
                if not sub_type:
                    raise ValueError(f"Subtipo de tarefa com ID externo {task_subtype_id} não encontrado no banco de dados.")
                
                task_type_id = sub_type.parent_type.external_id

                # Busca o processo no Legal One
                lawsuit = self.client.search_lawsuit_by_cnj(processo.numero_processo)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                end_datetime_iso = self._parse_and_format_deadline(processo.data_agendamento)

                # Monta o payload da tarefa
                task_payload = {
                    "description": f"Tarefa automática (Onerequest): Agendamento para o setor {processo.setor}",
                    "priority": "Normal",
                    "startDateTime": start_datetime_iso,
                    "endDateTime": end_datetime_iso,
                    "status": { "id": DEFAULT_TASK_STATUS_ID },
                    "typeId": task_type_id,
                    "subTypeId": task_subtype_id,
                    "responsibleOfficeId": office_id,
                    "originOfficeId": office_id,
                    "participants": [{"contact": {"id": processo.id_responsavel}, "isResponsible": True, "isExecuter": True, "isRequester": True}]
                }
                if processo.observacao:
                    task_payload['notes'] = processo.observacao

                # Cria e vincula a tarefa
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa (resposta inválida da API).")
                
                task_id = created_task['id']
                link_success = self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})
                if not link_success:
                    logging.warning(f"Tarefa ID {task_id} criada, mas falha ao vincular ao processo ID {lawsuit_id}.")

                log_item.status = "SUCESSO"
                log_item.created_task_id = task_id
                success_count += 1
                
            except Exception as e:
                error_msg = str(e)
                log_item.status = "FALHA"
                log_item.error_message = error_msg
                failed_items.append({"cnj": processo.numero_processo, "motivo": error_msg})
                logging.error(f"Falha ao processar CNJ {processo.numero_processo} (Onerequest): {error_msg}")
            
            finally:
                execution_log.items.append(log_item)
                await asyncio.sleep(0.1) # Pequeno delay para não sobrecarregar a API externa

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
# Conteúdo para: app/services/batch_strategies/spreadsheet_strategy.py

import logging
import asyncio
from io import BytesIO
from openpyxl import load_workbook
from datetime import date, timedelta, datetime, timezone, time
from zoneinfo import ZoneInfo

from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest, ProcessoResponsavel
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneTaskSubType

# Configurações podem ser movidas para um arquivo de configuração central no futuro
TASK_SUBTYPE_EXTERNAL_ID = 1132
TASK_TYPE_EXTERNAL_ID = 26
DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente

class SpreadsheetStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir de um arquivo de planilha (Excel).
    """
    def _get_next_business_day(self) -> date:
        """ Calcula o próximo dia útil. """
        today = date.today()
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5: # 5 = Sábado, 6 = Domingo
            next_day += timedelta(days=1)
        return next_day

    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        success_count = 0
        failed_items = []
        
        # Carrega o workbook a partir do conteúdo em bytes
        try:
            workbook = load_workbook(filename=BytesIO(request.file_content))
            sheet = workbook.active
        except Exception as e:
            raise ValueError(f"Não foi possível ler o arquivo Excel: {e}")

        # Valida o cabeçalho
        header = [cell.value for cell in sheet[1]]
        expected_header = ['CNJ', 'ID_RESPONSAVEL', 'OBSERVACAO']
        if header[:len(expected_header)] != expected_header:
            raise ValueError(f"Cabeçalho da planilha inválido. Esperado: {expected_header}, mas encontrado: {header}")

        # Pega todas as linhas exceto o cabeçalho
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        
        # Atualiza o total de itens no log de execução
        execution_log.total_items = len(rows)
        self.db.commit()

        # Prepara datas (mesma lógica da OnesidStrategy)
        local_tz = ZoneInfo("America/Sao_Paulo")
        deadline_date = self._get_next_business_day()
        aware_deadline = datetime.combine(deadline_date, time(23, 59, 59)).replace(tzinfo=local_tz)
        utc_deadline = aware_deadline.astimezone(timezone.utc)
        end_datetime_iso = utc_deadline.isoformat().replace('+00:00', 'Z')
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Valida o tipo/subtipo de tarefa no BD
        sub_type = self.db.query(LegalOneTaskSubType).filter(LegalOneTaskSubType.external_id == TASK_SUBTYPE_EXTERNAL_ID).first()
        if not sub_type or sub_type.parent_type.external_id != TASK_TYPE_EXTERNAL_ID:
            raise ValueError(f"Tipo/Subtipo de tarefa ({TASK_TYPE_EXTERNAL_ID}/{TASK_SUBTYPE_EXTERNAL_ID}) não configurado.")

        for row in rows:
            # Extrai dados da linha, garantindo que não quebre se a linha for curta
            cnj = str(row[0]) if row[0] else None
            id_responsavel = int(row[1]) if len(row) > 1 and row[1] else None
            observacao = str(row[2]) if len(row) > 2 and row[2] else None

            if not cnj or not id_responsavel:
                logging.warning(f"Linha ignorada por falta de dados: CNJ='{cnj}', ID_RESPONSAVEL='{id_responsavel}'")
                continue

            log_item = BatchExecutionItem(process_number=cnj, execution_id=execution_log.id)

            try:
                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')
                if not responsible_office_id:
                    raise Exception("Processo não possui Escritório Responsável.")

                task_payload = {
                    "description": f"Tarefa automática: Agendamento via Planilha para o processo {cnj}",
                    "priority": "Normal", "startDateTime": start_datetime_iso, "endDateTime": end_datetime_iso,
                    "status": { "id": DEFAULT_TASK_STATUS_ID }, "typeId": TASK_TYPE_EXTERNAL_ID,
                    "subTypeId": TASK_SUBTYPE_EXTERNAL_ID, "responsibleOfficeId": responsible_office_id,
                    "originOfficeId": responsible_office_id,
                    "participants": [{"contact": {"id": id_responsavel}, "isResponsible": True, "isExecuter": True, "isRequester": True}]
                }
                if observacao:
                    task_payload['notes'] = observacao

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
                failed_items.append({"cnj": cnj, "motivo": error_msg})
                logging.error(f"Falha ao processar CNJ {cnj} da planilha: {error_msg}")
            
            finally:
                execution_log.items.append(log_item)
                await asyncio.sleep(0.1)

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
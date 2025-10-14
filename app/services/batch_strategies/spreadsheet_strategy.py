# app/services/batch_strategies/spreadsheet_strategy.py

import logging
import asyncio
from io import BytesIO
from openpyxl import load_workbook
from datetime import datetime, timezone, time

from zoneinfo import ZoneInfo

from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneTaskSubType, LegalOneUser, LegalOneOffice
from sqlalchemy.orm import joinedload

DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente no Legal One

class SpreadsheetStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir de um arquivo de planilha (Excel).
    """

    def _parse_and_format_date_to_utc(self, date_value: any, time_value: any = None) -> str:
        """
        Função genérica para converter datas (datetime ou string) para o formato ISO 8601 UTC.
        Aceita um horário opcional no formato 'hh:mm'.
        Se o horário não for fornecido, a data é definida para o final do dia (23:59:59).
        """
        if not date_value:
            raise ValueError("Valor de data não pode ser nulo.")
        try:
            if isinstance(date_value, datetime):
                local_date = date_value
            else:
                date_str = str(date_value).split(' ')[0]
                if '-' in date_str:
                    local_date = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    local_date = datetime.strptime(date_str, "%d/%m/%Y")

            task_time = time(23, 59, 59) # Horário padrão (fim do dia)
            
            if time_value:
                try:
                    if isinstance(time_value, (datetime, time)):
                         task_time = time_value if isinstance(time_value, time) else time_value.time()
                    else:
                        task_time = datetime.strptime(str(time_value), "%H:%M").time()
                except (ValueError, TypeError):
                    logging.warning(f"Formato de hora inválido: '{time_value}'. Usando o horário padrão de fim de dia.")
            
            local_tz = ZoneInfo("America/Sao_Paulo")
            aware_datetime = datetime.combine(local_date.date(), task_time).replace(tzinfo=local_tz)

            utc_datetime = aware_datetime.astimezone(timezone.utc)
            return utc_datetime.isoformat().replace('+00:00', 'Z')
            
        except (ValueError, TypeError) as e:
            logging.error(f"Formato de data inválido: '{date_value}'. Erro: {e}")
            raise ValueError(f"Data inválida: '{date_value}'")

    def _format_date_for_description(self, date_value: any) -> str:
        # (Esta função permanece inalterada)
        if not date_value: return ""
        try:
            if isinstance(date_value, datetime): return date_value.strftime("%d/%m/%Y")
            date_str = str(date_value).split(' ')[0]
            if '-' in date_str:
                 date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            else:
                 date_obj = datetime.strptime(date_str, "%d/%m/%Y")
            return date_obj.strftime("%d/%m/%Y")
        except ValueError:
            return str(date_value).split(' ')[0]

    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        success_count = 0
        failed_items = []
        
        try:
            workbook = load_workbook(filename=BytesIO(request.file_content))
            sheet = workbook.active
        except Exception as e:
            raise ValueError(f"Não foi possível ler o arquivo Excel: {e}")

        COLUMN_MAP = {
            'ESCRITORIO': 0, 'CNJ': 1, 'PUBLISH_DATE': 8, 'SUBTIPO': 13, 
            'EXECUTANTE': 14, 'PRAZO': 15, 'DATA_TAREFA': 16, 'HORARIO': 17
        }
        
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        execution_log.total_items = len(rows)
        self.db.commit()

        logging.info("Pré-carregando dados de usuários, escritórios e tipos de tarefa para o cache.")
        users_cache = {user.name.strip().lower(): user for user in self.db.query(LegalOneUser).filter(LegalOneUser.is_active == True).all()}
        offices_cache = {office.path.strip().lower(): office for office in self.db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).all()}
        subtypes_cache = {sub.name.strip().lower(): sub for sub in self.db.query(LegalOneTaskSubType).options(joinedload(LegalOneTaskSubType.parent_type)).filter(LegalOneTaskSubType.is_active == True).all()}
        
        # --- INÍCIO DA MUDANÇA ---
        # 1. A variável 'start_datetime_iso' foi removida daqui, pois agora será definida por tarefa.

        for row in rows:
            office_name = str(row[COLUMN_MAP['ESCRITORIO']]).strip() if len(row) > COLUMN_MAP['ESCRITORIO'] and row[COLUMN_MAP['ESCRITORIO']] else None
            cnj = str(row[COLUMN_MAP['CNJ']]).strip() if len(row) > COLUMN_MAP['CNJ'] and row[COLUMN_MAP['CNJ']] else None
            publish_date_val = row[COLUMN_MAP['PUBLISH_DATE']] if len(row) > COLUMN_MAP['PUBLISH_DATE'] and row[COLUMN_MAP['PUBLISH_DATE']] else None
            subtype_name = str(row[COLUMN_MAP['SUBTIPO']]).strip() if len(row) > COLUMN_MAP['SUBTIPO'] and row[COLUMN_MAP['SUBTIPO']] else None
            user_name = str(row[COLUMN_MAP['EXECUTANTE']]).strip() if len(row) > COLUMN_MAP['EXECUTANTE'] and row[COLUMN_MAP['EXECUTANTE']] else None
            task_date = row[COLUMN_MAP['DATA_TAREFA']] if len(row) > COLUMN_MAP['DATA_TAREFA'] and row[COLUMN_MAP['DATA_TAREFA']] else None
            deadline_for_desc = row[COLUMN_MAP['PRAZO']] if len(row) > COLUMN_MAP['PRAZO'] and row[COLUMN_MAP['PRAZO']] else None
            schedule_time = row[COLUMN_MAP['HORARIO']] if len(row) > COLUMN_MAP['HORARIO'] and row[COLUMN_MAP['HORARIO']] else None

            log_item = BatchExecutionItem(process_number=cnj or "N/A", execution_id=execution_log.id)

            try:
                if not all([cnj, user_name, subtype_name, office_name, task_date, publish_date_val]):
                    raise ValueError("Dados essenciais faltando na linha (Escritório, CNJ, Data Publicação, Subtipo, Executante ou Data da Tarefa).")

                office = offices_cache.get(office_name.lower() if office_name else None)
                if not office: raise ValueError(f"Escritório com o caminho '{office_name}' não foi encontrado.")

                user = users_cache.get(user_name.lower() if user_name else None)
                if not user: raise ValueError(f"Usuário executante '{user_name}' não encontrado ou inativo.")
                
                sub_type = subtypes_cache.get(subtype_name.lower() if subtype_name else None)
                if not sub_type: raise ValueError(f"Subtipo de tarefa '{subtype_name}' não encontrado ou inativo.")

                # 2. Calculamos a data/hora final da tarefa
                end_datetime_iso = self._parse_and_format_date_to_utc(task_date, schedule_time)
                publish_date_iso = self._parse_and_format_date_to_utc(publish_date_val)

                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'): raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')
                if not responsible_office_id: raise Exception("Processo não possui Escritório Responsável.")
                
                formatted_date = self._format_date_for_description(deadline_for_desc)
                
                task_payload = {
                    "description": f"{sub_type.name} - {formatted_date}", "priority": "Normal",
                    # 3. Usamos o mesmo valor para 'startDateTime' e 'endDateTime'
                    "startDateTime": end_datetime_iso, 
                    "endDateTime": end_datetime_iso,
                    "publishDate": publish_date_iso,
                    "status": { "id": DEFAULT_TASK_STATUS_ID }, "typeId": sub_type.parent_type.external_id,
                    "subTypeId": sub_type.external_id, "responsibleOfficeId": responsible_office_id,
                    "originOfficeId": office.external_id,
                    "participants": [{"contact": {"id": user.external_id}, "isResponsible": True, "isExecuter": True, "isRequester": True}]
                }
                
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa (resposta inválida da API).")
                
                task_id = created_task['id']
                self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})

                log_item.status = "SUCESSO"
                log_item.created_task_id = task_id
                success_count += 1
                
            except Exception as e:
                error_msg = str(e)
                log_item.status = "FALHA"
                log_item.error_message = error_msg
                failed_items.append({"cnj": cnj or "N/A", "motivo": error_msg})
                logging.error(f"Falha ao processar CNJ {cnj}: {error_msg}")
            
            finally:
                execution_log.items.append(log_item)
                await asyncio.sleep(0.1)

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
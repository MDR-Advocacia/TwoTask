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

        # --- MAPEAMENTO DINÂMICO DE COLUNAS ---
        header_row = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
        header_map = {str(cell).strip().upper(): i for i, cell in enumerate(header_row) if cell is not None}

        indices = {
            'ESCRITORIO': header_map.get('ESCRITORIO'),
            'CNJ': header_map.get('CNJ'),
            'PUBLISH_DATE': header_map.get('PUBLISH_DATE'),
            'SUBTIPO': header_map.get('SUBTIPO'),
            'EXECUTANTE': header_map.get('EXECUTANTE'),
            'PRAZO': header_map.get('PRAZO'),
            'DATA_TAREFA': header_map.get('DATA_TAREFA'),
            'HORARIO': header_map.get('HORARIO'),
            'OBSERVACAO': header_map.get('OBSERVACAO'),
            'DESCRICAO': header_map.get('DESCRICAO') # Nova coluna para complemento da descrição
        }

        mandatory_fields = ['ESCRITORIO', 'CNJ', 'PUBLISH_DATE', 'SUBTIPO', 'EXECUTANTE', 'DATA_TAREFA']
        missing_cols = [col for col in mandatory_fields if indices[col] is None]
        
        if missing_cols:
            raise ValueError(f"Colunas obrigatórias ausentes na planilha: {', '.join(missing_cols)}")
        
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        execution_log.total_items = len(rows)
        self.db.commit()

        logging.info("Pré-carregando dados para o cache.")
        users_cache = {user.name.strip().lower(): user for user in self.db.query(LegalOneUser).filter(LegalOneUser.is_active == True).all()}
        offices_cache = {office.path.strip().lower(): office for office in self.db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).all()}
        subtypes_cache = {sub.name.strip().lower(): sub for sub in self.db.query(LegalOneTaskSubType).options(joinedload(LegalOneTaskSubType.parent_type)).filter(LegalOneTaskSubType.is_active == True).all()}
        
        for row in rows:
            def get_val(key):
                idx = indices.get(key)
                if idx is not None and idx < len(row) and row[idx] is not None:
                    return str(row[idx]).strip()
                return None

            office_name = get_val('ESCRITORIO')
            cnj = get_val('CNJ')
            publish_date_val = row[indices['PUBLISH_DATE']] if indices['PUBLISH_DATE'] is not None and indices['PUBLISH_DATE'] < len(row) else None
            subtype_name = get_val('SUBTIPO')
            user_name = get_val('EXECUTANTE')
            task_date = row[indices['DATA_TAREFA']] if indices['DATA_TAREFA'] is not None and indices['DATA_TAREFA'] < len(row) else None
            
            deadline_for_desc = row[indices['PRAZO']] if indices['PRAZO'] is not None and indices['PRAZO'] < len(row) else None
            schedule_time = row[indices['HORARIO']] if indices['HORARIO'] is not None and indices['HORARIO'] < len(row) else None
            observation_val = get_val('OBSERVACAO')
            extra_description = get_val('DESCRICAO') # Capturando o texto opcional

            log_item = BatchExecutionItem(process_number=cnj or "N/A", execution_id=execution_log.id)

            try:
                if not all([cnj, user_name, subtype_name, office_name, task_date, publish_date_val]):
                    raise ValueError("Dados essenciais faltando na linha.")

                office = offices_cache.get(office_name.lower() if office_name else None)
                if not office: raise ValueError(f"Escritório '{office_name}' não encontrado.")

                user = users_cache.get(user_name.lower() if user_name else None)
                if not user: raise ValueError(f"Usuário '{user_name}' não encontrado.")
                
                sub_type = subtypes_cache.get(subtype_name.lower() if subtype_name else None)
                if not sub_type: raise ValueError(f"Subtipo '{subtype_name}' não encontrado.")

                end_datetime_iso = self._parse_and_format_date_to_utc(task_date, schedule_time)
                publish_date_iso = self._parse_and_format_date_to_utc(publish_date_val)

                lawsuit = self.client.search_lawsuit_by_cnj(cnj)
                if not lawsuit or not lawsuit.get('id'): raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')
                if not responsible_office_id: raise Exception("Processo sem Escritório Responsável.")
                
                formatted_date = self._format_date_for_description(deadline_for_desc)
                
                # --- MONTAGEM DA DESCRIÇÃO DINÂMICA ---
                base_description = f"{sub_type.name} - {formatted_date}"
                if extra_description:
                    final_description = f"{base_description} - {extra_description}"
                else:
                    final_description = base_description
                # ---------------------------------------
                
                task_payload = {
                    "description": final_description, 
                    "priority": "Normal",
                    "startDateTime": end_datetime_iso, 
                    "endDateTime": end_datetime_iso,
                    "publishDate": publish_date_iso,
                    "notes": observation_val,
                    "status": { "id": DEFAULT_TASK_STATUS_ID }, 
                    "typeId": sub_type.parent_type.external_id,
                    "subTypeId": sub_type.external_id, 
                    "responsibleOfficeId": responsible_office_id,
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
                self.db.add(log_item)
                self.db.commit()
                await asyncio.sleep(0.1)

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
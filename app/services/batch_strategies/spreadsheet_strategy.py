# app/services/batch_strategies/spreadsheet_strategy.py

import logging
import asyncio
from io import BytesIO
from openpyxl import load_workbook
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import joinedload

from .base_strategy import BaseStrategy
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneTaskSubType, LegalOneUser, LegalOneOffice

DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente no Legal One

class SpreadsheetStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir de um arquivo de planilha (Excel).
    Refatorada para persistir dados de entrada (JSON) e permitir reprocessamento granular.
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

    async def _load_caches(self):
        """Helper para carregar caches do banco uma única vez"""
        return {
            'users': {u.name.strip().lower(): u for u in self.db.query(LegalOneUser).filter(LegalOneUser.is_active == True).all()},
            'offices': {o.path.strip().lower(): o for o in self.db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).all()},
            'subtypes': {s.name.strip().lower(): s for s in self.db.query(LegalOneTaskSubType).options(joinedload(LegalOneTaskSubType.parent_type)).filter(LegalOneTaskSubType.is_active == True).all()}
        }

    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        """Lê o arquivo, converte linhas em JSON, persiste e chama o processador individual."""
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
            'DESCRICAO': header_map.get('DESCRICAO')
        }

        mandatory_fields = ['ESCRITORIO', 'CNJ', 'PUBLISH_DATE', 'SUBTIPO', 'EXECUTANTE', 'DATA_TAREFA']
        missing_cols = [col for col in mandatory_fields if indices[col] is None]
        
        if missing_cols:
            raise ValueError(f"Colunas obrigatórias ausentes na planilha: {', '.join(missing_cols)}")
        
        rows = list(sheet.iter_rows(min_row=2, values_only=True))
        execution_log.total_items = len(rows)
        self.db.commit()

        logging.info(f"Iniciando processamento de {len(rows)} linhas. Carregando caches...")
        caches = await self._load_caches()
        
        for row in rows:
            # 1. Extrair dados para um dicionário limpo (JSON serializável)
            row_data = {}
            for key, idx in indices.items():
                val = row[idx] if idx is not None and idx < len(row) else None
                # Converter datas/objetos para string para salvar no JSON do banco
                if val is not None:
                    row_data[key] = str(val).strip()
                else:
                    row_data[key] = None

            cnj = row_data.get('CNJ')
            
            # 2. Cria o item no banco JÁ COM O JSON (input_data)
            log_item = BatchExecutionItem(
                process_number=cnj or "N/A", 
                execution_id=execution_log.id,
                input_data=row_data, # <--- PERSISTÊNCIA DOS DADOS ORIGINAIS
                status="PENDENTE"
            )
            self.db.add(log_item)
            self.db.commit() # Commit aqui garante que temos o ID do item e os dados salvos

            # 3. Processa o item usando os dados do dicionário (não da planilha direta)
            success = await self.process_single_item(log_item, row_data, caches)
            
            if success:
                success_count += 1
            else:
                failed_items.append({"cnj": cnj, "motivo": log_item.error_message})

            # Pequeno yield para não bloquear o event loop
            await asyncio.sleep(0.01)

        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}

    async def process_single_item(self, log_item: BatchExecutionItem, data: dict, caches: dict) -> bool:
        """
        Lógica isolada de processamento de um único item baseado em um dicionário de dados.
        Retorna True se sucesso, False se falha. Atualiza o log_item diretamente.
        """
        try:
            # Validações básicas
            required = ['CNJ', 'EXECUTANTE', 'SUBTIPO', 'ESCRITORIO', 'DATA_TAREFA', 'PUBLISH_DATE']
            # Verifica se campos obrigatórios têm valor (truthy)
            missing = [k for k in required if not data.get(k)]
            if missing:
                raise ValueError(f"Dados essenciais faltando no JSON: {', '.join(missing)}")

            # Lookups nos caches
            office_name = data.get('ESCRITORIO')
            office = caches['offices'].get(office_name.lower() if office_name else None)
            if not office: raise ValueError(f"Escritório '{office_name}' não encontrado.")

            user_name = data.get('EXECUTANTE')
            user = caches['users'].get(user_name.lower() if user_name else None)
            if not user: raise ValueError(f"Usuário '{user_name}' não encontrado.")
            
            subtype_name = data.get('SUBTIPO')
            sub_type = caches['subtypes'].get(subtype_name.lower() if subtype_name else None)
            if not sub_type: raise ValueError(f"Subtipo '{subtype_name}' não encontrado.")

            # Formatação de datas
            end_datetime_iso = self._parse_and_format_date_to_utc(data.get('DATA_TAREFA'), data.get('HORARIO'))
            publish_date_iso = self._parse_and_format_date_to_utc(data.get('PUBLISH_DATE'))

            # Chamadas API Legal One
            cnj = data.get('CNJ')
            lawsuit = self.client.search_lawsuit_by_cnj(cnj)
            if not lawsuit or not lawsuit.get('id'): raise Exception("Processo não encontrado no Legal One.")
            
            lawsuit_id = lawsuit['id']
            responsible_office_id = lawsuit.get('responsibleOfficeId')
            if not responsible_office_id: raise Exception("Processo sem Escritório Responsável.")
            
            # Montagem Descrição
            formatted_deadline = self._format_date_for_description(data.get('PRAZO'))
            base_description = f"{sub_type.name} - {formatted_deadline}"
            extra = data.get('DESCRICAO')
            final_description = f"{base_description} - {extra}" if extra else base_description
            
            # Payload
            task_payload = {
                "description": final_description, 
                "priority": "Normal",
                "startDateTime": end_datetime_iso, 
                "endDateTime": end_datetime_iso,
                "publishDate": publish_date_iso,
                "notes": data.get('OBSERVACAO'),
                "status": { "id": DEFAULT_TASK_STATUS_ID }, 
                "typeId": sub_type.parent_type.external_id,
                "subTypeId": sub_type.external_id, 
                "responsibleOfficeId": responsible_office_id,
                "originOfficeId": office.external_id,
                "participants": [{"contact": {"id": user.external_id}, "isResponsible": True, "isExecuter": True, "isRequester": True}]
            }
            
            created_task = self.client.create_task(task_payload)
            if not created_task or not created_task.get('id'):
                raise Exception("API retornou sucesso mas sem ID da tarefa.")
            
            task_id = created_task['id']
            self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})

            log_item.status = "SUCESSO"
            log_item.created_task_id = task_id
            log_item.error_message = None # Limpa erro anterior se houver
            self.db.commit()
            return True

        except Exception as e:
            log_item.status = "FALHA"
            log_item.error_message = str(e)
            self.db.commit()
            return False
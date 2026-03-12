# app/services/batch_task_creation_service.py

import logging
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session, joinedload
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest, BatchInteractiveCreationRequest
from app.services.batch_strategies.base_strategy import BaseStrategy
from app.services.batch_strategies.onesid_strategy import OnesidStrategy
from app.services.batch_strategies.spreadsheet_strategy import SpreadsheetStrategy
from app.services.batch_strategies.onerequest_strategy import OnerequestStrategy
from app.models.batch_execution import BatchExecution, BatchExecutionItem

class BatchTaskCreationService:
    """
    Orquestrador que seleciona a estratégia correta com base na 'fonte'
    para processar a criação de tarefas em lote.
    """
    def __init__(self, db: Session, client: LegalOneApiClient):
        self.db = db
        self.client = client
        self._strategies: dict[str, type[BaseStrategy]] = {
            "Onesid": OnesidStrategy,
            "Planilha": SpreadsheetStrategy,
            "OneRequest": OnerequestStrategy
        }

    async def process_spreadsheet_request(self, file_content: bytes, execution_id: int):
        """
        Orquestra o processamento de um arquivo de planilha em segundo plano.
        Recebe o ID da execução já criada pelo Controller.
        """
        logging.info(f"Iniciando processamento de lote via planilha. ID Execução: {execution_id}")
        
        # 1. Busca o log que já foi criado (e retornado ao front) pelo Controller
        execution_log = self.db.query(BatchExecution).filter(BatchExecution.id == execution_id).first()
        
        if not execution_log:
            logging.error(f"Log de execução {execution_id} não encontrado. Abortando.")
            return

        try:
            # Converte o conteúdo em bytes para um objeto que a estratégia possa usar
            spreadsheet_request = BatchTaskCreationRequest(
                fonte="Planilha",
                processos=[], 
                file_content=file_content
            )

            strategy_instance = SpreadsheetStrategy(self.db, self.client)
            
            # Executa a estratégia (que agora salva o progresso no banco a cada item)
            result = await strategy_instance.process_batch(spreadsheet_request, execution_log)
            
            # Atualiza o log com os totais finais
            execution_log.success_count = result.get("sucesso", 0)
            execution_log.failure_count = result.get("falhas", 0)
            logging.info(f"Processamento da planilha concluído. Resultado: {result}")

        except Exception as e:
            logging.error(f"Erro catastrófico ao processar a planilha: {e}", exc_info=True)
            if execution_log:
                # Tenta estimar falhas se possível
                total = execution_log.total_items or 0
                sucesso = execution_log.success_count or 0
                execution_log.failure_count = max(0, total - sucesso)
        
        finally:
            if execution_log:
                execution_log.end_time = datetime.now(timezone.utc)
                self.db.commit()

    # helper para timezone de Brasília
    def _get_brasilia_tz(self):
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            return timezone.utc

    def _now_brasilia(self):
        return datetime.now(self._get_brasilia_tz())  

    async def process_interactive_batch_request(self, request: BatchInteractiveCreationRequest):
        """
        Processa um lote de tarefas vindas do formulário interativo.
        """
        source_name = f"Planilha Interativa ({request.source_filename})"
        logging.info(f"Iniciando processamento de lote da fonte: '{source_name}' com {len(request.tasks)} tarefas.")
        now_utc = datetime.now(timezone.utc)
        
        execution_log = BatchExecution(
            source=source_name,
            total_items=len(request.tasks),
            start_time=now_utc
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)
        
        success_count = 0
        failed_items = []
        
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        for task_data in request.tasks:
            # AJUSTE 1: Salvamos input_data aqui também para permitir RETRY em tarefas interativas
            try:
                payload_json = task_data.model_dump()
            except AttributeError:
                payload_json = task_data.dict()

            log_item = BatchExecutionItem(
                process_number=task_data.cnj_number, 
                execution_id=execution_log.id,
                input_data=payload_json  # <--- Salva os dados para retry futuro
            )
            
            try:
                # Busca o processo no Legal One
                lawsuit = self.client.search_lawsuit_by_cnj(task_data.cnj_number)
                if not lawsuit or not lawsuit.get('id'):
                    raise Exception("Processo não encontrado no Legal One.")
                
                lawsuit_id = lawsuit['id']
                responsible_office_id = lawsuit.get('responsibleOfficeId')
                if not responsible_office_id:
                    raise Exception("Processo não possui Escritório Responsável definido.")

                # Converte a data para o formato UTC ISO 8601
                local_tz = ZoneInfo("America/Sao_Paulo")
                due_date_obj = datetime.strptime(task_data.due_date, "%Y-%m-%d")
                aware_deadline = datetime.combine(due_date_obj.date(), time(23, 59, 59)).replace(tzinfo=local_tz)
                end_datetime_iso = aware_deadline.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

                # Monta o payload da tarefa
                task_payload = {
                    "description": task_data.description,
                    "priority": "Normal",
                    "startDateTime": start_datetime_iso,
                    "endDateTime": end_datetime_iso,
                    "status": { "id": 0 }, # 0 = Pendente
                    "typeId": task_data.task_type_id,
                    "subTypeId": task_data.sub_type_id,
                    "responsibleOfficeId": responsible_office_id,
                    "originOfficeId": responsible_office_id, 
                    "participants": [{"contact": {"id": task_data.responsible_external_id}, "isResponsible": True, "isExecuter": True, "isRequester": True}]
                }

                # Cria e vincula a tarefa
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
                failed_items.append({"cnj": task_data.cnj_number, "motivo": error_msg})
            
            finally:
                self.db.add(log_item)
        
        execution_log.success_count = success_count
        execution_log.failure_count = len(failed_items)
        execution_log.end_time = datetime.now(timezone.utc)
        self.db.commit()
        logging.info(f"Processamento do lote interativo concluído. Sucessos: {success_count}, Falhas: {len(failed_items)}")

    async def process_batch_request(self, request: BatchTaskCreationRequest):
        """
        Ponto de entrada genérico (usado por outras fontes ou retries legados).
        """
        logging.info(f"Recebida requisição de lote da fonte: '{request.fonte}' com {len(request.processos)} processos.")
        now_utc = datetime.now(timezone.utc)
        
        # PASSO 1: Cria o registro principal da execução do lote no BD
        execution_log = BatchExecution(
            source=request.fonte,
            total_items=len(request.processos),
            start_time=now_utc
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)
        
        try:
            strategy_class = self._strategies.get(request.fonte)

            if not strategy_class:
                raise ValueError(f"Nenhuma estratégia encontrada para a fonte: '{request.fonte}'")

            strategy_instance = strategy_class(self.db, self.client)
            
            # PASSO 2: Executa a estratégia
            result = await strategy_instance.process_batch(request, execution_log)

            # PASSO 3: Atualiza o log principal
            execution_log.success_count = result.get("sucesso", 0)
            execution_log.failure_count = result.get("falhas", 0)
            logging.info(f"Processamento do lote da fonte '{request.fonte}' concluído. Resultado: {result}")

        except Exception as e:
            logging.error(f"Erro catastrófico ao processar o lote: {e}", exc_info=True)
            execution_log.failure_count = execution_log.total_items - execution_log.success_count
        
        finally:
            execution_log.end_time = datetime.now(timezone.utc)
            self.db.commit()

    # --- MÉTODO DE RETRY TURBINADO (SMART RETRY) ---
    async def retry_failed_items(self, original_execution_id: int, target_item_ids: list[int] = None):
        """
        Reprocessa itens falhos.
        - Se target_item_ids for fornecido: Reprocessa APENAS esses itens.
        - Se for None: Reprocessa TODOS os itens com falha.
        """
        logging.info(f"Iniciando retentativa INTELIGENTE para lote ID: {original_execution_id}")
        
        # Busca execução original e seus itens
        original_execution = self.db.query(BatchExecution).options(
            joinedload(BatchExecution.items)
        ).filter(BatchExecution.id == original_execution_id).first()

        if not original_execution:
            logging.error(f"Lote {original_execution_id} não encontrado.")
            return

        # --- LÓGICA DE FILTRAGEM ---
        failed_items = []
        for item in original_execution.items:
            # 1. Tem que estar com status FALHA
            if item.status != "FALHA":
                continue
            
            # 2. Tem que ter input_data salvo
            if item.input_data is None:
                continue

            # 3. SE o usuário mandou uma lista de IDs, o item tem que estar nela
            if target_item_ids and item.id not in target_item_ids:
                continue
            
            failed_items.append(item)
        
        if not failed_items:
            logging.warning(f"Nenhum item elegível para retry encontrado no lote {original_execution_id}.")
            return

        logging.info(f"Reprocessando {len(failed_items)} itens selecionados...")

        # Instancia a estratégia. 
        # NOTA: Para interativos, não temos uma "Strategy Class" dedicada ainda, usamos a SpreadsheetStrategy 
        # ou criamos uma InteractiveStrategy se necessário. 
        # Por enquanto, fallback para SpreadsheetStrategy que sabe lidar com dicionários genéricos.
        strategy_class = self._strategies.get(original_execution.source) or SpreadsheetStrategy
        strategy_instance = strategy_class(self.db, self.client)

        # Carrega caches se necessário
        caches = {}
        if hasattr(strategy_instance, '_load_caches'):
            caches = await strategy_instance._load_caches()

        retry_success_count = 0
        
        for item in failed_items:
            # Atualiza status visual para reprocessando
            item.status = "REPROCESSANDO"
            item.error_message = None
            self.db.commit()

            # Chama o método isolado da estratégia
            # Passamos o input_data que estava salvo no banco
            if hasattr(strategy_instance, 'process_single_item'):
                result = await strategy_instance.process_single_item(item, item.input_data, caches)
                if result:
                    retry_success_count += 1
            else:
                logging.error(f"Estratégia {original_execution.source} não suporta retry individual.")
                item.status = "FALHA"
                item.error_message = "Estratégia não implementa process_single_item."
                self.db.commit()
        
        # Atualiza contadores globais
        total_success = sum(1 for item in original_execution.items if item.status == "SUCESSO")
        original_execution.success_count = total_success
        original_execution.failure_count = original_execution.total_items - total_success
        original_execution.end_time = datetime.now(timezone.utc)
        self.db.commit()
        
        logging.info(f"Reprocessamento seletivo concluído.")
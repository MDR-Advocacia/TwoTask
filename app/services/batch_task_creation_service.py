# app/services/batch_task_creation_service.py
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest
from app.api.v1.schemas import BatchInteractiveCreationRequest
from app.services.batch_strategies.base_strategy import BaseStrategy
from app.services.batch_strategies.onesid_strategy import OnesidStrategy
from app.services.batch_strategies.spreadsheet_strategy import SpreadsheetStrategy
from app.services.batch_strategies.onerequest_strategy import OnerequestStrategy
from app.models.batch_execution import BatchExecution

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
            "Onerequest": OnerequestStrategy
        }


    async def process_spreadsheet_request(self, file_content: bytes):
        """
        Orquestra o processamento de um arquivo de planilha em segundo plano.
        """
        logging.info("Iniciando processamento de lote via planilha.")
        
        # Cria um log inicial. O total de itens será atualizado pela estratégia.
        execution_log = BatchExecution(
            source="Planilha",
            total_items=0 # Será atualizado após a leitura da planilha
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)

        try:
            # Converte o conteúdo em bytes para um objeto que a estratégia possa usar
            # e constrói um payload semelhante ao que a outra estratégia recebe.
            spreadsheet_request = BatchTaskCreationRequest(
                fonte="Planilha",
                processos=[], # Será preenchido pela estratégia
                # Passamos o conteúdo do arquivo via um campo extra no Pydantic model.
                # Para isso, precisaremos ajustar o schema. Por enquanto, vamos passar diretamente.
                file_content=file_content
            )

            strategy_instance = SpreadsheetStrategy(self.db, self.client)
            result = await strategy_instance.process_batch(spreadsheet_request, execution_log)
            
            # Atualiza o log com os totais finais
            execution_log.success_count = result.get("sucesso", 0)
            execution_log.failure_count = result.get("falhas", 0)
            logging.info(f"Processamento da planilha concluído. Resultado: {result}")

        except Exception as e:
            logging.error(f"Erro catastrófico ao processar a planilha: {e}", exc_info=True)
            if execution_log:
                execution_log.failure_count = execution_log.total_items - (execution_log.success_count or 0)
        
        finally:
            if execution_log:
                execution_log.end_time = datetime.now(timezone.utc)
                self.db.commit()
    # helper para timezone de Brasília

    async def process_interactive_batch_request(self, request: BatchInteractiveCreationRequest):
        """
        Processa um lote de tarefas vindas do formulário interativo.
        """
        source_name = f"Planilha Interativa ({request.source_filename})"
        logging.info(f"Iniciando processamento de lote da fonte: '{source_name}' com {len(request.tasks)} tarefas.")
        
        execution_log = BatchExecution(
            source=source_name,
            total_items=len(request.tasks)
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)
        
        success_count = 0
        failed_items = []
        
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        for task_data in request.tasks:
            log_item = BatchExecutionItem(process_number=task_data.cnj_number, execution_id=execution_log.id)
            
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
                    "originOfficeId": responsible_office_id, # Assumindo que a origem é a mesma, pode ser ajustado
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


    def _get_brasilia_tz(self):
        try:
            return ZoneInfo("America/Sao_Paulo")
        except Exception:
            # fallback seguro para UTC caso o ZoneInfo não esteja disponível
            return timezone.utc

    def _now_brasilia(self):
        return datetime.now(self._get_brasilia_tz())    

    async def process_batch_request(self, request: BatchTaskCreationRequest):
        """
        Ponto de entrada do serviço. Identifica a fonte, cria o log e executa a estratégia.
        """
        logging.info(f"Recebida requisição de lote da fonte: '{request.fonte}' com {len(request.processos)} processos.")
        
        # PASSO 1: Cria o registro principal da execução do lote no BD
        execution_log = BatchExecution(
            source=request.fonte,
            total_items=len(request.processos)
        )
        self.db.add(execution_log)
        self.db.commit()
        self.db.refresh(execution_log)
        
        try:
            strategy_class = self._strategies.get(request.fonte)

            if not strategy_class:
                raise ValueError(f"Nenhuma estratégia encontrada para a fonte: '{request.fonte}'")

            strategy_instance = strategy_class(self.db, self.client)
            
            # PASSO 2: Executa a estratégia, passando o objeto de log para ser preenchido
            result = await strategy_instance.process_batch(request, execution_log)

            # PASSO 3: Atualiza o log principal com os totais retornados pela estratégia
            execution_log.success_count = result.get("sucesso", 0)
            execution_log.failure_count = result.get("falhas", 0)
            logging.info(f"Processamento do lote da fonte '{request.fonte}' concluído. Resultado: {result}")

        except Exception as e:
            logging.error(f"Erro catastrófico ao processar o lote: {e}", exc_info=True)
            # Em caso de erro grave, preenche o restante como falha
            execution_log.failure_count = execution_log.total_items - execution_log.success_count
        
        finally:
            # PASSO 4: Garante que o tempo de finalização e o resultado sejam salvos no BD
            execution_log.end_time = datetime.now(timezone.utc)
            self.db.commit()

    # --- NOVO MÉTODO DE RETRY ---
    async def retry_failed_items(self, original_execution_id: int):
        """
        Busca os itens falhos de uma execução anterior e dispara um novo
        processamento em lote apenas com eles.
        """
        logging.info(f"Iniciando retentativa para os itens falhos do lote ID: {original_execution_id}")
        
        # Usamos joinedload para buscar os itens junto com a execução original
        original_execution = self.db.query(BatchExecution).options(
            joinedload(BatchExecution.items)
        ).filter(BatchExecution.id == original_execution_id).first()

        if not original_execution:
            logging.error(f"Tentativa de reprocessar um lote inexistente (ID: {original_execution_id}).")
            return

        failed_items = [item for item in original_execution.items if item.status == "FALHA"]

        if not failed_items:
            logging.warning(f"Nenhum item com falha encontrado para o lote ID: {original_execution_id}. Nenhuma ação necessária.")
            return

        # Monta um novo objeto de requisição com base nos itens que falharam
        # A lógica para extrair dados (id_responsavel, etc.) pode precisar de ajuste
        # dependendo de como esses dados são armazenados ou se precisam ser buscados novamente.
        # Por simplicidade, vamos assumir que o CNJ é suficiente por agora.
        retry_processos = [
            ProcessoResponsavel(
                numero_processo=item.process_number,
                # NOTA: id_responsavel e outros campos não estão no log.
                # Para estratégias que dependem disso (Onesid, Planilha),
                # seria necessário armazenar mais contexto no BatchExecutionItem.
                # Por agora, vamos focar no fluxo.
                id_responsavel=0, # Placeholder
                observacao=f"Retentativa do item ID {item.id} da execução {original_execution_id}"
            ) for item in failed_items
        ]

        retry_request = BatchTaskCreationRequest(
            fonte=original_execution.source,
            processos=retry_processos,
            # Se a fonte for planilha, precisaríamos do conteúdo do arquivo original.
            # Esta é uma limitação da abordagem simples.
            file_content=original_execution.file_content if hasattr(original_execution, 'file_content') else None
        )

        logging.info(f"Disparando um novo lote para {len(retry_processos)} itens que falharam.")
        # Reutiliza o método de processamento de lote existente
        await self.process_batch_request(retry_request)
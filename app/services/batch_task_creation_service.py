# app/services/batch_task_creation_service.py
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest
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
            "Planilha": SpreadsheetStrategy
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
# app/services/batch_strategies/base_strategy.py
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution

class BaseStrategy(ABC):
    """
    Classe base (contrato) para todas as estratégias de criação de tarefas em lote.
    Cada estratégia representa a lógica para uma 'fonte' diferente.
    """
    def __init__(self, db: Session, client: LegalOneApiClient):
        self.db = db
        self.client = client

    @abstractmethod
    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict:
        """
        Executa o processamento do lote. Deve retornar um dicionário com o resumo.
        """
        pass
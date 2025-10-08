# app/models/batch_execution.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.session import Base

class BatchExecution(Base):
    """
    Registra uma execução de criação de tarefas em lote. Cada registro
    corresponde a uma requisição recebida no endpoint de lote.
    """
    __tablename__ = "lotes_execucao"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String, nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    
    total_items = Column(Integer, nullable=False)
    success_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    
    # Relacionamento para ver todos os itens de uma execução
    items = relationship("BatchExecutionItem", back_populates="execution", cascade="all, delete-orphan")

class BatchExecutionItem(Base):
    """
    Registra o resultado do processamento de um item individual
    dentro de uma execução em lote (ex: um CNJ).
    """
    __tablename__ = "lotes_itens"

    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(Integer, ForeignKey("lotes_execucao.id"), nullable=False)
    
    process_number = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False)  # "SUCESSO" ou "FALHA"
    created_task_id = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True)
    
    # Relacionamento de volta para o registro principal da execução
    execution = relationship("BatchExecution", back_populates="items")
from sqlalchemy.orm import Session
from app.models.task_rule import TaskCoRequisiteRule
from typing import List, Dict

class TaskRuleService:
    def __init__(self, db: Session):
        self.db = db
        # Carrega todas as regras de co-ocorrência em memória para eficiência.
        # Em um sistema maior, poderíamos adicionar um cache aqui.
        self.rules = self.db.query(TaskCoRequisiteRule).all()

    def validate_co_requisites(self, tasks_to_validate: List[Dict]) -> None:
        """
        Valida um conjunto de tarefas de uma mesma publicação contra as regras de co-ocorrência.
        Levanta uma exceção se uma regra for violada.

        :param tasks_to_validate: Uma lista de dicionários, onde cada um representa uma
                                  tarefa a ser criada (contendo 'selected_subtype_id').
        """
        if not self.rules:
            # Se não há regras cadastradas, não há nada a fazer.
            return

        # Extrai os IDs dos subtipos de tarefas que o usuário está tentando criar
        subtype_ids_in_payload = {int(task.get('selected_subtype_id')) for task in tasks_to_validate if task.get('selected_subtype_id')}

        for rule in self.rules:
            # Verifica se uma tarefa que dispara uma regra está presente
            if rule.primary_subtype_id in subtype_ids_in_payload:
                # Se estiver, verifica se a tarefa requerida também está presente
                if rule.secondary_subtype_id not in subtype_ids_in_payload:
                    # Se não estiver, a regra foi violada.
                    raise ValueError(f"Regra de negócio violada: A tarefa '{rule.primary_subtype.name}' requer que uma tarefa do tipo '{rule.secondary_subtype.name}' também seja criada para a mesma publicação.")
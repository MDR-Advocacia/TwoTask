from sqlalchemy.orm import Session
from app.models.task_rule import TaskCoRequisiteRule
from app.models.legal_one import LegalOneTaskSubType # Importar o modelo de subtipo
from typing import List, Dict, Set

class TaskRuleService:
    def __init__(self, db: Session):
        self.db = db
        # Mapeamento otimizado: { id_principal -> {id_obrigatorio_1, id_obrigatorio_2} }
        self.rule_map: Dict[int, Set[int]] = {}
        
        # Carrega todas as regras do banco de dados
        rules = self.db.query(TaskCoRequisiteRule).all()
        for rule in rules:
            if rule.primary_subtype_id not in self.rule_map:
                # Se for a primeira vez que vemos essa tarefa principal, cria um novo conjunto
                self.rule_map[rule.primary_subtype_id] = set()
            # Adiciona a tarefa obrigatória ao conjunto da tarefa principal
            self.rule_map[rule.primary_subtype_id].add(rule.secondary_subtype_id)

    def validate_co_requisites(self, tasks_to_validate: List[Dict]) -> None:
        """
        Valida um conjunto de tarefas de uma mesma publicação contra as regras de co-ocorrência.
        Levanta uma exceção se uma regra for violada.
        """
        if not self.rule_map:
            return

        # Cria um conjunto com os IDs de subtipo enviados pelo usuário
        subtype_ids_in_payload = {int(task['selected_subtype_id']) for task in tasks_to_validate if task.get('selected_subtype_id')}

        # Itera sobre as tarefas enviadas pelo usuário
        for task_id in subtype_ids_in_payload:
            # Verifica se a tarefa atual é uma "tarefa principal" que possui regras
            if task_id in self.rule_map:
                
                # Pega o conjunto de tarefas obrigatórias para esta tarefa principal
                required_ids = self.rule_map[task_id]
                
                # A MÁGICA ACONTECE AQUI:
                # Verifica se o conjunto de tarefas obrigatórias é um subconjunto
                # do conjunto de tarefas enviadas pelo usuário.
                if not required_ids.issubset(subtype_ids_in_payload):
                    
                    # Se não for, calcula quais tarefas estão faltando para dar um feedback claro
                    missing_ids = required_ids - subtype_ids_in_payload
                    
                    # Busca os nomes no banco de dados para uma mensagem de erro amigável
                    primary_task_name = self.db.query(LegalOneTaskSubType.name).filter(LegalOneTaskSubType.id == task_id).scalar()
                    
                    missing_task_names_query = self.db.query(LegalOneTaskSubType.name).filter(LegalOneTaskSubType.id.in_(missing_ids)).all()
                    missing_names_str = ", ".join([f"'{name}'" for name, in missing_task_names_query])
                    
                    raise ValueError(
                        f"Regra de negócio violada: A tarefa '{primary_task_name}' requer que as seguintes tarefas também sejam criadas: {missing_names_str}."
                    )
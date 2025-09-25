# app/services/task_creation_service.py

from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneClient
from app.api.v1.schemas import (
    LegalOneTaskPayload, Relationship, ResponsibleUser
)


class TaskCreationService:
    def __init__(self, db: Session):
        self.db = db
        self.legal_one_client = LegalOneClient()

    def create_task_in_legal_one(self, task_data: dict, responsibles: list):
        """
        Prepara e envia os dados da tarefa para a API do Legal One.
        """
        access_token = self.legal_one_client.get_access_token()
        if not access_token:
            print("Erro ao obter o token de acesso.")
            return None

        relationships = [
            Relationship(id=resp['id'], type="CONTACT")
            for resp in responsibles
        ]

        responsible_users = [
            ResponsibleUser(id=resp['id'], name=resp['name'])
            for resp in responsibles
        ]

        payload = LegalOneTaskPayload(
            description=task_data.get("description", "Descrição Padrão"),
            case_id=task_data.get("case_id", 0),
            task_type_id=task_data.get("task_type_id"),
            deadline=task_data.get("deadline"),
            relationships=relationships,
            responsibles=responsible_users
        )

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        endpoint = "/v1/tasks"
        response = self.legal_one_client.post(
            endpoint,
            headers=headers,
            json=payload.dict()
        )

        if response and response.status_code == 201:
            print("Tarefa criada com sucesso no Legal One.")
            return response.json()
        else:
            error_details = response.text if response else "N/A"
            status_code = response.status_code if response else "N/A"
            print(
                "Falha ao criar tarefa no Legal One. "
                f"Status: {status_code}, Detalhes: {error_details}"
            )
            return None

    def process_task_trigger(self, trigger_data: dict):
        """
        Processa um gatilho para criar uma ou mais tarefas.
        """
        task_details = trigger_data.get("task_details", {})
        squad_member_ids = trigger_data.get("squad_member_ids", [])

        responsibles = [
            {"id": member_id, "name": f"Usuário {member_id}"}
            for member_id in squad_member_ids
        ]

        if not responsibles:
            print("Nenhum responsável encontrado para os IDs fornecidos.")
            return

        return self.create_task_in_legal_one(task_details, responsibles)
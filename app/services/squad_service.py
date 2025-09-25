# app/services/squad_service.py

from sqlalchemy.orm import Session, joinedload
from typing import List, Optional

from app.models import rules as models
from app.api.v1 import schemas

class SquadService:
    """
    Serviço para encapsular a lógica de negócio relacionada a Squads.
    """
    def __init__(self, db: Session):
        self.db = db

    def get_all_squads(self) -> List[models.Squad]:
        """
        Retorna todos os squads ativos com seus membros.
        A filtragem de membros inativos é feita no endpoint para garantir que a resposta da API
        esteja correta, enquanto o serviço retorna os dados brutos.
        """
        return (
            self.db.query(models.Squad)
            .options(joinedload(models.Squad.members).joinedload(models.SquadMember.user))
            .filter(models.Squad.is_active == True)
            .all()
        )

    def create_squad(self, squad_data: schemas.SquadCreateSchema) -> models.Squad:
        """
        Cria um novo squad e associa os membros a ele.
        """
        # Verifica se já existe um squad com o mesmo nome
        existing_squad = self.db.query(models.Squad).filter(models.Squad.name == squad_data.name).first()
        if existing_squad:
            raise ValueError(f"Squad com o nome '{squad_data.name}' já existe.")

        # Cria a nova instância do Squad
        new_squad = models.Squad(name=squad_data.name, is_active=True)
        self.db.add(new_squad)
        self.db.flush()  # Garante que o new_squad.id esteja disponível

        # Associa os membros
        for user_id in squad_data.member_ids:
            # Aqui, poderíamos adicionar uma verificação se o usuário existe em `legal_one_users`
            squad_member = models.SquadMember(
                squad_id=new_squad.id,
                legal_one_user_id=user_id,
                is_leader=False # A lógica de líder pode ser adicionada depois
            )
            self.db.add(squad_member)

        self.db.commit()
        self.db.refresh(new_squad)
        return new_squad

    def update_squad(self, squad_id: int, squad_data: schemas.SquadUpdateSchema) -> Optional[models.Squad]:
        """
        Atualiza um squad existente, incluindo nome e lista de membros.
        """
        squad = self.db.query(models.Squad).filter(models.Squad.id == squad_id).first()
        if not squad:
            return None

        # Atualiza o nome se fornecido
        if squad_data.name:
            # Verifica se o novo nome já está em uso por outro squad
            existing_squad = self.db.query(models.Squad).filter(models.Squad.name == squad_data.name, models.Squad.id != squad_id).first()
            if existing_squad:
                raise ValueError(f"Squad com o nome '{squad_data.name}' já existe.")
            squad.name = squad_data.name

        # Atualiza os membros se fornecido
        if squad_data.member_ids is not None:
            # Remove os membros existentes
            self.db.query(models.SquadMember).filter(models.SquadMember.squad_id == squad_id).delete()

            # Adiciona os novos membros
            for user_id in squad_data.member_ids:
                squad_member = models.SquadMember(
                    squad_id=squad_id,
                    legal_one_user_id=user_id,
                    is_leader=False
                )
                self.db.add(squad_member)

        self.db.commit()
        self.db.refresh(squad)
        return squad

    def deactivate_squad(self, squad_id: int) -> Optional[models.Squad]:
        """
        Desativa um squad, marcando-o como inativo.
        """
        squad = self.db.query(models.Squad).filter(models.Squad.id == squad_id).first()
        if not squad:
            return None

        squad.is_active = False
        self.db.commit()
        self.db.refresh(squad)
        return squad
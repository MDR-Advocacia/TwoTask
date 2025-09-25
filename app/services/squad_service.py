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
        Cria um novo squad, associando-o a um setor e definindo seus membros e líderes.
        """
        # Validações
        if self.db.query(models.Squad).filter(models.Squad.name == squad_data.name).first():
            raise ValueError(f"Squad com o nome '{squad_data.name}' já existe.")
        if not self.db.query(models.Sector).filter(models.Sector.id == squad_data.sector_id).first():
            raise ValueError(f"Setor com ID '{squad_data.sector_id}' não encontrado.")

        # Criação do Squad
        new_squad = models.Squad(
            name=squad_data.name,
            sector_id=squad_data.sector_id,
            is_active=True
        )
        self.db.add(new_squad)
        self.db.flush()

        # Associação de Membros
        for member_info in squad_data.members:
            squad_member = models.SquadMember(
                squad_id=new_squad.id,
                legal_one_user_id=member_info.user_id,
                is_leader=member_info.is_leader
            )
            self.db.add(squad_member)

        self.db.commit()
        self.db.refresh(new_squad)
        return new_squad

    def update_squad(self, squad_id: int, squad_data: schemas.SquadUpdateSchema) -> Optional[models.Squad]:
        """
        Atualiza um squad existente: nome, setor, e/ou lista de membros/líderes.
        """
        squad = self.db.query(models.Squad).filter(models.Squad.id == squad_id).first()
        if not squad:
            return None

        # Atualiza o nome
        if squad_data.name and squad_data.name != squad.name:
            if self.db.query(models.Squad).filter(models.Squad.name == squad_data.name, models.Squad.id != squad_id).first():
                raise ValueError(f"Squad com o nome '{squad_data.name}' já existe.")
            squad.name = squad_data.name

        # Atualiza o setor
        if squad_data.sector_id:
            if not self.db.query(models.Sector).filter(models.Sector.id == squad_data.sector_id).first():
                raise ValueError(f"Setor com ID '{squad_data.sector_id}' não encontrado.")
            squad.sector_id = squad_data.sector_id

        # Atualiza os membros (se a lista for fornecida)
        if squad_data.members is not None:
            # Remove membros antigos
            self.db.query(models.SquadMember).filter(models.SquadMember.squad_id == squad_id).delete()
            # Adiciona novos membros
            for member_info in squad_data.members:
                squad_member = models.SquadMember(
                    squad_id=squad_id,
                    legal_one_user_id=member_info.user_id,
                    is_leader=member_info.is_leader
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
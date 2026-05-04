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

    def get_all_squads(self, sector_id: Optional[int] = None) -> List[models.Squad]:
        """
        Retorna todos os squads ativos com seus membros.
        Pode ser filtrado por sector_id.
        """
        query = (
            self.db.query(models.Squad)
            .options(joinedload(models.Squad.members).joinedload(models.SquadMember.user))
            .filter(models.Squad.is_active == True)
        )

        if sector_id:
            query = query.filter(models.Squad.sector_id == sector_id)

        return query.order_by(models.Squad.name).all()

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
                is_leader=member_info.is_leader,
                is_assistant=getattr(member_info, "is_assistant", False),
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
                    is_leader=member_info.is_leader,
                    is_assistant=getattr(member_info, "is_assistant", False),
                )
                self.db.add(squad_member)

        self.db.commit()
        self.db.refresh(squad)
        return squad

    # ── Membros (CRUD individual) ─────────────────────────────────────
    # Endpoints granulares pra UI Admin: adicionar 1 user, remover 1
    # member, ou alternar leader/assistant em 1 member sem reescrever a
    # lista inteira (que era o caminho do PUT /squads/{id}).

    def add_member(
        self,
        squad_id: int,
        *,
        user_id: int,
        is_leader: bool = False,
        is_assistant: bool = False,
    ) -> models.SquadMember:
        squad = self.db.query(models.Squad).filter(models.Squad.id == squad_id).one_or_none()
        if squad is None:
            raise ValueError(f"Squad {squad_id} nao encontrada.")
        # User ja' faz parte?
        existing = (
            self.db.query(models.SquadMember)
            .filter(
                models.SquadMember.squad_id == squad_id,
                models.SquadMember.legal_one_user_id == user_id,
            )
            .one_or_none()
        )
        if existing is not None:
            raise ValueError(
                f"User {user_id} ja' e' membro da squad '{squad.name}'."
            )
        if is_leader:
            self._unset_other_role(squad_id, "is_leader")
        if is_assistant:
            self._unset_other_role(squad_id, "is_assistant")
        member = models.SquadMember(
            squad_id=squad_id,
            legal_one_user_id=user_id,
            is_leader=is_leader,
            is_assistant=is_assistant,
        )
        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def remove_member(self, squad_id: int, member_id: int) -> bool:
        member = (
            self.db.query(models.SquadMember)
            .filter(
                models.SquadMember.id == member_id,
                models.SquadMember.squad_id == squad_id,
            )
            .one_or_none()
        )
        if member is None:
            return False
        self.db.delete(member)
        self.db.commit()
        return True

    def update_member_roles(
        self,
        squad_id: int,
        member_id: int,
        *,
        is_leader: Optional[bool] = None,
        is_assistant: Optional[bool] = None,
    ) -> Optional[models.SquadMember]:
        """Toggle dos papeis. Quando seta TRUE, desmarca o anterior na
        mesma squad (max 1 leader e 1 assistant)."""
        member = (
            self.db.query(models.SquadMember)
            .filter(
                models.SquadMember.id == member_id,
                models.SquadMember.squad_id == squad_id,
            )
            .one_or_none()
        )
        if member is None:
            return None
        if is_leader is not None:
            if is_leader:
                self._unset_other_role(squad_id, "is_leader", except_member_id=member_id)
            member.is_leader = bool(is_leader)
        if is_assistant is not None:
            if is_assistant:
                self._unset_other_role(squad_id, "is_assistant", except_member_id=member_id)
            member.is_assistant = bool(is_assistant)
        self.db.commit()
        self.db.refresh(member)
        return member

    def _unset_other_role(
        self,
        squad_id: int,
        column_name: str,
        except_member_id: Optional[int] = None,
    ) -> None:
        """Desmarca `column_name` (is_leader|is_assistant) em todos os
        outros membros da squad. Garante a constraint logica de 1 por papel."""
        column = getattr(models.SquadMember, column_name)
        query = self.db.query(models.SquadMember).filter(
            models.SquadMember.squad_id == squad_id,
            column.is_(True),
        )
        if except_member_id is not None:
            query = query.filter(models.SquadMember.id != except_member_id)
        for other in query.all():
            setattr(other, column_name, False)

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
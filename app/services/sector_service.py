# app/services/sector_service.py

from sqlalchemy.orm import Session
from typing import List, Optional

from app.models import rules as models
from app.api.v1 import schemas

class SectorService:
    """
    Serviço para encapsular a lógica de negócio relacionada a Setores.
    """
    def __init__(self, db: Session):
        self.db = db

    def get_all_sectors(self) -> List[models.Sector]:
        """
        Retorna todos os setores ativos.
        """
        return self.db.query(models.Sector).filter(models.Sector.is_active == True).all()

    def create_sector(self, sector_data: schemas.SectorCreateSchema) -> models.Sector:
        """
        Cria um novo setor.
        """
        # Verifica se já existe um setor com o mesmo nome
        existing_sector = self.db.query(models.Sector).filter(models.Sector.name == sector_data.name).first()
        if existing_sector:
            raise ValueError(f"Setor com o nome '{sector_data.name}' já existe.")

        new_sector = models.Sector(name=sector_data.name, is_active=True)
        self.db.add(new_sector)
        self.db.commit()
        self.db.refresh(new_sector)
        return new_sector

    def update_sector(self, sector_id: int, sector_data: schemas.SectorUpdateSchema) -> Optional[models.Sector]:
        """
        Atualiza um setor existente.
        """
        sector = self.db.query(models.Sector).filter(models.Sector.id == sector_id).first()
        if not sector:
            return None

        if sector_data.name:
            # Verifica se o novo nome já está em uso por outro setor
            existing_sector = self.db.query(models.Sector).filter(models.Sector.name == sector_data.name, models.Sector.id != sector_id).first()
            if existing_sector:
                raise ValueError(f"Setor com o nome '{sector_data.name}' já existe.")
            sector.name = sector_data.name

        if sector_data.is_active is not None:
            sector.is_active = sector_data.is_active

        self.db.commit()
        self.db.refresh(sector)
        return sector

    def delete_sector(self, sector_id: int) -> Optional[models.Sector]:
        """
        "Deleta" um setor, marcando-o como inativo.
        Uma verificação pode ser adicionada para não permitir a desativação se houver squads ativos associados.
        """
        sector = self.db.query(models.Sector).filter(models.Sector.id == sector_id).first()
        if not sector:
            return None

        sector.is_active = False
        self.db.commit()
        self.db.refresh(sector)
        return sector
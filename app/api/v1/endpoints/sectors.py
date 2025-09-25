# app/api/v1/endpoints/sectors.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.dependencies import get_db
from app.api.v1 import schemas
from app.services.sector_service import SectorService

router = APIRouter()

def get_sector_service(db: Session = Depends(get_db)) -> SectorService:
    """
    Dependência para injetar o SectorService nos endpoints.
    """
    return SectorService(db)

@router.post("", response_model=schemas.Sector, status_code=201)
def create_sector(
    sector_data: schemas.SectorCreateSchema,
    service: SectorService = Depends(get_sector_service)
):
    """
    Cria um novo setor.
    """
    try:
        sector = service.create_sector(sector_data)
        return sector
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=List[schemas.Sector])
def get_sectors(service: SectorService = Depends(get_sector_service)):
    """
    Retorna todos os setores ativos.
    """
    return service.get_all_sectors()

@router.put("/{sector_id}", response_model=schemas.Sector)
def update_sector(
    sector_id: int,
    sector_data: schemas.SectorUpdateSchema,
    service: SectorService = Depends(get_sector_service)
):
    """
    Atualiza um setor existente.
    """
    try:
        updated_sector = service.update_sector(sector_id, sector_data)
        if not updated_sector:
            raise HTTPException(status_code=404, detail=f"Setor com ID {sector_id} não encontrado.")
        return updated_sector
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/{sector_id}", status_code=204)
def delete_sector(
    sector_id: int,
    service: SectorService = Depends(get_sector_service)
):
    """
    Desativa um setor (soft delete).
    """
    deleted_sector = service.delete_sector(sector_id)
    if not deleted_sector:
        raise HTTPException(status_code=404, detail=f"Setor com ID {sector_id} não encontrado.")
    return None
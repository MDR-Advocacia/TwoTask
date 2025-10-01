from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel

from app.core.dependencies import get_db
from app.models.legal_one import LegalOneOffice

router = APIRouter()

# --- Pydantic Schema for Office Data ---
class OfficeResponse(BaseModel):
    id: int
    name: str
    path: str
    external_id: int

    class Config:
        orm_mode = True

@router.get("/offices", response_model=List[OfficeResponse], summary="Listar todos os escritórios ativos", tags=["Offices"])
def get_all_offices(db: Session = Depends(get_db)):
    """
    Retorna uma lista de todos os escritórios (Offices) que estão marcados como ativos no sistema.
    """
    offices = db.query(LegalOneOffice).filter(LegalOneOffice.is_active == True).order_by(LegalOneOffice.name).all()
    return offices
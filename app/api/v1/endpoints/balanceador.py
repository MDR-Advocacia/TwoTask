"""Endpoints do Balanceador de Agenda.

Read-only (MOCK 2026-06-29): diagnóstico de carga + matriz de redistribuição +
detalhe por subtipo, lidos do snapshot perf_l1_tarefa. Reusa o gate por time do
Minha Equipe. A reatribuição efetiva (escrita no L1) entra na versão real.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.endpoints.performance import require_team_access
from app.core.auth import get_current_user
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.services.performance.balanceador import BalanceadorService

router = APIRouter(prefix="/balanceador", tags=["Balanceador de Agenda"])
_team = Depends(require_team_access)


@router.get("/diagnostico", summary="Carga pendente por colaborador (atrasado/fatal hoje/futuro)", dependencies=[_team])
def diagnostico(team: str = Query(...), db: Session = Depends(get_db)):
    return {"colaboradores": BalanceadorService(db).diagnostico(team)}


@router.get("/redistribuir", summary="Matriz subtipo × colaborador dos escolhidos", dependencies=[_team])
def redistribuir(
    team: str = Query(...),
    pessoas: str = Query(..., description="ids separados por vírgula"),
    dias: int = Query(0, description="janela futura em dias; 0 = tudo"),
    db: Session = Depends(get_db),
):
    ids = [int(x) for x in pessoas.split(",") if x.strip().isdigit()]
    return {"matriz": BalanceadorService(db).redistribuir_matriz(team, ids, dias)}


@router.get("/tarefas", summary="Tarefas individuais de um (colaborador, subtipo)", dependencies=[_team])
def tarefas(
    team: str = Query(...),
    pessoa_id: int = Query(...),
    subtipo: str = Query(...),
    dias: int = Query(0),
    db: Session = Depends(get_db),
):
    return {"tarefas": BalanceadorService(db).redistribuir_tarefas(team, pessoa_id, subtipo, dias)}


@router.get("/descricoes", summary="Descrição (assunto) ao vivo do L1 por task ids", dependencies=[_team])
def descricoes(team: str = Query(...), ids: str = Query(...), db: Session = Depends(get_db)):
    idlist = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    return {"descricoes": BalanceadorService(db).descricoes(idlist)}


@router.get("/live-pessoa", summary="Pendentes AO VIVO do L1 de uma pessoa (matriz + detalhe)", dependencies=[_team])
def live_pessoa(
    team: str = Query(...),
    pessoa_id: int = Query(...),
    dias: int = Query(0),
    incluir_atrasadas: bool = Query(True),
    db: Session = Depends(get_db),
):
    return BalanceadorService(db).live_pessoa(team, pessoa_id, dias, incluir_atrasadas)


@router.get("/usuarios", summary="Busca colaboradores no L1 (destinos externos da fila)", dependencies=[_team])
def usuarios(team: str = Query(...), busca: str = Query(""), db: Session = Depends(get_db)):
    return {"usuarios": BalanceadorService(db).buscar_usuarios(busca)}


class RegistrarLogReq(BaseModel):
    movimentos: list


@router.post("/log", summary="Registra o log de uma redistribuição (aba Relatórios)", dependencies=[_team])
def registrar_log(
    team: str = Query(...),
    req: RegistrarLogReq = ...,
    current_user: LegalOneUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return BalanceadorService(db).registrar_log(team, current_user, req.movimentos)


@router.get("/logs", summary="Lista os logs de redistribuição do time", dependencies=[_team])
def listar_logs(team: str = Query(...), db: Session = Depends(get_db)):
    return {"logs": BalanceadorService(db).listar_logs(team)}

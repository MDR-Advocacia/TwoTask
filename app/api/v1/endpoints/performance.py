"""Endpoints do módulo "Minha Equipe" (Performance de Equipes).

Restrito a administradores — é monitoramento de desempenho de colaboradores.
Lê das tabelas perf* (populadas pelo seed/ingestão). Ver
`docs/performance-equipes-plano.md`.
"""

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.dependencies import get_db
from app.models.legal_one import LegalOneUser
from app.services.performance import relatorios as rel_jobs
from app.services.performance.report import build_individual_pdf, build_sector_pdf
from app.services.performance.service import PerformanceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/performance", tags=["Performance (Minha Equipe)"])


_TEAM_KEY = "bb-reu"  # piloto: o Minha Equipe hoje só tem a equipe BB Réu.


def _require_admin(current_user: LegalOneUser = Depends(get_current_user)) -> LegalOneUser:
    """Acesso ao Minha Equipe: admin OU (permissão do menu + equipe liberada na árvore)."""
    if getattr(current_user, "role", "user") == "admin":
        return current_user
    if not getattr(current_user, "can_use_minha_equipe", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para o Minha Equipe.")
    equipes = [x for x in (getattr(current_user, "minha_equipe_equipes", None) or "").split(",") if x]
    if _TEAM_KEY not in equipes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta equipe.")
    return current_user


_admin = Depends(_require_admin)


@router.get("/equipe", summary="Lista a equipe com métricas + KPIs", dependencies=[_admin])
def equipe(
    days: int = Query(30, ge=1, le=365),
    cargo: Optional[str] = Query(None, description="Filtra por cargo (Advogado(a)/Estagiário(a)/Assistente)"),
    db: Session = Depends(get_db),
):
    return PerformanceService(db).equipe(days=days, cargo=cargo or None)


@router.get("/cargos", summary="Cargos distintos (filtro)", dependencies=[_admin])
def cargos(db: Session = Depends(get_db)):
    return {"cargos": PerformanceService(db).cargos()}


@router.get("/pessoa/{pessoa_id}", summary="Detalhe de uma pessoa (mix + ritmo/ócio)", dependencies=[_admin])
def pessoa(
    pessoa_id: int,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    out = PerformanceService(db).pessoa_detalhe(pessoa_id, days=days)
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada.")
    return out


@router.get("/tipos", summary="Mapa de impacto: volume/cycle/natureza por subtipo", dependencies=[_admin])
def tipos(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return {"tipos": PerformanceService(db).tipos(days=days)}


@router.get("/dashboard", summary="Painel do setor: vazão, pool/atrasado, jornada, top tipos", dependencies=[_admin])
def dashboard(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return PerformanceService(db).dashboard(days=days)


@router.get("/export", summary="Exporta xlsx de um recorte (atrasado/pendente/concluído)", dependencies=[_admin])
def export(
    escopo: str = Query("atrasado", pattern="^(atrasado|pendente|concluido)$"),
    pessoa_id: Optional[int] = Query(None),
    subtipo: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    data = PerformanceService(db).export_xlsx(escopo=escopo, pessoa_id=pessoa_id, subtipo=subtipo, days=days)
    fname = f"minha-equipe-{escopo}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/relatorio-setor", summary="Relatório PDF do setor (Sonnet + fallback)", dependencies=[_admin])
def relatorio_setor(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    pdf = build_sector_pdf(db, days=days)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="relatorio-minha-equipe-setor.pdf"'},
    )


@router.get("/pessoa/{pessoa_id}/relatorio", summary="Relatório PDF individual (raio-x + intervenções)", dependencies=[_admin])
def relatorio_pessoa(pessoa_id: int, days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    pdf = build_individual_pdf(db, pessoa_id, days=days)
    if pdf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada.")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="raio-x-pessoa-{pessoa_id}.pdf"'},
    )


# ── Relatórios como JOB persistente (sobrevivem à navegação) ──────────────
class CriarRelatorioReq(BaseModel):
    tipo: str = "setor"  # 'setor' | 'pessoa'
    days: int = 30
    pessoa_id: Optional[int] = None


@router.post("/relatorios", summary="Dispara a geração de um relatório (job persistente)")
def criar_relatorio(
    req: CriarRelatorioReq,
    background: BackgroundTasks,
    current_user: LegalOneUser = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    tipo = "pessoa" if req.tipo == "pessoa" else "setor"
    rid, label = rel_jobs.criar(db, tipo=tipo, days=req.days, pessoa_id=req.pessoa_id, user_id=current_user.id)
    background.add_task(rel_jobs.gerar, rid)
    return {"id": rid, "label": label, "status": "processando"}


@router.get("/relatorios", summary="Lista os relatórios do usuário")
def listar_relatorios(
    current_user: LegalOneUser = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    return {"items": rel_jobs.listar(db, current_user.id)}


@router.get("/relatorios/{relatorio_id}/download", summary="Baixa o PDF de um relatório pronto")
def baixar_relatorio(
    relatorio_id: int,
    current_user: LegalOneUser = Depends(_require_admin),
    db: Session = Depends(get_db),
):
    pdf, _label = rel_jobs.get_pdf(db, relatorio_id, current_user.id)
    if pdf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatório não está pronto ou não encontrado.")
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="relatorio-minha-equipe-{relatorio_id}.pdf"'},
    )

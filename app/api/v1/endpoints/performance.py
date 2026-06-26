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
from app.services.performance.teams import TEAM_KEYS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/performance", tags=["Performance (Minha Equipe)"])


def _user_teams(u) -> list:
    return [x for x in (getattr(u, "minha_equipe_equipes", None) or "").split(",") if x]


def _require_minha_equipe(current_user: LegalOneUser = Depends(get_current_user)) -> LegalOneUser:
    """Acesso ao módulo (qualquer time): admin OU permissão do menu."""
    if getattr(current_user, "role", "user") == "admin":
        return current_user
    if not getattr(current_user, "can_use_minha_equipe", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para o Minha Equipe.")
    return current_user


def require_team_access(
    team: str = Query(..., description="Slug do time (bb-reu, master-reu, ...)"),
    current_user: LegalOneUser = Depends(get_current_user),
) -> str:
    """Gate por time: admin vê todos; demais precisam do time liberado na árvore."""
    if team not in TEAM_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time inexistente.")
    if getattr(current_user, "role", "user") == "admin":
        return team
    if not getattr(current_user, "can_use_minha_equipe", False):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para o Minha Equipe.")
    if team not in _user_teams(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a este time.")
    return team


# Alias do gate de módulo (relatórios-job e sync não são por time).
_require_admin = _require_minha_equipe
_admin = Depends(_require_admin)
_team = Depends(require_team_access)


@router.get("/equipe", summary="Lista o time com métricas + KPIs", dependencies=[_team])
def equipe(
    team: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    cargo: Optional[str] = Query(None, description="Filtra por cargo"),
    db: Session = Depends(get_db),
):
    return PerformanceService(db).equipe(days=days, cargo=cargo or None, team=team)


@router.get("/cargos", summary="Cargos distintos do time (filtro)", dependencies=[_team])
def cargos(team: str = Query(...), db: Session = Depends(get_db)):
    return {"cargos": PerformanceService(db).cargos(team=team)}


@router.get("/pessoa/{pessoa_id}", summary="Detalhe de uma pessoa (mix + ritmo/ócio)", dependencies=[_team])
def pessoa(
    pessoa_id: int,
    team: str = Query(...),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    out = PerformanceService(db).pessoa_detalhe(pessoa_id, days=days)
    if out is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pessoa não encontrada.")
    return out


@router.get("/tipos", summary="Mapa de impacto por subtipo (do time)", dependencies=[_team])
def tipos(team: str = Query(...), days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return {"tipos": PerformanceService(db).tipos(days=days, team=team)}


@router.get("/dashboard", summary="Painel do time: vazão, pool/atrasado, jornada, top tipos", dependencies=[_team])
def dashboard(team: str = Query(...), days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    return PerformanceService(db).dashboard(days=days, team=team)


@router.get("/export", summary="Exporta xlsx de um recorte do time", dependencies=[_team])
def export(
    team: str = Query(...),
    escopo: str = Query("atrasado", pattern="^(atrasado|pendente|concluido)$"),
    pessoa_id: Optional[int] = Query(None),
    subtipo: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    data = PerformanceService(db).export_xlsx(escopo=escopo, pessoa_id=pessoa_id, subtipo=subtipo, days=days, team=team)
    fname = f"minha-equipe-{team}-{escopo}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/relatorio-setor", summary="Relatório PDF do time (Sonnet + fallback)", dependencies=[_team])
def relatorio_setor(team: str = Query(...), days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    pdf = build_sector_pdf(db, days=days, team=team)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="relatorio-{team}.pdf"'},
    )


@router.get("/pessoa/{pessoa_id}/relatorio", summary="Relatório PDF individual (raio-x + intervenções)", dependencies=[_team])
def relatorio_pessoa(pessoa_id: int, team: str = Query(...), days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
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
    team: str = "bb-reu"
    days: int = 30
    pessoa_id: Optional[int] = None


@router.post("/relatorios", summary="Dispara a geração de um relatório (job persistente)")
def criar_relatorio(
    req: CriarRelatorioReq,
    background: BackgroundTasks,
    current_user: LegalOneUser = Depends(_require_minha_equipe),
    db: Session = Depends(get_db),
):
    if req.team not in TEAM_KEYS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time inexistente.")
    if getattr(current_user, "role", "user") != "admin" and req.team not in _user_teams(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a este time.")
    tipo = "pessoa" if req.tipo == "pessoa" else "setor"
    rid, label = rel_jobs.criar(
        db, tipo=tipo, days=req.days, pessoa_id=req.pessoa_id, user_id=current_user.id, team=req.team
    )
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


# ── Ingestão dos dados (download do relatório do L1) ──────────────────────
@router.get("/sync", summary="Último sync da ingestão (download do relatório do L1)", dependencies=[_admin])
def sync_status(db: Session = Depends(get_db)):
    from app.services.performance.report_ingest import get_last_sync, ja_sincronizou_hoje

    return {"last_sync": get_last_sync(), "ja_sincronizou_hoje": ja_sincronizou_hoje()}


def _run_sync_bg() -> None:
    from app.db.session import SessionLocal
    from app.services.performance.report_ingest import baixar_e_ingerir

    db = SessionLocal()
    try:
        baixar_e_ingerir(db, force=True)
    except Exception:  # noqa: BLE001
        logger.exception("Minha Equipe: falha na ingestão manual.")
    finally:
        db.close()


@router.post("/sync", summary="Dispara a ingestão agora (baixa o relatório mais recente do L1)", dependencies=[_admin])
def sync_now(background: BackgroundTasks):
    background.add_task(_run_sync_bg)
    return {"ok": True, "mensagem": "Ingestão disparada — baixando o relatório do L1 e atualizando os dados."}

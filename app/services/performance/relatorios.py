"""Relatórios PDF como JOB persistente do Minha Equipe.

Desacopla a geração do navegador: dispara → gera no servidor (mesmo que a pessoa
saia) → guarda o PDF na linha → fica disponível pra baixar quando quiser.

- criar()   registra o pedido (status=processando) e devolve o id;
- gerar()   função de background: gera o PDF e grava na linha (pronto/erro);
- listar()  lista os relatórios do usuário (sem o blob), auto-errando jobs presos;
- get_pdf() bytes do PDF pronto.
"""

import datetime
import logging

from app.db.session import SessionLocal
from app.models.performance import PerfPessoa, PerfRelatorio
from app.services.performance.report import build_individual_pdf, build_sector_pdf

logger = logging.getLogger(__name__)

try:
    from zoneinfo import ZoneInfo

    _BRT = ZoneInfo("America/Sao_Paulo")
except Exception:  # pragma: no cover
    _BRT = None

_STALE_MIN = 5  # job preso (worker reiniciou no meio) há mais que isso vira erro.


def _now():
    return datetime.datetime.now(tz=_BRT) if _BRT else datetime.datetime.now()


def criar(db, tipo: str, days: int, pessoa_id=None, user_id=None, team=None):
    from app.services.performance.teams import team_label

    if tipo == "pessoa":
        nome = None
        if pessoa_id:
            row = db.query(PerfPessoa.nome).filter(PerfPessoa.id == pessoa_id).first()
            nome = row[0] if row else None
        label = f"Raio-X — {nome or ('pessoa #' + str(pessoa_id))} · {days}d"
    else:
        label = f"Time — {team_label(team) if team else 'todos'} · {days}d"
    rel = PerfRelatorio(
        tipo=tipo, team=team, days=days, pessoa_id=pessoa_id, label=label,
        status="processando", criado_por_id=user_id,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel.id, label


def gerar(relatorio_id: int):
    """Background: gera o PDF e grava na linha. Abre sessão própria (a do request já fechou)."""
    db = SessionLocal()
    try:
        rel = db.get(PerfRelatorio, relatorio_id)
        if rel is None:
            return
        try:
            if rel.tipo == "pessoa":
                pdf = build_individual_pdf(db, rel.pessoa_id, days=rel.days)
                if pdf is None:
                    raise ValueError("Pessoa não encontrada.")
            else:
                pdf = build_sector_pdf(db, days=rel.days, team=rel.team)
            rel.pdf = pdf
            rel.status = "pronto"
            rel.erro = None
        except Exception as e:  # noqa: BLE001
            logger.exception("Relatório %s falhou", relatorio_id)
            rel.status = "erro"
            rel.erro = str(e)[:480]
        rel.concluido_em = _now()
        db.commit()
    finally:
        db.close()


def listar(db, user_id) -> list:
    limite = _now() - datetime.timedelta(minutes=_STALE_MIN)
    presos = (
        db.query(PerfRelatorio)
        .filter(
            PerfRelatorio.criado_por_id == user_id,
            PerfRelatorio.status == "processando",
            PerfRelatorio.criado_em < limite,
        )
        .all()
    )
    for p in presos:
        p.status = "erro"
        p.erro = "Tempo excedido na geração."
        p.concluido_em = _now()
    if presos:
        db.commit()

    rows = (
        db.query(PerfRelatorio)
        .filter(PerfRelatorio.criado_por_id == user_id)
        .order_by(PerfRelatorio.criado_em.desc())
        .limit(50)
        .all()
    )

    def _iso(dt):
        return dt.isoformat() if dt else None

    return [
        {
            "id": r.id, "tipo": r.tipo, "label": r.label, "days": r.days,
            "status": r.status, "erro": r.erro,
            "criado_em": _iso(r.criado_em), "concluido_em": _iso(r.concluido_em),
        }
        for r in rows
    ]


def get_pdf(db, relatorio_id, user_id):
    rel = db.get(PerfRelatorio, relatorio_id)
    if rel is None or rel.criado_por_id != user_id or rel.status != "pronto" or not rel.pdf:
        return None, None
    return rel.pdf, rel.label

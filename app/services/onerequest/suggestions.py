"""Motor de sugestão de tratamento do OneRequest.

Regras DERIVADAS DO ESTUDO do histórico de produção (6.901 DMIs, 2026-06-19):
~83% de acerto de setor; responsável modal por setor; data = prazo do BB − 4
dias (moda; 85% dos casos caem em [prazo−6, prazo−1]).

São SUGESTÕES (o operador confirma) — ver decisão "pré-preencher" em
docs/onerequest-integracao-plano.md. Tudo aqui é parametrizável: ajustar as
listas/constantes abaixo recalibra as sugestões sem mexer no resto.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models.legal_one import LegalOneUser

# Setor: ordem importa (específicos primeiro; Encerramento é o catch-all do
# passivo). Match por keyword = confiança alta; fallback por polo = baixa.
SETOR_RULES: list[tuple[str, re.Pattern]] = [
    ("BB Autor", re.compile(r"HONOR|SUCUMB|COMPROVANTE|REPASSE|DESTINA|SUBS[IÍ]DIO|CONTRATUA|RATEIO|REEMBOLS", re.I)),
    ("BB Réu", re.compile(r"AJUIZAMENTO|VIABILIDADE|PER[IÍ]CIA|CADASTRAMENTO|ASSISTENTE|OPERA[ÇC]|PREFIXO|AG[EÊ]NCIA|COLABORADOR", re.I)),
    ("BB Recurso", re.compile(r"RECURSO|APELA[ÇC]|AGRAVO|EMBARGOS", re.I)),
    ("BB Encerramento", re.compile(r"ANALISAR|PUBLICA[ÇC]|BAIXAD|CIRCULAR|ANDAMENTO|NPJ", re.I)),
]
SETOR_FALLBACK_POLO = {"ativo": "BB Autor", "passivo": "BB Encerramento"}

# Setor previsto -> (nome do responsável modal no histórico, confiança %).
# Sem entrada = sem sugestão de responsável (ex.: BB Réu não tem padrão forte).
RESPONSAVEL_POR_SETOR: dict[str, tuple[str, int]] = {
    "BB Encerramento": ("Hellen Sthefane Dos Santos Fernandes", 80),
    "BB Recurso": ("Hellen Sthefane Dos Santos Fernandes", 85),
    "BB Autor": ("Luiz Eduardo Oliveira da Silva", 55),
    "N/A": ("Eduardo Henrique de Oliveira", 37),
}

# data_agendamento sugerida = prazo do BB − N dias (moda do histórico).
DATA_OFFSET_DIAS = 4


def sugerir_setor(titulo: Optional[str], polo: Optional[str]) -> tuple[str, bool]:
    """Retorna (setor, confianca_alta)."""
    t = (titulo or "").upper()
    for setor, rx in SETOR_RULES:
        if rx.search(t):
            return setor, True
    p = (polo or "").strip().lower()
    if p in SETOR_FALLBACK_POLO:
        return SETOR_FALLBACK_POLO[p], False
    return "N/A", False


def sugerir_data(prazo: Optional[str]) -> Optional[str]:
    """prazo (DD/MM/YYYY do BB) − DATA_OFFSET_DIAS -> DD/MM/YYYY."""
    s = (prazo or "").strip()
    try:
        d = datetime.strptime(s, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None
    return (d - timedelta(days=DATA_OFFSET_DIAS)).strftime("%d/%m/%Y")


def sugerir(db: Session, *, titulo: Optional[str], polo: Optional[str], prazo: Optional[str]) -> dict:
    setor, setor_forte = sugerir_setor(titulo, polo)
    resp_id = resp_nome = resp_conf = None
    regra_resp = RESPONSAVEL_POR_SETOR.get(setor)
    if regra_resp:
        nome, conf = regra_resp
        u = db.query(LegalOneUser).filter(LegalOneUser.name == nome).first()
        if u:
            resp_id, resp_nome, resp_conf = u.id, u.name, conf
    return {
        "setor": setor,
        "setor_confianca": "alta" if setor_forte else "baixa",
        "responsavel_user_id": resp_id,
        "responsavel_nome": resp_nome,
        "responsavel_confianca": resp_conf,
        "data_agendamento": sugerir_data(prazo),
    }

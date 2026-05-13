"""Camada de dominio do Classificador — criacao de lotes.

Duas formas de criar um lote nessa fase:

1. **Upload xlsx** (`create_lote_from_upload`): operador sobe planilha
   com lista de CNJs (+ colunas opcionais). Idempotencia por SHA256 do
   arquivo guardada em `filtros_aplicados.file_sha256` pra auditoria
   (sem UNIQUE constraint nessa fase — sub-otimo mas simples).

2. **Import de Prazos Iniciais** (`create_lote_from_prazos_iniciais`):
   operador define filtros (periodo, escritorio, status, cliente) e o
   sistema espelha (snapshot) os intakes existentes. Preserva
   source_intake_id pra rastreabilidade no relatorio.

Ambas criam o lote em status RASCUNHO. A captura L1 + classificacao
sao disparadas em fases separadas (Fase 2c e Fase 3).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, date
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.classificador import (
    ClassificadorLote,
    ClassificadorProcesso,
    LOTE_STATUS_RASCUNHO,
    PROC_STATUS_PENDENTE,
    SOURCE_PRAZOS_INICIAIS,
    SOURCE_UPLOAD_XLSX,
)
from app.models.prazo_inicial import PrazoInicialIntake
from app.services.classificador.xlsx_reader import (
    XlsxHeaderError,
    read_classificador_xlsx,
)

logger = logging.getLogger(__name__)


# Status de intake elegiveis pra espelhar em lote do Classificador.
# Apenas intakes ja tratados pelo HITL (com sugestoes confirmadas ou
# pelo menos classificadas) entram. Intakes em RECEBIDO / EM_CLASSIFICACAO
# /ERRO ficam de fora porque ainda nao tem dado consolidado.
PI_ELIGIBLE_STATUSES = frozenset({
    "CLASSIFICADO",
    "AGUARDANDO_CONFIG_TEMPLATE",
    "EM_REVISAO",
    "AGENDADO",
    "GED_ENVIADO",
    "CONCLUIDO",
    "CONCLUIDO_SEM_PROVIDENCIA",
})


class IntakeError(Exception):
    """Erro de logica de negocio do intake (mensagem volta pro operador)."""


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Upload XLSX
# ──────────────────────────────────────────────────────────────────────


def create_lote_from_upload(
    db: Session,
    *,
    nome: str,
    cliente_nome: Optional[str],
    descricao: Optional[str],
    file_filename: str,
    file_content: bytes,
    created_by_user_id: Optional[int],
) -> tuple[ClassificadorLote, list[str]]:
    """Cria lote a partir de upload xlsx.

    Retorna (lote_criado, warnings_do_parser). Warnings sao expostos pro
    operador (ex.: "linha X tem CNJ malformado").

    Levanta XlsxHeaderError se o arquivo for invalido (header, vazio, etc).
    Levanta IntakeError se nenhuma linha for elegivel.
    """
    if not nome or not nome.strip():
        raise IntakeError("Nome do lote e' obrigatorio.")

    nome = nome.strip()

    # Parser do xlsx
    warnings, rows = read_classificador_xlsx(file_content)
    if not rows:
        raise IntakeError(
            "Nenhuma linha valida encontrada na planilha. Verifique se "
            "as colunas estao preenchidas (mínimo: CNJ)."
        )

    file_sha256 = _sha256_hex(file_content)

    lote = ClassificadorLote(
        nome=nome,
        cliente_nome=cliente_nome.strip() if cliente_nome else None,
        descricao=descricao.strip() if descricao else None,
        status=LOTE_STATUS_RASCUNHO,
        source_summary={SOURCE_UPLOAD_XLSX: len(rows)},
        filtros_aplicados={
            "file_filename": file_filename,
            "file_sha256": file_sha256,
            "rows_no_arquivo": len(rows),
            "warnings": warnings[:50],  # cap pra nao explodir o JSON
        },
        total_processos=len(rows),
        snapshot_at=datetime.utcnow(),
        created_by_user_id=created_by_user_id,
    )
    db.add(lote)
    db.flush()  # pra ter o lote.id

    for row in rows:
        proc = ClassificadorProcesso(
            lote_id=lote.id,
            source=SOURCE_UPLOAD_XLSX,
            source_intake_id=None,
            cnj_number=row.get("cnj_number"),
            external_id=row.get("cliente_externo_id"),
            produto=row.get("produto"),
            # observacao guardada no capa_json.observacao_operador (nao tem
            # coluna propria — vai pra ser refrescado depois pela L1)
            capa_json={"observacao_operador": row.get("observacao")}
            if row.get("observacao")
            else None,
            status=PROC_STATUS_PENDENTE,
        )
        db.add(proc)

    db.commit()
    db.refresh(lote)
    logger.info(
        "Classificador: lote #%s criado via UPLOAD_XLSX (%s rows, sha=%s)",
        lote.id,
        len(rows),
        file_sha256[:8],
    )
    return lote, warnings


# ──────────────────────────────────────────────────────────────────────
# Import de Prazos Iniciais
# ──────────────────────────────────────────────────────────────────────


def _build_prazos_iniciais_query(
    db: Session,
    *,
    data_inicio: Optional[date],
    data_fim: Optional[date],
    office_id: Optional[int],
    cliente_nome_match: Optional[str],
    statuses: Optional[list[str]],
):
    """Constroi query base de intakes elegiveis aplicando os filtros."""
    q = db.query(PrazoInicialIntake)

    # Por default, so intakes tratados (CLASSIFICADO+). Se operador passar
    # statuses=[...] explicito, respeita (pode incluir RECEBIDO se quiser).
    filter_statuses = statuses if statuses else list(PI_ELIGIBLE_STATUSES)
    q = q.filter(PrazoInicialIntake.status.in_(filter_statuses))

    if data_inicio:
        q = q.filter(PrazoInicialIntake.received_at >= data_inicio)
    if data_fim:
        # data_fim INCLUSIVE — adiciona 1 dia
        from datetime import timedelta
        q = q.filter(
            PrazoInicialIntake.received_at < (data_fim + timedelta(days=1))
        )
    if office_id:
        q = q.filter(PrazoInicialIntake.office_id == office_id)
    if cliente_nome_match:
        # Match em metadata_json.cliente_nome ou em campo direto (defensivo —
        # alguns intakes tem cliente_nome em capa_json.parte_re_nome).
        # Pra simplicidade, busca em external_id (que pode ter codigo cliente)
        # ou nada — Fase 3 melhora isso.
        like_pattern = f"%{cliente_nome_match}%"
        q = q.filter(PrazoInicialIntake.external_id.ilike(like_pattern))

    return q


def preview_from_prazos_iniciais(
    db: Session,
    *,
    data_inicio: Optional[date],
    data_fim: Optional[date],
    office_id: Optional[int],
    cliente_nome_match: Optional[str],
    statuses: Optional[list[str]],
) -> dict:
    """Conta quantos intakes casam com os filtros + sample dos 5 primeiros.

    Usado pra UI mostrar "Vai criar lote com N processos. Confirmar?".
    """
    q = _build_prazos_iniciais_query(
        db,
        data_inicio=data_inicio,
        data_fim=data_fim,
        office_id=office_id,
        cliente_nome_match=cliente_nome_match,
        statuses=statuses,
    )

    count = q.count()
    sample = q.order_by(PrazoInicialIntake.received_at.desc()).limit(5).all()
    return {
        "count": count,
        "sample": [
            {
                "id": i.id,
                "cnj_number": i.cnj_number,
                "status": i.status,
                "received_at": i.received_at.isoformat() if i.received_at else None,
                "office_id": i.office_id,
            }
            for i in sample
        ],
    }


def create_lote_from_prazos_iniciais(
    db: Session,
    *,
    nome: str,
    cliente_nome: Optional[str],
    descricao: Optional[str],
    data_inicio: Optional[date],
    data_fim: Optional[date],
    office_id: Optional[int],
    cliente_nome_match: Optional[str],
    statuses: Optional[list[str]],
    created_by_user_id: Optional[int],
) -> ClassificadorLote:
    """Cria lote espelhando intakes de Prazos Iniciais que casam com os filtros.

    Cada intake elegivel vira 1 row em classificador_processo com
    source=PRAZOS_INICIAIS, source_intake_id preenchido pra rastreabilidade.

    Capa, partes, patrocinio etc. NAO sao copiados aqui — fica pra Fase
    2c (refresh L1) que vai chamar a L1 e atualizar os snapshots de cada
    processo. Aqui so amarra a referencia.
    """
    if not nome or not nome.strip():
        raise IntakeError("Nome do lote e' obrigatorio.")
    nome = nome.strip()

    q = _build_prazos_iniciais_query(
        db,
        data_inicio=data_inicio,
        data_fim=data_fim,
        office_id=office_id,
        cliente_nome_match=cliente_nome_match,
        statuses=statuses,
    )

    intakes = q.order_by(PrazoInicialIntake.received_at.desc()).all()
    if not intakes:
        raise IntakeError(
            "Nenhum intake de Prazos Iniciais casa com esses filtros."
        )

    filtros_payload = {
        "data_inicio": data_inicio.isoformat() if data_inicio else None,
        "data_fim": data_fim.isoformat() if data_fim else None,
        "office_id": office_id,
        "cliente_nome_match": cliente_nome_match,
        "statuses": statuses,
    }

    lote = ClassificadorLote(
        nome=nome,
        cliente_nome=cliente_nome.strip() if cliente_nome else None,
        descricao=descricao.strip() if descricao else None,
        status=LOTE_STATUS_RASCUNHO,
        source_summary={SOURCE_PRAZOS_INICIAIS: len(intakes)},
        filtros_aplicados=filtros_payload,
        total_processos=len(intakes),
        snapshot_at=datetime.utcnow(),
        created_by_user_id=created_by_user_id,
    )
    db.add(lote)
    db.flush()

    for intake in intakes:
        proc = ClassificadorProcesso(
            lote_id=lote.id,
            source=SOURCE_PRAZOS_INICIAIS,
            source_intake_id=intake.id,
            cnj_number=intake.cnj_number,
            lawsuit_id=intake.lawsuit_id,
            external_id=intake.external_id,
            # Capa nao e' copiada aqui — refresh L1 vai preencher depois
            status=PROC_STATUS_PENDENTE,
        )
        db.add(proc)

    db.commit()
    db.refresh(lote)
    logger.info(
        "Classificador: lote #%s criado via PRAZOS_INICIAIS (%s intakes)",
        lote.id,
        len(intakes),
    )
    return lote

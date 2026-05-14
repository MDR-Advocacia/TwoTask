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
    PROC_STATUS_READY,
    SOURCE_PRAZOS_INICIAIS,
    SOURCE_UPLOAD_XLSX,
)
from app.models.prazo_inicial import PrazoInicialIntake


def _partes_do_capa(capa_json):
    """Devolve (polo_ativo, polo_passivo) lidos do capa_json.

    Os extractors do PI (PJe/eproc/PROJUDI/TJSP-eproc/eSAJ) ja extraem
    partes mecanicamente e gravam dentro do capa_json sob essas chaves.
    Esse helper extrai pras COLUNAS separadas do ClassificadorProcesso
    (proc.polo_ativo, proc.polo_passivo) — pra UI renderizar e pra IA
    receber estruturado.

    Aceita capa em formato lista (PJe-style) ou string (eSAJ legacy).
    """
    if not isinstance(capa_json, dict):
        return None, None
    pa = capa_json.get("polo_ativo")
    pp = capa_json.get("polo_passivo")
    # Sanity: aceita lista de dicts OU string OU None. Tipos invalidos
    # viram None (pra nao quebrar UI ou serializacao).
    if pa is not None and not isinstance(pa, (list, str)):
        pa = None
    if pp is not None and not isinstance(pp, (list, str)):
        pp = None
    return pa, pp
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

    Tambem detecta LOTES CANDIDATOS — lotes pre-existentes que ja contem
    parte (ou todos) dos source_intake_id selecionados. Operador pode
    optar por ATUALIZAR um lote existente em vez de criar duplicado.

    Usado pra UI mostrar "Vai criar lote com N processos OU atualizar
    Lote #42 que tem 715 em comum".
    """
    from collections import Counter

    q = _build_prazos_iniciais_query(
        db,
        data_inicio=data_inicio,
        data_fim=data_fim,
        office_id=office_id,
        cliente_nome_match=cliente_nome_match,
        statuses=statuses,
    )

    intakes = q.order_by(PrazoInicialIntake.received_at.desc()).all()
    count = len(intakes)
    intake_ids = [i.id for i in intakes]

    # Detecta lotes que ja contem alguns dos intakes selecionados
    candidates = []
    if intake_ids:
        from app.models.classificador import (
            ClassificadorLote as _Lote,
            ClassificadorProcesso as _Proc,
            LOTE_STATUS_CANCELLED as _CANCELLED,
        )

        existing_procs = (
            db.query(_Proc.lote_id, _Proc.source_intake_id)
            .filter(_Proc.source_intake_id.in_(intake_ids))
            .filter(_Proc.source == SOURCE_PRAZOS_INICIAIS)
            .all()
        )
        counter: Counter = Counter()
        for lote_id, _intake_id in existing_procs:
            counter[lote_id] += 1

        # Top 5 lotes com mais intakes em comum
        for lote_id, matches in counter.most_common(5):
            lote = db.query(_Lote).filter(_Lote.id == lote_id).first()
            if not lote or lote.status == _CANCELLED:
                continue
            candidates.append({
                "id": lote.id,
                "nome": lote.nome,
                "cliente_nome": lote.cliente_nome,
                "status": lote.status,
                "total_processos": lote.total_processos or 0,
                "matching_intakes": matches,
                "created_at": lote.created_at.isoformat() if lote.created_at else None,
            })

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
            for i in intakes[:5]
        ],
        "candidate_lotes": candidates,
    }


def merge_into_existing_lote(
    db: Session,
    *,
    lote_id: int,
    intakes: list[PrazoInicialIntake],
    reset_classification: bool = False,
    only_new: bool = True,
) -> tuple[ClassificadorLote, dict]:
    """UPSERT (ou INSERT-only) de intakes num lote existente.

    Pra cada intake nos filtros:
    - Se ja existe `ClassificadorProcesso` com (lote_id, source_intake_id):
      * `only_new=True` (default): IGNORA (incremental — preserva
        processos antigos sem mexer)
      * `only_new=False`: ATUALIZA campos (cnj/capa/integra/partes) —
        comportamento UPSERT classico
    - Se nao existe → CRIA novo `ClassificadorProcesso` no lote

    `only_new=True` resolve o caso comum: operador ja importou 717
    intakes, entraram +8 novos no PI, agora quer pegar SO' os 8 sem
    tocar nos 717 antigos. Default escolhido porque e' o comportamento
    intuitivo do "aproveitar intakes".

    Processos do lote que NAO aparecem mais nos intakes ficam intactos
    (operador apaga manualmente se quiser).

    Por default PRESERVA classificacao IA existente. Se
    `reset_classification=True` (so' faz sentido com `only_new=False`),
    limpa esses campos e marca status=PRONTO_PARA_CLASSIFICAR pra
    reclassificar nos processos atualizados.

    Retorna (lote, stats) com counts.
    """
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise IntakeError(f"Lote #{lote_id} nao encontrado.")
    if lote.status == "CLASSIFICANDO":
        raise IntakeError(
            f"Lote #{lote_id} esta em CLASSIFICANDO — aguarde finalizar antes de atualizar."
        )

    intake_by_id = {i.id: i for i in intakes}
    intake_ids = list(intake_by_id.keys())

    # Busca processos ja existentes no lote pra esses intakes
    existing_procs = (
        db.query(ClassificadorProcesso)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .filter(ClassificadorProcesso.source_intake_id.in_(intake_ids))
        .all()
    )
    existing_by_intake = {p.source_intake_id: p for p in existing_procs}

    atualizados = 0
    criados = 0
    capturados_novos = 0
    ignorados_ja_no_lote = 0  # so' incrementa quando only_new=True

    for intake_id, intake in intake_by_id.items():
        existing = existing_by_intake.get(intake_id)
        has_data = bool(intake.capa_json or intake.integra_json)
        if existing and only_new:
            # Modo incremental — ja existe no lote, NAO mexe (preserva
            # classificacao IA + dados do intake antigo). Operador pode
            # rodar com only_new=False se quiser forcar re-import.
            ignorados_ja_no_lote += 1
            continue
        if existing:
            # UPSERT: atualiza campos de identificacao + capa+integra do PI
            existing.cnj_number = intake.cnj_number
            existing.lawsuit_id = intake.lawsuit_id
            existing.external_id = intake.external_id
            existing.capa_json = intake.capa_json or {}
            existing.integra_json = intake.integra_json or {}
            existing.natureza_processo = getattr(intake, "natureza_processo", None)
            existing.produto = getattr(intake, "produto", None)
            # Copia polo_ativo/polo_passivo do capa_json pras colunas
            # separadas (que a UI/serializer leem direto).
            pa, pp = _partes_do_capa(intake.capa_json)
            existing.polo_ativo = pa
            existing.polo_passivo = pp
            if reset_classification:
                existing.categoria_id = None
                existing.subcategoria_id = None
                existing.polo = None
                existing.valor_estimado = None
                existing.pcond_sugerido = None
                existing.prob_exito = None
                existing.justificativa = None
                existing.analise_estrategica = None
                existing.confianca = None
                existing.classificacao_response_json = None
                existing.contestacao_existente_json = None
                existing.status = PROC_STATUS_READY if has_data else PROC_STATUS_PENDENTE
                existing.data_classificacao = None
                existing.error_message = None
            atualizados += 1
        else:
            # Cria novo (copia capa+integra do PI tambem — ja extraidos la)
            pa, pp = _partes_do_capa(intake.capa_json)
            proc = ClassificadorProcesso(
                lote_id=lote_id,
                source=SOURCE_PRAZOS_INICIAIS,
                source_intake_id=intake_id,
                cnj_number=intake.cnj_number,
                lawsuit_id=intake.lawsuit_id,
                external_id=intake.external_id,
                capa_json=intake.capa_json or {},
                polo_ativo=pa,
                polo_passivo=pp,
                integra_json=intake.integra_json or {},
                natureza_processo=getattr(intake, "natureza_processo", None),
                produto=getattr(intake, "produto", None),
                status=PROC_STATUS_READY if has_data else PROC_STATUS_PENDENTE,
            )
            db.add(proc)
            criados += 1
            if has_data:
                capturados_novos += 1

    # Atualiza contadores desnormalizados (recount manual pra ficar coerente)
    from sqlalchemy import func
    total = (
        db.query(func.count(ClassificadorProcesso.id))
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .scalar()
    ) or 0
    lote.total_processos = total + criados  # criados ainda nao commitaram
    # Recalcula capturados (count de processos PRONTO/CLASSIFICADO no lote)
    lote.total_processos_capturados = (
        (lote.total_processos_capturados or 0) + capturados_novos
    )

    # Atualiza source_summary
    ss = dict(lote.source_summary or {})
    ss[SOURCE_PRAZOS_INICIAIS] = (ss.get(SOURCE_PRAZOS_INICIAIS, 0)
                                   + criados)  # so adiciona os novos
    lote.source_summary = ss

    # Reset status do lote se estava CLASSIFICADO + reset_classification
    if reset_classification and lote.status == "CLASSIFICADO":
        lote.status = LOTE_STATUS_RASCUNHO
        lote.classificacao_finished_at = None

    db.commit()
    db.refresh(lote)

    stats = {
        "atualizados": atualizados,
        "criados": criados,
        "ignorados_ja_no_lote": ignorados_ja_no_lote,
        "capturados_novos": capturados_novos,
        "total_no_lote": lote.total_processos,
        "reclassificar": reset_classification,
        "only_new": only_new,
    }
    logger.info(
        "Classificador: lote #%s merge via PRAZOS_INICIAIS (only_new=%s: "
        "+%d novos, ~%d atualizados, %d ignorados, reset_classification=%s)",
        lote_id, only_new, criados, atualizados, ignorados_ja_no_lote,
        reset_classification,
    )
    return lote, stats


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
    merge_into_lote_id: Optional[int] = None,
    reset_classification: bool = False,
    only_new: bool = True,
) -> tuple[ClassificadorLote, Optional[dict]]:
    """Cria lote OU atualiza existente espelhando intakes do PI.

    Se `merge_into_lote_id` informado → atualiza lote existente via
    `merge_into_existing_lote`. Comportamento depende de `only_new`:
    - `only_new=True` (default): SO' importa intakes ainda nao no lote
      (modo incremental — preserva os 717 antigos sem mexer)
    - `only_new=False`: UPSERT classico — atualiza existentes + cria novos

    Se NAO informado → cria lote novo (snapshot). Retorna (lote, None).

    `reset_classification=True` limpa os campos da IA dos processos
    atualizados e marca PRONTO_PARA_CLASSIFICAR. Implicitamente requer
    `only_new=False`, pois processos ignorados nao serao atualizados.
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

    # ─── CAMINHO UPSERT/INCREMENTAL (atualiza lote existente) ─────────
    if merge_into_lote_id is not None:
        lote, stats = merge_into_existing_lote(
            db,
            lote_id=merge_into_lote_id,
            intakes=intakes,
            reset_classification=reset_classification,
            only_new=only_new,
        )
        return lote, stats

    # ─── CAMINHO TRADICIONAL (cria novo lote) ─────────────────────────
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

    capturados = 0
    for intake in intakes:
        # Os intakes do PI ja tem capa_json + integra_json no DB
        # (extraidos pelo motor mecanico do PI). Copia direto e marca
        # PRONTO_PARA_CLASSIFICAR — pula a fase de refresh L1 (que e' stub).
        has_data = bool(intake.capa_json or intake.integra_json)
        pa, pp = _partes_do_capa(intake.capa_json)
        proc = ClassificadorProcesso(
            lote_id=lote.id,
            source=SOURCE_PRAZOS_INICIAIS,
            source_intake_id=intake.id,
            cnj_number=intake.cnj_number,
            lawsuit_id=intake.lawsuit_id,
            external_id=intake.external_id,
            # Copia dados do PI direto — eles ja foram extraidos mecanicamente la
            capa_json=intake.capa_json or {},
            polo_ativo=pa,
            polo_passivo=pp,
            integra_json=intake.integra_json or {},
            natureza_processo=getattr(intake, "natureza_processo", None),
            produto=getattr(intake, "produto", None),
            status=PROC_STATUS_READY if has_data else PROC_STATUS_PENDENTE,
        )
        db.add(proc)
        if has_data:
            capturados += 1

    # Atualiza contador de processos capturados (pra UI mostrar 717/717
    # em vez de 0/717 e habilitar o botao Classificar)
    lote.total_processos_capturados = capturados

    db.commit()
    db.refresh(lote)
    logger.info(
        "Classificador: lote #%s criado via PRAZOS_INICIAIS (%s intakes, %s capturados)",
        lote.id,
        len(intakes),
        capturados,
    )
    return lote, None

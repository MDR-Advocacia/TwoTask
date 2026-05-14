"""Agregador de dados pra geracao de relatorios do Classificador.

Monta um payload em memoria com TODOS os recortes que xlsx + pdf +
painel vao usar, lendo `classificador_lote/processo/pedido` + JOINs em
`classification_categories/subcategories`. Sem chamada Anthropic — IA
ja rodou na Fase 3.

Funcao principal:
  build_report_data(db, lote_id) -> dict

Estrutura do retorno:
  {
    "lote": {...},                  # cabecalho
    "kpis": {...},                  # totais + agregados
    "por_categoria": [{...}, ...],  # 1 row por categoria
    "por_subcategoria": [...],
    "por_patrocinio": [...],        # MDR vs OUTRO vs CONDUCAO
    "por_produto": [...],
    "por_uf": [...],
    "por_tribunal": [...],
    "top_n_valor": [...],           # top 20 processos por valor_estimado
    "pedidos_por_tipo": [...],
    "sentencas_resumo": {...},      # counts por tipo de sentenca
    "transito_julgado_resumo": {...},
    "processos": [...],             # detalhamento completo (1 row/processo)
    "pedidos": [...],               # detalhamento pedidos (1 row/pedido)
    "analise_estrategica_carteira": "...",  # texto agregado do lote
    "generated_at": "ISO",
  }
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.classificador import (
    ClassificadorLote,
    ClassificadorPedido,
    ClassificadorProcesso,
)
from app.models.classification_taxonomy import (
    ClassificationCategory,
    ClassificationSubcategory,
)

logger = logging.getLogger(__name__)


# Regex pra extrair UF do tribunal (TJSP -> SP, TRT5 -> "TRT5", TRF1 -> "TRF1")
_TJ_UF_RE = re.compile(r"^TJ([A-Z]{2})$", re.IGNORECASE)
_CNJ_UF_RE = re.compile(r"\.8\.(\d{2})\.")  # CNJ tem segmento .8.NN. = tribunal


def _decimal_or_none(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _safe_float(v: Any) -> Optional[float]:
    d = _decimal_or_none(v)
    return float(d) if d is not None else None


def _extract_uf(processo: ClassificadorProcesso) -> Optional[str]:
    """Extrai UF do tribunal ou do CNJ. Retorna codigo ISO de UF (SP, RJ, …)
    ou string descritiva pra tribunais federais (TRT/TRF + numero)."""
    capa = processo.capa_json if isinstance(processo.capa_json, dict) else {}
    tribunal = (capa.get("tribunal") or "").strip().upper()
    # TJSP, TJRJ, TJBA, ...
    m = _TJ_UF_RE.match(tribunal)
    if m:
        return m.group(1).upper()
    # TRT5, TRT15, TRF1, TST, STJ
    if tribunal and (tribunal.startswith("TRT") or tribunal.startswith("TRF") or
                      tribunal in ("TST", "STJ", "STF")):
        return tribunal
    # Fallback via CNJ — segmento .8.NN.: NN e' codigo do tribunal estadual
    cnj = processo.cnj_number or ""
    m2 = _CNJ_UF_RE.search(cnj)
    if m2:
        # 26=SP, 19=RJ, 05=BA, etc. — em vez de mapear codigo->UF (incompleto),
        # devolve "TJ-" + codigo pra agrupar
        return f"TJ-{m2.group(1)}"
    return None


def _extract_tribunal(processo: ClassificadorProcesso) -> Optional[str]:
    capa = processo.capa_json if isinstance(processo.capa_json, dict) else {}
    return capa.get("tribunal") or None


def _patrocinio_decisao(processo: ClassificadorProcesso) -> str:
    """Extrai decisao de patrocinio. Default = NAO_APLICAVEL quando bloco
    nao foi preenchido (intake sem vinculada Master)."""
    p = processo.patrocinio_json if isinstance(processo.patrocinio_json, dict) else {}
    if not p.get("aplicavel"):
        return "NAO_APLICAVEL"
    return p.get("decisao") or "INDETERMINADO"


def _sentenca_tipo(processo: ClassificadorProcesso) -> Optional[str]:
    resp = processo.classificacao_response_json
    if not isinstance(resp, dict):
        return None
    s = resp.get("sentenca") or {}
    if not isinstance(s, dict) or not s.get("existe"):
        return None
    return s.get("tipo")


def _transitou(processo: ClassificadorProcesso) -> bool:
    resp = processo.classificacao_response_json
    if not isinstance(resp, dict):
        return False
    t = resp.get("transito_julgado") or {}
    return isinstance(t, dict) and bool(t.get("transitado"))


def build_report_data(db: Session, lote_id: int) -> dict:
    """Monta o payload integral pro relatorio (xlsx + pdf + painel)."""
    lote = (
        db.query(ClassificadorLote)
        .filter(ClassificadorLote.id == lote_id)
        .first()
    )
    if lote is None:
        raise ValueError(f"Lote #{lote_id} nao encontrado.")

    processos = (
        db.query(ClassificadorProcesso)
        .filter(ClassificadorProcesso.lote_id == lote_id)
        .order_by(ClassificadorProcesso.id.asc())
        .all()
    )

    # Catalogos pra resolver IDs -> nomes
    cat_map: dict[int, str] = {
        c.id: c.name
        for c in db.query(ClassificationCategory)
        .filter(ClassificationCategory.taxonomy_version == "v2")
        .all()
    }
    sub_map: dict[int, str] = {
        s.id: s.name
        for s in db.query(ClassificationSubcategory)
        .filter(ClassificationSubcategory.taxonomy_version == "v2")
        .all()
    }

    # Pedidos do lote (1 query, group em python)
    pedidos_all = (
        db.query(ClassificadorPedido)
        .filter(ClassificadorPedido.processo_id.in_(
            [p.id for p in processos]
        ) if processos else False)
        .all()
    )
    pedidos_by_processo: dict[int, list[ClassificadorPedido]] = defaultdict(list)
    for ped in pedidos_all:
        pedidos_by_processo[ped.processo_id].append(ped)

    # ─── Agregacoes ──────────────────────────────────────────────────

    total_proc = len(processos)
    classificados = sum(1 for p in processos if p.status == "CLASSIFICADO")
    com_erro = sum(1 for p in processos if p.status in
                   ("ERRO_CAPTURA", "ERRO_CLASSIFICACAO"))

    soma_valor_causa = Decimal(0)
    soma_valor_estimado = Decimal(0)
    soma_pcond = Decimal(0)
    prob_exito_acc: list[Decimal] = []

    for p in processos:
        capa = p.capa_json if isinstance(p.capa_json, dict) else {}
        vc = _decimal_or_none(capa.get("valor_causa"))
        if vc:
            soma_valor_causa += vc
        ve = _decimal_or_none(p.valor_estimado)
        if ve:
            soma_valor_estimado += ve
        pc = _decimal_or_none(p.pcond_sugerido)
        if pc:
            soma_pcond += pc
        pe = _decimal_or_none(p.prob_exito)
        if pe is not None:
            prob_exito_acc.append(pe)

    prob_exito_medio = (
        sum(prob_exito_acc) / len(prob_exito_acc) if prob_exito_acc else None
    )

    kpis = {
        "total_processos": total_proc,
        "total_classificados": classificados,
        "total_com_erro": com_erro,
        "valor_total_causa": _safe_float(soma_valor_causa),
        "valor_total_estimado": _safe_float(soma_valor_estimado),
        "pcond_total": _safe_float(soma_pcond),
        "prob_exito_medio": _safe_float(prob_exito_medio),
    }

    # ─── Por categoria ───────────────────────────────────────────────
    cat_acc: dict[str, dict] = {}
    sub_acc: dict[str, dict] = {}
    patroc_acc: dict[str, dict] = {}
    produto_acc: dict[str, dict] = {}
    uf_acc: dict[str, dict] = {}
    trib_acc: dict[str, dict] = {}

    def _acc_init() -> dict:
        return {"qtd": 0, "valor_estimado": Decimal(0), "pcond": Decimal(0),
                "prob_exito_sum": Decimal(0), "prob_exito_n": 0}

    def _acc_add(d: dict, p: ClassificadorProcesso) -> None:
        d["qtd"] += 1
        ve = _decimal_or_none(p.valor_estimado)
        if ve:
            d["valor_estimado"] += ve
        pc = _decimal_or_none(p.pcond_sugerido)
        if pc:
            d["pcond"] += pc
        pe = _decimal_or_none(p.prob_exito)
        if pe is not None:
            d["prob_exito_sum"] += pe
            d["prob_exito_n"] += 1

    def _acc_finalize(d: dict) -> dict:
        return {
            "qtd": d["qtd"],
            "valor_estimado": _safe_float(d["valor_estimado"]),
            "pcond": _safe_float(d["pcond"]),
            "prob_exito_medio": _safe_float(
                d["prob_exito_sum"] / d["prob_exito_n"]
            ) if d["prob_exito_n"] else None,
        }

    for p in processos:
        cat_label = cat_map.get(p.categoria_id, "(sem categoria)") if p.categoria_id else "(sem categoria)"
        cat_acc.setdefault(cat_label, _acc_init())
        _acc_add(cat_acc[cat_label], p)

        sub_label = sub_map.get(p.subcategoria_id, "(sem subcategoria)") if p.subcategoria_id else "(sem subcategoria)"
        sub_key = f"{cat_label} / {sub_label}"
        sub_acc.setdefault(sub_key, _acc_init())
        _acc_add(sub_acc[sub_key], p)

        patroc = _patrocinio_decisao(p)
        patroc_acc.setdefault(patroc, _acc_init())
        _acc_add(patroc_acc[patroc], p)

        produto_label = p.produto or "(sem produto)"
        produto_acc.setdefault(produto_label, _acc_init())
        _acc_add(produto_acc[produto_label], p)

        uf = _extract_uf(p) or "(sem UF)"
        uf_acc.setdefault(uf, _acc_init())
        _acc_add(uf_acc[uf], p)

        trib = _extract_tribunal(p) or "(sem tribunal)"
        trib_acc.setdefault(trib, _acc_init())
        _acc_add(trib_acc[trib], p)

    def _sort_acc(acc: dict) -> list[dict]:
        rows = [
            {"label": k, **_acc_finalize(v)}
            for k, v in acc.items()
        ]
        rows.sort(key=lambda r: (r["valor_estimado"] or 0), reverse=True)
        return rows

    # ─── Top N por valor ─────────────────────────────────────────────
    procs_sorted = sorted(
        processos,
        key=lambda p: _safe_float(p.valor_estimado) or 0,
        reverse=True,
    )
    top_n = procs_sorted[:20]

    # ─── Pedidos por tipo ────────────────────────────────────────────
    pedido_tipo_acc: dict[str, dict] = {}
    for ped in pedidos_all:
        tp = ped.tipo_pedido or "(sem tipo)"
        d = pedido_tipo_acc.setdefault(tp, {
            "qtd": 0,
            "valor_indicado": Decimal(0),
            "valor_estimado": Decimal(0),
            "pcond": Decimal(0),
        })
        d["qtd"] += 1
        vi = _decimal_or_none(ped.valor_indicado)
        if vi:
            d["valor_indicado"] += vi
        ve = _decimal_or_none(ped.valor_estimado)
        if ve:
            d["valor_estimado"] += ve
        pc = _decimal_or_none(ped.aprovisionamento)
        if pc:
            d["pcond"] += pc

    pedidos_por_tipo = [
        {
            "tipo_pedido": k,
            "qtd": v["qtd"],
            "valor_indicado": _safe_float(v["valor_indicado"]),
            "valor_estimado": _safe_float(v["valor_estimado"]),
            "pcond": _safe_float(v["pcond"]),
        }
        for k, v in sorted(
            pedido_tipo_acc.items(),
            key=lambda kv: -kv[1]["qtd"],
        )
    ]

    # ─── Sentencas + transito ────────────────────────────────────────
    sent_counter = Counter(_sentenca_tipo(p) or "(sem sentenca)" for p in processos)
    sentencas_resumo = dict(sent_counter)
    transit_count = sum(1 for p in processos if _transitou(p))
    transito_julgado_resumo = {
        "transitados": transit_count,
        "nao_transitados": total_proc - transit_count,
    }

    # ─── Contestacoes — qualidade tecnica (genericas vs nao genericas) ──
    # Metrica de qualidade tecnica de contestacoes apresentadas: criterio
    # MECANICO baseado em presenca de doc probatorio na juntada (vide
    # classifier_prompts.py linhas 143-163).
    #   generica=true  -> juntada sem doc probatorio (so' burocraticos)
    #   generica=false -> juntada com pelo menos 1 doc probatorio
    #   generica=null  -> integra truncada / nao foi possivel apurar
    # Split por quem apresentou (MDR vs outros) pra evidenciar o
    # diferencial competitivo do escritorio.
    cont_total = 0
    cont_generica_true = 0
    cont_generica_false = 0
    cont_generica_null = 0
    cont_mdr_total = 0
    cont_mdr_generica = 0
    cont_mdr_nao_generica = 0
    cont_outros_total = 0
    cont_outros_generica = 0
    cont_outros_nao_generica = 0
    for p in processos:
        cont = p.contestacao_existente_json if isinstance(p.contestacao_existente_json, dict) else {}
        if not cont.get("existe"):
            continue
        cont_total += 1
        gen = cont.get("generica")
        por_mdr = cont.get("apresentada_por_mdr")
        if gen is True:
            cont_generica_true += 1
        elif gen is False:
            cont_generica_false += 1
        else:
            cont_generica_null += 1
        if por_mdr is True:
            cont_mdr_total += 1
            if gen is True:
                cont_mdr_generica += 1
            elif gen is False:
                cont_mdr_nao_generica += 1
        elif por_mdr is False:
            cont_outros_total += 1
            if gen is True:
                cont_outros_generica += 1
            elif gen is False:
                cont_outros_nao_generica += 1

    def _pct(num: int, den: int):
        if not den:
            return None
        return round(num / den * 100, 1)

    contestacoes_resumo = {
        "total_contestacoes": cont_total,
        "genericas": cont_generica_true,
        "nao_genericas": cont_generica_false,
        "indeterminadas": cont_generica_null,
        "pct_genericas": _pct(cont_generica_true, cont_total),
        "mdr_total": cont_mdr_total,
        "mdr_genericas": cont_mdr_generica,
        "mdr_nao_genericas": cont_mdr_nao_generica,
        "mdr_pct_genericas": _pct(cont_mdr_generica, cont_mdr_total),
        "outros_total": cont_outros_total,
        "outros_genericas": cont_outros_generica,
        "outros_nao_genericas": cont_outros_nao_generica,
        "outros_pct_genericas": _pct(cont_outros_generica, cont_outros_total),
    }

    # ─── Detalhamento (1 row/processo) ───────────────────────────────
    processos_detalhe = []
    for p in processos:
        capa = p.capa_json if isinstance(p.capa_json, dict) else {}
        patro = p.patrocinio_json if isinstance(p.patrocinio_json, dict) else {}
        cont = p.contestacao_existente_json if isinstance(p.contestacao_existente_json, dict) else {}
        resp = p.classificacao_response_json if isinstance(p.classificacao_response_json, dict) else {}
        sentenca = resp.get("sentenca") if isinstance(resp.get("sentenca"), dict) else {}
        primeira_hab = resp.get("primeira_habilitacao_master") if isinstance(resp.get("primeira_habilitacao_master"), dict) else {}

        processos_detalhe.append({
            "id": p.id,
            "cnj_number": p.cnj_number,
            "tribunal": capa.get("tribunal"),
            "vara": capa.get("vara") or capa.get("orgao_julgador"),
            "classe": capa.get("classe"),
            "uf": _extract_uf(p),
            "valor_causa": _safe_float(capa.get("valor_causa")),
            "polo": p.polo,
            "natureza_processo": p.natureza_processo,
            "produto": p.produto,
            "categoria": cat_map.get(p.categoria_id) if p.categoria_id else None,
            "subcategoria": sub_map.get(p.subcategoria_id) if p.subcategoria_id else None,
            "valor_estimado": _safe_float(p.valor_estimado),
            "pcond_sugerido": _safe_float(p.pcond_sugerido),
            "prob_exito": _safe_float(p.prob_exito),
            "confianca": _safe_float(p.confianca),
            "patrocinio_decisao": _patrocinio_decisao(p),
            "patrocinio_outro_advogado": patro.get("outro_advogado_nome"),
            "patrocinio_outro_oab": patro.get("outro_advogado_oab"),
            "patrocinio_outro_escritorio": patro.get("outro_escritorio_nome"),
            "patrocinio_suspeita_devolucao": patro.get("suspeita_devolucao"),
            "contestacao_existe": cont.get("existe"),
            "contestacao_por_mdr": cont.get("apresentada_por_mdr"),
            "contestacao_por_nome": cont.get("apresentada_por_nome"),
            "contestacao_generica": cont.get("generica"),
            "sentenca_existe": sentenca.get("existe") if sentenca else None,
            "sentenca_tipo": sentenca.get("tipo") if sentenca else None,
            "sentenca_data": sentenca.get("data") if sentenca else None,
            "sentenca_valor": _safe_float(sentenca.get("valor_condenacao")) if sentenca else None,
            "transito_julgado": _transitou(p),
            "primeira_hab_master_nome": primeira_hab.get("advogado_nome") if primeira_hab else None,
            "primeira_hab_master_oab": primeira_hab.get("advogado_oab") if primeira_hab else None,
            "primeira_hab_master_data": primeira_hab.get("data_habilitacao") if primeira_hab else None,
            "analise_estrategica": p.analise_estrategica,
            "status": p.status,
            "extractor_used": p.extractor_used,
            "extraction_confidence": p.extraction_confidence,
        })

    # ─── Detalhamento de pedidos (1 row/pedido) ──────────────────────
    pedidos_detalhe = []
    for ped in pedidos_all:
        proc = next((p for p in processos if p.id == ped.processo_id), None)
        pedidos_detalhe.append({
            "processo_id": ped.processo_id,
            "cnj_number": proc.cnj_number if proc else None,
            "tipo_pedido": ped.tipo_pedido,
            "natureza": ped.natureza,
            "valor_indicado": _safe_float(ped.valor_indicado),
            "valor_estimado": _safe_float(ped.valor_estimado),
            "fundamentacao_valor": ped.fundamentacao_valor,
            "probabilidade_perda": ped.probabilidade_perda,
            "aprovisionamento": _safe_float(ped.aprovisionamento),
            "fundamentacao_risco": ped.fundamentacao_risco,
        })

    # ─── Lote info pra capa ──────────────────────────────────────────
    lote_info = {
        "id": lote.id,
        "nome": lote.nome,
        "cliente_nome": lote.cliente_nome,
        "descricao": lote.descricao,
        "status": lote.status,
        "snapshot_at": lote.snapshot_at.isoformat() if lote.snapshot_at else None,
        "analise_estrategica_carteira": lote.analise_estrategica_carteira,
    }

    return {
        "lote": lote_info,
        "kpis": kpis,
        "por_categoria": _sort_acc(cat_acc),
        "por_subcategoria": _sort_acc(sub_acc),
        "por_patrocinio": _sort_acc(patroc_acc),
        "por_produto": _sort_acc(produto_acc),
        "por_uf": _sort_acc(uf_acc),
        "por_tribunal": _sort_acc(trib_acc),
        "top_n_valor": [
            {
                "id": p.id,
                "cnj_number": p.cnj_number,
                "tribunal": _extract_tribunal(p),
                "valor_estimado": _safe_float(p.valor_estimado),
                "pcond_sugerido": _safe_float(p.pcond_sugerido),
                "prob_exito": _safe_float(p.prob_exito),
                "categoria": cat_map.get(p.categoria_id) if p.categoria_id else None,
            }
            for p in top_n
        ],
        "pedidos_por_tipo": pedidos_por_tipo,
        "sentencas_resumo": sentencas_resumo,
        "transito_julgado_resumo": transito_julgado_resumo,
        "contestacoes_resumo": contestacoes_resumo,
        "processos": processos_detalhe,
        "pedidos": pedidos_detalhe,
        "analise_estrategica_carteira": lote.analise_estrategica_carteira,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

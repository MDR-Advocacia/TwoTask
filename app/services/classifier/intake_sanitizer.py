"""
Sanitizador de payload de intake antes da classificação Sonnet.

Aplicado em `build_user_message` (prazos_iniciais_prompts.py) ANTES de
serializar o JSON pro modelo. Não muta os JSONs originais — recebe
deepcopy e devolve versões reduzidas. Os JSONs no banco continuam
íntegros pra auditoria/HITL.

Reduções aplicadas (medidas em 17 intakes reais, base.xlsx):

  1. Drop `document_text_preview` em cada item da timeline
     (redundante: é prefixo do `document_text` já presente).
  2. Limpa `header_text` mantendo só as 2 primeiras linhas úteis
     (label + "Juntado por X em data") — descarta linhas de
     "Ícone de seta", "N de M", "Ícone de download", etc.
  3. Limpa boilerplate de `document_text` por regex —
     marcadores de paginação (`Num. X - Pág. N`), assinatura
     eletrônica, URLs de consulta, número de documento, "Este
     documento foi gerado pelo usuário ...".
  4. Re-classifica `document_kind` pelo TIPO declarado no label
     do PJe (parte após o ID numérico). Conserta falsos positivos
     onde anexos viram "sentença" porque o label tinha "INCOMPETÊN".
  5. Drop `metadata` inteiro (origem, portal_key, source_row etc.
     não ajudam a classificar — só rastreabilidade de ingestão).
  6. Filtra `detalhes_extra` mantendo só campos NOVOS (que não
     duplicam capa): Jurisdição, Autuação, Tutela/liminar?,
     Prioridade?, Cargo judicial, Competência, Juízo 100% digital?.

Estimativa total: 18-20% menos tokens enviados ao Sonnet.
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Regex de boilerplate (Pje) ─────────────────────────────────────────
# Multilinha, case-insensitive. Cada linha matched é removida inteira.
_BOILERPLATE_PATTERNS = [
    re.compile(r"(?im)^\s*Num\.\s*\d+\s*-\s*Pág\.\s*\d+\s*$"),
    re.compile(r"(?im)^\s*Assinado eletronicamente por:.*$"),
    re.compile(r"(?im)^\s*https?://\S+\s*$"),
    re.compile(r"(?im)^\s*Número do documento:\s*\S+.*$"),
    re.compile(r"(?im)^\s*Este documento foi gerado.*$"),
]

# Compacta múltiplas quebras de linha que sobram após remoção
_MULTI_NEWLINE = re.compile(r"\n{3,}")

# Linha "Ícone..." e contadores "N de M" — ruído de UI capturado pelo
# scraper. Match exato pra não comer texto legítimo que possa falar de
# "ícone" no corpo de uma petição.
_HEADER_NOISE = re.compile(r"(?im)^\s*(?:Ícone\b.*|\d+\s+de\s+\d+)\s*$\n?")


# ── Re-classificação de document_kind ──────────────────────────────────
# O label do PJe segue o padrão "<id_numérico> - <Tipo declarado>". O
# tipo declarado é a fonte da verdade. O scraper hoje usa heurísticas
# em cima do título completo (que pode citar palavras que confundem),
# então re-classificamos aqui pelo tipo limpo.

_KIND_KEYWORDS = (
    # ordem importa: testes mais específicos primeiro
    ("Sentença", "sentenca"),
    ("Acórdão", "acordao"),
    ("Decisão", "decisao"),
    ("Despacho", "despacho"),
    ("Habilitação", "habilitacao"),  # Petição (Habilitação)
    ("Inicial", "peticao_inicial"),  # Petição Inicial
    ("Contestação", "contestacao"),
    ("Mandado", "mandado"),
    ("Certidão", "certidao_relevante"),
    ("Ofício", "oficio"),
    ("Petição", "peticao_intermediaria"),  # demais petições
    ("Documento de Comprovação", "outros"),
    ("Documento de Identificação", "outros"),
    ("Procuração", "outros"),
    ("Outros documentos", "outros"),
    ("Informação 2º Grau", "outros"),
    ("Informação", "outros"),
)


def _reclassify_kind_from_label(label: str, fallback: str) -> str:
    """
    Deriva `document_kind` a partir do tipo declarado no label.
    Se nada bate, devolve o fallback (kind original do scraper).

    Exemplos:
      "548733331 - Sentença"                          -> "sentenca"
      "551202764 - Petição (Habilitação)"             -> "habilitacao"
      "548786798 - Petição (1  INICIAL LUIZ MENEZES)" -> "peticao_inicial"
      "548786797 - Petição Inicial"                   -> "peticao_inicial"
      "548786806 - Documento de Comprovação (5 BGO)"  -> "outros"
    """
    if not label:
        return fallback
    # Tenta isolar o tipo declarado (depois do " - ")
    if " - " in label:
        tipo_chunk = label.split(" - ", 1)[1]
    else:
        tipo_chunk = label
    # Normaliza espaços
    tipo_chunk = " ".join(tipo_chunk.split())

    for needle, kind in _KIND_KEYWORDS:
        if needle.lower() in tipo_chunk.lower():
            return kind
    return fallback


# ── Detalhes_extra: campos que NÃO duplicam capa ───────────────────────
# Capa já tem: classe, assunto, vara/órgão, valor_causa, segredo, gratuita.
# Mantemos só o que é genuinamente novo.
_DETALHES_KEEP = frozenset({
    "Jurisdição",
    "Autuação",
    "Tutela/liminar?",
    "Prioridade?",
    "Cargo judicial",
    "Competência",
    "Juízo 100% digital?",
})


def _clean_header_text(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    cleaned = _HEADER_NOISE.sub("", value)
    # Compacta novelinhas múltiplas que sobram
    cleaned = _MULTI_NEWLINE.sub("\n\n", cleaned).strip()
    return cleaned


def _clean_document_text(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    cleaned = value
    for pat in _BOILERPLATE_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = _MULTI_NEWLINE.sub("\n\n", cleaned).strip()
    return cleaned


def _sanitize_timeline(timeline: list) -> list:
    """Devolve a timeline com itens sanitizados (cópia rasa, novos dicts)."""
    out: list = []
    for item in timeline or []:
        if not isinstance(item, dict):
            out.append(item)
            continue
        new_item = dict(item)  # cópia rasa do item

        # 1. Drop preview redundante
        new_item.pop("document_text_preview", None)

        # 2. Limpa header_text
        if "header_text" in new_item:
            new_item["header_text"] = _clean_header_text(new_item["header_text"])

        # 3. Limpa boilerplate de document_text
        if "document_text" in new_item:
            new_item["document_text"] = _clean_document_text(
                new_item["document_text"]
            )

        # 4. Re-classifica kind pelo label do PJe
        original_kind = new_item.get("document_kind") or "outros"
        new_kind = _reclassify_kind_from_label(
            new_item.get("label") or "", original_kind,
        )
        if new_kind != original_kind:
            new_item["document_kind"] = new_kind
            new_item["document_kind_original"] = original_kind  # rastreio

        out.append(new_item)
    return out


def _rebuild_documentos_relevantes(timeline: list) -> dict:
    """
    Reconstrói o índice `documentos_relevantes` a partir da timeline
    sanitizada — garante coerência com os `document_kind` re-classificados.
    """
    buckets = {
        "peticao_inicial": [],
        "decisoes": [],
        "despachos": [],
        "sentencas": [],
        "certidoes_relevantes": [],
        "contestacoes": [],
        "peticoes_intermediarias": [],
        "mandados": [],
    }
    kind_to_bucket = {
        "peticao_inicial": "peticao_inicial",
        "decisao": "decisoes",
        "despacho": "despachos",
        "sentenca": "sentencas",
        "acordao": "sentencas",  # acórdão entra junto com sentença pra HITL
        "certidao_relevante": "certidoes_relevantes",
        "contestacao": "contestacoes",
        "peticao_intermediaria": "peticoes_intermediarias",
        "mandado": "mandados",
    }
    for idx, item in enumerate(timeline or []):
        if not isinstance(item, dict):
            continue
        kind = item.get("document_kind")
        bucket_name = kind_to_bucket.get(kind)
        if not bucket_name:
            continue
        buckets[bucket_name].append({
            "timeline_index": idx,
            "document_id": item.get("document_id"),
            "link_id": item.get("link_id"),
            "label": item.get("label"),
            "timeline_date": item.get("timeline_date"),
            "protocol_date": item.get("protocol_date"),
            "header_text": item.get("header_text"),
            "document_kind": kind,
        })
    return buckets


def _filter_detalhes_extra(detalhes: dict) -> dict:
    if not isinstance(detalhes, dict):
        return detalhes or {}
    return {k: v for k, v in detalhes.items() if k in _DETALHES_KEEP}


def sanitize_for_classification(
    capa: Any,
    integra: Any,
    metadata: Optional[Any] = None,
) -> tuple[Any, Any, Optional[Any]]:
    """
    Recebe os 3 blocos do intake e devolve versões sanitizadas APENAS
    pra envio ao classificador. Não muta os originais.

    `metadata` é aceito mas ignorado (sempre retorna None) — não vai
    pro prompt porque não traz sinal jurídico, só rastreabilidade.
    """
    # Capa: passa direto, é compacta e tipada.
    capa_out = capa

    # Integra: deepcopy parcial — só os blocos que vamos editar.
    integra_out: dict
    if isinstance(integra, dict):
        integra_out = {**integra}
        timeline_clean = _sanitize_timeline(integra.get("timeline") or [])
        integra_out["timeline"] = timeline_clean
        # Re-deriva o índice pra refletir os kinds corrigidos
        integra_out["documentos_relevantes"] = _rebuild_documentos_relevantes(
            timeline_clean,
        )
        integra_out["detalhes_extra"] = _filter_detalhes_extra(
            integra.get("detalhes_extra") or {},
        )
    else:
        integra_out = integra

    # Metadata: dropado do prompt.
    return capa_out, integra_out, None


def estimate_reduction(
    capa: Any, integra: Any, metadata: Optional[Any] = None,
) -> dict:
    """Helper de observabilidade: tamanho antes/depois em chars."""
    import json

    def _serialize(obj: Any) -> int:
        try:
            return len(json.dumps(obj, ensure_ascii=False, default=str))
        except Exception:
            return 0

    before = _serialize(capa) + _serialize(integra) + _serialize(metadata)
    capa_s, integra_s, _ = sanitize_for_classification(capa, integra, metadata)
    after = _serialize(capa_s) + _serialize(integra_s)
    return {
        "before_chars": before,
        "after_chars": after,
        "saved_chars": before - after,
        "saved_pct": round(100 * (before - after) / before, 1) if before else 0.0,
    }

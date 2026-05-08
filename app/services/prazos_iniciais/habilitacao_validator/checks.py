"""
Funcoes individuais de checagem da habilitacao MDR.

Cada check e' uma funcao pura: recebe o texto ja normalizado (e o intake
quando precisa de contexto) e devolve um dict no formato:

    {
        "id": "C2",
        "label": "Pedido de publicacoes exclusivas em nome do titular",
        "criticidade": "CRITICO" | "AVISO",
        "status": "OK" | "ALERTA" | "FALHA" | "PULADO",
        "detalhe": "..." ou None,
    }

Nenhum check levanta — falhas viram status FALHA com mensagem.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from app.services.prazos_iniciais.habilitacao_validator.constants import (
    ANCHOR_PETICAO_HABILITACAO,
    ANCHOR_PROCURACAO,
    ANCHOR_SUBSTABELECIMENTO,
    CNJ_REGEX,
    OABS_ESCRITORIO_MIN,
    TITULAR_NOME,
    TITULAR_NOME_VARIANTS,
    TITULAR_OAB_NUM_VARIANTS,
    TITULAR_OAB_UF,
)
from app.services.prazos_iniciais.habilitacao_validator.text import (
    normalize_marker,
)

# ─── Status individuais ─────────────────────────────────────────────

CHECK_OK = "OK"
CHECK_FAILED = "FALHA"
CHECK_WARNING = "ALERTA"
CHECK_SKIPPED = "PULADO"

CRIT_CRITICAL = "CRITICO"
CRIT_WARNING = "AVISO"


def _result(
    check_id: str,
    label: str,
    criticidade: str,
    status: str,
    detalhe: Optional[str] = None,
) -> dict:
    return {
        "id": check_id,
        "label": label,
        "criticidade": criticidade,
        "status": status,
        "detalhe": detalhe,
    }


def _has_any(text_norm: str, options: tuple[str, ...]) -> bool:
    return any(opt in text_norm for opt in options)


def _titular_alts_norm() -> tuple[str, ...]:
    return tuple(normalize_marker(v) for v in TITULAR_NOME_VARIANTS)


def _has_titular_oab(text_norm: str) -> bool:
    """True se algum numero da OAB do titular + UF aparecem no texto."""
    uf_norm = TITULAR_OAB_UF.lower()
    if uf_norm not in text_norm:
        return False
    return any(num in text_norm for num in TITULAR_OAB_NUM_VARIANTS)


# ─── Checks individuais ─────────────────────────────────────────────


def check_peticao_habilitacao(text_norm: str) -> dict:
    """C1 — peticao de habilitacao esta presente (3 marcadores tipicos)."""
    anchors = tuple(normalize_marker(a) for a in ANCHOR_PETICAO_HABILITACAO)
    has_juizo = _has_any(text_norm, anchors)
    has_habilitacao_word = "habilitacao" in text_norm
    has_requerer = "requerer" in text_norm or "requer " in text_norm

    if has_juizo and has_habilitacao_word and has_requerer:
        return _result("C1", "Peticao de habilitacao encontrada", CRIT_CRITICAL, CHECK_OK)

    missing = []
    if not has_juizo:
        missing.append("invocacao ao juizo ('Respeitavel Juizo')")
    if not has_habilitacao_word:
        missing.append("palavra 'habilitacao'")
    if not has_requerer:
        missing.append("verbo 'requerer'")
    return _result(
        "C1", "Peticao de habilitacao encontrada", CRIT_CRITICAL, CHECK_FAILED,
        f"Nao encontrei marcadores tipicos da peticao: {', '.join(missing)}.",
    )


def check_pedido_exclusivamente(text_norm: str) -> dict:
    """C2 — pedido (d) com EXCLUSIVAMENTE + nome + OAB do titular, perto."""
    titular_alts = _titular_alts_norm()
    has_exclusivamente = "exclusivamente" in text_norm
    has_nome = any(alt in text_norm for alt in titular_alts)
    has_oab = _has_titular_oab(text_norm)

    if has_exclusivamente and has_nome and has_oab:
        idx_excl = text_norm.find("exclusivamente")
        idx_nome = -1
        for alt in titular_alts:
            i = text_norm.find(alt)
            if i >= 0 and (idx_nome < 0 or i < idx_nome):
                idx_nome = i
        if idx_nome >= 0 and abs(idx_excl - idx_nome) <= 800:
            return _result(
                "C2",
                "Pedido de publicacoes exclusivas em nome do titular",
                CRIT_CRITICAL, CHECK_OK,
            )
        return _result(
            "C2",
            "Pedido de publicacoes exclusivas em nome do titular",
            CRIT_CRITICAL, CHECK_FAILED,
            "Encontrei 'EXCLUSIVAMENTE', nome e OAB do titular, mas em "
            "partes distantes da peca — confirme se o pedido (d) esta "
            "completo e na peticao de habilitacao.",
        )

    missing = []
    if not has_exclusivamente:
        missing.append("'EXCLUSIVAMENTE'")
    if not has_nome:
        missing.append(f"nome do titular ({TITULAR_NOME})")
    if not has_oab:
        missing.append(
            f"OAB/{TITULAR_OAB_UF} {TITULAR_OAB_NUM_VARIANTS[0]}"
        )
    return _result(
        "C2",
        "Pedido de publicacoes exclusivas em nome do titular",
        CRIT_CRITICAL, CHECK_FAILED,
        f"Sem o pedido (d) padrao. Faltou: {', '.join(missing)}. "
        "Risco de nulidade processual (CPC 272 §5º) — intimacoes "
        "publicadas em nome de outro advogado nao tem efeito.",
    )


def check_assinatura_titular(text_norm: str) -> dict:
    """C3 — nome + OAB do titular aparecem ao final da peca."""
    titular_alts = _titular_alts_norm()
    has_nome = any(alt in text_norm for alt in titular_alts)
    has_oab = _has_titular_oab(text_norm)

    if not (has_nome and has_oab):
        return _result(
            "C3", "Assinatura do advogado titular", CRIT_CRITICAL, CHECK_FAILED,
            f"Nao localizei {TITULAR_NOME} + OAB/{TITULAR_OAB_UF} "
            f"{TITULAR_OAB_NUM_VARIANTS[0]} na peca.",
        )

    closure_markers = (
        "nestes termos",
        "termos em que",
        "data do protocolo",
        "natal/rn",
        "natal /rn",
    )
    has_closure = any(m in text_norm for m in closure_markers)
    if not has_closure:
        return _result(
            "C3", "Assinatura do advogado titular", CRIT_CRITICAL, CHECK_WARNING,
            "Nome e OAB do titular presentes, mas sem fecho tipico "
            "('Nestes termos', 'Natal/RN, na data do protocolo').",
        )
    return _result("C3", "Assinatura do advogado titular", CRIT_CRITICAL, CHECK_OK)


def check_procuracao(text_norm: str) -> dict:
    """C4 — procuracao anexa (palavra 'PROCURACAO' + 'outorga(nte)')."""
    anchors = tuple(normalize_marker(a) for a in ANCHOR_PROCURACAO)
    has_procuracao = _has_any(text_norm, anchors)
    has_outorga = "outorga" in text_norm
    if has_procuracao and has_outorga:
        return _result("C4", "Procuracao anexa", CRIT_CRITICAL, CHECK_OK)
    return _result(
        "C4", "Procuracao anexa", CRIT_CRITICAL, CHECK_FAILED,
        "Nao encontrei a procuracao (palavra 'PROCURACAO' + 'outorga(nte)').",
    )


def check_substabelecimento(text_norm: str) -> dict:
    """C5 — substabelecimento anexo."""
    anchors = tuple(normalize_marker(a) for a in ANCHOR_SUBSTABELECIMENTO)
    if _has_any(text_norm, anchors):
        return _result("C5", "Substabelecimento anexo", CRIT_CRITICAL, CHECK_OK)
    return _result(
        "C5", "Substabelecimento anexo", CRIT_CRITICAL, CHECK_FAILED,
        "Nao encontrei o substabelecimento (palavra 'SUBSTABELECIMENTO').",
    )


def check_cnj_match(text_norm: str, cnj_intake: Optional[str]) -> dict:
    """C6 — CNJ do intake bate com o que aparece no PDF."""
    cnj_digits = re.sub(r"\D", "", cnj_intake or "")
    if not cnj_digits or len(cnj_digits) < 15:
        return _result(
            "C6", "Numero do processo bate com o intake", CRIT_CRITICAL, CHECK_FAILED,
            "CNJ do intake invalido ou ausente.",
        )

    matches = re.findall(CNJ_REGEX, text_norm)
    found_digits = {re.sub(r"\D", "", m) for m in matches}

    if cnj_digits in found_digits:
        return _result("C6", "Numero do processo bate com o intake", CRIT_CRITICAL, CHECK_OK)

    if matches:
        sample = ", ".join(sorted(found_digits)[:2])
        return _result(
            "C6", "Numero do processo bate com o intake", CRIT_CRITICAL, CHECK_FAILED,
            f"PDF contem CNJ(s) [{sample}] — nao bate com o intake "
            f"({cnj_digits}). PDF trocado?",
        )

    return _result(
        "C6", "Numero do processo bate com o intake", CRIT_CRITICAL, CHECK_FAILED,
        "Nao localizei nenhum numero CNJ no PDF.",
    )


def check_cliente_match(text_norm: str, intake: Any) -> dict:
    """C7 — algum nome do cliente do intake (polo passivo) na habilitacao."""
    capa = getattr(intake, "capa_json", None) or {}
    polo_passivo = capa.get("polo_passivo") or []
    candidatos: list[str] = []
    for parte in polo_passivo:
        if isinstance(parte, dict):
            nome = parte.get("nome")
            if nome and isinstance(nome, str):
                candidatos.append(nome)

    if not candidatos:
        return _result(
            "C7", "Cliente do intake aparece na habilitacao",
            CRIT_CRITICAL, CHECK_SKIPPED,
            "Capa do intake sem polo passivo cadastrado — sem nome de "
            "cliente pra checar.",
        )

    # Tokens descartaveis (genericos demais — match isolado nao confirma).
    GENERIC_TOKENS = {
        "banco", "associacao", "associação", "ltda", "s/a", "sa",
        "do", "da", "de", "dos", "das", "e", "em",
    }

    for nome in candidatos:
        nome_norm = normalize_marker(nome).lower()
        if not nome_norm:
            continue
        # Match exato do nome inteiro.
        if nome_norm in text_norm:
            return _result(
                "C7", "Cliente do intake aparece na habilitacao",
                CRIT_CRITICAL, CHECK_OK,
                f"Cliente '{nome}' encontrado integralmente na habilitacao.",
            )
        # Match por tokens significativos (>=4 chars, nao genericos).
        tokens = [
            t for t in nome_norm.split()
            if len(t) >= 4 and t not in GENERIC_TOKENS
        ]
        if len(tokens) >= 2 and all(t in text_norm for t in tokens):
            return _result(
                "C7", "Cliente do intake aparece na habilitacao",
                CRIT_CRITICAL, CHECK_OK,
                f"Cliente '{nome}' encontrado (match parcial: "
                f"{', '.join(tokens[:3])}).",
            )

    sample = "; ".join(candidatos[:3])
    return _result(
        "C7", "Cliente do intake aparece na habilitacao",
        CRIT_CRITICAL, CHECK_FAILED,
        f"Nenhum dos clientes do intake aparece na habilitacao: {sample}.",
    )


def check_oab_escritorio(text_norm: str) -> dict:
    """C8 (AVISO) — alguma OAB conhecida do escritorio aparece."""
    found: list[str] = []
    for oab in OABS_ESCRITORIO_MIN:
        oab_norm = normalize_marker(oab).lower()
        oab_no_dot = oab_norm.replace(".", "")
        if oab_norm in text_norm or oab_no_dot in text_norm.replace(".", ""):
            found.append(oab)
    if found:
        return _result(
            "C8", "OAB do escritorio no substabelecimento",
            CRIT_WARNING, CHECK_OK,
            f"OABs encontradas: {', '.join(found[:3])}.",
        )
    return _result(
        "C8", "OAB do escritorio no substabelecimento",
        CRIT_WARNING, CHECK_WARNING,
        "Nenhuma OAB conhecida do escritorio encontrada — confirme se a "
        "lista de advogados substabelecidos esta correta.",
    )


def check_data_assinatura(text_norm: str, intake: Any) -> dict:
    """C9 (AVISO) — data mais recente no PDF e' plausivel (<= hoje, >= 6m)."""
    pattern = r"\b(\d{2}/\d{2}/\d{4})\b"
    matches = re.findall(pattern, text_norm)
    if not matches:
        return _result(
            "C9", "Data de assinatura plausivel", CRIT_WARNING, CHECK_SKIPPED,
            "Nao encontrei datas no formato DD/MM/AAAA.",
        )

    today = date.today()
    parsed: list[date] = []
    for m in matches:
        try:
            d, mth, y = m.split("/")
            parsed.append(date(int(y), int(mth), int(d)))
        except (ValueError, TypeError):
            continue

    if not parsed:
        return _result(
            "C9", "Data de assinatura plausivel", CRIT_WARNING, CHECK_SKIPPED,
            "Datas encontradas mas em formato inesperado.",
        )

    max_date = max(parsed)
    if max_date > today:
        return _result(
            "C9", "Data de assinatura plausivel", CRIT_WARNING, CHECK_WARNING,
            f"Data mais recente no PDF e' {max_date.isoformat()} (no futuro).",
        )
    if (today - max_date).days > 180:
        return _result(
            "C9", "Data de assinatura plausivel", CRIT_WARNING, CHECK_WARNING,
            f"Data mais recente no PDF e' {max_date.isoformat()} "
            "(mais de 6 meses) — habilitacao antiga?",
        )
    return _result(
        "C9", "Data de assinatura plausivel", CRIT_WARNING, CHECK_OK,
        f"Data mais recente: {max_date.isoformat()}.",
    )

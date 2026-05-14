"""Extrator MECANICO de audiencias a partir do texto cru do processo.

Usado pra BACKFILL retroativo em processos ja classificados ANTES do
cla004 (que adicionou audiencias ao schema da IA). Roda regex no
`integra_json.texto_cru` e devolve lista de dicts no mesmo formato que
a IA geraria — pra UI/PDF renderizarem identicamente.

Cobertura estimada: ~70-80% dos casos obvios (audiencia designada com
data/hora explicitas). Casos limites (audiencia em ata sem cabecalho,
redesignacao em despacho complexo) podem escapar — operador pode rodar
reclassify IA completa pra cobrir.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ─── Regex de detecao de audiencia ──────────────────────────────────────

# Padrao 1: "audiencia designada para DD/MM/AAAA as HH:MM"
# Variantes capturadas:
#   "audiencia designada para 12/05/2026 as 14:30"
#   "audiencia designada para o dia 12/05/2026 as 14h30"
#   "audiencia marcada para 12 de maio de 2026 as 14:30"
#   "fica designada audiencia de instrucao para 12/05/2026 as 14:30"
_RE_AUDIENCIA_DESIGNADA = re.compile(
    r"audi[eê]ncia[^\n]{0,30}"  # "audiencia [de tipo]" (até 30 chars de ruído)
    r"(?:designada|marcada|aprazada|aprasada|redesignada)"
    r"[^\n]{0,40}?"
    r"(?:para|em|no\s+dia)\s+(?:o\s+dia\s+)?"
    r"(\d{1,2})/(\d{1,2})/(\d{4})"  # data DD/MM/AAAA
    r"[^\n]{0,40}?"
    r"(?:\s+(?:as|às|às)\s+(\d{1,2})[h:](\d{2}))?",  # hora HH:MM (opcional)
    re.IGNORECASE,
)

# Padrao 2: "ata de audiencia" — sempre realizada
_RE_ATA_AUDIENCIA = re.compile(
    r"ata\s+(?:da\s+)?audi[eê]ncia",
    re.IGNORECASE,
)

# Padrao 3: tipo da audiencia
_RE_TIPO_CONCILIACAO = re.compile(
    r"audi[eê]ncia[^\n]{0,80}?(?:de\s+)?(?:concilia[çc][aã]o|media[çc][aã]o)",
    re.IGNORECASE,
)
_RE_TIPO_INSTRUCAO = re.compile(
    r"audi[eê]ncia[^\n]{0,80}?(?:de\s+)?(?:instru[çc][aã]o|aiju)",
    re.IGNORECASE,
)
_RE_TIPO_UNA = re.compile(
    r"audi[eê]ncia[^\n]{0,80}?una",
    re.IGNORECASE,
)

# Padrao 4: cancelamento
_RE_AUDIENCIA_CANCELADA = re.compile(
    r"audi[eê]ncia[^\n]{0,80}?(?:cancelada|prejudicada|tornada\s+sem\s+efeito)",
    re.IGNORECASE,
)

# Padrao 5: comparecimento - "compareceu o(a) advogado(a)"
# Pattern: nome em CAIXA ALTA OU Title Case + OAB
_RE_COMPARECEU_ADV = re.compile(
    r"compareceu[^\n]{0,30}?"
    r"(?:o\s+|a\s+|os\s+|as\s+)?"
    r"(?:advogad[oa]s?|patron[oa]s?|defensor(?:[ae]s?)?|procurador(?:[ae]s?)?)\s+"
    r"(?:Dr\.|Dra\.|Sr\.|Sra\.)?\s*"
    r"([A-ZÀ-Ú][A-Za-zÀ-ÿ\s\.\-]{4,80}?)"
    r"\s*[,\.\(]\s*"
    r"(?:OAB[\/\s]*([A-Z]{2})[\/\s]*(\d{1,6})|inscrit[ao]\s+na\s+OAB[\/\s]*([A-Z]{2})[\/\s]*(\d{1,6}))",
    re.IGNORECASE,
)

# Padrao 6: "presentes:" ou "presente(s)"
_RE_PRESENTES_HEADER = re.compile(
    r"presentes?\s*:\s*",
    re.IGNORECASE,
)

# URLs de videoconferencia (Meet, Zoom, Teams, Cisco, etc.)
_RE_VIDEOCONF_URL = re.compile(
    r"https?://(?:meet\.google\.com|zoom\.us|teams\.microsoft\.com|"
    r"meet\.jit\.si|webex\.com|cnj\.jus\.br/audiencia|"
    r"[a-z0-9.\-]+\.(?:jus|com|net)\.br/[a-z0-9./\-]*?(?:audiencia|sala|reuniao|meet))"
    r"[^\s\"]*",
    re.IGNORECASE,
)


def _classify_tipo(snippet: str) -> Optional[str]:
    """Decide o tipo da audiencia a partir do trecho contextual."""
    if _RE_TIPO_CONCILIACAO.search(snippet):
        return "conciliacao"
    if _RE_TIPO_INSTRUCAO.search(snippet):
        return "instrucao"
    if _RE_TIPO_UNA.search(snippet):
        return "una"
    return "outra"


def _parse_data(dia: str, mes: str, ano: str) -> Optional[date]:
    try:
        d = int(dia)
        m = int(mes)
        y = int(ano)
        if not (1 <= d <= 31 and 1 <= m <= 12 and 1900 <= y <= 2100):
            return None
        return date(y, m, d)
    except (ValueError, TypeError):
        return None


def _parse_hora(hh: Optional[str], mm: Optional[str]) -> Optional[time]:
    if not hh:
        return None
    try:
        h = int(hh)
        mi = int(mm) if mm else 0
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            return None
        return time(h, mi)
    except (ValueError, TypeError):
        return None


def _is_cancelada(snippet: str) -> bool:
    return bool(_RE_AUDIENCIA_CANCELADA.search(snippet))


def _is_ata(snippet: str) -> bool:
    """Trecho contem 'ata de audiencia' → audiencia foi realizada."""
    return bool(_RE_ATA_AUDIENCIA.search(snippet))


def _extract_comparecimentos(snippet: str) -> list[dict]:
    """Extrai advogados presentes de um snippet (ata ou similar)."""
    out: list[dict] = []
    seen = set()
    for m in _RE_COMPARECEU_ADV.finditer(snippet):
        nome = " ".join(m.group(1).strip().split())
        uf = m.group(2) or m.group(4)
        num = m.group(3) or m.group(5)
        if not nome or len(nome) < 4:
            continue
        key = nome.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "polo": None,
            "advogado_nome": nome.title(),
            "advogado_oab": f"OAB/{uf} {num}" if (uf and num) else None,
            "e_mdr_ou_vinculada": None,
            "parte_representada": None,
        })
    return out


def _extract_local(snippet: str) -> Optional[str]:
    """Tenta extrair local presencial OU URL de videoconferencia."""
    url_match = _RE_VIDEOCONF_URL.search(snippet)
    if url_match:
        return url_match.group(0)[:300]
    # Padrao presencial: "sala N", "Foro", "no enderecu N"
    sala_match = re.search(
        r"(sala\s+\d+[^,\n]{0,80}|foro\s+[^,\n]{0,80}|"
        r"vara\s+[^,\n]{0,80}\s+do\s+foro\s+[^,\n]{0,80})",
        snippet,
        re.IGNORECASE,
    )
    if sala_match:
        return sala_match.group(1).strip()[:300]
    return None


def extract_audiencias_from_text(
    texto_cru: str,
    today: Optional[date] = None,
    window_chars: int = 800,
) -> list[dict]:
    """Extrai lista de audiencias do texto cru via regex mecanico.

    Args:
        texto_cru: o blob de texto extraido do PDF (`integra_json.texto_cru`)
        today: data de referencia pra determinar agendada vs realizada
               (default: date.today())
        window_chars: janela de contexto ao redor de cada match (pra
                      extrair tipo, comparecimentos, local)

    Returns:
        Lista de dicts no formato compativel com AudienciaResponse:
        [
          {
            "data": "2026-06-15", "hora": "14:00", "tipo": "conciliacao",
            "local_ou_link": "...", "status": "agendada",
            "comparecimentos": [], "resultado": null, "fonte": "..."
          },
          ...
        ]
        Lista vazia se nada detectado.
    """
    if not texto_cru or len(texto_cru) < 50:
        return []
    if today is None:
        today = date.today()

    audiencias: list[dict] = []
    seen_keys: set[tuple] = set()  # dedup por (data, hora) — evita repeticoes

    for m in _RE_AUDIENCIA_DESIGNADA.finditer(texto_cru):
        d = _parse_data(m.group(1), m.group(2), m.group(3))
        if not d:
            continue
        t = _parse_hora(m.group(4), m.group(5))
        key = (d.isoformat(), t.isoformat() if t else None)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        # Janela de contexto: 200 chars antes + window_chars depois
        start = max(0, m.start() - 200)
        end = min(len(texto_cru), m.end() + window_chars)
        snippet = texto_cru[start:end]

        tipo = _classify_tipo(snippet)
        cancelada = _is_cancelada(snippet)
        if cancelada:
            status = "cancelada"
        elif d < today:
            status = "realizada"  # passada — assumimos que rolou
        else:
            status = "agendada"

        comparecimentos = []
        if status == "realizada" or _is_ata(snippet):
            comparecimentos = _extract_comparecimentos(snippet)
            status = "realizada"  # forca pra realizada quando tem ata

        local = _extract_local(snippet)

        # Snippet limpo pra fonte (1 frase com os ~150 chars ao redor)
        fonte_start = max(0, m.start() - 50)
        fonte_end = min(len(texto_cru), m.end() + 100)
        fonte = (
            texto_cru[fonte_start:fonte_end]
            .replace("\n", " ")
            .strip()
        )
        fonte = re.sub(r"\s+", " ", fonte)[:200]

        audiencias.append({
            "data": d.isoformat(),
            "hora": t.isoformat()[:5] if t else None,  # HH:MM
            "tipo": tipo,
            "local_ou_link": local,
            "status": status,
            "comparecimentos": comparecimentos,
            "resultado": None,
            "fonte": fonte,
        })

    # Ordena por data (mais antigas primeiro)
    audiencias.sort(key=lambda a: a.get("data") or "")
    return audiencias

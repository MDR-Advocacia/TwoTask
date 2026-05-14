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

# Padrao 1 (DESPACHO/DECISAO formato A): "audiencia designada para DD/MM/AAAA"
#   "audiencia designada para 12/05/2026 as 14:30"
#   "audiencia marcada para 12 de maio de 2026 as 14:30"
#   "fica designada audiencia de instrucao para 12/05/2026 as 14:30"
_RE_AUDIENCIA_DESIGNADA = re.compile(
    r"audi[eê]ncia[^\n]{0,30}"
    r"(?:designada|marcada|aprazada|aprasada|redesignada|prevista|aprazo|incluida)"
    r"[^\n]{0,40}?"
    r"(?:para|em|no\s+dia)\s+(?:o\s+dia\s+)?"
    r"(\d{1,2})/(\d{1,2})/(\d{4})"
    r"[^\n]{0,40}?"
    r"(?:\s+(?:as|às|as)\s+(\d{1,2})[h:](\d{2}))?",
    re.IGNORECASE,
)

# Padrao 1B (DESPACHO/DECISAO formato B — verbo PRIMEIRO):
#   "Designo audiencia de conciliacao para o dia DD/MM/AAAA as HH:MM"
#   "Redesigno a audiencia de instrucao para DD/MM/AAAA"
_RE_AUDIENCIA_VERBO_PRIMEIRO = re.compile(
    r"(?:redesigno|designo|determino|determinar)"
    r"[^\n]{0,30}?audi[eê]ncia[^\n]{0,40}?"
    r"(?:para|em|no\s+dia)\s+(?:o\s+dia\s+)?"
    r"(\d{1,2})/(\d{1,2})/(\d{4})"
    r"[^\n]{0,40}?"
    r"(?:\s+(?:as|às|as)\s+(\d{1,2})[h:](\d{2}))?",
    re.IGNORECASE,
)

# Padrao 2 (MOVIMENTACAO CHAPADA do sistema — PJe/eproc/eSAJ/PROJUDI):
# rotulos curtos da linha do tempo, "audiencia" + qualquer ruido < 60 chars
# + data + hora. Tolerante a:
#   "Audiencia designada — 15/06/2026 14:00"
#   "Audiencia de conciliacao — 12/05/2026 09:30"
#   "Audiencia (conciliacao) 12/05/2026 - 14:00"
#   "Audiencia de Conciliacao (Civel) 30/06/2026 14:30"
#   "Designacao de audiencia — Audiencia de conciliacao - 15/06/2026 10:00"
# O ruido `[^\d\n]{0,60}?` aceita QUALQUER coisa exceto digito/quebra de
# linha — evita pular pra outra movimentacao mas tolera palavras
# arbitrarias ("designada", "marcada", "(Civel)", etc).
_RE_AUDIENCIA_MOVIMENTACAO = re.compile(
    r"(?:designa[çc][aã]o\s+de\s+)?"
    r"audi[eê]ncia\b"
    r"[^\d\n]{0,60}?"
    r"(\d{1,2})/(\d{1,2})/(\d{4})"
    r"(?:[\s\-—,]+(?:as|às|as)?\s*(\d{1,2})[h:](\d{2}))?",
    re.IGNORECASE,
)

# Padrao 2B (PAUTA INVERTIDA — data ANTES de "audiencia"):
#   "12/06/2026 09:30 - Audiencia de conciliacao - Sala 1"
#   "DD/MM/AAAA HH:MM - Audiencia [tipo]"
# Usado em pautas/grade horaria de varas/foros.
_RE_AUDIENCIA_PAUTA_DATA_PRIMEIRO = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})"
    r"\s+(\d{1,2}):(\d{2})"
    r"\s*[-—:]\s*"
    r"audi[eê]ncia",
    re.IGNORECASE,
)

# Padrao 3 (EVENTO especifico em movimentacao):
# "Audiencia redesignada para 20/06/2026"
# "Audiencia realizada em 12/05/2026"
# "Audiencia cancelada — 12/05/2026"
# RESTRITIVO: a data DEVE estar a no maximo 30 chars depois do evento
# (evita pegar data de outra movimentacao mais a frente)
_RE_AUDIENCIA_EVENTO = re.compile(
    r"audi[eê]ncia\s+"
    r"(redesignada|realizada|cancelada|prejudicada|adiada|suspensa|n[aã]o\s+realizada)"
    r"[\s\-—,:]{0,30}?(?:para|em|no\s+dia|—|-|:)?\s*"
    r"(\d{1,2})/(\d{1,2})/(\d{4})"
    r"(?:[\s\-—,]+(?:as|às|as)?\s*(\d{1,2})[h:](\d{2}))?",
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
    # Dedup inteligente: indexado por data; quando ja existe entrada com hora,
    # nao adiciona nova entrada sem hora pra mesma data (e vice-versa).
    by_data: dict[str, list[dict]] = {}

    def _check_dedup(d: date, t: Optional[time]) -> bool:
        """Retorna True se ja existe entrada compativel — pula.

        Tambem REMOVE entries sem hora quando uma com hora chega depois
        (consolida pra entry mais informativa).
        """
        key = d.isoformat()
        existing = by_data.get(key) or []
        if not existing:
            return False
        new_hora = t.isoformat()[:5] if t else None
        for e in existing:
            e_hora = e.get("hora")
            if e_hora == new_hora:
                return True  # match exato → skipa
        # Se chegou aqui, ja tem entry(s) pra mesma data mas hora diferente:
        # - entrada NOVA sem hora + existente com hora → skipa nova (existente vence)
        # - entrada NOVA com hora + existente(s) sem hora → remove existentes sem hora
        if new_hora is None:
            # so' skipa se TODAS as existentes tem hora preenchida
            if all(e.get("hora") for e in existing):
                return True
            # senao deixa entrar (pode ser audiencia em outro dia/hora)
            return False
        # NOVA tem hora — remove existentes SEM hora pra mesma data
        # (consolida pra entry mais informativa)
        by_data[key] = [e for e in existing if e.get("hora")]
        return False

    def _build_entry(
        d: date,
        t: Optional[time],
        snippet: str,
        match_start: int,
        match_end: int,
        forced_status: Optional[str] = None,
        forced_tipo: Optional[str] = None,
    ) -> Optional[dict]:
        """Constroi 1 entrada de audiencia + checa dedup."""
        if _check_dedup(d, t):
            return None

        tipo = forced_tipo or _classify_tipo(snippet)

        if forced_status:
            status = forced_status
        else:
            cancelada = _is_cancelada(snippet)
            if cancelada:
                status = "cancelada"
            elif d < today:
                status = "realizada"  # passada — assumimos que rolou
            else:
                status = "agendada"

        comparecimentos: list[dict] = []
        if status == "realizada" or _is_ata(snippet):
            comparecimentos = _extract_comparecimentos(snippet)
            status = "realizada"  # forca pra realizada quando tem ata

        local = _extract_local(snippet)

        # Snippet limpo pra fonte (1 frase com os ~150 chars ao redor)
        fonte_start = max(0, match_start - 50)
        fonte_end = min(len(texto_cru), match_end + 100)
        fonte = (
            texto_cru[fonte_start:fonte_end]
            .replace("\n", " ")
            .strip()
        )
        fonte = re.sub(r"\s+", " ", fonte)[:200]

        entry = {
            "data": d.isoformat(),
            "hora": t.isoformat()[:5] if t else None,  # HH:MM
            "tipo": tipo,
            "local_ou_link": local,
            "status": status,
            "comparecimentos": comparecimentos,
            "resultado": None,
            "fonte": fonte,
        }
        by_data.setdefault(d.isoformat(), []).append(entry)
        return entry

    # PADRAO 3 (EVENTO especifico) — rodado PRIMEIRO porque tem status
    # forcado (cancelada/redesignada/realizada). Se rodasse depois,
    # padroes mais genericos pegariam com status errado.
    _STATUS_MAP = {
        "redesignada": "agendada",  # a NOVA data e' a que conta
        "realizada": "realizada",
        "cancelada": "cancelada",
        "prejudicada": "cancelada",
        "adiada": "cancelada",
        "suspensa": "cancelada",
        "nao realizada": "cancelada",
        "não realizada": "cancelada",
    }
    for m in _RE_AUDIENCIA_EVENTO.finditer(texto_cru):
        evento = m.group(1).lower().strip()
        evento = re.sub(r"\s+", " ", evento)
        forced_status = _STATUS_MAP.get(evento)
        if not forced_status:
            continue
        d = _parse_data(m.group(2), m.group(3), m.group(4))
        if not d:
            continue
        t = _parse_hora(m.group(5), m.group(6))
        start = max(0, m.start() - 150)
        end = min(len(texto_cru), m.end() + 400)
        _build_entry(
            d, t, texto_cru[start:end],
            m.start(), m.end(),
            forced_status=forced_status,
        )

    # PADRAO 1: despacho/decisao "audiencia designada para DD/MM/AAAA"
    for m in _RE_AUDIENCIA_DESIGNADA.finditer(texto_cru):
        d = _parse_data(m.group(1), m.group(2), m.group(3))
        if not d:
            continue
        t = _parse_hora(m.group(4), m.group(5))
        start = max(0, m.start() - 200)
        end = min(len(texto_cru), m.end() + window_chars)
        _build_entry(d, t, texto_cru[start:end], m.start(), m.end())

    # PADRAO 1B: verbo primeiro — "Designo audiencia ... para DD/MM/AAAA"
    for m in _RE_AUDIENCIA_VERBO_PRIMEIRO.finditer(texto_cru):
        d = _parse_data(m.group(1), m.group(2), m.group(3))
        if not d:
            continue
        t = _parse_hora(m.group(4), m.group(5))
        start = max(0, m.start() - 100)
        end = min(len(texto_cru), m.end() + window_chars)
        _build_entry(d, t, texto_cru[start:end], m.start(), m.end())

    # PADRAO 2B: pauta invertida — "DD/MM/AAAA HH:MM - Audiencia ..."
    for m in _RE_AUDIENCIA_PAUTA_DATA_PRIMEIRO.finditer(texto_cru):
        d = _parse_data(m.group(1), m.group(2), m.group(3))
        if not d:
            continue
        t = _parse_hora(m.group(4), m.group(5))
        start = max(0, m.start() - 50)
        end = min(len(texto_cru), m.end() + 300)
        _build_entry(d, t, texto_cru[start:end], m.start(), m.end())

    # PADRAO 2: movimentacao chapada — RODA POR ULTIMO porque e' o mais
    # permissivo (pode dar falso positivo em datas soltas com "audiencia"
    # por perto)
    for m in _RE_AUDIENCIA_MOVIMENTACAO.finditer(texto_cru):
        d = _parse_data(m.group(1), m.group(2), m.group(3))
        if not d:
            continue
        t = _parse_hora(m.group(4), m.group(5))
        start = max(0, m.start() - 100)
        end = min(len(texto_cru), m.end() + 300)
        _build_entry(d, t, texto_cru[start:end], m.start(), m.end())

    # Recolhe entries (preserva ordem de insercao dentro do by_data)
    audiencias = [e for entries in by_data.values() for e in entries]

    # Ordena por data (mais antigas primeiro)
    audiencias.sort(key=lambda a: a.get("data") or "")
    return audiencias

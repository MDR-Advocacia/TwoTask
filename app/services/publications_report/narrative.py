"""Diagnóstico crítico do relatório de performance.

Gera a parte analítica (texto executivo) a partir das métricas. Usa o Sonnet
preso a uma ESTRUTURA RÍGIDA de seções e a um registro formal (sem
coloquialismos, sem primeira pessoa, sem emojis). Se a chave da Anthropic
não estiver configurada ou a chamada falhar, cai num fallback determinístico
que segue exatamente a mesma estrutura.

Saída: dict com as chaves
  sumario_executivo, diagnostico_capacidade, desigualdade_pools,
  capacidade_ociosa, recomendacoes (lista), ressalvas (lista).
"""

from __future__ import annotations

import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_SECOES = (
    "sumario_executivo",
    "diagnostico_capacidade",
    "desigualdade_pools",
    "capacidade_ociosa",
    "recomendacoes",
    "ressalvas",
)

_SYSTEM = (
    "Você é um analista de operações jurídicas redigindo um relatório executivo "
    "de performance para a diretoria de um escritório de advocacia. Registro "
    "formal, impessoal e objetivo, em português do Brasil. PROIBIDO: coloquialismos, "
    "gírias, primeira pessoa, emojis, exclamações, hipérboles e qualquer afirmação "
    "não sustentada pelos dados fornecidos. Baseie-se EXCLUSIVAMENTE nas métricas do "
    "JSON recebido. Quando citar números, use os valores do JSON. O foco é capacity "
    "da equipe, dimensionamento de pessoal e oportunidades de rebalanceamento."
)

_INSTRUCAO = (
    "Com base nas métricas a seguir, redija o diagnóstico crítico de performance da "
    "equipe de tratamento de publicações. Responda ESTRITAMENTE em JSON válido, sem "
    "texto fora do JSON, com as chaves exatas:\n"
    '  "sumario_executivo": parágrafo único (4-6 frases) com a conclusão central, '
    "incluindo a recomendação de dimensionamento da equipe;\n"
    '  "diagnostico_capacidade": parágrafo sobre volume, custo por decisão e produção '
    "por operador, distinguindo velocidade de capacidade utilizada;\n"
    '  "desigualdade_pools": parágrafo sobre a distribuição desigual de pools por '
    "escritório e seu efeito sobre a produção individual;\n"
    '  "capacidade_ociosa": parágrafo sobre utilização e horário de término, '
    "identificando capacidade não utilizada;\n"
    '  "recomendacoes": lista de 3 a 5 itens, cada um uma frase imperativa formal;\n'
    '  "ressalvas": lista de 2 a 4 itens sobre limites metodológicos.\n'
    "Não use markdown dentro dos valores. Métricas:\n"
)


def build_narrative(metrics: dict) -> dict:
    """Retorna o diagnóstico crítico (Sonnet com fallback determinístico)."""
    api_key = settings.anthropic_api_key
    if not api_key:
        logger.info("Relatório de performance: ANTHROPIC_API_KEY ausente — usando fallback determinístico.")
        return _fallback(metrics)

    try:
        import anthropic

        model = getattr(settings, "prazos_iniciais_classifier_model", None) or "claude-sonnet-4-6"
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=2500,
            temperature=0.2,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": _INSTRUCAO + json.dumps(metrics, ensure_ascii=False),
            }],
        )
        raw = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
        data = _parse_json(raw)
        # Garante todas as seções; o que faltar vem do fallback.
        fb = _fallback(metrics)
        out = {}
        for k in _SECOES:
            v = data.get(k)
            out[k] = v if v else fb[k]
        out["_fonte"] = "sonnet"
        return out
    except Exception:
        logger.exception("Relatório de performance: falha no Sonnet — usando fallback determinístico.")
        return _fallback(metrics)


def _parse_json(raw: str) -> dict:
    s = (raw or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.lstrip().lower().startswith("json"):
            s = s.lstrip()[4:]
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


# ──────────────────────────────────────────────────────────────────────
# Fallback determinístico — mesma estrutura, linguagem formal.
# ──────────────────────────────────────────────────────────────────────

def _fmt(n) -> str:
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _fallback(m: dict) -> dict:
    f = m["funil"]
    t = m["totais"]
    d = m["demanda"]
    prod = m.get("producao", [])
    custo = m.get("custo_por_decisao", [])
    ocio = m.get("ociosidade", [])
    pools = [p for p in m.get("pools", []) if p["pool_dia"] >= 1]

    top = prod[0] if prod else None
    # Operador mais lento por mediana de agendar.
    lentos = [c for c in custo if c.get("med_agendar_s")]
    mais_lento = max(lentos, key=lambda c: c["med_agendar_s"]) if lentos else None
    rapidos = [c for c in custo if c.get("mediana_s")]
    mais_rapido = min(rapidos, key=lambda c: c["mediana_s"]) if rapidos else None
    # Pool máximo e mínimo.
    pool_max = max(pools, key=lambda p: p["pool_dia"]) if pools else None
    pool_min = min(pools, key=lambda p: p["pool_dia"]) if pools else None
    # Operador que termina mais cedo (capacidade ociosa).
    cedo = min(ocio, key=lambda o: o["fim_medio"]) if ocio else None

    sumario = (
        f"No período analisado, a equipe processou {_fmt(t['total_decisoes'])} decisões humanas "
        f"({_fmt(t['agendadas'])} agendamentos e {_fmt(t['ignoradas'])} ciências), com média de "
        f"{_fmt(t['decisoes_dia_util'])} decisões por dia útil. A classificação automática descartou "
        f"{f['auto_descartado_pct']}% das publicações capturadas antes de qualquer intervenção humana, e "
        f"o backlog corrente é de {_fmt(d['backlog_atual'])} itens, indicando equilíbrio entre demanda e vazão. "
        "A análise de utilização e a desigualdade de pools por escritório indicam folga de capacidade compatível "
        "com a operação por uma pessoa a menos, condicionada ao rebalanceamento da fila e à equalização de ritmo "
        "entre operadores."
    )

    diag = (
        f"O custo efetivo medido por decisão é de aproximadamente {_fmt(t.get('custo_efetivo_s'))} segundos, "
        f"resultando em cerca de {t.get('trabalho_horas_dia') or '—'} horas de trabalho ativo por dia útil. "
    )
    if top:
        diag += (
            f"O operador de maior produção registra {_fmt(top['por_dia'])} decisões por dia ativo. "
        )
    if mais_rapido and mais_lento and mais_rapido["nome"] != mais_lento["nome"]:
        diag += (
            f"Observa-se dispersão relevante de ritmo: a mediana mais baixa por decisão é de "
            f"{_fmt(mais_rapido['mediana_s'])} segundos, enquanto o agendamento mais lento atinge "
            f"{_fmt(mais_lento['med_agendar_s'])} segundos — diferença que reflete produtividade, não complexidade do pool."
        )

    pools_txt = (
        "A distribuição de trabalho por escritório é acentuadamente desigual. "
    )
    if pool_max and pool_min and pool_max["escritorio"] != pool_min["escritorio"]:
        pools_txt += (
            f"O maior pool ({pool_max['escritorio']}) gera cerca de {_fmt(pool_max['pool_dia'])} publicações por dia útil, "
            f"contra aproximadamente {_fmt(pool_min['pool_dia'])} do menor pool relevante ({pool_min['escritorio']}). "
            "A produção individual reflete, em grande medida, o tamanho do pool atribuído, e não a capacidade do operador, "
            "o que recomenda cautela ao interpretar volume como desempenho."
        )

    ocio_txt = "A medição de utilização revela capacidade não utilizada. "
    if cedo:
        ocio_txt += (
            f"O operador com término mais precoce encerra suas atividades, em média, às {cedo['fim_medio']}, "
            f"com utilização de {_fmt(cedo['util_pct'])}% do tempo logado, evidenciando esvaziamento antecipado do pool. "
            "Esse padrão indica que parte da capacidade contratada permanece ociosa por limitação de fila, não de competência."
        )

    recs = [
        "Unificar a fila de tratamento e atribuir o trabalho por capacidade, eliminando a segmentação rígida por escritório.",
        "Direcionar a capacidade ociosa identificada para o pool de maior volume, reduzindo a concentração de fila.",
    ]
    if mais_lento:
        recs.append(
            f"Promover a equalização de ritmo do operador de menor produtividade ({mais_lento['nome']}) ao patamar já demonstrado pela equipe."
        )
    recs.append("Manter uma posição de reserva para absorção dos picos de demanda, sem mantê-la como rotina.")

    ressalvas = [
        "O tempo de trabalho ativo é medido pelo intervalo entre decisões e subestima o esforço real, pois não captura a leitura de casos complexos nem o tempo que não termina em decisão registrada.",
        "As métricas refletem exclusivamente o período selecionado e o estado atual da base; variações sazonais e picos pontuais podem alterar o dimensionamento.",
        "Registros de autoria com grafia divergente para um mesmo operador podem fragmentar a produção individual e devem ser consolidados na origem.",
    ]

    return {
        "sumario_executivo": sumario,
        "diagnostico_capacidade": diag,
        "desigualdade_pools": pools_txt,
        "capacidade_ociosa": ocio_txt,
        "recomendacoes": recs,
        "ressalvas": ressalvas,
        "_fonte": "fallback",
    }

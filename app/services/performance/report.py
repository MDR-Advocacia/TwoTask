"""Relatórios PDF do "Minha Equipe" — do setor e do indivíduo.

Sonnet preso a estrutura rígida + registro formal (sem coloquialismos), com
fallback determinístico de mesma estrutura — igual ao relatório de Publicações.
HTML autossuficiente → PDF via Chromium (reusa publications_report.pdf.html_to_pdf).

Dois relatórios:
- sector_report_pdf(db, days)            — diagnóstico do setor no período.
- individual_report_pdf(db, pessoa_id, days) — raio-x da pessoa + intervenções sugeridas.
"""

from __future__ import annotations

import html as _html
import json
import logging
from datetime import date, datetime
from decimal import Decimal

from app.core.config import settings
from app.services.performance.service import PerformanceService
from app.services.publications_report.pdf import html_to_pdf

logger = logging.getLogger(__name__)


# ── helpers de formatação ─────────────────────────────────────────────
def _json_default(o):
    if isinstance(o, Decimal):
        f = float(o)
        return int(f) if f.is_integer() else f
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)


def _e(s) -> str:
    return _html.escape("" if s is None else str(s))


def _n(v, suf="", dash="—") -> str:
    if v is None:
        return dash
    try:
        f = float(v)
        s = f"{int(round(f)):,}".replace(",", ".") if f == int(f) else f"{f:.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return _e(v)
    return f"{s}{suf}"


def _list(items) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in (items or [])) + "</ul>"


def _kpi(label, value, hint="") -> str:
    return (
        f'<div class="kpi"><div class="l">{_e(label)}</div><div class="v">{value}</div>'
        f'<div class="h">{_e(hint)}</div></div>'
    )


_STYLE = """
<style>
  :root{--ink:#1c1c1a;--muted:#5f5e5a;--hint:#8b8a83;--line:#d9d7cd;--blue:#378ADD;--teal:#1d9e75;--amber:#ba7517;--rose:#be123c;--bg:#f2f0e9;}
  *{box-sizing:border-box;} html,body{margin:0;padding:0;}
  @page{size:A4;margin:14mm 14mm 16mm;}
  body{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);font-size:12px;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  h1{font-size:23px;font-weight:600;margin:0 0 2px;letter-spacing:-.4px;}
  h2{font-size:15px;font-weight:600;margin:16px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--ink);}
  h3{font-size:12.5px;font-weight:600;margin:11px 0 4px;}
  p{margin:0 0 7px;text-align:justify;} .sub{color:var(--muted);font-size:12px;} .meta{color:var(--hint);font-size:10px;}
  .tag{display:inline-block;font-size:9px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;padding:2px 7px;border-radius:4px;background:var(--bg);color:var(--muted);}
  .head{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:9px;margin-bottom:5px;}
  .logo{font-size:15px;font-weight:700;letter-spacing:-.3px;} .logo span{color:var(--blue);}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin:11px 0;}
  .kpis.k3{grid-template-columns:repeat(3,1fr);} .kpis.k5{grid-template-columns:repeat(5,1fr);}
  .kpi{background:var(--bg);border-radius:7px;padding:8px 9px;}
  .kpi .l{font-size:9.5px;color:var(--muted);} .kpi .v{font-size:17px;font-weight:600;line-height:1.15;margin-top:2px;} .kpi .h{font-size:9px;color:var(--hint);margin-top:1px;}
  table{width:100%;border-collapse:collapse;margin:6px 0 9px;font-size:11px;}
  th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1.5px solid var(--ink);padding:4px 6px;font-size:9.5px;text-transform:uppercase;letter-spacing:.3px;}
  td{padding:4px 6px;border-bottom:1px solid var(--line);} td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}
  .note{background:var(--bg);border-left:3px solid var(--blue);border-radius:0 6px 6px 0;padding:8px 10px;margin:9px 0;font-size:11px;}
  .verdict{border:2px solid var(--ink);border-radius:9px;padding:10px 12px;margin:10px 0;}
  .verdict h3{margin-top:0;}
  ul{margin:4px 0 9px;padding-left:16px;} li{margin:3px 0;}
  .pill{display:inline-block;font-size:9px;font-weight:600;padding:1px 6px;border-radius:10px;}
  .op{background:#dbeafe;color:#1e5fa8;} .pr{background:#d1fae5;color:#0f7a55;} .ru{background:#eceae3;color:#6b6a63;}
  .red{color:var(--rose);font-weight:600;} .amber{color:var(--amber);}
  .avoid{page-break-inside:avoid;}
  .foot{margin-top:14px;border-top:1px solid var(--line);padding-top:5px;font-size:9px;color:var(--hint);display:flex;justify-content:space-between;}
</style>
"""

_CAT_PILL = {"operacional": ('<span class="pill op">Operacional</span>'),
             "profundo": ('<span class="pill pr">Profundo</span>'),
             "ruido": ('<span class="pill ru">Ruído</span>')}


# ══════════════════════════════════════════════════════════════════════
# SETOR
# ══════════════════════════════════════════════════════════════════════
_SYS_SETOR = (
    "Você é um analista de operações jurídicas redigindo um relatório executivo de "
    "desempenho de uma equipe para a diretoria de um escritório de advocacia. Registro "
    "formal, impessoal e objetivo, em português do Brasil. PROIBIDO: coloquialismos, "
    "primeira pessoa, emojis, exclamações e afirmações não sustentadas pelos dados. "
    "Use exclusivamente as métricas do JSON. Distinga trabalho operacional (alta "
    "frequência, em que cadência/ócio valem) de trabalho profundo (avaliado por volume, "
    "tempo de ciclo e cumprimento de prazo)."
)
_INSTR_SETOR = (
    "Com base nas métricas do setor a seguir, redija o diagnóstico crítico. Responda "
    "ESTRITAMENTE em JSON válido, sem texto fora do JSON, com as chaves exatas:\n"
    '  "sumario_executivo": parágrafo único (4-6 frases) com a conclusão central;\n'
    '  "producao": parágrafo sobre vazão e produção por pessoa, comparando pares de mesmo cargo;\n'
    '  "prazo_risco": parágrafo sobre tarefas pendentes e vencidas e onde o risco se concentra;\n'
    '  "gargalos": parágrafo sobre os tipos de tarefa que mais represam/atrasam;\n'
    '  "recomendacoes": lista de 3 a 5 frases imperativas formais;\n'
    '  "ressalvas": lista de 2 a 4 limites metodológicos.\n'
    "Sem markdown nos valores. Métricas:\n"
)
_SEC_SETOR = ("sumario_executivo", "producao", "prazo_risco", "gargalos", "recomendacoes", "ressalvas")


def _sector_metrics(db, days: int) -> dict:
    svc = PerformanceService(db)
    eq = svc.equipe(days=days)
    dash = svc.dashboard(days=days)
    return {
        "periodo_dias": days,
        "kpis_equipe": eq["kpis"],
        "kpis_risco": dash["kpis"],
        "vazao": dash["vazao"][:15],
        "backlog": [b for b in dash["backlog"] if b["backlog"] > 0][:15],
        "top_tipos": dash["top_tipos"],
    }


def _sector_fallback(m: dict) -> dict:
    ke, kr = m["kpis_equipe"], m["kpis_risco"]
    vaz, bk, top = m["vazao"], m["backlog"], m["top_tipos"]
    top_vaz = vaz[0] if vaz else None
    top_atr = max(bk, key=lambda x: x["atrasado"]) if bk else None
    pior = max(top, key=lambda x: x["atrasado"]) if top else None
    sumario = (
        f"No período de {m['periodo_dias']} dias, a equipe concluiu {_n(ke['concluido'])} tarefas, com "
        f"{ke['pessoas_ativas']} de {ke['pessoas_total']} integrantes ativos e cumprimento de prazo de "
        f"{_n(ke['no_prazo_pct'])}%. A carga aberta soma {_n(kr['backlog_total'])} tarefas, das quais "
        f"{_n(kr['atrasado_total'])} estão vencidas. A leitura de produção considera a natureza das tarefas: "
        "indicadores de ritmo aplicam-se ao trabalho operacional, enquanto o trabalho de maior complexidade é "
        "avaliado por volume, tempo de ciclo e cumprimento de prazo."
    )
    producao = (
        f"A maior vazão individual registra {_n(top_vaz['concluido']) if top_vaz else '—'} tarefas concluídas no "
        "período. A produção por pessoa reflete o cargo e a natureza das tarefas atribuídas, o que recomenda comparar "
        "integrantes de mesma função antes de qualquer conclusão sobre produtividade."
    )
    prazo = f"O setor acumula {_n(kr['atrasado_total'])} tarefas vencidas sobre {_n(kr['backlog_total'])} pendentes. "
    if top_atr:
        prazo += f"A maior concentração de atraso recai sobre {_e(top_atr['nome'])}, com {_n(top_atr['atrasado'])} tarefas vencidas."
    gargalos = (
        f"Entre os tipos de tarefa, {_e(pior['subtipo'])} apresenta o maior volume vencido "
        f"({_n(pior['atrasado'])} de {_n(pior['pendente'])} pendentes), configurando o principal gargalo de prazo do setor."
        if pior else "Não há concentração relevante de atraso por tipo de tarefa no período."
    )
    recs = [
        "Priorizar a regularização das tarefas vencidas, iniciando pelos responsáveis e tipos de maior concentração.",
        "Redistribuir a carga aberta entre integrantes com folga de capacidade, respeitando a natureza das tarefas.",
        "Acompanhar semanalmente o percentual do pool vencido como indicador de risco operacional.",
        "Comparar produtividade apenas entre pares de mesmo cargo, evitando leituras enviesadas por volume.",
    ]
    ressalvas = [
        "Cadência e ócio só são confiáveis no segmento operacional; no trabalho profundo, o intervalo entre conclusões reflete esforço não cronometrado.",
        "As métricas refletem o período selecionado e o estado atual da base de tarefas.",
        "A atribuição por pessoa depende do registro correto de autoria no Legal One.",
    ]
    return {
        "sumario_executivo": sumario, "producao": producao, "prazo_risco": prazo,
        "gargalos": gargalos, "recomendacoes": recs, "ressalvas": ressalvas, "_fonte": "fallback",
    }


def _render_setor(m: dict, nar: dict) -> str:
    ke, kr = m["kpis_equipe"], m["kpis_risco"]
    o = ['<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">',
         "<title>Relatório — Minha Equipe</title>", _STYLE, "</head><body>"]
    o.append(
        '<div class="head"><div><div class="tag">Relatório executivo · uso interno</div>'
        '<h1>Desempenho da Equipe — BB Réu</h1>'
        '<div class="sub">Diagnóstico crítico de produção, prazo e carga</div></div>'
        '<div style="text-align:right"><div class="logo">Duna<span>Flow</span></div>'
        f'<div class="meta">MDR Advocacia</div><div class="meta">Período: últimos {m["periodo_dias"]} dias</div></div></div>'
    )
    o.append('<div class="kpis k5">')
    o.append(_kpi("Concluídas", _n(ke["concluido"]), "no período"))
    o.append(_kpi("No prazo", _n(ke["no_prazo_pct"], "%"), "das c/ prazo"))
    o.append(_kpi("Pendentes", _n(kr["backlog_total"]), "pool aberto"))
    o.append(_kpi("Atrasadas", _n(kr["atrasado_total"]), "vencidas"))
    o.append(_kpi("Ativos", f'{ke["pessoas_ativas"]}/{ke["pessoas_total"]}', "no período"))
    o.append("</div>")

    o.append("<h2>Sumário executivo</h2>")
    o.append(f"<p>{_e(nar.get('sumario_executivo',''))}</p>")
    o.append("<h2>Produção e vazão</h2>")
    o.append(f"<p>{_e(nar.get('producao',''))}</p>")

    o.append('<div class="avoid"><h3>Maiores vazões (concluídas no período)</h3>')
    o.append("<table><tr><th>Pessoa</th><th>Cargo</th><th class='n'>Concluídas</th><th class='n'>Por dia</th></tr>")
    for v in m["vazao"][:10]:
        o.append(f"<tr><td>{_e(v['nome'])}</td><td>{_e(v['cargo'])}</td><td class='n'>{_n(v['concluido'])}</td><td class='n'>{_n(v['throughput_dia'])}</td></tr>")
    o.append("</table></div>")

    o.append("<h2>Prazo e risco</h2>")
    o.append(f"<p>{_e(nar.get('prazo_risco',''))}</p>")
    o.append('<div class="avoid"><h3>Maior pool aberto e atraso por pessoa</h3>')
    o.append("<table><tr><th>Pessoa</th><th>Cargo</th><th class='n'>Pendentes</th><th class='n'>Atrasadas</th></tr>")
    for b in sorted(m["backlog"], key=lambda x: -x["atrasado"])[:10]:
        atr = f'<span class="red">{_n(b["atrasado"])}</span>' if b["atrasado"] else "0"
        o.append(f"<tr><td>{_e(b['nome'])}</td><td>{_e(b['cargo'])}</td><td class='n'>{_n(b['backlog'])}</td><td class='n'>{atr}</td></tr>")
    o.append("</table></div>")

    o.append("<h2>Gargalos por tipo de tarefa</h2>")
    o.append(f"<p>{_e(nar.get('gargalos',''))}</p>")
    o.append('<div class="avoid"><table><tr><th>Tipo de tarefa</th><th>Natureza</th><th class="n">Concluídas</th><th class="n">Pendentes</th><th class="n">Atrasadas</th></tr>')
    for t in m["top_tipos"]:
        atr = f'<span class="red">{_n(t["atrasado"])}</span>' if t["atrasado"] else "0"
        o.append(f"<tr><td>{_e(t['subtipo'])}</td><td>{_CAT_PILL.get(t['categoria'],'')}</td><td class='n'>{_n(t['volume'])}</td><td class='n'>{_n(t['pendente'])}</td><td class='n'>{atr}</td></tr>")
    o.append("</table></div>")

    o.append('<div class="verdict"><h3>Recomendações</h3>')
    o.append(_list(nar.get("recomendacoes", [])))
    o.append("</div>")
    o.append("<h3>Ressalvas metodológicas</h3>")
    o.append(_list(nar.get("ressalvas", [])))
    fonte = "análise assistida por IA (Sonnet)" if nar.get("_fonte") == "sonnet" else "geração determinística"
    o.append(f'<div class="foot"><span>DunaFlow · Minha Equipe — diagnóstico por {fonte}</span><span>Confidencial · MDR Advocacia</span></div>')
    o.append("</body></html>")
    return "".join(o)


def _narrative(system, instr, metrics, secoes, fallback) -> dict:
    api_key = settings.anthropic_api_key
    if not api_key:
        logger.info("Relatório Minha Equipe: ANTHROPIC_API_KEY ausente — fallback.")
        return fallback
    try:
        import anthropic

        model = getattr(settings, "prazos_iniciais_classifier_model", None) or "claude-sonnet-4-6"
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model, max_tokens=2500, temperature=0.2, system=system,
            messages=[{"role": "user", "content": instr + json.dumps(metrics, ensure_ascii=False, default=_json_default)}],
        )
        raw = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        data = _parse_json(raw)
        out = {k: (data.get(k) or fallback[k]) for k in secoes}
        out["_fonte"] = "sonnet"
        return out
    except Exception:
        logger.exception("Relatório Minha Equipe: Sonnet falhou — fallback.")
        return fallback


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


# ══════════════════════════════════════════════════════════════════════
# INDIVÍDUO
# ══════════════════════════════════════════════════════════════════════
_SYS_INDIV = (
    "Você é um analista de operações jurídicas redigindo uma avaliação individual de "
    "desempenho para a coordenação de um escritório de advocacia. Registro formal, "
    "impessoal e objetivo, em português do Brasil. PROIBIDO: coloquialismos, primeira "
    "pessoa, emojis e afirmações não sustentadas pelos dados. Use exclusivamente as "
    "métricas do JSON. Distinga trabalho operacional de trabalho profundo. As "
    "intervenções devem ser concretas, proporcionais aos dados e sem juízo de valor pessoal."
)
_INSTR_INDIV = (
    "Com base nas métricas da pessoa a seguir, redija a avaliação. Responda ESTRITAMENTE "
    "em JSON válido, sem texto fora do JSON, com as chaves exatas:\n"
    '  "sumario": parágrafo único (3-5 frases) com o panorama da pessoa;\n'
    '  "desempenho": parágrafo sobre produção, ritmo e cumprimento de prazo no período;\n'
    '  "carga_futura": parágrafo sobre as tarefas pendentes e vencidas;\n'
    '  "riscos": parágrafo sobre os principais focos de atraso;\n'
    '  "intervencoes": lista de 2 a 4 ações concretas sugeridas (frases imperativas formais), ou lista com um item indicando que não há intervenção imediata;\n'
    '  "ressalvas": lista de 2 a 3 limites metodológicos.\n'
    "Sem markdown nos valores. Métricas:\n"
)
_SEC_INDIV = ("sumario", "desempenho", "carga_futura", "riscos", "intervencoes", "ressalvas")


def _individual_fallback(d: dict) -> dict:
    p, k, r, f = d["pessoa"], d["passado"]["kpis"], d["passado"]["ritmo"], d["futuro"]
    pend_top = max(f["por_tipo"], key=lambda x: x["atrasado"]) if f["por_tipo"] else None
    sumario = (
        f"{_e(p['nome'])} ({_e(p['cargo'])}) concluiu {_n(k['concluido'])} tarefas no período de {d['periodo_dias']} "
        f"dias, com ritmo de {_n(k['throughput_dia'])} por dia ativo e cumprimento de prazo de {_n(k['no_prazo_pct'])}%. "
        f"Mantém {_n(f['pendente'])} tarefas em aberto, das quais {_n(f['atrasado'])} estão vencidas."
    )
    desempenho = f"O tempo mediano de ciclo é de {_n(k['cycle_dias'])} dias. "
    if r.get("oper_share") is not None:
        desempenho += (
            f"A fatia operacional do trabalho é de {_n(r['oper_share'])}%, "
            + ("o que torna confiáveis os indicadores de cadência e ócio."
               if r["oper_share"] >= 50 else
               "de modo que cadência e ócio devem ser lidos com cautela, predominando trabalho de maior complexidade.")
        )
    carga = (
        f"A carga futura é de {_n(f['pendente'])} tarefas pendentes"
        + (f", sendo {_n(f['atrasado'])} já vencidas." if f["atrasado"] else ", sem tarefas vencidas no momento.")
    )
    if pend_top and pend_top["atrasado"]:
        riscos = f"O maior foco de atraso é {_e(pend_top['subtipo'])}, com {_n(pend_top['atrasado'])} tarefas vencidas."
    elif f["atrasado"] == 0:
        riscos = "Não há tarefas vencidas no momento; o risco de prazo é baixo."
    else:
        riscos = "O atraso distribui-se entre os tipos pendentes sem concentração relevante."
    interv = []
    if f["atrasado"] > 0:
        interv.append("Estabelecer plano de regularização das tarefas vencidas, com prazo definido e acompanhamento.")
    if r.get("oper_share", 100) >= 50 and r.get("ocio_pct") is not None and r["ocio_pct"] >= 50:
        interv.append("Avaliar a ocupação ao longo da jornada, dada a folga indicada pelo índice de ócio.")
    if k.get("no_prazo_pct") is not None and k["no_prazo_pct"] < 50:
        interv.append("Reforçar o cumprimento de prazo, atualmente abaixo de 50% das tarefas com prazo definido.")
    if not interv:
        interv.append("Manter o acompanhamento regular; os indicadores não evidenciam intervenção imediata.")
    ressalvas = [
        "Cadência e ócio só são confiáveis quando a fatia operacional é alta.",
        "As métricas refletem o período selecionado e o estado atual da base.",
        "A atribuição depende do registro correto de autoria no Legal One.",
    ]
    return {
        "sumario": sumario, "desempenho": desempenho, "carga_futura": carga, "riscos": riscos,
        "intervencoes": interv, "ressalvas": ressalvas, "_fonte": "fallback",
    }


def _render_indiv(d: dict, nar: dict) -> str:
    p, k, r, f = d["pessoa"], d["passado"]["kpis"], d["passado"]["ritmo"], d["futuro"]
    o = ['<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">',
         "<title>Raio-X — Minha Equipe</title>", _STYLE, "</head><body>"]
    o.append(
        '<div class="head"><div><div class="tag">Avaliação individual · uso interno</div>'
        f'<h1>{_e(p["nome"])}</h1>'
        f'<div class="sub">{_e(p["cargo"])}{(" · Squad " + _e(p["squad"])) if p.get("squad") else ""}</div></div>'
        '<div style="text-align:right"><div class="logo">Duna<span>Flow</span></div>'
        f'<div class="meta">MDR Advocacia · BB Réu</div><div class="meta">Período: últimos {d["periodo_dias"]} dias</div></div></div>'
    )
    o.append("<h2>Sumário</h2>")
    o.append(f"<p>{_e(nar.get('sumario',''))}</p>")

    o.append("<h2>Passado — desempenho</h2>")
    o.append('<div class="kpis k5">')
    o.append(_kpi("Concluídas", _n(k["concluido"])))
    o.append(_kpi("Ritmo/dia", _n(k["throughput_dia"])))
    o.append(_kpi("No prazo", _n(k["no_prazo_pct"], "%")))
    o.append(_kpi("Cycle time", _n(k["cycle_dias"], " d")))
    o.append(_kpi("Dias ativos", _n(k["dias_ativos"])))
    o.append("</div>")
    o.append('<div class="kpis k3">')
    o.append(_kpi("Cadência", _n(r.get("cadencia_seg"), " s"), "tempo por tarefa"))
    o.append(_kpi("Ócio", _n(r.get("ocio_pct"), "%"), "da jornada"))
    o.append(_kpi("Fatia operacional", _n(r.get("oper_share"), "%"), "confiabilidade do ritmo"))
    o.append("</div>")
    o.append(f"<p>{_e(nar.get('desempenho',''))}</p>")
    if d["passado"]["mix"]:
        o.append('<div class="avoid"><h3>Composição das concluídas</h3>')
        o.append("<table><tr><th>Tipo de tarefa</th><th>Natureza</th><th class='n'>Volume</th><th class='n'>Cycle</th><th class='n'>No prazo</th></tr>")
        for m in d["passado"]["mix"][:10]:
            o.append(f"<tr><td>{_e(m['subtipo'])}</td><td>{_CAT_PILL.get(m['categoria'],'')}</td><td class='n'>{_n(m['volume'])}</td><td class='n'>{_n(m['cycle_dias'],' d')}</td><td class='n'>{_n(m['no_prazo_pct'],'%')}</td></tr>")
        o.append("</table></div>")

    o.append("<h2>Futuro — carga aberta</h2>")
    o.append('<div class="kpis k3">')
    o.append(_kpi("Pendentes", _n(f["pendente"]), "pool aberto"))
    o.append(_kpi("Atrasadas", _n(f["atrasado"]), "vencidas"))
    o.append(_kpi("Sem prazo", _n(f["sem_prazo"]), "sem data"))
    o.append("</div>")
    o.append(f"<p>{_e(nar.get('carga_futura',''))}</p>")
    o.append(f"<p>{_e(nar.get('riscos',''))}</p>")
    if f["por_tipo"]:
        o.append('<div class="avoid"><h3>Pendentes por tipo</h3>')
        o.append("<table><tr><th>Tipo de tarefa</th><th>Natureza</th><th class='n'>Pendentes</th><th class='n'>Atrasadas</th></tr>")
        for t in f["por_tipo"][:10]:
            atr = f'<span class="red">{_n(t["atrasado"])}</span>' if t["atrasado"] else "0"
            o.append(f"<tr><td>{_e(t['subtipo'])}</td><td>{_CAT_PILL.get(t['categoria'],'')}</td><td class='n'>{_n(t['total'])}</td><td class='n'>{atr}</td></tr>")
        o.append("</table></div>")
    if f["urgentes"]:
        o.append('<div class="avoid"><h3>Próximos prazos</h3>')
        o.append("<table><tr><th>Tipo de tarefa</th><th>Prazo</th><th>Situação</th></tr>")
        for u in f["urgentes"][:12]:
            if u["dias"] is None:
                sit = "sem prazo"
            elif u["dias"] < 0:
                sit = f'<span class="red">atrasada há {abs(u["dias"])}d</span>'
            elif u["dias"] == 0:
                sit = '<span class="red">vence hoje</span>'
            else:
                sit = f'<span class="amber">vence em {u["dias"]}d</span>'
            o.append(f"<tr><td>{_e(u['subtipo'])}</td><td>{_e(u['prazo'])}</td><td>{sit}</td></tr>")
        o.append("</table></div>")

    o.append('<div class="verdict"><h3>Intervenções sugeridas</h3>')
    o.append(_list(nar.get("intervencoes", [])))
    o.append("</div>")
    o.append("<h3>Ressalvas</h3>")
    o.append(_list(nar.get("ressalvas", [])))
    fonte = "análise assistida por IA (Sonnet)" if nar.get("_fonte") == "sonnet" else "geração determinística"
    o.append(f'<div class="foot"><span>DunaFlow · Raio-X individual por {fonte}</span><span>Confidencial · MDR Advocacia</span></div>')
    o.append("</body></html>")
    return "".join(o)


# ══════════════════════════════════════════════════════════════════════
# API pública
# ══════════════════════════════════════════════════════════════════════
def build_sector_pdf(db, days: int = 30) -> bytes:
    m = _sector_metrics(db, days)
    nar = _narrative(_SYS_SETOR, _INSTR_SETOR, m, _SEC_SETOR, _sector_fallback(m))
    return html_to_pdf(_render_setor(m, nar))


def build_individual_pdf(db, pessoa_id: int, days: int = 30) -> bytes | None:
    d = PerformanceService(db).pessoa_detalhe(pessoa_id, days=days)
    if d is None:
        return None
    nar = _narrative(_SYS_INDIV, _INSTR_INDIV, d, _SEC_INDIV, _individual_fallback(d))
    return html_to_pdf(_render_indiv(d, nar))

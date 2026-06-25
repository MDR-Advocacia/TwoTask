"""Renderiza o relatório de performance em HTML pronto para impressão A4.

Estrutura fixa de 6 páginas: 2 de resumo executivo + 4 de detalhamento.
O HTML é autossuficiente (CSS inline, sem JS) e vira PDF via Chromium.
"""

from __future__ import annotations

import html
from datetime import date


def _e(s) -> str:
    return html.escape("" if s is None else str(s))


def _n(v, suf="", dash="—"):
    if v is None:
        return dash
    try:
        f = float(v)
        s = f"{int(round(f)):,}".replace(",", ".") if f == int(f) else f"{f:.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return _e(v)
    return f"{s}{suf}"


def _br_date(iso: str) -> str:
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return _e(iso)


_STYLE = """
<style>
  :root{--ink:#1c1c1a;--muted:#5f5e5a;--hint:#888780;--line:#d3d1c7;--blue:#378ADD;--blue-d:#0c447c;--teal:#1d9e75;--gray:#b4b2a9;--graybg:#f1efe8;--amber:#ba7517;}
  *{box-sizing:border-box;} html,body{margin:0;padding:0;}
  body{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);font-size:12.5px;line-height:1.55;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact;}
  .page{width:210mm;height:297mm;padding:17mm 16mm 14mm;margin:0 auto;position:relative;overflow:hidden;}
  .brk{page-break-after:always;}
  @page{size:A4;margin:0;}
  h1{font-size:24px;font-weight:600;margin:0 0 2px;letter-spacing:-.4px;}
  h2{font-size:16px;font-weight:600;margin:18px 0 7px;padding-bottom:5px;border-bottom:2px solid var(--ink);}
  h3{font-size:13px;font-weight:600;margin:13px 0 4px;}
  p{margin:0 0 8px;} .sub{color:var(--muted);font-size:12px;} .meta{color:var(--hint);font-size:10.5px;}
  .tag{display:inline-block;font-size:9.5px;font-weight:600;letter-spacing:.4px;text-transform:uppercase;padding:2px 7px;border-radius:4px;background:var(--graybg);color:var(--muted);}
  .head{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:10px;margin-bottom:4px;}
  .logo{font-size:15px;font-weight:700;letter-spacing:-.3px;} .logo span{color:var(--blue);}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:12px 0;}
  .kpi{background:var(--graybg);border-radius:7px;padding:9px 10px;}
  .kpi .l{font-size:10px;color:var(--muted);} .kpi .v{font-size:18px;font-weight:600;line-height:1.15;margin-top:2px;} .kpi .h{font-size:9.5px;color:var(--hint);margin-top:1px;}
  table{width:100%;border-collapse:collapse;margin:8px 0 10px;font-size:11.5px;}
  th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1.5px solid var(--ink);padding:5px 7px;font-size:10px;text-transform:uppercase;letter-spacing:.3px;}
  td{padding:5px 7px;border-bottom:1px solid var(--line);} td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;}
  tr.tot td{font-weight:600;border-top:1.5px solid var(--ink);border-bottom:none;}
  .note{background:var(--graybg);border-left:3px solid var(--blue);border-radius:0 6px 6px 0;padding:9px 11px;margin:10px 0;font-size:11.5px;}
  .barrow{display:grid;grid-template-columns:155px 1fr 52px;gap:9px;align-items:center;margin:4px 0;font-size:11px;}
  .barrow .val{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);}
  .bar{position:relative;height:15px;background:var(--graybg);border-radius:4px;overflow:hidden;}
  .bar>i{position:absolute;left:0;top:0;bottom:0;border-radius:4px;}
  .stack{display:flex;height:15px;border-radius:4px;overflow:hidden;}
  .legend{display:flex;gap:14px;font-size:10px;color:var(--muted);margin:2px 0 6px;}
  .legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:middle;}
  ul{margin:5px 0 10px;padding-left:17px;} li{margin:3px 0;}
  .verdict{border:2px solid var(--ink);border-radius:9px;padding:11px 13px;margin:11px 0;}
  .verdict h3{margin-top:0;}
  .foot{position:absolute;bottom:8mm;left:16mm;right:16mm;display:flex;justify-content:space-between;font-size:9px;color:var(--hint);border-top:1px solid var(--line);padding-top:5px;}
</style>
"""


def _foot(pag: int) -> str:
    return (
        '<div class="foot"><span>DunaFlow · Relatório Crítico de Performance — Publicações</span>'
        '<span>Confidencial — MDR Advocacia</span>'
        f'<span>Pág. {pag} de 6</span></div>'
    )


def _kpi(label, value, hint) -> str:
    return f'<div class="kpi"><div class="l">{_e(label)}</div><div class="v">{value}</div><div class="h">{_e(hint)}</div></div>'


def _paras(text: str) -> str:
    return f"<p>{_e(text)}</p>"


def _list(items) -> str:
    return "<ul>" + "".join(f"<li>{_e(i)}</li>" for i in (items or [])) + "</ul>"


def render_html(metrics: dict, narrative: dict, date_from: date, date_to: date) -> str:
    per = metrics["periodo"]
    f = metrics["funil"]
    t = metrics["totais"]
    d = metrics["demanda"]
    prod = metrics.get("producao", [])[:8]
    custo = metrics.get("custo_por_decisao", [])[:8]
    pools = [p for p in metrics.get("pools", []) if p["pool_dia"] >= 1][:8]
    ocio = metrics.get("ociosidade", [])[:8]
    hist = metrics.get("histograma", [])
    periodo_txt = f"{_br_date(per['de'])} a {_br_date(per['ate'])}"

    out = ['<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">',
           "<title>Relatório Crítico de Performance — Publicações</title>", _STYLE, "</head><body>"]

    # ─────────── PÁGINA 1 — RESUMO EXECUTIVO ───────────
    out.append('<section class="page">')
    out.append(
        '<div class="head"><div><div class="tag">Relatório executivo · uso interno</div>'
        '<h1>Relatório Crítico de Performance</h1>'
        '<div class="sub">Capacity da equipe de tratamento de Publicações</div></div>'
        '<div style="text-align:right"><div class="logo">Duna<span>Flow</span></div>'
        f'<div class="meta">MDR Advocacia</div><div class="meta">Período: {_e(periodo_txt)}</div></div></div>'
    )
    out.append(
        f'<div class="meta" style="margin:6px 0 10px">{per["dias_corridos"]} dias corridos · '
        f'~{per["dias_uteis"]} dias úteis · Fonte: base de produção do Flow · '
        'medições por timestamp real de cada decisão, em horário de Brasília.</div>'
    )
    out.append('<div class="kpis">')
    out.append(_kpi("Decisões no período", _n(t["total_decisoes"]), f'~{_n(t["decisoes_dia_util"])}/dia útil'))
    out.append(_kpi("IA descarta sozinha", f'{f["auto_descartado_pct"]}%', "antes do humano"))
    out.append(_kpi("Custo real/decisão", _n(t["custo_efetivo_s"], " s"), "cronometrado"))
    out.append(_kpi("Backlog atual", _n(d["backlog_atual"]), "estado corrente"))
    out.append("</div>")
    out.append("<h2>Sumário executivo</h2>")
    out.append(_paras(narrative.get("sumario_executivo", "")))
    out.append("<h2>Funil do período</h2>")
    out.append("<table><tr><th>Etapa</th><th class='n'>Volume</th><th class='n'>%</th></tr>")
    tc = f["total_capturado"] or 1
    out.append(f"<tr><td>Capturado do Legal One</td><td class='n'>{_n(f['total_capturado'])}</td><td class='n'>100%</td></tr>")
    out.append(f"<tr><td>IA descarta sozinha (duplicada + obsoleta)</td><td class='n'>{_n(f['auto_descartado'])}</td><td class='n'>{f['auto_descartado_pct']}%</td></tr>")
    out.append(f"<tr><td>Precisou de decisão humana</td><td class='n'>{_n(f['precisou_humano'])}</td><td class='n'>{round(100*f['precisou_humano']/tc)}%</td></tr>")
    out.append(f"<tr class='tot'><td>Backlog pendente (período)</td><td class='n'>{_n(f['backlog_pendente'])}</td><td class='n'>{round(100*f['backlog_pendente']/tc)}%</td></tr>")
    out.append("</table>")
    out.append('<div class="note">A classificação automática remove uma fração relevante do funil antes de qualquer '
               'intervenção humana — o operador trata apenas o que exige decisão.</div>')
    out.append(_foot(1))
    out.append("</section>")

    # ─────────── PÁGINA 2 — RESUMO EXECUTIVO (cont.) ───────────
    out.append('<section class="page brk">')
    out.append('<h2 style="margin-top:0">Diagnóstico de capacidade</h2>')
    out.append(_paras(narrative.get("diagnostico_capacidade", "")))
    out.append("<h2>Desigualdade de pools</h2>")
    out.append(_paras(narrative.get("desigualdade_pools", "")))
    out.append("<h2>Capacidade ociosa</h2>")
    out.append(_paras(narrative.get("capacidade_ociosa", "")))
    out.append('<div class="verdict"><h3>Recomendações</h3>')
    out.append(_list(narrative.get("recomendacoes", [])))
    out.append("</div>")
    out.append(_foot(2))
    out.append("</section>")

    # ─────────── PÁGINA 3 — DETALHE: FUNIL + CUSTO ───────────
    out.append('<section class="page brk">')
    out.append('<div class="tag">Detalhamento</div><h1 style="font-size:20px">A · Demanda, vazão e custo</h1>')
    out.append("<h2>A.1 Demanda × vazão</h2>")
    out.append('<div class="kpis" style="grid-template-columns:repeat(3,1fr)">')
    out.append(_kpi("Demanda humana", f'~{_n(d["demanda_dia"])}/dia', "publicações que exigem decisão"))
    out.append(_kpi("Vazão da equipe", f'~{_n(d["vazao_dia"])}/dia', "decisões tratadas"))
    out.append(_kpi("Trabalho ativo/dia", _n(t["trabalho_horas_dia"], " h"), "hands-on estimado"))
    out.append("</div>")
    out.append("<h2>A.2 Custo real por decisão (cronometrado)</h2>")
    out.append("<table><tr><th>Operador</th><th class='n'>Decisões</th><th class='n'>Mediana</th>"
               "<th class='n'>Agendar</th><th class='n'>Ignorar</th><th class='n'>% lote</th></tr>")
    for c in custo:
        out.append(
            f"<tr><td>{_e(c['nome'])}</td><td class='n'>{_n(c['decisoes'])}</td>"
            f"<td class='n'>{_n(c['mediana_s'],' s')}</td><td class='n'>{_n(c['med_agendar_s'],' s')}</td>"
            f"<td class='n'>{_n(c['med_ignorar_s'],' s')}</td><td class='n'>{_n(c['pct_lote'],'%')}</td></tr>"
        )
    out.append("</table>")
    out.append("<h3>Distribuição dos intervalos entre decisões</h3>")
    hmax = max((h["n"] for h in hist), default=1) or 1
    out.append('<div class="legend"><span><i style="background:var(--blue)"></i>Rápido (&lt; 1 min)</span>'
               '<span><i style="background:var(--gray)"></i>Mais lento / pausa</span></div>')
    for h in hist:
        col = "var(--blue)" if h["faixa"] in ("0-5s", "5-30s", "30-60s") else "var(--gray)"
        w = round(100 * h["n"] / hmax)
        out.append(f'<div class="barrow"><div>{_e(h["faixa"])}</div>'
                   f'<div class="bar"><i style="width:{w}%;background:{col}"></i></div>'
                   f'<div class="val">{_n(h["n"])}</div></div>')
    out.append(_foot(3))
    out.append("</section>")

    # ─────────── PÁGINA 4 — DETALHE: PRODUÇÃO + POOLS ───────────
    out.append('<section class="page brk">')
    out.append('<div class="tag">Detalhamento</div><h2 style="margin-top:6px">B · Produção individual</h2>')
    out.append("<table><tr><th>Operador</th><th class='n'>Agendou</th><th class='n'>Ignorou</th>"
               "<th class='n'>Total</th><th class='n'>Dias</th><th class='n'>Por dia</th></tr>")
    for r in prod:
        out.append(
            f"<tr><td>{_e(r['nome'])}</td><td class='n'>{_n(r['agendou'])}</td><td class='n'>{_n(r['ignorou'])}</td>"
            f"<td class='n'>{_n(r['total'])}</td><td class='n'>{_n(r['dias'])}</td><td class='n'>{_n(r['por_dia'])}</td></tr>"
        )
    out.append("</table>")
    out.append('<div class="note">O volume por dia reflete em grande parte o tamanho do pool atribuído, e não apenas a '
               'capacidade do operador. A leitura conjunta com o custo por decisão separa ritmo de carga.</div>')
    out.append("<h2>B.1 Pools por escritório</h2>")
    out.append('<div class="legend"><span><i style="background:var(--blue)"></i>Passivo (Réu)</span>'
               '<span><i style="background:var(--teal)"></i>Ativo (Autor)</span></div>')
    pmax = max((p["pool_dia"] for p in pools), default=1) or 1
    for p in pools:
        col = "var(--teal)" if p.get("polo") == "ativo" else "var(--blue)"
        w = round(100 * p["pool_dia"] / pmax)
        out.append(f'<div class="barrow"><div>{_e(p["escritorio"])}</div>'
                   f'<div class="bar"><i style="width:{w}%;background:{col}"></i></div>'
                   f'<div class="val">{_n(p["pool_dia"])}/dia</div></div>')
    out.append(_foot(4))
    out.append("</section>")

    # ─────────── PÁGINA 5 — DETALHE: CAPACIDADE OCIOSA ───────────
    out.append('<section class="page brk">')
    out.append('<div class="tag">Detalhamento</div><h2 style="margin-top:6px">C · Capacidade ociosa</h2>')
    out.append("<table><tr><th>Operador</th><th class='n'>Janela</th><th class='n'>Hands-on</th>"
               "<th class='n'>Utilização</th><th class='n'>Termina</th><th class='n'>Dias</th></tr>")
    for o in ocio:
        out.append(
            f"<tr><td>{_e(o['nome'])}</td><td class='n'>{_n(o['janela_h'],' h')}</td>"
            f"<td class='n'>{_n(o['handson_h'],' h')}</td><td class='n'>{_n(o['util_pct'],'%')}</td>"
            f"<td class='n'>{_e(o['fim_medio'])}</td><td class='n'>{_n(o['dias'])}</td></tr>"
        )
    out.append("</table>")
    out.append('<div class="legend"><span><i style="background:var(--blue)"></i>Trabalho real (hands-on)</span>'
               '<span><i style="background:var(--line)"></i>Capacidade ociosa (ref. ~7 h)</span></div>')
    for o in ocio:
        worked = min(float(o["handson_h"] or 0), 7.0)
        wp = round(100 * worked / 7.0)
        out.append(
            f'<div class="barrow"><div>{_e(o["nome"])} <span class="meta">· sai {_e(o["fim_medio"])}</span></div>'
            f'<div class="stack"><div style="width:{wp}%;background:var(--blue)"></div>'
            f'<div style="width:{100-wp}%;background:var(--line)"></div></div>'
            f'<div class="val">{_n(o["handson_h"],"h")}</div></div>'
        )
    out.append('<div class="note">Utilização e horário de término medem a capacidade efetivamente empregada. Término '
               'precoce e baixa utilização indicam esvaziamento antecipado do pool — capacidade disponível não consumida.</div>')
    out.append(_foot(5))
    out.append("</section>")

    # ─────────── PÁGINA 6 — RECOMENDAÇÕES + MÉTODO ───────────
    out.append('<section class="page">')
    out.append('<div class="tag">Detalhamento</div><h2 style="margin-top:6px">D · Recomendações e metodologia</h2>')
    out.append('<div class="verdict"><h3>Recomendações</h3>')
    out.append(_list(narrative.get("recomendacoes", [])))
    out.append("</div>")
    out.append("<h3>Ressalvas metodológicas</h3>")
    out.append(_list(narrative.get("ressalvas", [])))
    out.append("<h3>Como as métricas foram apuradas</h3>")
    out.append(
        "<ul>"
        "<li>Janela em horário de Brasília; o custo por decisão é o intervalo real entre tratamentos consecutivos "
        "(LAG sobre o timestamp), descartando cliques em lote (&lt; 5 s) e pausas (&gt; 10 min).</li>"
        "<li>O funil considera os registros capturados no período; o backlog corrente é o estado atual da base.</li>"
        "<li>Os pools por escritório derivam do filtro da busca (office_filter → escritório do Legal One).</li>"
        "<li>O tempo hands-on subestima o esforço real (não capta a leitura de casos complexos nem o tempo sem decisão registrada).</li>"
        "</ul>"
    )
    fonte = "análise assistida por IA (Sonnet)" if narrative.get("_fonte") == "sonnet" else "geração determinística"
    out.append(f'<div class="meta" style="margin-top:14px">Diagnóstico crítico produzido por {fonte}, '
               f'a partir de métricas determinísticas extraídas da base de produção. Geração sob demanda do supervisor.</div>')
    out.append(_foot(6))
    out.append("</section>")

    out.append("</body></html>")
    return "".join(out)

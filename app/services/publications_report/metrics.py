"""Consultas de capacity do módulo de Publicações, parametrizadas por período.

Todas as janelas usam a DATA EM HORÁRIO DE BRASÍLIA (`America/Sao_Paulo`),
para que "o dia" bata com o expediente do operador. O custo por decisão é
medido pelo intervalo real entre tratamentos consecutivos (LAG sobre o
timestamp), descartando cliques em lote (gap < 5s) e pausas (gap > 10min).
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# Predicado de janela em BRT, reusado por coluna.
_W = "({col} AT TIME ZONE 'America/Sao_Paulo')::date BETWEEN :dfrom AND :dto"

_AUTO_DESCARTE = ("DESCARTADO_DUPLICADA", "DESCARTADO_OBSOLETA")
# Constantes (não input do usuário) — inline no SQL pra evitar bind de tupla.
_AUTO_SQL = "('DESCARTADO_DUPLICADA', 'DESCARTADO_OBSOLETA')"
_HIST_ORDER = ["0-5s", "5-30s", "30-60s", "1-2min", "2-5min", "5-10min", ">10min"]


def _business_days(d0: date, d1: date) -> int:
    n, d = 0, d0
    while d <= d1:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(n, 1)


def _rows(db: Session, sql: str, params: dict) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(text(sql), params)]


def _num(v, default=0):
    return default if v is None else v


def compute_metrics(db: Session, date_from: date, date_to: date) -> dict:
    """Compila todas as métricas de capacity para o período [date_from, date_to]."""
    p = {"dfrom": date_from, "dto": date_to}
    dias_uteis = _business_days(date_from, date_to)

    # ── 1) Funil (intake do período: capturado → auto-descarte → humano) ──
    funil = _rows(
        db,
        f"""
        SELECT
          count(*) AS total,
          count(*) FILTER (WHERE status IN {_AUTO_SQL}) AS auto,
          count(*) FILTER (WHERE status NOT IN {_AUTO_SQL}) AS humano,
          count(*) FILTER (WHERE status = 'CLASSIFICADO') AS backlog
        FROM publicacao_registros
        WHERE {_W.format(col='created_at')}
        """,
        p,
    )[0]
    total_cap = _num(funil["total"])
    auto = _num(funil["auto"])
    humano = _num(funil["humano"])
    funil_out = {
        "total_capturado": total_cap,
        "auto_descartado": auto,
        "auto_descartado_pct": round(100.0 * auto / total_cap) if total_cap else 0,
        "precisou_humano": humano,
        "backlog_pendente": _num(funil["backlog"]),
    }

    # ── 2) Totais agendar/ignorar no período ──
    tot = _rows(
        db,
        f"""
        SELECT
          count(*) FILTER (WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}) AS agendadas,
          count(*) FILTER (WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}) AS ignoradas
        FROM publicacao_registros
        WHERE {_W.format(col='scheduled_at')} OR {_W.format(col='ignored_at')}
        """,
        p,
    )[0]
    agendadas = _num(tot["agendadas"])
    ignoradas = _num(tot["ignoradas"])
    total_dec = agendadas + ignoradas

    # ── 3) Produção por operador ──
    producao = _rows(
        db,
        f"""
        WITH ev AS (
          SELECT scheduled_by_name AS nome, (scheduled_at AT TIME ZONE 'America/Sao_Paulo')::date AS dia, 1 AS ag, 0 AS ig
          FROM publicacao_registros WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}
          UNION ALL
          SELECT ignored_by_name, (ignored_at AT TIME ZONE 'America/Sao_Paulo')::date, 0, 1
          FROM publicacao_registros WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}
        )
        SELECT nome, sum(ag) AS agendou, sum(ig) AS ignorou, sum(ag)+sum(ig) AS total,
               count(DISTINCT dia) AS dias,
               round((sum(ag)+sum(ig))::numeric / NULLIF(count(DISTINCT dia),0), 0) AS por_dia
        FROM ev WHERE nome IS NOT NULL
        GROUP BY nome HAVING sum(ag)+sum(ig) >= 1 ORDER BY total DESC
        """,
        p,
    )

    # ── 4) Custo real por decisão (gaps) ──
    custo = _rows(
        db,
        f"""
        WITH ev AS (
          SELECT scheduled_by_name AS nome, scheduled_at AS ts, 'agendar' AS tipo
          FROM publicacao_registros WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}
          UNION ALL
          SELECT ignored_by_name, ignored_at, 'ignorar'
          FROM publicacao_registros WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}
        ),
        g AS (
          SELECT nome, tipo,
            EXTRACT(EPOCH FROM (ts - lag(ts) OVER (PARTITION BY nome ORDER BY ts))) AS gap
          FROM ev WHERE nome IS NOT NULL
        )
        SELECT nome,
          count(*) FILTER (WHERE gap IS NOT NULL) AS decisoes,
          round(100.0*count(*) FILTER (WHERE gap>=0 AND gap<5)/NULLIF(count(*) FILTER (WHERE gap IS NOT NULL),0)) AS pct_lote,
          round(percentile_cont(0.5) WITHIN GROUP (ORDER BY gap) FILTER (WHERE gap>=5 AND gap<=600)) AS mediana_s,
          round(percentile_cont(0.5) WITHIN GROUP (ORDER BY gap) FILTER (WHERE tipo='agendar' AND gap>=5 AND gap<=600)) AS med_agendar_s,
          round(percentile_cont(0.5) WITHIN GROUP (ORDER BY gap) FILTER (WHERE tipo='ignorar' AND gap>=5 AND gap<=600)) AS med_ignorar_s,
          round(avg(gap) FILTER (WHERE gap>=0 AND gap<=600)) AS efetivo_s
        FROM g GROUP BY nome HAVING count(*) FILTER (WHERE gap IS NOT NULL) >= 30 ORDER BY decisoes DESC
        """,
        p,
    )
    # Custo efetivo ponderado team-wide.
    soma_dec = sum(_num(c["decisoes"]) for c in custo)
    custo_efetivo = (
        round(sum(_num(c["decisoes"]) * _num(c["efetivo_s"]) for c in custo) / soma_dec)
        if soma_dec else None
    )

    # ── 5) Histograma de intervalos ──
    hist_raw = {
        r["faixa"]: r["n"]
        for r in _rows(
            db,
            f"""
            WITH ev AS (
              SELECT scheduled_by_name AS nome, scheduled_at AS ts FROM publicacao_registros
              WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}
              UNION ALL
              SELECT ignored_by_name, ignored_at FROM publicacao_registros
              WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}
            ),
            g AS (SELECT EXTRACT(EPOCH FROM (ts - lag(ts) OVER (PARTITION BY nome ORDER BY ts))) AS gap
                  FROM ev WHERE nome IS NOT NULL)
            SELECT CASE WHEN gap<5 THEN '0-5s' WHEN gap<30 THEN '5-30s' WHEN gap<60 THEN '30-60s'
                        WHEN gap<120 THEN '1-2min' WHEN gap<300 THEN '2-5min' WHEN gap<600 THEN '5-10min'
                        ELSE '>10min' END AS faixa, count(*) AS n
            FROM g WHERE gap IS NOT NULL GROUP BY 1
            """,
            p,
        )
    }
    histograma = [{"faixa": f, "n": _num(hist_raw.get(f))} for f in _HIST_ORDER]

    # ── 6) Pools por escritório (office_filter da busca → external_id) ──
    pools_raw = _rows(
        db,
        f"""
        WITH ev AS (
          SELECT search_id AS sid FROM publicacao_registros
          WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}
          UNION ALL
          SELECT search_id FROM publicacao_registros
          WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}
        )
        SELECT coalesce(b.office_filter, '(sem filtro)') AS office_filter, count(*) AS pool
        FROM ev JOIN publicacao_buscas b ON b.id = ev.sid
        GROUP BY 1 ORDER BY pool DESC
        """,
        p,
    )
    oficios = {
        str(r["external_id"]): {"nome": r["nome"], "polo": r["polo_scope"]}
        for r in _rows(
            db,
            "SELECT external_id, coalesce(path, name) AS nome, polo_scope "
            "FROM legal_one_offices WHERE external_id IS NOT NULL",
            {},
        )
    }
    pools = []
    for r in pools_raw:
        of = (r["office_filter"] or "").strip()
        pool = _num(r["pool"])
        if "," in of:
            nome, polo = "Multi-escritório", "ativo"
        elif of in oficios:
            nome, polo = oficios[of]["nome"], oficios[of]["polo"]
        else:
            nome, polo = of or "(sem filtro)", None
        pools.append({
            "escritorio": nome, "polo": polo, "pool": pool,
            "pool_dia": round(pool / dias_uteis),
        })

    # ── 7) Capacidade ociosa por operador ──
    ociosidade = _rows(
        db,
        f"""
        WITH ev AS (
          SELECT scheduled_by_name AS nome, scheduled_at AS ts FROM publicacao_registros
          WHERE scheduled_at IS NOT NULL AND {_W.format(col='scheduled_at')}
          UNION ALL
          SELECT ignored_by_name, ignored_at FROM publicacao_registros
          WHERE ignored_at IS NOT NULL AND {_W.format(col='ignored_at')}
        ),
        g AS (
          SELECT nome, ts, (ts AT TIME ZONE 'America/Sao_Paulo')::date AS dia,
            EXTRACT(EPOCH FROM (ts - lag(ts) OVER (
              PARTITION BY nome, (ts AT TIME ZONE 'America/Sao_Paulo')::date ORDER BY ts))) AS gap
          FROM ev WHERE nome IS NOT NULL
        ),
        perday AS (
          SELECT nome, dia, count(*) AS dec,
            EXTRACT(EPOCH FROM (max(ts)-min(ts))) AS janela_s,
            coalesce(sum(gap) FILTER (WHERE gap>0 AND gap<=600), 0) AS ativo_s,
            (max(ts) AT TIME ZONE 'America/Sao_Paulo')::time AS fim_local
          FROM g GROUP BY nome, dia
        )
        SELECT nome, count(*) AS dias, round(avg(dec)) AS dec_dia,
          round(avg(janela_s)/3600.0, 1) AS janela_h,
          round(avg(ativo_s)/3600.0, 1) AS handson_h,
          round(100.0*sum(ativo_s)/NULLIF(sum(janela_s),0)) AS util_pct,
          to_char((avg(EXTRACT(EPOCH FROM fim_local))||' seconds')::interval, 'HH24:MI') AS fim_medio
        FROM perday WHERE dec >= 10 GROUP BY nome HAVING count(*) >= 3 ORDER BY dec_dia DESC
        """,
        p,
    )

    # ── 8) Backlog corrente (estado atual, não janela) ──
    backlog_atual = _num(
        _rows(db, "SELECT count(*) AS n FROM publicacao_registros WHERE status='CLASSIFICADO'", {})[0]["n"]
    )

    return {
        "periodo": {
            "de": date_from.isoformat(),
            "ate": date_to.isoformat(),
            "dias_corridos": (date_to - date_from).days + 1,
            "dias_uteis": dias_uteis,
        },
        "funil": funil_out,
        "totais": {
            "agendadas": agendadas,
            "ignoradas": ignoradas,
            "total_decisoes": total_dec,
            "mix_agendar_pct": round(100.0 * agendadas / total_dec) if total_dec else 0,
            "custo_efetivo_s": custo_efetivo,
            "decisoes_dia_util": round(total_dec / dias_uteis),
            "trabalho_horas_dia": (
                round((total_dec / dias_uteis) * custo_efetivo / 3600.0, 1)
                if custo_efetivo else None
            ),
        },
        "demanda": {
            "demanda_dia": round(humano / dias_uteis),
            "vazao_dia": round(total_dec / dias_uteis),
            "backlog_atual": backlog_atual,
        },
        "producao": producao,
        "custo_por_decisao": custo,
        "histograma": histograma,
        "pools": pools,
        "ociosidade": ociosidade,
    }

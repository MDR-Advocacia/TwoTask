"""Exporta varredura_andamento_raw + capa pra NDJSON consultavel.

Estrutura de cada linha (1 processo por linha):
    {
      "lawsuit_id": 11306,
      "cnj": "...",
      "office_id": 23,
      "run_id": 53,
      "run_started_at": "...",
      "window_days": 60,
      "qtd_andamentos": 12,
      "capa": {...},
      "andamentos": [
        {"data": "2026-05-06", "hora": "00:09",
         "tipo": "Andamento", "texto": "...",
         "movimentado_por": "...", "ordem": 0},
        ...
      ]
    }

Uso:
    docker exec onetask-api-1 python //app/app/runners/legalone/_export_andamento_raw.py \\
        --office-id 23 --triggered-by-prefix bb-temperatura-v2- \\
        --out /tmp/andamentos-bb-v2.jsonl

    docker cp onetask-api-1:/tmp/andamentos-bb-v2.jsonl ./

Filtros (todos opcionais):
    --office-id N
    --triggered-by-prefix STR (ex.: 'bb-temperatura-v2-', 'planilha-relatorios')
    --run-id N (1 run especifica)
    --since YYYY-MM-DD (andamentos a partir dessa data)
    --tipo-evento STR (filtra por andamento_tipo exato no banco)
    --out PATH (default /tmp/andamentos-export.jsonl)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
logger = logging.getLogger("varredura.export")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--office-id", type=int, default=None)
    parser.add_argument("--triggered-by-prefix", type=str, default=None)
    parser.add_argument("--run-id", type=int, default=None)
    parser.add_argument("--since", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--tipo-evento", type=str, default=None)
    parser.add_argument("--out", type=str, default="/tmp/andamentos-export.jsonl")
    args = parser.parse_args()

    from app.db.session import SessionLocal
    from app.models.varredura import (
        VarreduraAndamentoRaw,
        VarreduraProcessado,
        VarreduraRun,
    )
    from sqlalchemy import and_, or_

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        # 1) Quais runs incluir
        q_runs = db.query(VarreduraRun)
        if args.run_id:
            q_runs = q_runs.filter(VarreduraRun.id == args.run_id)
        if args.triggered_by_prefix:
            q_runs = q_runs.filter(
                VarreduraRun.triggered_by.like(f"{args.triggered_by_prefix}%")
            )
        runs = q_runs.order_by(VarreduraRun.id).all()
        run_ids = [r.id for r in runs]
        if not run_ids:
            logger.error("Nenhuma run bate com os filtros.")
            return
        logger.info("Runs incluidas: %s", len(run_ids))

        # 2) Processados (dedup por lawsuit_id; mais recente vence)
        q_proc = db.query(VarreduraProcessado).filter(
            VarreduraProcessado.run_id.in_(run_ids)
        )
        if args.office_id:
            q_proc = q_proc.filter(
                or_(
                    VarreduraProcessado.office_id == args.office_id,
                    VarreduraProcessado.office_id.is_(None),
                )
            )
        proc_por_lid: dict[int, "VarreduraProcessado"] = {}
        for p in q_proc:
            cur = proc_por_lid.get(p.lawsuit_id)
            if cur is None or (p.run_id or 0) > (cur.run_id or 0):
                proc_por_lid[p.lawsuit_id] = p
        logger.info("Processados unicos: %s", len(proc_por_lid))

        if not proc_por_lid:
            logger.error("Nenhum processo encontrado.")
            return

        # 3) Andamentos brutos
        q_ands = db.query(VarreduraAndamentoRaw).filter(
            VarreduraAndamentoRaw.run_id.in_(run_ids),
            VarreduraAndamentoRaw.lawsuit_id.in_(list(proc_por_lid.keys())),
        )
        if args.since:
            try:
                d = datetime.strptime(args.since, "%Y-%m-%d").date()
                q_ands = q_ands.filter(VarreduraAndamentoRaw.andamento_data >= d)
            except ValueError:
                logger.error("--since invalido (use YYYY-MM-DD)")
                return
        if args.tipo_evento:
            q_ands = q_ands.filter(
                VarreduraAndamentoRaw.andamento_tipo == args.tipo_evento
            )

        ands_por_lid: dict[int, list] = {}
        total = 0
        for a in q_ands.order_by(
            VarreduraAndamentoRaw.lawsuit_id,
            VarreduraAndamentoRaw.ordem,
        ):
            ands_por_lid.setdefault(a.lawsuit_id, []).append(a)
            total += 1
        logger.info("Andamentos brutos: %s", total)

        # 4) Mapa run_id -> metadados
        run_meta = {r.id: r for r in runs}

        # 5) Escreve NDJSON
        with out_path.open("w", encoding="utf-8") as f:
            written = 0
            for lid, p in sorted(proc_por_lid.items()):
                ands = ands_por_lid.get(lid, [])
                if args.since or args.tipo_evento:
                    if not ands:
                        continue  # filtro afastou todos
                r = run_meta.get(p.run_id)
                doc = {
                    "lawsuit_id": lid,
                    "cnj": p.cnj_number,
                    "office_id": p.office_id,
                    "run_id": p.run_id,
                    "run_started_at": r.started_at.isoformat() if r and r.started_at else None,
                    "window_days": r.window_days if r else None,
                    "triggered_by": r.triggered_by if r else None,
                    "qtd_andamentos": len(ands),
                    "capa": p.capa_json,
                    "andamentos": [
                        {
                            "data": a.andamento_data.isoformat() if a.andamento_data else None,
                            "hora": a.andamento_hora,
                            "tipo": a.andamento_tipo,
                            "texto": a.andamento_texto,
                            "movimentado_por": a.andamento_movimentado_por,
                            "ordem": a.ordem,
                        }
                        for a in ands
                    ],
                }
                f.write(json.dumps(doc, ensure_ascii=False, default=str))
                f.write("\n")
                written += 1
        logger.info("NDJSON gerado: %s linhas em %s", written, out_path)
        logger.info("Tamanho: %s bytes", out_path.stat().st_size)
    finally:
        db.close()


if __name__ == "__main__":
    main()

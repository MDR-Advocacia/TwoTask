"""Orquestra a varredura de andamentos.

Fluxo:
  1. Operador POSTa /api/v1/varredura/runs com responsible_office_ids.
  2. Service resolve lawsuit_ids via OfficeLawsuitIndexService + cache da
     API L1. Une os ids dos varios offices.
  3. Cria 1 VarreduraProcessado PENDENTE pra cada lawsuit.
  4. Dispara subprocess Node em thread daemon — runner abre browser,
     loga no OnePass, navega DetailsAndamentos de cada processo, raspa
     andamentos dos ultimos N dias, escreve status.json incrementalmente.
  5. Thread polla status.json a cada 5s e sincroniza banco. Quando o
     subprocess termina, sincronizacao final + marca run DONE/FAILED.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.legal_one import LegalOneOffice
from app.models.varredura import (
    ALL_TIPOS_EVENTO,
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_FAILED,
    QUEUE_STATUS_PENDING,
    QUEUE_STATUS_PROCESSING,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_DONE,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    VarreduraAchado,
    VarreduraProcessado,
    VarreduraRun,
)
from app.services.legal_one_client import LegalOneApiClient
from app.services.office_lawsuit_index_service import OfficeLawsuitIndexService
from app.services.prazos_iniciais.legacy_task_helpers import (
    resolve_node_binary,
    resolve_project_root,
    resolve_web_credentials,
)
from app.services.varredura.regex_eventos import detect_eventos

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _output_root() -> Path:
    return (
        resolve_project_root()
        / "output"
        / "playwright"
        / "legalone"
        / "varredura-andamentos"
    )


def _runner_script() -> Path:
    return (
        resolve_project_root()
        / "app"
        / "runners"
        / "legalone"
        / "varredura-andamentos.js"
    )


def _run_dir(run_id: int) -> Path:
    return _output_root() / f"run-{run_id}"


# ── Parse de data PT-BR ────────────────────────────────────────────────


_DATE_PT_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _parse_pt_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    m = _DATE_PT_RE.search(s)
    if not m:
        return None
    try:
        d, mo, y = map(int, m.groups())
        return date(y, mo, d)
    except ValueError:
        return None


# ── Service ───────────────────────────────────────────────────────────


class VarreduraService:
    def __init__(self, db: Session):
        self.db = db

    # ── Resolucao de lawsuit_ids ──────────────────────────────────────

    def _fetch_office_ids_paginated(
        self,
        client: LegalOneApiClient,
        office_id: int,
        *,
        max_ids: Optional[int] = None,
    ) -> set[int]:
        """Busca todos os lawsuit_ids de um office via API L1, paginando
        manualmente com $top=30 + $skip. Mesmo padrao do
        OfficeLawsuitIndexService._do_full_sync, mas sem persistir indice.
        """
        from urllib.parse import quote

        ids: set[int] = set()
        page_size = 30  # cap da API L1
        skip = 0
        while True:
            params = {
                "$filter": f"responsibleOfficeId eq {int(office_id)}",
                "$select": "id",
                "$top": page_size,
                "$skip": skip,
            }
            for endpoint in ("/Lawsuits", "/Litigations"):
                qs = "&".join(
                    f"{k}={quote(str(v), safe='')}" for k, v in params.items()
                )
                url = f"{client.base_url}{endpoint}?{qs}"
                try:
                    resp = client._request_with_retry("GET", url)
                    data = resp.json()
                    items = data.get("value", []) or []
                    for it in items:
                        lid = it.get("id")
                        if lid is None:
                            continue
                        try:
                            ids.add(int(lid))
                        except (TypeError, ValueError):
                            continue
                    if max_ids is not None and len(ids) >= max_ids:
                        return set(list(ids)[:max_ids])
                    if len(items) < page_size:
                        return ids
                    skip += page_size
                    break  # next page, mesmo endpoint
                except Exception as exc:
                    logger.warning(
                        "varredura.resolve.api_page_failed office=%s endpoint=%s skip=%s err=%s",
                        office_id, endpoint, skip, exc,
                    )
                    continue
            else:
                # Os dois endpoints falharam pra essa pagina — para.
                return ids

    def _resolve_lawsuit_ids(
        self,
        office_ids: list[int],
        *,
        max_total: Optional[int] = None,
    ) -> tuple[list[int], dict[int, int]]:
        """
        Retorna (lista_unica_de_lawsuit_ids, mapa_lawsuit_to_office).
        Estrategia:
          1. Pra cada office, tenta o indice local primeiro.
          2. Se vazio, faz fetch paginado direto da API L1.
          3. Best-effort: dispara ensure_sync em background pra
             popular indice pra proxima vez.
        max_total: limite global do total de IDs (pra varreduras incidentais
        nao estourarem com 8000 processos).
        """
        all_ids: set[int] = set()
        lawsuit_to_office: dict[int, int] = {}

        index_svc = OfficeLawsuitIndexService(self.db)
        client: Optional[LegalOneApiClient] = None

        for off_id in office_ids:
            if max_total is not None and len(all_ids) >= max_total:
                break
            from_index = index_svc.get_lawsuit_ids(off_id)
            if from_index:
                for lid in from_index:
                    if max_total is not None and len(all_ids) >= max_total:
                        break
                    all_ids.add(lid)
                    lawsuit_to_office.setdefault(lid, off_id)
                logger.info(
                    "varredura.resolve.from_index office=%s ids=%s",
                    off_id, len(from_index),
                )
                continue

            if client is None:
                try:
                    client = LegalOneApiClient()
                except Exception as exc:
                    logger.warning(
                        "varredura.resolve.client_init_failed err=%s", exc,
                    )
                    continue
            remaining = (
                None
                if max_total is None
                else max(0, max_total - len(all_ids))
            )
            try:
                from_api = self._fetch_office_ids_paginated(
                    client, off_id, max_ids=remaining,
                )
            except Exception as exc:
                logger.warning(
                    "varredura.resolve.api_fetch_failed office=%s err=%s",
                    off_id, exc,
                )
                continue
            for lid in from_api:
                if max_total is not None and len(all_ids) >= max_total:
                    break
                all_ids.add(lid)
                lawsuit_to_office.setdefault(lid, off_id)
            logger.info(
                "varredura.resolve.from_api office=%s ids=%s",
                off_id, len(from_api),
            )
            try:
                index_svc.ensure_sync(off_id, force_full=False)
            except Exception:
                pass

        return sorted(all_ids), lawsuit_to_office

    # ── Criar nova run ────────────────────────────────────────────────

    def create_run_from_list(
        self,
        *,
        identifiers: list[str],
        window_days: int = 30,
        triggered_by: Optional[str] = None,
    ) -> tuple[VarreduraRun, list[str]]:
        """
        Cria varredura a partir de uma lista mista de CNJs e/ou lawsuit_ids.
        Retorna (run, unresolved_identifiers).

        Detecta o formato: tem digito/digito/digito ou hifen/ponto = CNJ;
        somente inteiros = lawsuit_id.
        """
        window_days = max(1, min(365, int(window_days)))

        # Normaliza e classifica
        cnjs_raw: list[str] = []
        lawsuit_ids: set[int] = set()
        for raw in identifiers:
            if not raw:
                continue
            s = str(raw).strip()
            if not s:
                continue
            # Tem digitos + qualquer separador pt-BR de CNJ?
            digits = "".join(ch for ch in s if ch.isdigit())
            if len(digits) >= 15:  # CNJ tem 20 digitos
                cnjs_raw.append(digits)
            else:
                try:
                    lawsuit_ids.add(int(digits))
                except ValueError:
                    pass

        # Resolve CNJs -> lawsuit_id via API L1
        cnj_to_id: dict[str, int] = {}
        cnj_unresolved: list[str] = []
        if cnjs_raw:
            try:
                client = LegalOneApiClient()
                matches = client.search_lawsuits_by_cnj_numbers(cnjs_raw)
                # `matches` chaveado pelo cnj normalizado do client (pode
                # incluir ou nao formatacao); pegamos id de cada payload.
                # Tambem mapeia em normalizado pra montar lookup.
                for cnj_norm in cnjs_raw:
                    payload = None
                    for k, v in matches.items():
                        if "".join(ch for ch in str(k) if ch.isdigit()) == cnj_norm:
                            payload = v
                            break
                    if payload is None:
                        cnj_unresolved.append(cnj_norm)
                        continue
                    pid = payload.get("id")
                    if pid is None:
                        cnj_unresolved.append(cnj_norm)
                        continue
                    cnj_to_id[cnj_norm] = int(pid)
                    lawsuit_ids.add(int(pid))
            except Exception as exc:
                logger.warning("varredura.from_list.cnj_lookup_failed err=%s", exc)
                cnj_unresolved.extend(cnjs_raw)

        if not lawsuit_ids:
            raise ValueError(
                "Nenhum CNJ/lawsuit_id valido na lista (todos invalidos "
                "ou nao encontrados no L1)."
            )

        # Cria run
        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=_utcnow(),
            responsible_office_ids=[],
            window_days=window_days,
            triggered_by=triggered_by,
            total_processos=len(lawsuit_ids),
        )
        self.db.add(run)
        self.db.flush()

        # Resolve CNJ map dos lawsuit_ids
        cnjs_for_ids = self._fetch_cnj_map(list(lawsuit_ids))
        # Sobrescreve com o que veio direto da resolucao por CNJ
        id_to_cnj_resolved: dict[int, str] = {v: k for k, v in cnj_to_id.items()}
        cnjs_for_ids.update(id_to_cnj_resolved)

        processados = []
        for lid in sorted(lawsuit_ids):
            processados.append(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=lid,
                    cnj_number=cnjs_for_ids.get(lid),
                    office_id=None,
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        self.db.bulk_save_objects(processados)
        self.db.commit()
        self.db.refresh(run)

        logger.info(
            "varredura.run.from_list.created id=%s total=%s unresolved=%s",
            run.id, run.total_processos, len(cnj_unresolved),
        )

        threading.Thread(
            target=_run_subprocess_worker,
            args=(run.id,),
            daemon=True,
            name=f"varredura-run-{run.id}",
        ).start()

        return run, cnj_unresolved

    def create_run(
        self,
        *,
        responsible_office_ids: list[int],
        window_days: int = 30,
        triggered_by: Optional[str] = None,
        max_processos: Optional[int] = None,
    ) -> VarreduraRun:
        if not responsible_office_ids:
            raise ValueError("responsible_office_ids vazio.")
        window_days = max(1, min(365, int(window_days)))
        if max_processos is not None:
            max_processos = max(1, min(5000, int(max_processos)))

        run = VarreduraRun(
            status=RUN_STATUS_RUNNING,
            started_at=_utcnow(),
            responsible_office_ids=list(responsible_office_ids),
            window_days=window_days,
            triggered_by=triggered_by,
        )
        self.db.add(run)
        self.db.flush()  # pra ter o run.id

        lawsuit_ids, lawsuit_to_office = self._resolve_lawsuit_ids(
            responsible_office_ids,
            max_total=max_processos,
        )

        if not lawsuit_ids:
            run.status = RUN_STATUS_DONE
            run.completed_at = _utcnow()
            run.total_processos = 0
            run.error_message = (
                "Nenhum processo encontrado pros offices selecionados. "
                "Confira o indice local (OfficeLawsuitIndex) ou rode um "
                "sync antes."
            )
            self.db.commit()
            self.db.refresh(run)
            return run

        # Resolve cnj_number do cache local (lawsuit_cache) — best-effort.
        cnjs = self._fetch_cnj_map(lawsuit_ids)

        processados = []
        for lid in lawsuit_ids:
            processados.append(
                VarreduraProcessado(
                    run_id=run.id,
                    lawsuit_id=lid,
                    cnj_number=cnjs.get(lid),
                    office_id=lawsuit_to_office.get(lid),
                    queue_status=QUEUE_STATUS_PENDING,
                )
            )
        self.db.bulk_save_objects(processados)
        run.total_processos = len(lawsuit_ids)
        self.db.commit()
        self.db.refresh(run)

        logger.info(
            "varredura.run.created id=%s offices=%s lawsuits=%s window=%s",
            run.id, responsible_office_ids, len(lawsuit_ids), window_days,
        )

        # Dispara processamento em background.
        threading.Thread(
            target=_run_subprocess_worker,
            args=(run.id,),
            daemon=True,
            name=f"varredura-run-{run.id}",
        ).start()

        return run

    @staticmethod
    def _fetch_cnj_map(lawsuit_ids: list[int]) -> dict[int, str]:
        from app.models.lawsuit_cache import LawsuitCache

        db = SessionLocal()
        try:
            rows = (
                db.query(LawsuitCache)
                .filter(LawsuitCache.lawsuit_id.in_(lawsuit_ids))
                .all()
            )
            out: dict[int, str] = {}
            for r in rows:
                payload = r.payload or {}
                cnj = (
                    payload.get("identifierNumber")
                    or payload.get("cnjNumber")
                    or payload.get("cnj_number")
                )
                if cnj:
                    out[r.lawsuit_id] = str(cnj)
            return out
        finally:
            db.close()

    # ── Leitura ───────────────────────────────────────────────────────

    @staticmethod
    def _run_to_dict(run: VarreduraRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": (
                run.completed_at.isoformat() if run.completed_at else None
            ),
            "responsible_office_ids": list(run.responsible_office_ids or []),
            "window_days": run.window_days,
            "total_processos": run.total_processos,
            "total_processados": run.total_processados,
            "total_achados": run.total_achados,
            "total_falhas": run.total_falhas,
            "triggered_by": run.triggered_by,
            "error_message": run.error_message,
        }

    @staticmethod
    def _processado_to_dict(p: VarreduraProcessado) -> dict[str, Any]:
        return {
            "id": p.id,
            "run_id": p.run_id,
            "lawsuit_id": p.lawsuit_id,
            "cnj_number": p.cnj_number,
            "office_id": p.office_id,
            "queue_status": p.queue_status,
            "attempt_count": p.attempt_count,
            "last_attempt_at": (
                p.last_attempt_at.isoformat() if p.last_attempt_at else None
            ),
            "completed_at": (
                p.completed_at.isoformat() if p.completed_at else None
            ),
            "total_andamentos_lidos": p.total_andamentos_lidos,
            "total_achados": p.total_achados,
            "last_error": p.last_error,
            "last_reason": p.last_reason,
        }

    @staticmethod
    def _achado_to_dict(a: VarreduraAchado) -> dict[str, Any]:
        return {
            "id": a.id,
            "run_id": a.run_id,
            "processado_id": a.processado_id,
            "lawsuit_id": a.lawsuit_id,
            "cnj_number": a.cnj_number,
            "andamento_data": (
                a.andamento_data.isoformat() if a.andamento_data else None
            ),
            "andamento_hora": a.andamento_hora,
            "andamento_tipo": a.andamento_tipo,
            "andamento_texto": a.andamento_texto,
            "andamento_movimentado_por": a.andamento_movimentado_por,
            "tipo_evento": a.tipo_evento,
            "regex_matched": a.regex_matched,
            "tratado": a.tratado,
            "tratado_em": a.tratado_em.isoformat() if a.tratado_em else None,
            "tratado_por": a.tratado_por,
            "observacao": a.observacao,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    def get_run(self, run_id: int) -> Optional[dict[str, Any]]:
        run = (
            self.db.query(VarreduraRun)
            .filter(VarreduraRun.id == run_id)
            .first()
        )
        if run is None:
            return None
        return self._run_to_dict(run)

    def list_runs(
        self,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = self.db.query(VarreduraRun)
        if status:
            q = q.filter(VarreduraRun.status == status)
        total = q.count()
        items = (
            q.order_by(VarreduraRun.id.desc())
            .limit(max(1, min(500, int(limit))))
            .offset(max(0, int(offset)))
            .all()
        )
        return {
            "total": int(total or 0),
            "items": [self._run_to_dict(r) for r in items],
        }

    def list_processados(
        self,
        *,
        run_id: int,
        queue_status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = self.db.query(VarreduraProcessado).filter(
            VarreduraProcessado.run_id == run_id
        )
        if queue_status:
            q = q.filter(VarreduraProcessado.queue_status == queue_status)
        total = q.count()
        items = (
            q.order_by(VarreduraProcessado.id.asc())
            .limit(max(1, min(500, int(limit))))
            .offset(max(0, int(offset)))
            .all()
        )
        return {
            "total": int(total or 0),
            "items": [self._processado_to_dict(p) for p in items],
        }

    def list_achados(
        self,
        *,
        run_id: Optional[int] = None,
        tipo_evento: Optional[str] = None,
        tratado: Optional[bool] = None,
        cnj_search: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = self.db.query(VarreduraAchado)
        if run_id is not None:
            q = q.filter(VarreduraAchado.run_id == run_id)
        if tipo_evento:
            if tipo_evento not in ALL_TIPOS_EVENTO:
                raise ValueError(f"tipo_evento invalido: {tipo_evento}")
            q = q.filter(VarreduraAchado.tipo_evento == tipo_evento)
        if tratado is not None:
            q = q.filter(VarreduraAchado.tratado == bool(tratado))
        if cnj_search:
            s = cnj_search.strip()
            if s:
                q = q.filter(VarreduraAchado.cnj_number.ilike(f"%{s}%"))
        total = q.count()
        items = (
            q.order_by(
                VarreduraAchado.andamento_data.desc().nullslast(),
                VarreduraAchado.id.desc(),
            )
            .limit(max(1, min(500, int(limit))))
            .offset(max(0, int(offset)))
            .all()
        )
        return {
            "total": int(total or 0),
            "items": [self._achado_to_dict(a) for a in items],
        }

    def update_achado(
        self,
        achado_id: int,
        *,
        tratado: bool,
        observacao: Optional[str] = None,
        tratado_por: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        a = (
            self.db.query(VarreduraAchado)
            .filter(VarreduraAchado.id == achado_id)
            .first()
        )
        if a is None:
            return None
        a.tratado = bool(tratado)
        a.tratado_em = _utcnow() if tratado else None
        a.tratado_por = tratado_por if tratado else None
        if observacao is not None:
            a.observacao = observacao.strip() or None
        self.db.commit()
        self.db.refresh(a)
        return self._achado_to_dict(a)

    def cancel_run(self, run_id: int) -> Optional[dict[str, Any]]:
        run = (
            self.db.query(VarreduraRun)
            .filter(VarreduraRun.id == run_id)
            .first()
        )
        if run is None:
            return None
        if run.status not in {RUN_STATUS_RUNNING}:
            return self._run_to_dict(run)
        run.status = RUN_STATUS_CANCELLED
        run.completed_at = _utcnow()
        # Marca pendentes como falha (cancelados pelo operador).
        (
            self.db.query(VarreduraProcessado)
            .filter(
                VarreduraProcessado.run_id == run_id,
                VarreduraProcessado.queue_status.in_(
                    [QUEUE_STATUS_PENDING, QUEUE_STATUS_PROCESSING]
                ),
            )
            .update(
                {
                    "queue_status": QUEUE_STATUS_FAILED,
                    "last_reason": "cancelled_by_operator",
                    "last_error": "Run cancelada pelo operador.",
                    "updated_at": _utcnow(),
                },
                synchronize_session=False,
            )
        )
        self.db.commit()
        self.db.refresh(run)
        return self._run_to_dict(run)

    def recover_zombies(
        self,
        *,
        threshold_minutes: int = 10,
    ) -> dict[str, Any]:
        threshold = max(1, int(threshold_minutes))
        cutoff = _utcnow() - timedelta(minutes=threshold)
        zombies = (
            self.db.query(VarreduraProcessado)
            .filter(
                VarreduraProcessado.queue_status == QUEUE_STATUS_PROCESSING,
                (VarreduraProcessado.last_attempt_at < cutoff)
                | (VarreduraProcessado.last_attempt_at.is_(None)),
            )
            .all()
        )
        recovered = 0
        for z in zombies:
            z.queue_status = QUEUE_STATUS_PENDING
            z.last_reason = "zombie_recovered"
            z.last_error = (
                f"PROCESSANDO sem update > {threshold}min. "
                "Marcado como PENDENTE — nova run nao re-processa "
                "automaticamente; use a UI."
            )
            z.updated_at = _utcnow()
            recovered += 1
        if recovered:
            self.db.commit()
        return {
            "recovered_count": recovered,
            "threshold_minutes": threshold,
        }


# ── Worker em thread daemon — roda o subprocess Node ──────────────────


_POLL_INTERVAL_SECONDS = 5.0
_SUBPROCESS_TIMEOUT_HOURS = 4  # safety cap


def _run_subprocess_worker(run_id: int) -> None:
    """Roda numa thread daemon. Sessao SQLAlchemy propria."""
    db = SessionLocal()
    try:
        _run_subprocess_worker_impl(db, run_id)
    except Exception as exc:
        logger.exception(
            "varredura.worker.unexpected_error run=%s err=%s", run_id, exc,
        )
        try:
            run = (
                db.query(VarreduraRun)
                .filter(VarreduraRun.id == run_id)
                .first()
            )
            if run is not None and run.status == RUN_STATUS_RUNNING:
                run.status = RUN_STATUS_FAILED
                run.completed_at = _utcnow()
                run.error_message = f"Worker crashou: {exc}"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _run_subprocess_worker_impl(db: Session, run_id: int) -> None:
    run = db.query(VarreduraRun).filter(VarreduraRun.id == run_id).first()
    if run is None:
        logger.error("varredura.worker.run_not_found id=%s", run_id)
        return
    if run.status != RUN_STATUS_RUNNING:
        logger.info(
            "varredura.worker.skip status=%s id=%s", run.status, run_id,
        )
        return

    # Items pendentes pra essa run.
    items = (
        db.query(VarreduraProcessado)
        .filter(
            VarreduraProcessado.run_id == run_id,
            VarreduraProcessado.queue_status == QUEUE_STATUS_PENDING,
        )
        .all()
    )
    if not items:
        run.status = RUN_STATUS_DONE
        run.completed_at = _utcnow()
        db.commit()
        return

    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.json"
    output_path = run_dir / "status.json"
    log_path = run_dir / "runner.log"
    err_path = run_dir / "runner.err.log"

    # Marca items como PROCESSANDO em bloco.
    now = _utcnow()
    item_ids = [it.id for it in items]
    (
        db.query(VarreduraProcessado)
        .filter(VarreduraProcessado.id.in_(item_ids))
        .update(
            {
                "queue_status": QUEUE_STATUS_PROCESSING,
                "last_attempt_at": now,
                "attempt_count": VarreduraProcessado.attempt_count + 1,
                "updated_at": now,
            },
            synchronize_session=False,
        )
    )
    db.commit()

    # Input pro runner.
    payload_items = []
    for it in items:
        payload_items.append(
            {
                "processadoId": it.id,
                "lawsuitId": it.lawsuit_id,
                "cnjNumber": it.cnj_number or "",
            }
        )
    input_path.write_text(
        json.dumps(
            {
                "windowDays": run.window_days,
                "items": payload_items,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Subprocess Node.
    node = resolve_node_binary()
    script = _runner_script()
    cmd = [
        node,
        str(script),
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--max-attempts",
        "2",
    ]
    creds = resolve_web_credentials()
    env = {**os.environ, **creds}

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(  # noqa: S603
        cmd,
        cwd=str(script.parent),
        env=env,
        stdout=log_path.open("ab"),
        stderr=err_path.open("ab"),
        creationflags=creation_flags,
    )
    logger.info(
        "varredura.worker.subprocess.started run=%s pid=%s items=%s",
        run_id, proc.pid, len(items),
    )

    # Poll loop: enquanto subprocess vivo, sync periodico com banco.
    deadline = time.monotonic() + _SUBPROCESS_TIMEOUT_HOURS * 3600
    last_synced = -1
    while True:
        ret = proc.poll()
        if ret is not None:
            break
        if time.monotonic() > deadline:
            logger.warning(
                "varredura.worker.subprocess.timeout run=%s pid=%s",
                run_id, proc.pid,
            )
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            break
        # Sync intermediario do status.json (best-effort)
        last_synced = _sync_from_status_file(
            db, run_id, output_path, last_synced
        )
        time.sleep(_POLL_INTERVAL_SECONDS)

    # Sync final.
    _sync_from_status_file(db, run_id, output_path, last_synced, final=True)

    # Resumo: marca run como DONE se tudo OK, FAILED se algum erro.
    run = db.query(VarreduraRun).filter(VarreduraRun.id == run_id).first()
    if run is None:
        return
    # Recalcula contadores
    totais = (
        db.query(
            func.count(VarreduraProcessado.id),
            func.sum(
                case(
                    (
                        VarreduraProcessado.queue_status
                        == QUEUE_STATUS_COMPLETED,
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        VarreduraProcessado.queue_status
                        == QUEUE_STATUS_FAILED,
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(VarreduraProcessado.total_achados),
        )
        .filter(VarreduraProcessado.run_id == run_id)
        .first()
    )
    total_proc, processados_ok, processados_fail, total_achados = (
        totais or (0, 0, 0, 0)
    )
    run.total_processos = int(total_proc or 0)
    run.total_processados = int(
        (processados_ok or 0) + (processados_fail or 0)
    )
    run.total_falhas = int(processados_fail or 0)
    run.total_achados = int(total_achados or 0)
    if proc.returncode == 0 and run.total_falhas == 0:
        run.status = RUN_STATUS_DONE
    elif proc.returncode == 0:
        run.status = RUN_STATUS_DONE  # com falhas parciais
    else:
        run.status = RUN_STATUS_FAILED
        if not run.error_message:
            run.error_message = (
                f"Subprocess Node terminou com returncode={proc.returncode}. "
                f"Veja {err_path}."
            )
    run.completed_at = _utcnow()
    db.commit()
    logger.info(
        "varredura.worker.finished run=%s status=%s total=%s achados=%s falhas=%s",
        run_id,
        run.status,
        run.total_processos,
        run.total_achados,
        run.total_falhas,
    )


def _sync_from_status_file(
    db: Session,
    run_id: int,
    status_path: Path,
    last_synced_index: int,
    *,
    final: bool = False,
) -> int:
    """Le o status.json escrito pelo runner Node e atualiza items+achados.

    Retorna o ultimo indice sincronizado.
    """
    if not status_path.exists():
        return last_synced_index

    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return last_synced_index

    items: list[dict[str, Any]] = data.get("items") or []
    new_last = last_synced_index
    for idx, it in enumerate(items):
        if idx <= last_synced_index and not final:
            continue
        status = (it.get("status") or "").lower()
        if status not in {"ok", "error", "pending"}:
            continue
        processado_id = it.get("processadoId")
        if not processado_id:
            continue
        if status == "pending" and not final:
            # ainda em processamento — skip
            continue
        _apply_item_outcome(db, run_id, processado_id, it)
        new_last = idx
    return new_last


def _apply_item_outcome(
    db: Session,
    run_id: int,
    processado_id: int,
    item: dict[str, Any],
) -> None:
    """Persiste resultado de 1 processo (status + andamentos -> achados)."""
    p = (
        db.query(VarreduraProcessado)
        .filter(
            VarreduraProcessado.id == processado_id,
            VarreduraProcessado.run_id == run_id,
        )
        .first()
    )
    if p is None:
        return
    if p.queue_status in {QUEUE_STATUS_COMPLETED, QUEUE_STATUS_FAILED}:
        return  # idempotente

    status = (item.get("status") or "").lower()
    andamentos = item.get("andamentos") or []
    error = item.get("error")

    now = _utcnow()
    if status == "error":
        p.queue_status = QUEUE_STATUS_FAILED
        p.last_error = (str(error) if error else "Erro desconhecido")[:1000]
        p.last_reason = "runner_error"
        p.completed_at = now
        p.updated_at = now
        db.commit()
        return

    # status == "ok"
    p.total_andamentos_lidos = len(andamentos)

    # Aplica regex em cada andamento e cria achados
    achados_criados = 0
    for and_ in andamentos:
        texto = (and_.get("texto") or "").strip()
        if not texto:
            continue
        detections = detect_eventos(texto)
        if not detections:
            continue
        d = _parse_pt_date(and_.get("data"))
        for det in detections:
            db.add(
                VarreduraAchado(
                    run_id=run_id,
                    processado_id=p.id,
                    lawsuit_id=p.lawsuit_id,
                    cnj_number=p.cnj_number,
                    andamento_data=d,
                    andamento_hora=(and_.get("hora") or "")[:8] or None,
                    andamento_tipo=(and_.get("tipo") or "")[:64] or None,
                    andamento_texto=texto,
                    andamento_movimentado_por=(
                        (and_.get("movimentadoPor") or "")[:255] or None
                    ),
                    tipo_evento=det.tipo,
                    regex_matched=det.matched_text[:500],
                )
            )
            achados_criados += 1

    p.total_achados = achados_criados
    p.queue_status = QUEUE_STATUS_COMPLETED
    p.completed_at = now
    p.last_reason = "ok" if achados_criados > 0 else "no_matches"
    p.last_error = None
    p.updated_at = now
    db.commit()

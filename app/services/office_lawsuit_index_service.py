"""
Serviço de sincronização do índice de processos por escritório.

Responsabilidades:
- Full sync: baixa todos os lawsuit_ids do escritório (paginado), faz upsert
- Incremental sync: pede só os processos modificados desde o último sync
- Gerencia estado em office_lawsuit_sync (progresso, status, erro)
- Fallback pra full sync se incremental não for suportado pela API

A sincronização roda em thread/background — não bloqueia o request HTTP.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.office_lawsuit_index import OfficeLawsuitIndex, OfficeLawsuitSync
from app.services.legal_one_client import LegalOneApiClient


logger = logging.getLogger(__name__)


FULL_SYNC_TTL = timedelta(hours=24)
INCREMENTAL_LOOKBACK = timedelta(hours=1)  # margem de segurança no since


class OfficeLawsuitIndexService:
    """Gerencia o índice persistente de processos por escritório."""

    def __init__(self, db: Session, client: Optional[LegalOneApiClient] = None):
        self.db = db
        self.client = client or LegalOneApiClient()

    # ────────────────────────────────────────────────
    # Leitura (consumido pelo publication_search_service)
    # ────────────────────────────────────────────────

    def get_lawsuit_ids(self, office_id: int) -> set[int]:
        """Retorna o conjunto de lawsuit_ids já indexados pro escritório."""
        rows = (
            self.db.query(OfficeLawsuitIndex.lawsuit_id)
            .filter(OfficeLawsuitIndex.office_id == office_id)
            .all()
        )
        return {r[0] for r in rows}

    def get_sync_state(self, office_id: int) -> Optional[OfficeLawsuitSync]:
        return (
            self.db.query(OfficeLawsuitSync)
            .filter(OfficeLawsuitSync.office_id == office_id)
            .one_or_none()
        )

    def is_fresh(self, office_id: int) -> bool:
        """True se há um full_sync dentro do TTL."""
        state = self.get_sync_state(office_id)
        if state is None or state.last_full_sync_at is None:
            return False
        last = state.last_full_sync_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last) < FULL_SYNC_TTL

    # ────────────────────────────────────────────────
    # Trigger: dispara sync em background
    # ────────────────────────────────────────────────

    def ensure_sync(self, office_id: int, force_full: bool = False) -> OfficeLawsuitSync:
        """
        Garante que o índice do escritório está atualizado.
        - Se não há sync ainda ou está stale ou force_full=True → dispara full sync
        - Se está fresh mas tem incremental disponível e > 10min → dispara incremental
        - Sempre retorna o estado atual (pode estar in_progress=True)
        """
        state = self._get_or_create_state(office_id)

        # Já tem sync rodando? retorna sem disparar outra
        if state.in_progress:
            return state

        needs_full = (
            force_full
            or state.last_full_sync_at is None
            or not self.is_fresh(office_id)
        )

        if needs_full:
            self._launch_background(office_id, mode="full")
        elif state.supports_incremental:
            # Incremental leve se passou mais de 10min do último sync
            last_inc = state.last_incremental_at or state.last_full_sync_at
            if last_inc is not None:
                if last_inc.tzinfo is None:
                    last_inc = last_inc.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - last_inc) > timedelta(minutes=10):
                    self._launch_background(office_id, mode="incremental")

        # Retorna o estado após possivelmente marcar in_progress
        self.db.refresh(state)
        return state

    # ────────────────────────────────────────────────
    # Implementação da sync (roda em thread)
    # ────────────────────────────────────────────────

    def _launch_background(self, office_id: int, mode: str) -> None:
        """Marca como in_progress e dispara thread pra rodar o sync."""
        state = self._get_or_create_state(office_id)
        state.in_progress = True
        state.last_sync_status = "running"
        state.last_sync_error = None
        state.progress_pct = 0
        state.started_at = datetime.now(timezone.utc)
        state.finished_at = None
        self.db.commit()

        t = threading.Thread(
            target=_run_sync_thread,
            args=(office_id, mode),
            daemon=True,
            name=f"office-sync-{office_id}-{mode}",
        )
        t.start()
        logger.info("Sync %s iniciado pro escritório %s", mode, office_id)

    # ────────────────────────────────────────────────
    # Helpers internos
    # ────────────────────────────────────────────────

    def _get_or_create_state(self, office_id: int) -> OfficeLawsuitSync:
        state = self.get_sync_state(office_id)
        if state is None:
            state = OfficeLawsuitSync(office_id=office_id)
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state


# ────────────────────────────────────────────────
# Thread worker (sessão própria)
# ────────────────────────────────────────────────

def _run_sync_thread(office_id: int, mode: str) -> None:
    """Executa full ou incremental sync numa sessão dedicada."""
    db = SessionLocal()
    client = LegalOneApiClient()
    try:
        state = (
            db.query(OfficeLawsuitSync)
            .filter(OfficeLawsuitSync.office_id == office_id)
            .one()
        )
        if mode == "full":
            _do_full_sync(db, client, state)
        else:
            _do_incremental_sync(db, client, state)
    except Exception as exc:
        logger.exception("Erro no sync office=%s mode=%s: %s", office_id, mode, exc)
        try:
            state = (
                db.query(OfficeLawsuitSync)
                .filter(OfficeLawsuitSync.office_id == office_id)
                .one_or_none()
            )
            if state:
                state.in_progress = False
                state.last_sync_status = "error"
                state.last_sync_error = str(exc)[:1000]
                state.finished_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _do_full_sync(
    db: Session, client: LegalOneApiClient, state: OfficeLawsuitSync
) -> None:
    office_id = state.office_id
    logger.info("Full sync escritório %s: iniciando...", office_id)

    total_reported: Optional[int] = None
    all_ids: set[int] = set()
    page_size = 30  # Legal One OData $top cap
    skip = 0
    pages_fetched = 0

    while True:
        params = {
            "$filter": f"responsibleOfficeId eq {office_id}",
            "$select": "id",
            "$top": page_size,
            "$skip": skip,
        }
        if pages_fetched == 0:
            params["$count"] = "true"

        page = _fetch_lawsuits_page(client, params)
        if page is None:
            break

        items = page.get("value", [])
        for it in items:
            lid = it.get("id")
            if lid is not None:
                try:
                    all_ids.add(int(lid))
                except (TypeError, ValueError):
                    pass

        if pages_fetched == 0 and page.get("@odata.count") is not None:
            total_reported = int(page["@odata.count"])

        pages_fetched += 1

        # Atualiza progresso
        if total_reported:
            pct = min(99, int(len(all_ids) * 100 / max(total_reported, 1)))
        else:
            pct = min(99, pages_fetched)  # fallback grosseiro
        state.progress_pct = pct
        db.commit()

        if len(items) < page_size:
            break
        skip += page_size

    # Upsert em batches
    now = datetime.now(timezone.utc)
    _bulk_upsert_ids(db, office_id, all_ids, now)

    # Remove IDs que sumiram (processo trocou de escritório ou foi removido).
    # Só fazemos isso num full sync.
    _prune_missing_ids(db, office_id, all_ids)

    state.last_full_sync_at = now
    state.last_incremental_at = now
    state.total_ids = len(all_ids)
    state.in_progress = False
    state.last_sync_status = "success"
    state.last_sync_error = None
    state.progress_pct = 100
    state.finished_at = now
    db.commit()

    logger.info(
        "Full sync escritório %s: concluído. %s processos indexados.",
        office_id, len(all_ids),
    )


def _do_incremental_sync(
    db: Session, client: LegalOneApiClient, state: OfficeLawsuitSync
) -> None:
    """
    Tenta incremental via modificationDate. Se a API não suportar (400 no filtro),
    marca supports_incremental=False e cai pra full sync.
    """
    office_id = state.office_id
    since = state.last_incremental_at or state.last_full_sync_at
    if since is None:
        _do_full_sync(db, client, state)
        return

    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_safe = since - INCREMENTAL_LOOKBACK
    since_iso = since_safe.strftime("%Y-%m-%dT%H:%M:%SZ")

    logger.info(
        "Incremental sync escritório %s desde %s...", office_id, since_iso,
    )

    all_ids: set[int] = set()
    page_size = 30  # Legal One OData $top cap
    skip = 0

    while True:
        params = {
            "$filter": (
                f"responsibleOfficeId eq {office_id} "
                f"and modificationDate gt {since_iso}"
            ),
            "$select": "id",
            "$top": page_size,
            "$skip": skip,
        }
        try:
            page = _fetch_lawsuits_page(client, params, raise_on_400=True)
        except _IncrementalNotSupported:
            logger.warning(
                "Escritório %s: API não suporta modificationDate, caindo pra full sync.",
                office_id,
            )
            state.supports_incremental = False
            db.commit()
            _do_full_sync(db, client, state)
            return

        if page is None:
            break

        items = page.get("value", [])
        for it in items:
            lid = it.get("id")
            if lid is not None:
                try:
                    all_ids.add(int(lid))
                except (TypeError, ValueError):
                    pass

        if len(items) < page_size:
            break
        skip += page_size

    now = datetime.now(timezone.utc)
    if all_ids:
        _bulk_upsert_ids(db, office_id, all_ids, now)

    # Recalcula total
    total = db.query(OfficeLawsuitIndex).filter(
        OfficeLawsuitIndex.office_id == office_id
    ).count()

    state.last_incremental_at = now
    state.total_ids = total
    state.in_progress = False
    state.last_sync_status = "success"
    state.last_sync_error = None
    state.progress_pct = 100
    state.finished_at = now
    db.commit()

    logger.info(
        "Incremental escritório %s: %s novos/modificados. Total: %s.",
        office_id, len(all_ids), total,
    )


# ────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────

class _IncrementalNotSupported(Exception):
    pass


def _fetch_lawsuits_page(
    client: LegalOneApiClient,
    params: dict,
    raise_on_400: bool = False,
) -> Optional[dict]:
    """
    Busca uma página do /Lawsuits (fallback em /Litigations) aplicando os
    params OData. Retorna o dict bruto ({value, @odata.count, ...}) ou None.
    """
    import requests
    from urllib.parse import quote

    for endpoint in ("/Lawsuits", "/Litigations"):
        qs_parts = []
        for k, v in params.items():
            # Mantém encoding consistente com o resto do client
            qs_parts.append(f"{k}={quote(str(v), safe='')}")
        url = f"{client.base_url}{endpoint}?" + "&".join(qs_parts)
        try:
            resp = client._request_with_retry("GET", url)
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 400 and raise_on_400:
                raise _IncrementalNotSupported(str(exc))
            logger.warning(
                "Falha em %s (status=%s), tentando próximo endpoint.", endpoint, status,
            )
            continue
        except Exception as exc:
            logger.warning("Erro em %s: %s", endpoint, exc)
            continue
    return None


def _bulk_upsert_ids(
    db: Session, office_id: int, lawsuit_ids: set[int], seen_at: datetime
) -> None:
    if not lawsuit_ids:
        return
    rows = [
        {"office_id": office_id, "lawsuit_id": lid, "last_seen_at": seen_at}
        for lid in lawsuit_ids
    ]
    # Batches de 1000 pra não estourar parâmetros
    BATCH = 1000
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        stmt = pg_insert(OfficeLawsuitIndex).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["office_id", "lawsuit_id"],
            set_={"last_seen_at": stmt.excluded.last_seen_at},
        )
        db.execute(stmt)
    db.commit()


def _prune_missing_ids(
    db: Session, office_id: int, current_ids: set[int]
) -> None:
    """Remove índices cujo lawsuit_id não veio no full sync atual."""
    if not current_ids:
        return
    existing = {
        r[0]
        for r in db.query(OfficeLawsuitIndex.lawsuit_id)
        .filter(OfficeLawsuitIndex.office_id == office_id)
        .all()
    }
    to_remove = existing - current_ids
    if not to_remove:
        return
    # Remove em batches
    BATCH = 1000
    ids_list = list(to_remove)
    for i in range(0, len(ids_list), BATCH):
        chunk = ids_list[i : i + BATCH]
        (
            db.query(OfficeLawsuitIndex)
            .filter(OfficeLawsuitIndex.office_id == office_id)
            .filter(OfficeLawsuitIndex.lawsuit_id.in_(chunk))
            .delete(synchronize_session=False)
        )
    db.commit()
    logger.info(
        "Full sync escritório %s: %s IDs removidos (não vieram no sync).",
        office_id, len(to_remove),
    )

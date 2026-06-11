"""Worker periodico da Atualizacao de Contatos — enriquece os contatos do L1.

CORE do modulo: pega itens PENDENTE de lotes em PROCESSING e, item a item:
  1. acha o contato pelo documento (CPF -> /Individuals, CNPJ -> /Companies);
  2. le' as colecoes existentes (phones/emails/addresses) — idempotencia;
  3. POST so' do que falta (ou, em dry_run, apenas monta o plano sem escrever).

Garantias (espelham o upload_worker do GED):
- Claim-then-process: marca PROCESSANDO + commit ANTES das chamadas L1; crash
  no meio deixa o item PROCESSANDO. O reaper reseta PROCESSANDO travado ->
  PENDENTE. Ao re-processar, a leitura dos existentes evita duplicar o que
  ja' foi gravado (idempotencia natural).
- Concorrencia 1 (max_instances=1, coalesce): o _rate_limiter global do L1
  ja' serializa o throughput; paralelizar nao ganha nada.

Gatilho: settings.contatos_legalone_worker_enabled (default True).
Registrado no startup do FastAPI (main.py lifespan).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.contato_update import (
    BATCH_STATUS_PROCESSING,
    DOC_KIND_CNPJ,
    ITEM_STATUS_DUPLICADO,
    ITEM_STATUS_ERRO,
    ITEM_STATUS_NAO_ENCONTRADO,
    ITEM_STATUS_PENDENTE,
    ITEM_STATUS_PROCESSANDO,
    ITEM_STATUS_SUCESSO,
    ContatoAtualizacaoBatch,
    ContatoAtualizacaoItem,
)
from app.services.contatos_legalone import batch_service, l1_contacts

logger = logging.getLogger(__name__)

JOB_ID = "contatos_legalone_enrich"


def _digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def _reap_stuck(db) -> int:
    """Reseta itens PROCESSANDO travados -> PENDENTE (recuperacao de crash)."""
    stuck_minutes = max(1, settings.contatos_legalone_stuck_minutes)
    threshold = datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)
    stuck = (
        db.query(ContatoAtualizacaoItem)
        .join(
            ContatoAtualizacaoBatch,
            ContatoAtualizacaoItem.batch_id == ContatoAtualizacaoBatch.id,
        )
        .filter(
            ContatoAtualizacaoItem.status == ITEM_STATUS_PROCESSANDO,
            ContatoAtualizacaoItem.updated_at < threshold,
            ContatoAtualizacaoBatch.status == BATCH_STATUS_PROCESSING,
        )
        .all()
    )
    for it in stuck:
        it.status = ITEM_STATUS_PENDENTE
        it.error_message = "Reprocessado (item travou em PROCESSANDO — possivel crash)."
    if stuck:
        db.commit()
        logger.warning(
            "Contatos: %d item(ns) travado(s) resetado(s) pra PENDENTE.", len(stuck)
        )
    return len(stuck)


def _addr_key(addr: dict[str, Any]) -> tuple:
    """Chave de dedupe de endereco: (linha, numero, cidade_id)."""
    return (
        str(addr.get("addressLine1") or "").strip().lower(),
        str(addr.get("addressNumber") or "").strip(),
        addr.get("cityId"),
    )


def _process_one_item(db, item_id: int) -> None:
    """Enriquece 1 contato. Tolerante a falha — vira ERRO com a msg do L1."""
    from app.services.legal_one_client import LegalOneApiClient

    item = db.get(ContatoAtualizacaoItem, item_id)
    if item is None:
        return
    if item.status != ITEM_STATUS_PENDENTE:  # guard de idempotencia / corrida
        return

    # Claim ANTES das chamadas L1 (commit) — evita re-pegar em outro tick.
    item.status = ITEM_STATUS_PROCESSANDO
    item.attempts = (item.attempts or 0) + 1
    db.commit()

    batch = item.batch
    dry = bool(batch.dry_run)
    now = datetime.now(timezone.utc)

    payload = item.payload_json or {}
    name = payload.get("name")
    phones = payload.get("phones") or []
    email = payload.get("email")
    address = payload.get("address")

    result: dict[str, Any] = {
        "dry_run": dry,
        "found": None,
        "contact_id": None,
        "city_id": None,
        "created": {"phones": 0, "emails": 0, "addresses": 0, "name": 0},
        "planned": {"phones": [], "emails": [], "addresses": [], "name": []},
        "skipped": [],
        "errors": [],
    }

    try:
        client = LegalOneApiClient()
        resource = (
            l1_contacts.RESOURCE_COMPANIES
            if item.doc_kind == DOC_KIND_CNPJ
            else l1_contacts.RESOURCE_INDIVIDUALS
        )

        found = l1_contacts.find_contact(client, resource, item.doc_number)
        result["found"] = len(found)
        if len(found) == 0:
            item.status = ITEM_STATUS_NAO_ENCONTRADO
            item.error_message = "Documento nao encontrado como contato no Legal One."
            item.result_json = result
            item.processed_at = now
            db.commit()
            return
        if len(found) > 1:
            item.status = ITEM_STATUS_DUPLICADO
            item.error_message = (
                f"{len(found)} contatos com o mesmo documento (tratamento manual)."
            )
            item.result_json = result
            item.processed_at = now
            db.commit()
            return

        contact_id = int(found[0]["id"])
        item.contact_id = contact_id
        result["contact_id"] = contact_id

        # Le' os existentes (idempotencia).
        existing_phones = l1_contacts.get_collection(
            client, resource, contact_id, l1_contacts.COLL_PHONES
        )
        existing_emails = l1_contacts.get_collection(
            client, resource, contact_id, l1_contacts.COLL_EMAILS
        )
        existing_addresses = (
            l1_contacts.get_collection(
                client, resource, contact_id, l1_contacts.COLL_ADDRESSES
            )
            if address
            else []
        )

        existing_phone_digits = {_digits(p.get("number")) for p in existing_phones}
        existing_email_lower = {
            str(e.get("email") or "").strip().lower() for e in existing_emails
        }
        existing_addr_keys = {_addr_key(a) for a in existing_addresses}

        had_error = False

        # ── Nome ── (PATCH escalar; so' ajusta se veio no CSV e mudou).
        current_name = (found[0].get("name") or "").strip()
        if name and name.strip() and name.strip().casefold() != current_name.casefold():
            if dry:
                result["planned"]["name"].append(
                    {"de": current_name or None, "para": name.strip()}
                )
            else:
                try:
                    l1_contacts.patch_contact_name(client, resource, contact_id, name.strip())
                    result["created"]["name"] = 1
                except l1_contacts.ContatoL1Error as exc:
                    had_error = True
                    result["errors"].append(str(exc))
        elif name and name.strip():
            result["skipped"].append("nome ja esta atualizado")

        # ── Telefones ──
        set_main = len(existing_phones) == 0  # so' vira principal se nao havia
        for num in phones:
            d = _digits(num)
            if d and d in existing_phone_digits:
                result["skipped"].append(f"telefone {num} ja existe")
                continue
            phone_payload = {
                "number": num,
                "typeId": settings.contatos_legalone_phone_type_id,
                "isMainPhone": set_main,
            }
            set_main = False
            if dry:
                result["planned"]["phones"].append(phone_payload)
            else:
                try:
                    l1_contacts.post_collection(
                        client, resource, contact_id, l1_contacts.COLL_PHONES, phone_payload
                    )
                    result["created"]["phones"] += 1
                except l1_contacts.ContatoL1Error as exc:
                    had_error = True
                    result["errors"].append(str(exc))
            existing_phone_digits.add(d)

        # ── E-mail ──
        if email:
            if email.strip().lower() in existing_email_lower:
                result["skipped"].append(f"email {email} ja existe")
            else:
                is_first_email = len(existing_emails) == 0
                email_payload = {
                    "email": email,
                    "typeId": settings.contatos_legalone_email_type_id,
                    "isMainEmail": is_first_email,
                    # L1 exige >=1 e-mail com billing/invoicing; o 1o que entra
                    # (quando o contato nao tinha e-mail) assume esse papel.
                    "isBillingEmail": is_first_email,
                    "isInvoicingEmail": is_first_email,
                }
                if dry:
                    result["planned"]["emails"].append(email_payload)
                else:
                    try:
                        l1_contacts.post_collection(
                            client, resource, contact_id, l1_contacts.COLL_EMAILS, email_payload
                        )
                        result["created"]["emails"] += 1
                    except l1_contacts.ContatoL1Error as exc:
                        had_error = True
                        result["errors"].append(str(exc))

        # ── Endereco ──
        if address:
            city_id, city_status = l1_contacts.resolve_city_id(
                client, address.get("cidade") or "", address.get("uf") or ""
            )
            result["city_id"] = city_id
            if city_status != l1_contacts.CITY_OK or city_id is None:
                result["skipped"].append(
                    f"endereco pulado (cidade {address.get('cidade')}/{address.get('uf')} "
                    f"{city_status})"
                )
            else:
                is_first_addr = len(existing_addresses) == 0
                addr_payload = {
                    "type": "Residential",
                    "addressLine1": address.get("logradouro") or "",
                    "addressNumber": address.get("numero") or "",
                    "addressLine2": address.get("complemento") or "",
                    "neighborhood": address.get("bairro") or "",
                    "cityId": city_id,
                    "areaCode": address.get("cep") or "",
                    "isMainAddress": is_first_addr,
                    # L1 exige >=1 endereco com billing/invoicing; idem e-mail.
                    "isBillingAddress": is_first_addr,
                    "isInvoicingAddress": is_first_addr,
                }
                if _addr_key(addr_payload) in existing_addr_keys:
                    result["skipped"].append("endereco ja existe")
                elif dry:
                    result["planned"]["addresses"].append(addr_payload)
                else:
                    try:
                        l1_contacts.post_collection(
                            client, resource, contact_id, l1_contacts.COLL_ADDRESSES, addr_payload
                        )
                        result["created"]["addresses"] += 1
                    except l1_contacts.ContatoL1Error as exc:
                        had_error = True
                        result["errors"].append(str(exc))

        item.result_json = result
        item.processed_at = now
        if had_error:
            item.status = ITEM_STATUS_ERRO
            item.error_message = "; ".join(result["errors"])[:1000]
        else:
            item.status = ITEM_STATUS_SUCESSO
            item.error_message = None
        db.commit()
        logger.info(
            "Contatos %s: item=%s contato=%s created=%s skipped=%d dry=%s",
            "DRY" if dry else "OK",
            item.id, contact_id, result["created"], len(result["skipped"]), dry,
        )
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        item.status = ITEM_STATUS_ERRO
        item.error_message = f"{type(exc).__name__}: {exc}"[:1000]
        item.result_json = result
        item.processed_at = now
        db.commit()
        logger.exception(
            "Contatos ERRO inesperado: item=%s lote=%s", item.id, item.batch_id
        )


def _finalize_batch_if_done(db, batch_id: int) -> None:
    """Recomputa contadores; se nada pende, fecha o lote."""
    batch = db.get(ContatoAtualizacaoBatch, batch_id)
    if batch is None or batch.status != BATCH_STATUS_PROCESSING:
        return
    batch_service.recompute_counters(db, batch)
    if batch.total_pendente == 0:
        batch_service._finalize_status(batch)
    db.commit()


def _tick() -> None:
    """Uma execucao do worker. Nao levanta — apenas loga falhas."""
    db = SessionLocal()
    try:
        _reap_stuck(db)

        per_tick = max(1, settings.contatos_legalone_worker_batch_size)
        items = (
            db.query(ContatoAtualizacaoItem)
            .join(
                ContatoAtualizacaoBatch,
                ContatoAtualizacaoItem.batch_id == ContatoAtualizacaoBatch.id,
            )
            .filter(
                ContatoAtualizacaoItem.status == ITEM_STATUS_PENDENTE,
                ContatoAtualizacaoBatch.status == BATCH_STATUS_PROCESSING,
            )
            .order_by(ContatoAtualizacaoItem.created_at.asc())
            .limit(per_tick)
            .all()
        )
        if not items:
            return

        item_ids = [it.id for it in items]
        affected = {it.batch_id for it in items}
        logger.info("Contatos: processando %d item(ns) neste tick.", len(item_ids))

        for iid in item_ids:
            _process_one_item(db, iid)

        for bid in affected:
            _finalize_batch_if_done(db, bid)
    finally:
        db.close()


def _run_tick() -> None:
    """Adapter sincrono pro APScheduler."""
    try:
        _tick()
    except Exception:  # noqa: BLE001
        logger.exception("Contatos: erro inesperado no tick.")


def register_contatos_legalone_job(scheduler) -> None:
    """Registra o job periodico. No-op se o worker estiver desligado."""
    if not settings.contatos_legalone_worker_enabled:
        logger.info(
            "Contatos worker NAO registrado (contatos_legalone_worker_enabled=False)."
        )
        return

    interval = max(5, settings.contatos_legalone_worker_interval_seconds)
    scheduler.add_job(
        _run_tick,
        trigger="interval",
        seconds=interval,
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "Contatos worker registrado (intervalo=%ds, batch_size=%d).",
        interval, settings.contatos_legalone_worker_batch_size,
    )

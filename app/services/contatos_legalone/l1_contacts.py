"""Wrapper fino sobre o LegalOneApiClient pras rotas de contato.

Reusa toda a infra do client existente (auth Basic->Bearer, token-bucket
rate limiter global 1.2 req/s, retry/backoff em 401/429) chamando
`client._request_with_retry`. NAO duplica auth nem abre sessao propria.

Rotas (ver ESTUDO-API-CONTATOS-LEGALONE.md):
- find_contact:     GET /{Individuals|Companies}?$filter=identificationNumber eq '<doc>'
- get_collection:   GET /{resource}({id})/{phones|emails|addresses}
- post_collection:  POST /{resource}({id})/{phones|emails|addresses}   (escrita)
- resolve_city_id:  GET /Cities?$filter=name eq '<cidade>' and state/stateCode eq '<uf>'

A escrita (post_collection) e' o unico passo que o estudo nao validou ao
vivo (so' a leitura) — por isso o worker tem modo dry-run.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# Recursos OData (pessoa fisica x juridica) — mesmo padrao de navegacao.
RESOURCE_INDIVIDUALS = "Individuals"
RESOURCE_COMPANIES = "Companies"

# Navigation properties (colecoes) de um contato.
COLL_PHONES = "phones"
COLL_EMAILS = "emails"
COLL_ADDRESSES = "addresses"

# Status da resolucao de cidade.
CITY_OK = "OK"
CITY_NOT_FOUND = "NOT_FOUND"
CITY_AMBIGUOUS = "AMBIGUOUS"

# Cache global (CIDADE_UPPER, UF_UPPER) -> city_id (ou None p/ nao encontrada).
# Cidade->id e' invariante global; cachear evita re-bater /Cities por linha.
_CITY_CACHE: dict[tuple[str, str], Optional[int]] = {}
_CITY_LOCK = threading.Lock()


class ContatoL1Error(Exception):
    """Falha numa chamada de contato ao L1 — inclui status + corpo do erro."""


def _escape(client: Any, value: str) -> str:
    """Escapa aspas simples pro literal OData (delega ao helper do client)."""
    try:
        return client._escape_odata_literal(value)
    except Exception:  # noqa: BLE001
        return (value or "").replace("'", "''")


def _value_list(response: requests.Response) -> list[dict[str, Any]]:
    try:
        data = response.json()
    except ValueError:
        return []
    if isinstance(data, dict):
        return data.get("value", []) or []
    return []


# ─── Busca do contato pelo documento ─────────────────────────────────────


def find_contact(client: Any, resource: str, doc_number: str) -> list[dict[str, Any]]:
    """GET /{resource}?$filter=identificationNumber eq '<doc>'  (top=2).

    Devolve a lista `value` (0, 1 ou 2 itens — 2 sinaliza duplicidade). O doc
    e' usado COM mascara (e' como o L1 guarda em identificationNumber).
    """
    lit = _escape(client, doc_number)
    url = (
        f"{client.base_url}/{resource}"
        f"?$filter=identificationNumber eq '{lit}'&$top=2"
    )
    resp = client._request_with_retry("GET", url)
    return _value_list(resp)


# ─── Leitura das colecoes existentes (idempotencia) ──────────────────────


def get_collection(
    client: Any, resource: str, contact_id: int, coll: str
) -> list[dict[str, Any]]:
    """GET /{resource}({id})/{coll} — telefones/e-mails/enderecos atuais."""
    url = f"{client.base_url}/{resource}({int(contact_id)})/{coll}"
    resp = client._request_with_retry("GET", url)
    return _value_list(resp)


# ─── Escrita (navigation property POST) ──────────────────────────────────


def post_collection(
    client: Any, resource: str, contact_id: int, coll: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """POST /{resource}({id})/{coll} com o PhoneModel/EmailModel/AddressModel.

    Retorna {status_code, id, body}. Levanta ContatoL1Error em falha (com o
    corpo do erro do L1 pra diagnostico).
    """
    url = f"{client.base_url}/{resource}({int(contact_id)})/{coll}"
    try:
        resp = client._request_with_retry(
            "POST", url, json=payload, headers={"Accept": "application/json"}
        )
    except requests.exceptions.HTTPError as exc:  # 4xx (ex.: 400 payload invalido)
        body = ""
        status = None
        if exc.response is not None:
            status = exc.response.status_code
            body = (exc.response.text or "")[:800]
        raise ContatoL1Error(
            f"POST /{resource}({contact_id})/{coll} falhou "
            f"(HTTP {status}): {body}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise ContatoL1Error(
            f"POST /{resource}({contact_id})/{coll} erro de rede: {exc}"
        ) from exc

    created_id = None
    body: Any = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            created_id = body.get("id")
    except ValueError:
        body = None  # 204 No Content / corpo vazio — normal no OData
    return {"status_code": resp.status_code, "id": created_id, "body": body}


# ─── Ajuste do nome (PATCH escalar) ──────────────────────────────────────


def patch_contact_name(
    client: Any, resource: str, contact_id: int, name: str
) -> dict[str, Any]:
    """PATCH /{resource}(id) com {name} — ajusta o nome do contato.

    Diferente de phones/emails/addresses (proibidos no PATCH e feitos por
    navigation property), `name` e' campo escalar do PersonModel/CompanyModel
    e pode ir no corpo do PATCH. Retorna {status_code}; levanta ContatoL1Error
    em falha (com o corpo do erro do L1).
    """
    url = f"{client.base_url}/{resource}({int(contact_id)})"
    try:
        resp = client._request_with_retry(
            "PATCH", url, json={"name": name}, headers={"Accept": "application/json"}
        )
    except requests.exceptions.HTTPError as exc:
        body = ""
        status = None
        if exc.response is not None:
            status = exc.response.status_code
            body = (exc.response.text or "")[:800]
        raise ContatoL1Error(
            f"PATCH /{resource}({contact_id}) name falhou (HTTP {status}): {body}"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise ContatoL1Error(
            f"PATCH /{resource}({contact_id}) name erro de rede: {exc}"
        ) from exc
    return {"status_code": resp.status_code}


# ─── Resolucao de cidade -> cityId ───────────────────────────────────────


def resolve_city_id(
    client: Any, cidade: str, uf: str
) -> tuple[Optional[int], str]:
    """Resolve (CIDADE, UF) -> cityId via GET /Cities (cacheado).

    Retorna (city_id|None, status) com status em {OK, NOT_FOUND, AMBIGUOUS}.
    Filtro insensivel a acento/caixa (confirmado no estudo), entao os nomes
    MAIUSCULOS sem acento do CSV casam direto. Nao chuta cidade.
    """
    name = (cidade or "").strip()
    state = (uf or "").strip().upper()
    if not name or not state:
        return None, CITY_NOT_FOUND

    key = (name.upper(), state)
    with _CITY_LOCK:
        if key in _CITY_CACHE:
            cached = _CITY_CACHE[key]
            return cached, (CITY_OK if cached is not None else CITY_NOT_FOUND)

    name_lit = _escape(client, name)
    uf_lit = _escape(client, state)
    url = (
        f"{client.base_url}/Cities"
        f"?$filter=name eq '{name_lit}' and state/stateCode eq '{uf_lit}'"
        f"&$expand=state&$top=3"
    )
    try:
        resp = client._request_with_retry("GET", url)
        rows = _value_list(resp)
    except Exception:  # noqa: BLE001
        logger.exception("Contatos: falha ao resolver cidade %s/%s.", name, state)
        return None, CITY_NOT_FOUND

    if not rows:
        with _CITY_LOCK:
            _CITY_CACHE[key] = None  # cacheia "nao encontrada" p/ nao re-bater
        return None, CITY_NOT_FOUND
    if len(rows) > 1:
        # Ambiguidade (homonima na mesma UF) — nao cacheia, loga e devolve.
        return None, CITY_AMBIGUOUS

    city_id = rows[0].get("id")
    city_id = int(city_id) if city_id is not None else None
    with _CITY_LOCK:
        _CITY_CACHE[key] = city_id
    return city_id, (CITY_OK if city_id is not None else CITY_NOT_FOUND)


def city_cache_size() -> int:
    """Tamanho do cache de cidades (diagnostico)."""
    with _CITY_LOCK:
        return len(_CITY_CACHE)

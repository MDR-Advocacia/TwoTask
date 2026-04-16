# app/services/legal_one_client.py

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class LegalOneAuthenticationError(RuntimeError):
    pass


class LegalOneApiClient:
    _session = requests.Session()
    _CNJ_LOOKUP_BATCH_SIZE = 20
    _PROCESS_LOOKUP_SELECT = "id,identifierNumber,responsibleOfficeId,creationDate"

    class _Auth:
        token: Optional[str] = None
        expires_at: datetime = datetime.min
        lock = threading.Lock()
        LEEWAY = 120

    class _CacheManager:
        _instance: Optional["LegalOneApiClient._CacheManager"] = None
        _caches: Dict[str, Dict] = {"areas": {}, "positions": {}}
        _last_load_times: Dict[str, Optional[datetime]] = {"areas": None, "positions": None}
        CACHE_TTL = timedelta(hours=1)

        def __new__(cls):
            if cls._instance is None:
                cls._instance = super(LegalOneApiClient._CacheManager, cls).__new__(cls)
            return cls._instance

        def is_stale(self, cache_name: str) -> bool:
            return (
                not self._caches.get(cache_name)
                or not self._last_load_times.get(cache_name)
                or datetime.utcnow() > self._last_load_times[cache_name] + self.CACHE_TTL
            )

        def get(self, cache_name: str, item_id: int) -> Optional[Any]:
            return self._caches.get(cache_name, {}).get(item_id)

        def populate(self, cache_name: str, items: List[Dict[str, Any]]):
            self._caches[cache_name] = {int(item["id"]): item for item in items if item.get("id")}
            self._last_load_times[cache_name] = datetime.utcnow()
            logging.info("Cache '%s' populado com %s registros.", cache_name, len(self._caches[cache_name]))

    def __init__(self):
        self.base_url = settings.legal_one_base_url or os.environ.get("LEGAL_ONE_BASE_URL")
        self.client_id = settings.legal_one_client_id or os.environ.get("LEGAL_ONE_CLIENT_ID")
        self.client_secret = settings.legal_one_client_secret or os.environ.get("LEGAL_ONE_CLIENT_SECRET")
        self._cache_manager = self._CacheManager()
        self.logger = logging.getLogger(__name__)
        if not all([self.base_url, self.client_id, self.client_secret]):
            raise ValueError("As variaveis de ambiente da API Legal One devem ser configuradas.")

    def _to_int(self, value: Any) -> Optional[int]:
        try:
            return int(value)
        except (ValueError, TypeError, SystemError):
            return None

    @staticmethod
    def _normalize_cnj_number(cnj_number: Any) -> str:
        if cnj_number is None:
            return ""
        return str(cnj_number).strip()

    @staticmethod
    def _escape_odata_literal(value: str) -> str:
        return value.replace("'", "''")

    @staticmethod
    def _chunk_list(items: List[str], chunk_size: int) -> List[List[str]]:
        return [items[index : index + chunk_size] for index in range(0, len(items), chunk_size)]

    def _refresh_token_if_needed(self, force: bool = False):
        now = datetime.utcnow()
        with self._Auth.lock:
            if not force and self._Auth.token and now < self._Auth.expires_at - timedelta(seconds=self._Auth.LEEWAY):
                return

            self.logger.info("Renovando token OAuth (force=%s)...", force)
            auth_url = "https://api.thomsonreuters.com/legalone/oauth?grant_type=client_credentials"
            try:
                response = self._session.post(auth_url, auth=(self.client_id, self.client_secret), timeout=30)
                response.raise_for_status()
                data = response.json()
                expires_in = int(data.get("expires_in", 1800))
                self._Auth.token = data["access_token"]
                self._Auth.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.logger.info(
                    "Novo token obtido. Valido ate: %s UTC",
                    self._Auth.expires_at.strftime("%Y-%m-%d %H:%M:%S"),
                )
            except requests.exceptions.HTTPError as exc:
                self.logger.error(
                    "Falha ao renovar token OAuth: %s - %s",
                    exc.response.status_code,
                    exc.response.text,
                )
                if exc.response is not None and exc.response.status_code in (401, 403):
                    raise LegalOneAuthenticationError(
                        "Falha de autenticacao no Legal One. Verifique LEGAL_ONE_CLIENT_ID e LEGAL_ONE_CLIENT_SECRET."
                    ) from exc
                raise
            except Exception as exc:
                self.logger.error("Erro inesperado ao renovar token: %s", exc)
                raise

    def _authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._Auth.token}", **kwargs.pop("headers", {})}
        response = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
        if response.status_code == 401:
            self.logger.warning("401 Unauthorized detectado. Forcando refresh e repetindo a chamada.")
            self._refresh_token_if_needed(force=True)
            headers["Authorization"] = f"Bearer {self._Auth.token}"
            response = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
        return response

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        import random

        retry_exceptions = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
        last_exception = None

        # 8 tentativas com backoff exponencial + jitter para não ter threads
        # paralelas acordando em uníssono e re-batendo em 429 juntas.
        for attempt in range(8):
            try:
                response = self._authenticated_request(method, url, **kwargs)
                if response.status_code == 404:
                    # 404 não é transitório — propaga imediatamente para o
                    # caller tratar (ex.: get_lawsuit_responsible_user).
                    response.raise_for_status()
                    return response
                if response.status_code in (429, 500, 502, 503, 504):
                    wait = (2 ** attempt) + random.uniform(0, 2)
                    self.logger.warning(
                        "Status %s recebido. Nova tentativa em %.1fs (attempt %d/8).",
                        response.status_code, wait, attempt + 1,
                    )
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except retry_exceptions as exc:
                last_exception = exc
                wait = (2 ** attempt) + random.uniform(0, 2)
                self.logger.warning(
                    "Erro de conexao (%s): %s. Nova tentativa em %.1fs.",
                    type(exc).__name__, exc, wait,
                )
                time.sleep(wait)

        if last_exception:
            self.logger.error("Esgotadas tentativas apos erro de conexao: %s", last_exception)
            raise last_exception

        raise requests.exceptions.RequestException("Maximo de tentativas excedido sem sucesso.")

    def _paginated_catalog_loader(self, endpoint: str, params: Optional[dict] = None) -> List[Dict[str, Any]]:
        all_items: List[Dict[str, Any]] = []
        base_url = f"{self.base_url}{endpoint}"
        current_params = (params or {}).copy()
        current_params["$count"] = "true"
        url = base_url
        is_first_page = True

        while url:
            try:
                response = self._request_with_retry("GET", url, params=current_params)
                data = response.json()
                page = data.get("value", [])
                all_items.extend(page)
                if is_first_page:
                    self.logger.info(
                        "Auditoria: Servidor reportou %s itens para '%s'.",
                        data.get("@odata.count", "N/A"),
                        endpoint,
                    )
                    is_first_page = False

                next_link = data.get("@odata.nextLink")
                if next_link:
                    url, current_params = next_link, None
                else:
                    break
            except requests.exceptions.HTTPError as exc:
                self.logger.error("Erro HTTP ao carregar catalogo de '%s': %s", endpoint, exc.response.text)
                if exc.response is not None and exc.response.status_code in (401, 403):
                    raise LegalOneAuthenticationError(
                        f"Falha de autenticacao ao carregar o catalogo '{endpoint}'."
                    ) from exc
                break

        self.logger.info("Carregamento do catalogo '%s' concluido. Total: %s.", endpoint, len(all_items))
        return all_items

    def get_all_allocatable_areas(self) -> list[dict]:
        endpoint = "/areas"
        # Nao limite a primeira pagina: escritorios novos podem ficar fora do sync
        # quando a API tiver mais de 30 areas.
        params = {"$select": "id,name,path,allocateData", "$orderby": "id"}
        all_areas = self._paginated_catalog_loader(endpoint, params)
        return [area for area in all_areas if area.get("allocateData")]

    def get_all_users(self) -> list[dict]:
        self.logger.info("Buscando todos os usuarios...")
        endpoint = "/Users"
        params = {"$select": "id,name,email,isActive", "$orderby": "id"}
        return self._paginated_catalog_loader(endpoint, params)

    def _search_process_endpoint_by_cnj_numbers(
        self,
        endpoint: str,
        cnj_numbers: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        matches: Dict[str, Dict[str, Any]] = {}
        normalized_numbers = []
        seen_numbers = set()
        for cnj_number in cnj_numbers:
            normalized = self._normalize_cnj_number(cnj_number)
            if not normalized or normalized in seen_numbers:
                continue
            normalized_numbers.append(normalized)
            seen_numbers.add(normalized)

        for cnj_chunk in self._chunk_list(normalized_numbers, self._CNJ_LOOKUP_BATCH_SIZE):
            filter_clause = " or ".join(
                f"identifierNumber eq '{self._escape_odata_literal(cnj_number)}'"
                for cnj_number in cnj_chunk
            )
            params = {
                "$filter": filter_clause,
                "$select": self._PROCESS_LOOKUP_SELECT,
                "$top": max(len(cnj_chunk), 1),
            }
            results = self._paginated_catalog_loader(endpoint, params)
            for item in results:
                identifier_number = self._normalize_cnj_number(item.get("identifierNumber"))
                if identifier_number and identifier_number not in matches:
                    matches[identifier_number] = item

        return matches

    def search_lawsuits_by_cnj_numbers(self, cnj_numbers: List[str]) -> Dict[str, Dict[str, Any]]:
        normalized_numbers = []
        seen_numbers = set()
        for cnj_number in cnj_numbers:
            normalized = self._normalize_cnj_number(cnj_number)
            if not normalized or normalized in seen_numbers:
                continue
            normalized_numbers.append(normalized)
            seen_numbers.add(normalized)

        if not normalized_numbers:
            return {}

        self.logger.info("Precarregando %s processos distintos por CNJ.", len(normalized_numbers))
        matches = self._search_process_endpoint_by_cnj_numbers("/Lawsuits", normalized_numbers)

        missing_numbers = [cnj_number for cnj_number in normalized_numbers if cnj_number not in matches]
        if missing_numbers:
            self.logger.info(
                "%s CNJs nao encontrados em Lawsuits. Tentando fallback em Litigations.",
                len(missing_numbers),
            )
            fallback_matches = self._search_process_endpoint_by_cnj_numbers("/Litigations", missing_numbers)
            for cnj_number, item in fallback_matches.items():
                matches.setdefault(cnj_number, item)

        self.logger.info("Precarregamento de processos concluido. Encontrados %s de %s CNJs.", len(matches), len(normalized_numbers))
        return matches

    def fetch_lawsuits_by_ids(self, lawsuit_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Busca processos pelos seus IDs internos do Legal One em batch.
        Usado para enriquecer publicações (relationships) com responsibleOfficeId.

        Consulta primeiro o cache local (`lawsuit_cache`, TTL 24h) e só
        chama a API do Legal One para os IDs com cache miss ou expirados.

        Retorna dict {lawsuit_id: {id, identifierNumber, responsibleOfficeId}}
        """
        unique_ids: List[int] = []
        seen: set = set()
        for lid in lawsuit_ids:
            try:
                n = int(lid)
            except (TypeError, ValueError):
                continue
            if n in seen:
                continue
            unique_ids.append(n)
            seen.add(n)

        if not unique_ids:
            return {}

        matches: Dict[int, Dict[str, Any]] = {}

        # 1) Cache hits ─────────────────────────────────────────────────
        cache_hits, cache_misses = self._lawsuit_cache_lookup(unique_ids)
        matches.update(cache_hits)

        if cache_hits:
            self.logger.info(
                "Lawsuit cache: %s hits / %s ids (misses: %s).",
                len(cache_hits), len(unique_ids), len(cache_misses),
            )

        if not cache_misses:
            return matches

        self.logger.info("Buscando %s processos por ID interno (cache miss).", len(cache_misses))
        fetched_from_api: Dict[int, Dict[str, Any]] = {}

        # Tenta primeiro em /Lawsuits, depois fallback em /Litigations
        for endpoint in ("/Lawsuits", "/Litigations"):
            missing = [lid for lid in cache_misses if lid not in fetched_from_api]
            if not missing:
                break

            for chunk in self._chunk_list([str(x) for x in missing], self._CNJ_LOOKUP_BATCH_SIZE):
                filter_clause = " or ".join(f"id eq {lid}" for lid in chunk)
                params = {
                    "$filter": filter_clause,
                    "$select": self._PROCESS_LOOKUP_SELECT,
                    "$top": min(len(chunk), 30),
                }
                try:
                    results = self._paginated_catalog_loader(endpoint, params)
                    for item in results:
                        item_id = item.get("id")
                        if item_id is not None:
                            fetched_from_api[int(item_id)] = item
                except Exception as exc:
                    self.logger.warning("Erro ao buscar lote em %s: %s", endpoint, exc)

        # 2) Grava no cache os novos resultados ─────────────────────────
        if fetched_from_api:
            self._lawsuit_cache_upsert(fetched_from_api)

        matches.update(fetched_from_api)

        self.logger.info(
            "Processos: %s (cache) + %s (API) = %s de %s.",
            len(cache_hits), len(fetched_from_api), len(matches), len(unique_ids),
        )
        return matches

    def fetch_lawsuit_ids_by_office(self, office_id: int) -> set[int]:
        """
        Retorna o conjunto de IDs de processos cujo responsibleOfficeId == office_id.

        Usa o endpoint /Lawsuits (fallback em /Litigations) com $select=id
        e paginação. Resultado é armazenado no cache em memória do client
        por 1 hora para evitar chamadas repetidas durante a mesma busca.
        """
        from time import time

        cache = getattr(self, "_lawsuit_ids_by_office_cache", None)
        if cache is None:
            cache = {}
            self._lawsuit_ids_by_office_cache = cache

        entry = cache.get(office_id)
        if entry and (time() - entry["ts"] < 3600):
            return entry["ids"]

        ids: set[int] = set()
        for endpoint in ("/Lawsuits", "/Litigations"):
            try:
                params = {
                    "$filter": f"responsibleOfficeId eq {int(office_id)}",
                    "$select": "id",
                    "$top": 100,
                }
                results = self._paginated_catalog_loader(endpoint, params)
                for item in results:
                    lid = item.get("id")
                    if lid is not None:
                        try:
                            ids.add(int(lid))
                        except (TypeError, ValueError):
                            pass
                if ids:
                    break
            except Exception as exc:
                self.logger.warning(
                    "Falha ao listar processos do escritório %s em %s: %s",
                    office_id, endpoint, exc,
                )

        self.logger.info(
            "Processos do escritório %s: %s IDs carregados.", office_id, len(ids)
        )
        cache[office_id] = {"ts": time(), "ids": ids}
        return ids

    # ──────────────────────────────────────────────────────────────
    # lawsuit_cache (TTL 24h)
    # ──────────────────────────────────────────────────────────────

    def _lawsuit_cache_lookup(
        self, ids: List[int]
    ) -> (Dict[int, Dict[str, Any]], List[int]):
        """Retorna (hits, misses) consultando a tabela lawsuit_cache."""
        from app.db.session import SessionLocal
        from app.models.lawsuit_cache import LawsuitCache, LAWSUIT_CACHE_TTL

        hits: Dict[int, Dict[str, Any]] = {}
        misses: List[int] = []

        session = SessionLocal()
        try:
            rows = (
                session.query(LawsuitCache)
                .filter(LawsuitCache.lawsuit_id.in_(ids))
                .all()
            )
            by_id = {r.lawsuit_id: r for r in rows}
            for lid in ids:
                entry = by_id.get(lid)
                if entry is not None and entry.is_fresh(LAWSUIT_CACHE_TTL):
                    hits[lid] = entry.payload
                else:
                    misses.append(lid)
        except Exception as exc:
            self.logger.warning("Falha ao ler lawsuit_cache: %s — bypass.", exc)
            return {}, list(ids)
        finally:
            session.close()

        return hits, misses

    def _lawsuit_cache_upsert(self, fetched: Dict[int, Dict[str, Any]]) -> None:
        """Grava/atualiza entradas em lawsuit_cache."""
        from datetime import datetime, timezone

        from app.db.session import SessionLocal
        from app.models.lawsuit_cache import LawsuitCache

        if not fetched:
            return

        session = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            existing = {
                r.lawsuit_id: r
                for r in session.query(LawsuitCache)
                .filter(LawsuitCache.lawsuit_id.in_(list(fetched.keys())))
                .all()
            }
            for lid, payload in fetched.items():
                row = existing.get(lid)
                if row is None:
                    session.add(
                        LawsuitCache(
                            lawsuit_id=lid,
                            payload=payload,
                            fetched_at=now,
                        )
                    )
                else:
                    row.payload = payload
                    row.fetched_at = now
            session.commit()
        except Exception as exc:
            session.rollback()
            self.logger.warning("Falha ao gravar lawsuit_cache: %s", exc)
        finally:
            session.close()

    def search_lawsuit_by_cnj(self, cnj_number: str) -> Optional[Dict[str, Any]]:
        normalized_cnj = self._normalize_cnj_number(cnj_number)
        self.logger.info("Buscando processo com CNJ: %s", normalized_cnj)
        lawsuit = self.search_lawsuits_by_cnj_numbers([normalized_cnj]).get(normalized_cnj)
        if lawsuit:
            return lawsuit

        self.logger.warning("Nenhum processo encontrado para o CNJ %s em nenhuma das tentativas.", normalized_cnj)
        return None

    def get_lawsuit_by_id(
        self,
        lawsuit_id: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self.logger.info("Buscando processo ID %s.", lawsuit_id)
        endpoint = f"/Lawsuits/{lawsuit_id}"
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retry("GET", url, params=params)
        return response.json()

    def get_lawsuit_responsible_user(self, lawsuit_id: int) -> Optional[Dict[str, Any]]:
        """
        Busca o responsável principal (participante com isResponsible=True)
        da pasta/processo no Legal One. Retorna o primeiro encontrado ou None.

        Estratégia: usar `/Lawsuits/{id}?$expand=Participants` numa única
        chamada — evita o path minúsculo `/lawsuits/{id}/participants` que
        devolve 404 em massa na versão atual da API, e reduz para 1 request
        por pasta (eliminando o risco de 429 em cascata N+1).

        Returns:
            dict com {id, name, ...} do contato responsável, ou None.
        """
        # Tenta sub-resource /Participants em /Lawsuits primeiro; se 404,
        # cai pro /Litigations — o linkId que vem em relationships.Litigation
        # das publicações pode apontar para qualquer uma das duas entities.
        for base_entity in ("/Lawsuits", "/Litigations"):
            try:
                endpoint = f"{base_entity}/{lawsuit_id}/Participants"
                url = f"{self.base_url}{endpoint}"
                response = self._request_with_retry("GET", url)
                data = response.json() or {}
                participants = data.get("value") or []
                self.logger.info(
                    "%s/%s/Participants → %d participantes.",
                    base_entity, lawsuit_id, len(participants),
                )
                for p in participants:
                    # O responsável é identificado pelo type == "PersonInCharge".
                    # Legacy: isResponsible / IsResponsible (alguns payloads).
                    p_type = p.get("type") or p.get("Type")
                    if (
                        p_type == "PersonInCharge"
                        or p.get("isResponsible")
                        or p.get("IsResponsible")
                    ):
                        # Campos no nível raiz (contactId, contactName) ou aninhados.
                        contact = p.get("contact") or p.get("Contact") or {}
                        return {
                            "id": (
                                p.get("contactId")
                                or p.get("ContactId")
                                or contact.get("id")
                                or contact.get("Id")
                            ),
                            "name": (
                                p.get("contactName")
                                or p.get("ContactName")
                                or contact.get("name")
                                or contact.get("Name")
                                or contact.get("displayName")
                                or contact.get("DisplayName")
                            ),
                            "email": (
                                p.get("email")
                                or p.get("Email")
                                or contact.get("email")
                                or contact.get("Email")
                            ),
                            "isResponsible": True,
                            "source_entity": base_entity,
                            "raw": p,
                        }
                # Achou a entity com participantes mas ninguém marcado como
                # responsável — não faz sentido tentar a outra.
                if participants:
                    return None
                # Sem participantes? pode ser que esteja na outra entity.
                continue
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 404:
                    continue
                self.logger.warning(
                    "HTTP %s em %s/%s/Participants.", status_code, base_entity, lawsuit_id
                )
                return None
            except Exception as exc:
                self.logger.warning(
                    "Erro em %s/%s/Participants: %s", base_entity, lawsuit_id, exc
                )
                return None

        self.logger.info(
            "ID %s não encontrado em /Lawsuits nem /Litigations.", lawsuit_id
        )
        return None

    def fetch_lawsuit_responsibles_batch(
        self, lawsuit_ids: List[int], max_workers: int = 2
    ) -> Dict[int, Dict[str, Any]]:
        """
        Busca o responsável principal de múltiplos processos em paralelo.
        Retorna dict {lawsuit_id: {id, name, email, ...}} somente para
        os processos que possuem responsável identificado.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result: Dict[int, Dict[str, Any]] = {}
        if not lawsuit_ids:
            return result

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_id = {
                executor.submit(self.get_lawsuit_responsible_user, lid): lid
                for lid in lawsuit_ids
            }
            for future in as_completed(future_to_id):
                lid = future_to_id[future]
                try:
                    resp = future.result()
                    if resp:
                        result[lid] = resp
                except Exception as exc:
                    self.logger.warning("Erro ao buscar responsável do processo %s: %s", lid, exc)
        return result

    def get_lawsuit_participants(
        self,
        lawsuit_id: int,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        self.logger.info("Buscando participantes do processo ID %s.", lawsuit_id)
        endpoint = f"/Lawsuits/{lawsuit_id}/Participants"
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retry("GET", url, params=params)
        data = response.json()
        return data.get("value", [])

    def get_litigation_participant_positions(
        self,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        self.logger.info("Buscando posicoes de participantes do contencioso.")
        endpoint = "/LitigationParticipantPositions"
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retry("GET", url, params=params)
        data = response.json()
        return data.get("value", [])

    def patch_lawsuit_participant(
        self,
        lawsuit_id: int,
        participant_id: int,
        participant_payload: Dict[str, Any],
    ) -> bool:
        self.logger.info(
            "Atualizando participante %s do processo %s com payload: %s",
            participant_id,
            lawsuit_id,
            participant_payload,
        )
        endpoint = f"/Lawsuits/{lawsuit_id}/Participants/{participant_id}"
        url = f"{self.base_url}{endpoint}"
        try:
            self._request_with_retry("PATCH", url, json=participant_payload)
            return True
        except requests.exceptions.HTTPError as exc:
            self.logger.error(
                "Erro HTTP ao atualizar participante %s do processo %s: %s",
                participant_id,
                lawsuit_id,
                exc.response.text,
            )
            self.logger.error(
                "Payload enviado que causou o erro:\n%s",
                json.dumps(participant_payload, indent=2, ensure_ascii=False),
            )
            return False

    # Campos aceitos pela API Legal One em POST /Tasks.
    # Qualquer chave fora desta lista é removida antes do envio para evitar
    # o erro OData "Does not support untyped value in non-open type."
    _TASK_API_FIELDS = {
        "description", "priority", "startDateTime", "endDateTime",
        "publishDate", "notes", "status", "typeId", "subTypeId",
        "participants", "responsibleOfficeId", "originOfficeId",
        "lawsuitId", "folderId", "externalId",
    }

    def _sanitize_task_payload(self, task_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Remove campos internos (ex.: template_name, suggested_responsible) do payload
        antes de enviar à API Legal One, que rejeita campos desconhecidos."""
        clean = {k: v for k, v in task_payload.items() if k in self._TASK_API_FIELDS}
        # Remove valores null explícitos que a API rejeita
        clean = {k: v for k, v in clean.items() if v is not None}
        return clean

    def create_task(self, task_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        clean_payload = self._sanitize_task_payload(task_payload)
        self.logger.info("Criando tarefa com payload: %s", clean_payload)
        endpoint = "/Tasks"
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._request_with_retry("POST", url, json=clean_payload)
            return response.json()
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro HTTP %s ao criar tarefa. Resposta: %s", exc.response.status_code, exc.response.text)
            self.logger.error("Payload enviado que causou o erro:\n%s", json.dumps(clean_payload, indent=2))
            return None

    def link_task_to_lawsuit(self, task_id: int, link_payload: Dict[str, Any]) -> bool:
        self.logger.info("Vinculando tarefa ID %s com payload: %s", task_id, link_payload)
        endpoint = f"/tasks/{task_id}/relationships"
        url = f"{self.base_url}{endpoint}"
        try:
            self._request_with_retry("POST", url, json=link_payload)
            return True
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro HTTP ao vincular tarefa %s: %s", task_id, exc.response.text)
            return False

    def add_participant_to_task(self, task_id: int, participant_payload: Dict[str, Any]) -> bool:
        self.logger.info("Adicionando participante a tarefa ID %s com payload: %s", task_id, participant_payload)
        endpoint = f"/tasks/{task_id}/participants"
        url = f"{self.base_url}{endpoint}"
        try:
            self._request_with_retry("POST", url, json=participant_payload)
            return True
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro HTTP ao adicionar participante a tarefa %s: %s", task_id, exc.response.text)
            return False

    # ──────────────────────────────────────────────────────────────
    # Motor de Busca de Publicações (Updates)
    # ──────────────────────────────────────────────────────────────

    def fetch_publications(
        self,
        date_from: str,
        date_to: Optional[str] = None,
        origin_type: str = "OfficialJournalsCrawler",
        office_id: Optional[int] = None,
        top: int = 30,
        skip: int = 0,
        count: bool = True,
    ) -> Dict[str, Any]:
        """
        Busca publicações (andamentos) na API do Legal One.

        Args:
            date_from: Data inicial ISO (ex: 2026-04-01T00:00:00Z)
            date_to: Data final ISO (opcional)
            origin_type: Tipo de origem (OfficialJournalsCrawler, ProgressesCrawler, Manual)
            office_id: ID do escritório para filtrar via relationships
            top: Limite de resultados por página
            skip: Offset para paginação
            count: Incluir contagem total

        Returns:
            Dict com 'value' (lista de publicações), '@odata.count', '@odata.nextLink'
        """
        def _clean_date(d: str) -> str:
            """Remove milissegundos e garante formato aceito pela API: 2026-04-07T00:00:00Z"""
            # Remove milissegundos: 2026-04-07T00:00:00.000Z → 2026-04-07T00:00:00Z
            if "." in d:
                d = d.split(".")[0] + "Z"
            # Se só tem data (2026-04-07), adiciona horário
            if len(d) == 10:
                d = d + "T00:00:00Z"
            return d

        date_from = _clean_date(date_from)
        if date_to:
            date_to = _clean_date(date_to)

        # Campo usado no filtro de datas: por padrão creationDate (data em
        # que o L1 disponibilizou a publicação). Pode ser alterado via env
        # `PUBLICATION_CAPTURE_DATE_FIELD=date` para voltar ao comportamento
        # anterior (filtro pela data efetiva da publicação no diário).
        try:
            from app.core.config import settings as _s
            date_field = (_s.publication_capture_date_field or "creationDate").strip()
        except Exception:
            date_field = "creationDate"

        filters = []
        filters.append(f"originType eq '{self._escape_odata_literal(origin_type)}'")
        filters.append(f"{date_field} ge {date_from}")
        if date_to:
            filters.append(f"{date_field} le {date_to}")

        filter_str = " and ".join(filters)

        # Monta a query string manualmente para evitar que requests encode o '$'
        # em %24filter, %24expand etc. — a API OData do LegalOne não aceita isso.
        from urllib.parse import quote
        qs_parts = [
            f"$filter={quote(filter_str, safe='')}",
            "$expand=relationships",
            f"$orderby={quote(date_field + ' desc', safe='')}",
            f"$top={top}",
            f"$skip={skip}",
        ]
        if count:
            qs_parts.append("$count=true")

        url = f"{self.base_url}/Updates?" + "&".join(qs_parts)
        self.logger.info("Buscando publicacoes: %s", filter_str)

        try:
            response = self._request_with_retry("GET", url)
            data = response.json()
            publications = data.get("value", [])

            # Filtrar por escritório se necessário (via relationship linkId)
            if office_id is not None:
                publications = [
                    pub for pub in publications
                    if any(
                        rel.get("linkType") == "Litigation"
                        for rel in (pub.get("relationships") or [])
                    )
                ]

            self.logger.info(
                "Publicacoes encontradas: %s (total reportado: %s)",
                len(publications),
                data.get("@odata.count", "N/A"),
            )
            return {
                "value": publications,
                "@odata.count": data.get("@odata.count", 0),
                "@odata.nextLink": data.get("@odata.nextLink"),
            }
        except requests.exceptions.HTTPError as exc:
            resp_text = exc.response.text if exc.response is not None else "(sem response)"
            self.logger.error(
                "Erro ao buscar publicacoes: %s | Status: %s | Body: %s",
                exc,
                exc.response.status_code if exc.response is not None else "?",
                resp_text,
            )
            raise

    def fetch_all_publications(
        self,
        date_from: str,
        date_to: Optional[str] = None,
        origin_type: str = "OfficialJournalsCrawler",
        max_pages: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Busca TODAS as publicações paginando automaticamente.
        Usa o mesmo padrão de _paginated_catalog_loader.
        """
        all_publications: List[Dict[str, Any]] = []
        skip = 0
        page_size = 30  # LegalOne limita $top a 30
        total_reported: Optional[int] = None

        # max_pages aumentado: com 30/pag, 500 pags = 15.000 publicacoes max
        for page in range(max_pages):
            result = self.fetch_publications(
                date_from=date_from,
                date_to=date_to,
                origin_type=origin_type,
                top=page_size,
                skip=skip,
                count=(page == 0),
            )

            if page == 0:
                total_reported = int(result.get("@odata.count") or 0)
                self.logger.info("Total de publicacoes reportado pela API: %s", total_reported)

            items = result.get("value", [])
            if not items:
                break

            all_publications.extend(items)

            # Paginacao baseada em count + item count (LegalOne nao retorna @odata.nextLink)
            if total_reported is not None and len(all_publications) >= total_reported:
                break
            if len(items) < page_size:
                break

            skip += page_size

        self.logger.info(
            "Busca completa: %s publicacoes carregadas (total reportado: %s).",
            len(all_publications),
            total_reported,
        )
        return all_publications

    def get_publication_by_id(self, update_id: int) -> Optional[Dict[str, Any]]:
        """Busca uma publicação específica pelo ID."""
        url = f"{self.base_url}/Updates/{update_id}?$expand=relationships"
        try:
            response = self._request_with_retry("GET", url)
            return response.json()
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro ao buscar publicacao %s: %s", update_id, exc.response.text if exc.response else exc)
            return None

    def get_update_types(self) -> List[Dict[str, Any]]:
        """Retorna os tipos de andamento/atualização disponíveis."""
        return self._paginated_catalog_loader("/UpdateAppointmentTaskTypes")

    def get_offices(self) -> List[Dict[str, Any]]:
        """Retorna os escritórios disponíveis (para filtro de publicações)."""
        return self._paginated_catalog_loader("/Offices")

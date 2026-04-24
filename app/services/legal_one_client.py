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


class LegalOneGedUploadError(RuntimeError):
    """
    Falha em algum dos 3 passos do upload GED (GetContainer / PUT blob /
    POST Documents). A mensagem inclui contexto sobre em qual passo
    ocorreu e o body de erro retornado pelo servidor quando disponível.
    """
    pass


class _GlobalRateLimiter:
    """
    Token-bucket rate limiter compartilhado por todas as instâncias do client.
    Garante no máximo `rate` requests por segundo globalmente, independente
    de quantas threads estejam rodando.

    Legal One: 90 req/min ≈ 1.5 req/s.  Usamos 1.2 req/s como margem.
    """

    _instance: Optional["_GlobalRateLimiter"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init(rate=1.2)
        return cls._instance

    def _init(self, rate: float):
        self._rate = rate          # tokens por segundo
        self._capacity = 5.0       # burst máximo
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._bucket_lock = threading.Lock()

    def acquire(self):
        """Bloqueia até ter 1 token disponível."""
        while True:
            with self._bucket_lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                # Calcula quanto esperar pelo próximo token
                wait = (1.0 - self._tokens) / self._rate

            time.sleep(wait)


class LegalOneApiClient:
    _session = requests.Session()
    # Reduzido de 20 pra 10 porque _cnj_variants gera ate 3 variantes
    # por CNJ (original + digits puros + formato canonico). Com batch=20
    # a lista de filter_parts chegava a 60 e o $top excedia o teto de
    # 30 do endpoint /Lawsuits + /Litigations do L1 — resultado: todo
    # o precarregamento devolvia 0 processos e o batch de planilha
    # quebrava com 'Processo nao encontrado no Legal One' em todas as
    # linhas. Com batch=10, maximo 30 filter_parts -> cabe no limite.
    _CNJ_LOOKUP_BATCH_SIZE = 10
    _PROCESS_LOOKUP_SELECT = "id,identifierNumber,responsibleOfficeId,creationDate"
    _rate_limiter = _GlobalRateLimiter()

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
    def _cnj_variants(cnj: str) -> List[str]:
        """
        Gera variantes comuns de formatação de um CNJ para tornar o lookup
        tolerante à divergência de formato entre quem envia (automação
        externa, usuário) e como o Legal One armazena internamente.

        Formato canônico CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos).
        Geradas (em ordem estável pra cache-friendly):
          1) o valor como veio (strip);
          2) 20 dígitos puros;
          3) formato canônico com máscara.

        Duplicatas são removidas mantendo a ordem de inserção.
        """
        cnj = (cnj or "").strip()
        if not cnj:
            return []
        digits = "".join(ch for ch in cnj if ch.isdigit())
        variants: List[str] = [cnj]
        if len(digits) == 20:
            formatted = (
                f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}."
                f"{digits[13]}.{digits[14:16]}.{digits[16:20]}"
            )
            for variant in (digits, formatted):
                if variant not in variants:
                    variants.append(variant)
        return variants

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

        for attempt in range(8):
            # Rate limiter global: aguarda slot antes de cada tentativa.
            # Isso impede que múltiplas threads estourem 90 req/min.
            self._rate_limiter.acquire()

            try:
                response = self._authenticated_request(method, url, **kwargs)
                if response.status_code == 404:
                    response.raise_for_status()
                    return response
                if response.status_code in (429, 500, 502, 503, 504):
                    # 429 = rate-limited. Espera mais longo e com jitter amplo
                    # para evitar thundering herd entre threads.
                    if response.status_code == 429:
                        wait = min(60, (3 ** attempt)) + random.uniform(1, 5)
                    else:
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
            # Pra cada CNJ, geramos todas as variantes (dígitos puros +
            # canônico com máscara) e expandimos o filtro OData com OR.
            # Isso resolve o caso de "processo existe no L1 mas lookup
            # retorna vazio" quando o formato armazenado difere do enviado.
            #
            # Também mantemos um reverse-map: {variante -> cnj_original}
            # pra, ao receber a resposta do L1, voltar a chave do match
            # pra forma canônica que o chamador passou.
            variant_to_original: Dict[str, str] = {}
            filter_parts: List[str] = []
            for cnj_number in cnj_chunk:
                for variant in self._cnj_variants(cnj_number):
                    if variant not in variant_to_original:
                        variant_to_original[variant] = cnj_number
                        filter_parts.append(
                            f"identifierNumber eq '{self._escape_odata_literal(variant)}'"
                        )
            filter_clause = " or ".join(filter_parts)
            params = {
                "$filter": filter_clause,
                # $top precisa caber TODAS as variantes — L1 pode devolver
                # múltiplos matches se variantes do mesmo CNJ coexistirem.
                # Cap em 30 porque o L1 rejeita top > 30 nos endpoints
                # /Lawsuits e /Litigations (HTTP 400 "The limit of '30' for
                # Top query has been exceeded"). A paginacao via nextLink
                # cuida do raro caso em que ha mais que 30 matches no chunk.
                "$select": self._PROCESS_LOOKUP_SELECT,
                "$top": min(max(len(filter_parts), 1), 30),
            }
            results = self._paginated_catalog_loader(endpoint, params)
            for item in results:
                identifier_number = self._normalize_cnj_number(item.get("identifierNumber"))
                # Mapeia a resposta de volta pro CNJ original do chamador:
                # se achou pela variante "digits-only", queremos indexar pelo
                # CNJ como foi pedido (senão o chamador não encontra no dict).
                key = variant_to_original.get(identifier_number, identifier_number)
                if key and key not in matches:
                    matches[key] = item

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
        # Zera o último erro pra não vazar informação de uma tentativa anterior.
        self._last_create_task_error = None
        try:
            response = self._request_with_retry("POST", url, json=clean_payload)
            return response.json()
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro HTTP %s ao criar tarefa. Resposta: %s", exc.response.status_code, exc.response.text)
            self.logger.error("Payload enviado que causou o erro:\n%s", json.dumps(clean_payload, indent=2))
            # Guarda o erro pra que o chamador possa consultar e propagar
            # uma mensagem detalhada pro operador (via format_last_create_task_error).
            parsed_detail: Optional[dict] = None
            try:
                parsed_detail = exc.response.json()
            except Exception:  # noqa: BLE001
                parsed_detail = None
            self._last_create_task_error = {
                "status_code": exc.response.status_code,
                "raw_text": exc.response.text,
                "parsed": parsed_detail,
            }
            return None

    # Mapa técnico→operacional pros campos que o L1 reclama.
    # Chaves são os `target` que vêm na resposta 400 do L1.
    _L1_FIELD_LABELS_PT = {
        "status.id": "Status",
        "publishDate": "Data de publicação",
        "originOfficeId": "Escritório de origem",
        "responsibleOfficeId": "Escritório responsável",
        "typeId": "Tipo da tarefa",
        "subTypeId": "Subtipo da tarefa",
        "SubTypeId": "Subtipo da tarefa",
        "participants": "Participantes",
        "description": "Descrição",
        "notes": "Observações",
        "startDateTime": "Data de início",
        "endDateTime": "Prazo final",
        "priority": "Prioridade",
        "contact.id": "Responsável",
    }

    # Categorias de problema (classificadas a partir do `code` do L1 e
    # palavras-chave da mensagem). Cada categoria vira um título legível.
    @staticmethod
    def _classify_l1_error_detail(detail: dict) -> str:
        """
        Retorna um rótulo de categoria simples baseado no detail do L1:
          - 'missing' — campo vazio / obrigatório
          - 'invalid' — valor recusado (formato, fora do catálogo)
          - 'conflict' — duplicata / concorrência
          - 'other' — fallback quando não reconhecemos
        """
        code = (detail.get("code") or "").lower()
        msg_lower = (detail.get("message") or "").lower()
        if code in {"nullvalue", "required", "missing"}:
            return "missing"
        if "obrigat" in msg_lower or "required" in msg_lower:
            return "missing"
        if code in {"notfound", "invalidvalue", "invalidformat", "validation"}:
            if "obrigat" in msg_lower:
                return "missing"
            return "invalid"
        if code in {"conflict", "duplicate"}:
            return "conflict"
        return "other"

    def _label_field(self, target: str) -> str:
        """Traduz um `target` do L1 pra rótulo PT-BR. Fallback: o próprio target."""
        if not target:
            return ""
        if target in self._L1_FIELD_LABELS_PT:
            return self._L1_FIELD_LABELS_PT[target]
        # Tenta chave base quando o target vem aninhado tipo "participants[0].contact.id"
        for key, label in self._L1_FIELD_LABELS_PT.items():
            if target.startswith(key) or target.endswith(key):
                return label
        return target

    def format_last_create_task_error(self) -> Optional[str]:
        """
        Retorna uma string humana descrevendo o último erro de create_task.

        Formato de saída agrupado por categoria (uma linha por categoria,
        campos separados por vírgula):

            Campos obrigatórios não enviados: Data de publicação, Escritório de origem
            Valor inválido: Subtipo da tarefa

        Fallback: HTTP status + trecho do raw_text quando o parse falha.
        Retorna None quando não há erro registrado.
        """
        last = getattr(self, "_last_create_task_error", None)
        if not last:
            return None
        parsed = last.get("parsed") or {}
        err = parsed.get("error") if isinstance(parsed, dict) else None

        if isinstance(err, dict):
            details = err.get("details") or []
            # Agrupa campos por categoria pra dar uma frase por tipo de problema.
            buckets: dict[str, list[str]] = {
                "missing": [],
                "invalid": [],
                "conflict": [],
                "other": [],
            }
            other_messages: list[str] = []
            if isinstance(details, list):
                for d in details:
                    if not isinstance(d, dict):
                        continue
                    target = (d.get("target") or "").strip()
                    category = self._classify_l1_error_detail(d)
                    label = self._label_field(target)
                    if label and category in buckets:
                        # Evita duplicar o mesmo campo em categorias diferentes
                        # (L1 às vezes reporta 2 erros pro mesmo field).
                        if label not in buckets[category]:
                            buckets[category].append(label)
                    elif not label:
                        msg_line = (d.get("message") or "").strip()
                        if msg_line:
                            other_messages.append(msg_line)

            lines: list[str] = []
            if buckets["missing"]:
                lines.append("Campos obrigatórios não enviados: "
                             + ", ".join(buckets["missing"]))
            if buckets["invalid"]:
                lines.append("Valor inválido em: " + ", ".join(buckets["invalid"]))
            if buckets["conflict"]:
                lines.append("Conflito em: " + ", ".join(buckets["conflict"]))
            if buckets["other"]:
                lines.append("Verifique: " + ", ".join(buckets["other"]))
            for extra in other_messages[:3]:
                # Frases soltas que não conseguimos mapear — mostra em linha
                # separada mas cortada pra não poluir.
                lines.append(extra[:200])

            if lines:
                return "\n".join(lines)

            # Se só veio a mensagem genérica ("Existem erros de validação..."),
            # mostra ela pra pelo menos ter algum texto.
            summary = (err.get("message") or "").strip()
            if summary:
                return summary

        # Fallback: raw_text truncado
        raw = (last.get("raw_text") or "").strip()
        status = last.get("status_code")
        if raw:
            return f"HTTP {status}: {raw[:300]}"
        return f"HTTP {status} (sem corpo legível)."

    def get_task_by_id(self, task_id: int) -> Dict[str, Any]:
        self.logger.info("Buscando tarefa ID %s.", task_id)
        endpoint = f"/Tasks/{task_id}"
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retry("GET", url)
        return response.json()

    def get_task_relationships(self, task_id: int) -> List[Dict[str, Any]]:
        self.logger.info("Buscando relacionamentos da tarefa ID %s.", task_id)
        endpoint = f"/tasks/{task_id}/relationships"
        url = f"{self.base_url}{endpoint}"
        response = self._request_with_retry("GET", url)
        data = response.json() or {}
        return data.get("value", [])

    def search_tasks(
        self,
        *,
        filter_expression: str,
        top: int = 50,
        orderby: str = "id desc",
        select: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca tarefas no Legal One via OData.

        O caller monta o filtro para manter o metodo generico e
        reutilizavel em fluxos diferentes.
        """
        params = {
            "$filter": filter_expression,
            "$select": (
                select
                or (
                    "id,description,creationDate,statusId,typeId,subTypeId,"
                    "responsibleOfficeId,originOfficeId,startDateTime,endDateTime,"
                    "effectiveStartDateTime,effectiveEndDateTime,priority"
                )
            ),
            "$top": max(1, int(top)),
            "$orderby": orderby,
        }
        return self._paginated_catalog_loader("/Tasks", params)

    def find_tasks_for_lawsuit(
        self,
        lawsuit_id: int,
        *,
        type_id: Optional[int] = None,
        subtype_id: Optional[int] = None,
        status_ids: Optional[List[int]] = None,
        top: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Retorna tarefas vinculadas ao processo informado.

        O filtro por vinculo usa `relationships/any(...)`, que funciona no
        tenant atual e evita varrer todas as tarefas localmente.
        """
        clauses = [
            (
                "relationships/any("
                f"r: r/linkType eq 'Litigation' and r/linkId eq {int(lawsuit_id)}"
                ")"
            )
        ]
        if type_id is not None:
            clauses.append(f"typeId eq {int(type_id)}")
        if subtype_id is not None:
            clauses.append(f"subTypeId eq {int(subtype_id)}")
        if status_ids:
            normalized_status_ids = [
                int(status_id)
                for status_id in status_ids
                if status_id is not None
            ]
            if normalized_status_ids:
                status_filter = " or ".join(
                    f"statusId eq {status_id}"
                    for status_id in normalized_status_ids
                )
                clauses.append(f"({status_filter})")

        return self.search_tasks(
            filter_expression=" and ".join(clauses),
            top=top,
        )

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
    # GED (ECM) — Upload de Documentos
    # ──────────────────────────────────────────────────────────────
    # Fluxo documentado no swagger oficial (legal-one-firms-brazil-api):
    #
    #   1) GET /Documents/GetContainer(fileExtension='pdf')
    #      → retorna DocumentUploadModel:
    #        { id, externalId (URL SAS do Azure Blob),
    #          fileName (nome temp no container),
    #          uploadedFileSize (0 nesse ponto) }
    #
    #   2) PUT {externalId} (a URL retornada acima) com os BYTES do PDF.
    #      Esse PUT vai direto pro Azure Blob Storage (não passa pela
    #      API do L1 nem precisa do Authorization Bearer — a URL já tem
    #      o SAS embutido). Header obrigatório:
    #        - x-ms-blob-type: BlockBlob
    #        - Content-Type: application/pdf
    #
    #   3) POST /Documents com DocumentModel:
    #        { archive (nome visível), description, typeId ("2-48"),
    #          notes, fileUploader: { ExternalId, FileName, UploadedFileSize },
    #          relationships: [{ Link: "Litigation", LinkItem: { Id: ... } }] }
    #      → retorna o DocumentModel com `id` — esse é o ged_document_id.

    def upload_document_to_ged(
        self,
        *,
        file_bytes: bytes,
        file_name: str,
        type_id: str,
        litigation_id: int,
        archive_name: Optional[str] = None,
        description: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> int:
        """
        Faz upload de um PDF no GED do L1 vinculado a um processo (Litigation).
        Retorna o `document_id` criado.

        Levanta `LegalOneGedUploadError` com mensagem humana em qualquer
        falha de um dos 3 passos. O chamador pode capturar e traduzir.
        """
        # Passo 1 — obtém container temp.
        ext = "pdf"
        get_container_endpoint = (
            f"/Documents/GetContainer(fileExtension='{ext}')"
        )
        get_container_url = f"{self.base_url}{get_container_endpoint}"
        try:
            resp = self._request_with_retry("GET", get_container_url)
            container = resp.json() or {}
        except requests.exceptions.HTTPError as exc:
            body = exc.response.text if exc.response is not None else ""
            raise LegalOneGedUploadError(
                f"Falha no GetContainer do GED: HTTP {exc.response.status_code if exc.response else '?'}. {body[:400]}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LegalOneGedUploadError(f"Erro ao obter container do GED: {exc}") from exc

        external_id = container.get("externalId")
        temp_file_name = container.get("fileName") or file_name
        if not external_id:
            raise LegalOneGedUploadError(
                f"GetContainer não retornou externalId. Resposta: {container}"
            )

        # Passo 2 — PUT bytes direto no Azure Blob. URL já tem SAS
        # embutido; não usamos nossos headers de Authorization aqui.
        try:
            put_response = requests.put(
                external_id,
                data=file_bytes,
                headers={
                    "Content-Type": "application/pdf",
                    "x-ms-blob-type": "BlockBlob",
                },
                timeout=60,
            )
            put_response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = exc.response.text[:400] if exc.response is not None else ""
            raise LegalOneGedUploadError(
                f"Falha no PUT do blob (Azure): HTTP {status}. {body}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LegalOneGedUploadError(f"Erro ao enviar bytes pro blob: {exc}") from exc

        # Passo 3 — POST metadata + relationship + fileUploader.
        post_endpoint = "/Documents"
        post_url = f"{self.base_url}{post_endpoint}"
        payload: Dict[str, Any] = {
            "archive": archive_name or file_name,
            "description": description or file_name,
            "typeId": type_id,
            "fileName": temp_file_name,
            "fileUploader": {
                "ExternalId": external_id,
                "FileName": file_name,
                "UploadedFileSize": len(file_bytes),
            },
            "relationships": [
                {
                    "Link": "Litigation",
                    "LinkItem": {"Id": int(litigation_id)},
                }
            ],
        }
        if notes:
            payload["notes"] = notes

        self.logger.info(
            "GED upload: POST /Documents litigation=%s type=%s size=%d",
            litigation_id, type_id, len(file_bytes),
        )
        try:
            resp = self._request_with_retry("POST", post_url, json=payload)
            created = resp.json() or {}
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = exc.response.text[:400] if exc.response is not None else ""
            raise LegalOneGedUploadError(
                f"Falha no POST /Documents: HTTP {status}. {body}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LegalOneGedUploadError(f"Erro ao criar registro no GED: {exc}") from exc

        document_id = created.get("id")
        if not document_id:
            raise LegalOneGedUploadError(
                f"POST /Documents não retornou id. Resposta: {created}"
            )
        return int(document_id)

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

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
    _PROCESS_LOOKUP_SELECT = "id,identifierNumber,responsibleOfficeId"

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
        retry_exceptions = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
        last_exception = None

        for attempt in range(5):
            try:
                response = self._authenticated_request(method, url, **kwargs)
                if response.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt
                    self.logger.warning("Status %s recebido. Nova tentativa em %ss.", response.status_code, wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except retry_exceptions as exc:
                last_exception = exc
                wait = 2 ** attempt
                self.logger.warning("Erro de conexao (%s): %s. Nova tentativa em %ss.", type(exc).__name__, exc, wait)
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
        params = {"$select": "id,name,path,allocateData", "$orderby": "id", "$top": 30}
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

    def search_lawsuit_by_cnj(self, cnj_number: str) -> Optional[Dict[str, Any]]:
        normalized_cnj = self._normalize_cnj_number(cnj_number)
        self.logger.info("Buscando processo com CNJ: %s", normalized_cnj)
        lawsuit = self.search_lawsuits_by_cnj_numbers([normalized_cnj]).get(normalized_cnj)
        if lawsuit:
            return lawsuit

        self.logger.warning("Nenhum processo encontrado para o CNJ %s em nenhuma das tentativas.", normalized_cnj)
        return None

    def create_task(self, task_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.logger.info("Criando tarefa com payload: %s", task_payload)
        endpoint = "/Tasks"
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._request_with_retry("POST", url, json=task_payload)
            return response.json()
        except requests.exceptions.HTTPError as exc:
            self.logger.error("Erro HTTP %s ao criar tarefa. Resposta: %s", exc.response.status_code, exc.response.text)
            self.logger.error("Payload enviado que causou o erro:\n%s", json.dumps(task_payload, indent=2))
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

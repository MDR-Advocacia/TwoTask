# app/services/legal_one_client.py

import requests
import os
import logging
import time
import threading
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    _session = requests.Session()

    class _Auth:
        token: Optional[str] = None
        expires_at: datetime = datetime.min
        lock = threading.Lock()
        LEEWAY = 120

    class _CacheManager:
        _instance: Optional['_CacheManager'] = None
        _caches: Dict[str, Dict] = {"areas": {}, "positions": {}}
        _last_load_times: Dict[str, Optional[datetime]] = {"areas": None, "positions": None}
        CACHE_TTL = timedelta(hours=1)
        def __new__(cls):
            if cls._instance is None:
                cls._instance = super(LegalOneApiClient._CacheManager, cls).__new__(cls)
            return cls._instance
        def is_stale(self, cache_name: str) -> bool:
            return not self._caches.get(cache_name) or not self._last_load_times.get(cache_name) or \
                   datetime.utcnow() > self._last_load_times[cache_name] + self.CACHE_TTL
        def get(self, cache_name: str, item_id: int) -> Optional[Any]:
            return self._caches.get(cache_name, {}).get(item_id)
        def populate(self, cache_name: str, items: List[Dict[str, Any]]):
            self._caches[cache_name] = {int(item['id']): item for item in items if item.get('id')}
            self._last_load_times[cache_name] = datetime.utcnow()
            logging.info(f"Cache '{cache_name}' populado com {len(self._caches[cache_name])} registros.")

    def __init__(self):
        self.base_url = os.environ.get("LEGAL_ONE_BASE_URL")
        self.client_id = os.environ.get("LEGAL_ONE_CLIENT_ID")
        self.client_secret = os.environ.get("LEGAL_ONE_CLIENT_SECRET")
        self._cache_manager = self._CacheManager()
        self.logger = logging.getLogger(__name__)
        if not all([self.base_url, self.client_id, self.client_secret]):
            raise ValueError("As variáveis de ambiente da API Legal One devem ser configuradas.")

    def _to_int(self, x: Any) -> Optional[int]:
        try: return int(x)
        except (ValueError, TypeError, SystemError): return None

    def _refresh_token_if_needed(self, force: bool = False):
        now = datetime.utcnow()
        with self._Auth.lock:
            if not force and self._Auth.token and now < self._Auth.expires_at - timedelta(seconds=self._Auth.LEEWAY):
                return
            self.logger.info("Renovando token OAuth (force=%s)...", force)
            auth_url = "https://api.thomsonreuters.com/legalone/oauth?grant_type=client_credentials"
            try:
                resp = self._session.post(auth_url, auth=(self.client_id, self.client_secret), timeout=30)
                resp.raise_for_status()
                data = resp.json()
                expires_in = int(data.get("expires_in", 1800))
                self._Auth.token = data["access_token"]
                self._Auth.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                self.logger.info("Novo token obtido. Válido até: %s UTC", self._Auth.expires_at.strftime('%Y-%m-%d %H:%M:%S'))
            except requests.exceptions.HTTPError as e:
                self.logger.error("Falha ao renovar token OAuth: %s - %s", e.response.status_code, e.response.text)
                raise
            except Exception as e:
                self.logger.error("Erro inesperado ao renovar token: %s", e)
                raise

    def _authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._Auth.token}", **kwargs.pop("headers", {})}
        r = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
        if r.status_code == 401:
            self.logger.warning("401 Unauthorized detectado. Forçando refresh e repetindo a chamada.")
            self._refresh_token_if_needed(force=True)
            headers["Authorization"] = f"Bearer {self._Auth.token}"
            r = self._session.request(method, url, headers=headers, timeout=30, **kwargs)
        return r

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:

        retry_exceptions = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ChunkedEncodingError
        )

        last_exception = None

        for i in range(5):
            try:
                r = self._authenticated_request(method, url, **kwargs)
                if r.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** i
                    self.logger.warning(f"Status {r.status_code} recebido. Nova tentativa em {wait}s.")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                return r
            except retry_exceptions as e:
                last_exception = e
                wait = 2 ** i
                self.logger.warning(f"Erro de conexão ({type(e).__name__}): {e}. Nova tentativa em {wait}s.")
                time.sleep(wait)
                continue
            
        if last_exception:
            self.logger.error(f"Esgotadas tentativas após erro de conexão: {last_exception}")
            raise last_exception    
        
        raise requests.exceptions.RequestException("Máximo de tentativas excedido sem sucesso.")

    def _paginated_catalog_loader(self, endpoint: str, params: Optional[dict] = None) -> List[Dict[str, Any]]:
        all_items = []
        base_url = f"{self.base_url}{endpoint}"
        current_params = (params or {}).copy()
        page_size = self._to_int(current_params.get("$top", 30)) or 30
        current_params["$count"] = "true"
        url = base_url
        is_first_page = True
        while url:
            try:
                r = self._request_with_retry("GET", url, params=current_params)
                data = r.json()
                page = data.get("value", [])
                all_items.extend(page)
                if is_first_page:
                    self.logger.info(f"Auditoria: Servidor reportou {data.get('@odata.count', 'N/A')} itens para '{endpoint}'.")
                    is_first_page = False
                next_link = data.get("@odata.nextLink")
                if next_link:
                    url, current_params = next_link, None
                else:
                    break
            except requests.exceptions.HTTPError as e:
                self.logger.error(f"Erro HTTP ao carregar catálogo de '{endpoint}': {e.response.text}")
                break
        self.logger.info(f"Carregamento do catálogo '{endpoint}' concluído. Total: {len(all_items)}.")
        return all_items
    
    # --- MÉTODO RESTAURADO 1 ---
    def get_all_allocatable_areas(self) -> list[dict]:
        endpoint = "/areas"
        params = {"$select": "id,name,path,allocateData", "$orderby": "id", "$top": 30}
        all_areas = self._paginated_catalog_loader(endpoint, params)
        return [area for area in all_areas if area.get("allocateData")]

    # --- MÉTODO RESTAURADO 2 ---
    def get_all_users(self) -> list[dict]:
        self.logger.info("Buscando todos os usuários...")
        endpoint = "/Users"
        params = {"$select": "id,name,email,isActive", "$orderby": "id"}
        return self._paginated_catalog_loader(endpoint, params)

    def search_lawsuit_by_cnj(self, cnj_number: str) -> Optional[Dict[str, Any]]:
        self.logger.info(f"Buscando processo com CNJ: {cnj_number}")
        
        # Tentativa 1: Buscar como Lawsuit (principal)
        endpoint = "/Lawsuits"
        params = {"$filter": f"identifierNumber eq '{cnj_number}'", "$select": "id,identifierNumber,responsibleOfficeId", "$top": 1}
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._request_with_retry("GET", url, params=params)
            data = response.json()
            results = data.get("value", [])
            if results:
                self.logger.info(f"Processo encontrado como 'Lawsuit' principal.")
                return results[0]
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao buscar processo por CNJ como Lawsuit: {e.response.text}")
            # Não retorna, permite que o fallback seja executado
            
        # Tentativa 2: Fallback para buscar como Litigations (incidentes/recursos)
        self.logger.info(f"Processo não encontrado como 'Lawsuit'. Tentando busca em 'Litigations' (incidentes/recursos)...")
        endpoint_fallback = "/Litigations"
        url_fallback = f"{self.base_url}{endpoint_fallback}"
        try:
            response_fallback = self._request_with_retry("GET", url_fallback, params=params)
            data_fallback = response_fallback.json()
            results_fallback = data_fallback.get("value", [])
            if results_fallback:
                self.logger.info(f"Processo encontrado como 'Litigation'.")
                return results_fallback[0]
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao buscar processo por CNJ como Litigation: {e.response.text}")

        self.logger.warning(f"Nenhum processo encontrado para o CNJ {cnj_number} em nenhuma das tentativas.")
        return None

    def create_task(self, task_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        self.logger.info(f"Criando tarefa com payload: {task_payload}")
        endpoint = "/Tasks"
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._request_with_retry("POST", url, json=task_payload)
            return response.json()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP {e.response.status_code} ao criar tarefa. Resposta: {e.response.text}")
            self.logger.error(f"Payload enviado que causou o erro:\n{json.dumps(task_payload, indent=2)}")
            return None

    def link_task_to_lawsuit(self, task_id: int, link_payload: Dict[str, Any]) -> bool:
        self.logger.info(f"Vinculando tarefa ID {task_id} com payload: {link_payload}")
        endpoint = f"/tasks/{task_id}/relationships"
        url = f"{self.base_url}{endpoint}"
        try:
            self._request_with_retry("POST", url, json=link_payload)
            return True
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao vincular tarefa {task_id}: {e.response.text}")
            return False

    def add_participant_to_task(self, task_id: int, participant_payload: Dict[str, Any]) -> bool:
        self.logger.info(f"Adicionando participante à tarefa ID {task_id} com payload: {participant_payload}")
        endpoint = f"/tasks/{task_id}/participants"
        url = f"{self.base_url}{endpoint}"
        try:
            self._request_with_retry("POST", url, json=participant_payload)
            return True
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao adicionar participante à tarefa {task_id}: {e.response.text}")
            return False
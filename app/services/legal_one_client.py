# Conteúdo completo e atualizado para: app/services/legal_one_client.py

import requests
import os
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    """
    Cliente robusto para interagir com a API Legal One, com cache, retries, 
    paginação segura e gerenciamento de token de nível de produção (thread-safe).
    """
    _session = requests.Session()

    class _Auth:
        token: Optional[str] = None
        expires_at: datetime = datetime.min
        lock = threading.Lock()
        LEEWAY = 120  # segundos de folga

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
            return not self._caches[cache_name] or not self._last_load_times[cache_name] or \
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
            self.logger.error("As variáveis de ambiente da API Legal One não foram configuradas.")
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
            resp = self._session.post(
                auth_url,
                auth=(self.client_id, self.client_secret),
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            expires_in = int(data.get("expires_in", 1800))
            
            self._Auth.token = data["access_token"]
            self._Auth.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            self.logger.info("Novo token obtido. Válido até: %s UTC", self._Auth.expires_at)

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
        for i in range(5):
            r = self._authenticated_request(method, url, **kwargs)
            if r.status_code in (429, 500, 502, 503, 504):
                wait = 2 ** i
                self.logger.warning(f"Status {r.status_code} recebido. Nova tentativa em {wait}s.")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        return r

    def _paginated_catalog_loader(self, endpoint: str, params: Optional[dict] = None) -> List[Dict[str, Any]]:
        all_items, base_url = [], f"{self.base_url}{endpoint}"
        current_params = (params or {}).copy()
        page_size = self._to_int(current_params.get("$top", 30)) or 30
        current_params["$count"] = "true"
        url = base_url
        is_first_page = True

        while url:
            try:
                r = self._request_with_retry("GET", url, params=current_params)
                data = r.json()
                page = data.get("value", data.get("items", []))
                all_items.extend(page)

                if is_first_page:
                    server_count = data.get("@odata.count", "N/A")
                    self.logger.info(f"Auditoria: Servidor reportou {server_count} itens para o catálogo '{endpoint}'.")
                    is_first_page = False

                next_link = data.get("@odata.nextLink")
                if next_link:
                    url, current_params = next_link, None
                    continue

                if len(page) < page_size: break
                
                offset = self._to_int(current_params.get("$skip", 0)) or 0
                current_params = (params or {}).copy()
                current_params["$skip"] = offset + page_size
                url = base_url
                
            except requests.exceptions.HTTPError as e:
                self.logger.error(f"Erro HTTP ao carregar catálogo de '{endpoint}': {e.response.text}")
                break
        
        self.logger.info(f"Carregamento do catálogo '{endpoint}' concluído. Total baixado: {len(all_items)}.")
        return all_items
    
    def get_all_allocatable_areas(self) -> list[dict]:
        endpoint = "/areas"
        params = {"$select": "id,name,path,allocateData", "$orderby": "id", "$top": 30}
        all_areas = self._paginated_catalog_loader(endpoint, params)
        return [area for area in all_areas if area.get("allocateData")]
    
    def get_all_task_types_and_subtypes(self) -> dict:
        self.logger.info("Buscando Tipos de Tarefa (passo 1/2)...")
        task_types = self._paginated_catalog_loader(
            "/UpdateAppointmentTaskTypes",
            {"$filter": "isTaskType eq true", "$select": "id,name", "$orderby": "id", "$top": 30}
        )
        
        self.logger.info("Buscando todos os Subtipos (passo 2/2)...")
        all_subtypes = self._paginated_catalog_loader(
            "/UpdateAppointmentTaskSubtypes",
            {"$select": "id,name,parentTypeId", "$orderby": "id", "$top": 30}
        )

        task_type_ids = {self._to_int(t["id"]) for t in task_types if t.get("id") is not None}
        relevant_subtypes = [st for st in all_subtypes if self._to_int(st.get("parentTypeId")) in task_type_ids]
        
        missing_parents = sorted({
            self._to_int(st["parentTypeId"]) for st in all_subtypes 
            if st.get("parentTypeId") and self._to_int(st.get("parentTypeId")) not in task_type_ids
        })
        if missing_parents:
            self.logger.warning(f"{len(missing_parents)} IDs de pais de subtipos não foram encontrados nos tipos de tarefa: {missing_parents[:20]}...")

        self.logger.info(f"Join concluído: {len(task_types)} tipos, {len(relevant_subtypes)} subtipos relevantes.")
        
        return {"types": task_types, "subtypes": relevant_subtypes}

    def get_all_users(self) -> list[dict]:
        """
        Busca todos os usuários do Legal One.
        """
        self.logger.info("Buscando todos os usuários...")
        endpoint = "/Users"
        params = {
            "$select": "id,name,email,isActive",
            "$orderby": "id",
            "$top": 30
        }
        return self._paginated_catalog_loader(endpoint, params)

    def search_lawsuit_by_cnj(self, cnj_number: str) -> Optional[Dict[str, Any]]:
        """
        Busca um processo (Lawsuit) pelo seu número CNJ.
        Retorna o primeiro resultado encontrado ou None.
        """
        self.logger.info(f"Buscando processo com CNJ: {cnj_number}")
        endpoint = "/Lawsuits"
        # OData filter requires strings to be in single quotes
        params = {
            "$filter": f"identifierNumber eq '{cnj_number}'",
            "$select": "id,identifierNumber,responsibleOfficeId",
            "$top": 1
        }
        url = f"{self.base_url}{endpoint}"
        try:
            response = self._request_with_retry("GET", url, params=params)
            data = response.json()
            results = data.get("value", [])
            if results:
                lawsuit = results[0]
                self.logger.info(f"Processo encontrado: ID {lawsuit.get('id')} para o CNJ {cnj_number}")
                return lawsuit
            else:
                self.logger.warning(f"Nenhum processo encontrado para o CNJ: {cnj_number}")
                return None
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao buscar processo por CNJ '{cnj_number}': {e.response.text}")
            return None
        except Exception as e:
            self.logger.error(f"Erro inesperado ao buscar processo por CNJ '{cnj_number}': {e}")
            return None

    def create_task(self, task_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Cria uma nova tarefa no Legal One.
        Retorna o dicionário da tarefa criada ou None em caso de erro.
        """
        self.logger.info(f"Criando tarefa com payload: {task_payload}")
        endpoint = "/Tasks"
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self._request_with_retry("POST", url, json=task_payload)
            created_task = response.json()
            self.logger.info(f"Tarefa criada com sucesso. ID: {created_task.get('id')}")
            return created_task
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao criar tarefa: {e.response.text}")
            return None
        except Exception as e:
            self.logger.error(f"Erro inesperado ao criar tarefa: {e}")
            return None

    def link_task_to_lawsuit(self, task_id: int, lawsuit_id: int) -> bool:
        """
        Cria uma relação entre uma tarefa e um processo (Litigation).
        """
        self.logger.info(f"Vinculando tarefa ID {task_id} ao processo ID {lawsuit_id}")
        endpoint = f"/tasks/{task_id}/relationships"
        url = f"{self.base_url}{endpoint}"
        payload = {
            "linkType": "Litigation",
            "linkId": lawsuit_id
        }
        
        try:
            # A resposta pode ser 201 ou 204, sem corpo JSON.
            self._request_with_retry("POST", url, json=payload)
            self.logger.info("Vínculo entre tarefa e processo criado com sucesso.")
            return True
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao vincular tarefa {task_id} ao processo {lawsuit_id}: {e.response.text}")
            return False

    def add_participant_to_task(self, task_id: int, contact_id: int, is_responsible: bool = False, is_requester: bool = False, is_executer: bool = False) -> bool:
        """
        Adiciona um participante a uma tarefa.
        """
        self.logger.info(f"Adicionando participante (contato ID {contact_id}) à tarefa ID {task_id}")
        endpoint = f"/tasks/{task_id}/participants"
        url = f"{self.base_url}{endpoint}"
        payload = {
            "contact": {"id": contact_id},
            "isResponsible": is_responsible,
            "isRequester": is_requester,
            "isExecuter": is_executer
        }
        
        try:
            self._request_with_retry("POST", url, json=payload)
            self.logger.info(f"Participante adicionado com sucesso à tarefa {task_id}.")
            return True
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"Erro HTTP ao adicionar participante à tarefa {task_id}: {e.response.text}")
            return False
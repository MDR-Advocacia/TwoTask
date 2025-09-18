# feat(client): enrich lawsuit with area hierarchy and main responsible person
# file: app/services/legal_one_client.py

import requests
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    """
    Cliente para interagir com a API Legal One, enriquecendo dados de processos com
    hierarquia de áreas e identificação do responsável principal.
    """

    class _CacheManager:
        """Cache singleton genérico para armazenar catálogos da API."""
        _instance: Optional['_CacheManager'] = None
        _caches: Dict[str, Dict] = {
            "areas": {},
            "positions": {}
        }
        _last_load_times: Dict[str, Optional[datetime]] = {
            "areas": None,
            "positions": None
        }
        CACHE_TTL = timedelta(hours=1)

        def __new__(cls):
            if cls._instance is None:
                cls._instance = super(LegalOneApiClient._CacheManager, cls).__new__(cls)
            return cls._instance

        def is_stale(self, cache_name: str) -> bool:
            return not self._caches[cache_name] or not self._last_load_times[cache_name] or \
                   datetime.now() > self._last_load_times[cache_name] + self.CACHE_TTL

        def get(self, cache_name: str, item_id: int) -> Optional[Any]:
            return self._caches.get(cache_name, {}).get(item_id)

        def populate(self, cache_name: str, items: List[Dict[str, Any]]):
            self._caches[cache_name] = {int(item['id']): item for item in items}
            self._last_load_times[cache_name] = datetime.now()
            logging.info(f"Cache '{cache_name}' populado com {len(self._caches[cache_name])} registros.")

    def __init__(self):
        self.base_url = os.environ.get("LEGAL_ONE_BASE_URL")
        self.client_id = os.environ.get("LEGAL_ONE_CLIENT_ID")
        self.client_secret = os.environ.get("LEGAL_ONE_CLIENT_SECRET")
        self._token = None
        self._token_expiry = datetime.now()
        self._cache_manager = self._CacheManager()
        if not all([self.base_url, self.client_id, self.client_secret]):
            raise ValueError("As variáveis de ambiente da API Legal One devem ser configuradas.")

    def _refresh_token_if_needed(self):
        if datetime.now() >= self._token_expiry - timedelta(seconds=60):
            logging.info("Token expirado. Solicitando um novo.")
            auth_url = "https://api.thomsonreuters.com/legalone/oauth?grant_type=client_credentials"
            try:
                response = requests.post(auth_url, auth=(self.client_id, self.client_secret))
                response.raise_for_status()
                data = response.json()
                self._token = data["access_token"]
                expires_in = int(data.get("expires_in", 1800))
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
            except requests.exceptions.RequestException as e:
                logging.error(f"Falha ao obter token: {e}")
                raise

    def _authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}", **kwargs.pop("headers", {})}
        return requests.request(method, url, headers=headers, timeout=30, **kwargs)

    def _paginated_catalog_loader(self, endpoint: str, params: dict) -> List[Dict[str, Any]]:
        """Motor genérico para carregar catálogos paginados via @odata.nextLink."""
        all_items = []
        next_url = f"{self.base_url}{endpoint}"
        
        while next_url:
            try:
                logging.info(f"Buscando página do catálogo: {next_url}")
                response = self._authenticated_request("GET", next_url, params=params)
                response.raise_for_status()
                data = response.json()
                
                all_items.extend(data.get("value", []))
                next_url = data.get("@odata.nextLink")
                params = None
            except requests.exceptions.HTTPError as e:
                logging.error(f"Erro HTTP ao carregar catálogo de '{endpoint}': {e.response.text}")
                break
        
        logging.info(f"Carregamento do catálogo '{endpoint}' concluído. Total: {len(all_items)}.")
        return all_items

    def _ensure_cache_is_fresh(self, cache_name: str, endpoint: str, params: dict):
        """Garante que um cache específico esteja populado, carregando se necessário."""
        if self._cache_manager.is_stale(cache_name):
            items = self._paginated_catalog_loader(endpoint, params)
            self._cache_manager.populate(cache_name, items)

    def get_enriched_lawsuit_data(self, identifier_number: str) -> Optional[dict]:
        """
        Busca e enriquece os dados de um processo com a hierarquia da área responsável
        e a identificação do participante responsável principal.
        """
        # 1. Carregar Caches necessários
        self._ensure_cache_is_fresh(
            cache_name="areas",
            endpoint="/areas",
            params={"$select": "id,name,path,parentAreaId", "$filter": "allocateData eq true", "$top": 30}
        )
        self._ensure_cache_is_fresh(
            cache_name="positions",
            endpoint="/LitigationParticipantPositions",
            params={"$select": "id,name", "$top": 30}
        )

        # 2. Buscar o processo, já expandindo os participantes
        lawsuit_data = self._get_lawsuit_with_participants(identifier_number)
        if not lawsuit_data:
            return None

        # 3. Enriquecer com a Hierarquia da Área Responsável
        area_id = lawsuit_data.get("responsibleOfficeId")
        if area_id:
            area_info = self._cache_manager.get("areas", area_id)
            if area_info:
                lawsuit_data["responsibleArea"] = {
                    "name": area_info.get("name"),
                    "path": area_info.get("path"),
                    "hierarchy": area_info.get("path", "").split("/")
                }
            else:
                lawsuit_data["responsibleArea"] = {"name": "Área não encontrada no cache"}
        
        # 4. Enriquecer com o Responsável Principal (PersonInCharge)
        main_responsible = self._find_main_responsible(lawsuit_data.get("participants", []))
        if main_responsible:
            lawsuit_data["mainResponsible"] = main_responsible

        # Limpeza final
        lawsuit_data.pop("participants", None) # Remove a lista original de participantes
        lawsuit_data.pop("responsibleOfficeId", None) # Remove o ID redundante

        return lawsuit_data

    def _get_lawsuit_with_participants(self, identifier_number: str) -> Optional[dict]:
        """Busca os dados do processo, incluindo a lista de participantes."""
        url = f"{self.base_url}/Lawsuits"
        params = {
            "$filter": f"identifierNumber eq '{identifier_number}'",
            "$select": "id,folder,identifierNumber,responsibleOfficeId",
            "$expand": "participants($select=type,contactName,isMainParticipant,positionId)"
        }
        logging.info(f"Buscando processo e participantes para '{identifier_number}'")
        try:
            response = self._authenticated_request("GET", url, params=params)
            response.raise_for_status()
            data = response.json()
            return data["value"][0] if data.get("value") else None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar processo com participantes: {e}")
            raise

    def _find_main_responsible(self, participants: List[Dict]) -> Optional[Dict]:
        """Encontra o PersonInCharge principal na lista de participantes."""
        responsible_participants = [p for p in participants if p.get("type") == "PersonInCharge"]
        if not responsible_participants:
            return None
        
        # Prioriza quem está marcado como 'isMainParticipant', senão pega o primeiro da lista.
        main_person = next((p for p in responsible_participants if p.get("isMainParticipant")), responsible_participants[0])
        
        position_id = main_person.get("positionId")
        position_name = None
        if position_id:
            position_info = self._cache_manager.get("positions", position_id)
            if position_info:
                position_name = position_info.get("name")

        return {
            "name": main_person.get("contactName"),
            "position": position_name or "Cargo não informado"
        }
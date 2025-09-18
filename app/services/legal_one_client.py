# file: app/services/legal_one_client.py

import requests
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    def __init__(self):
        self.base_url = os.environ.get("LEGAL_ONE_BASE_URL")
        self.client_id = os.environ.get("LEGAL_ONE_CLIENT_ID")
        self.client_secret = os.environ.get("LEGAL_ONE_CLIENT_SECRET")

        self._token = None
        self._token_expiry = datetime.now()

        if not all([self.base_url, self.client_id, self.client_secret]):
            raise ValueError("As variáveis de ambiente LEGAL_ONE_BASE_URL, LEGAL_ONE_CLIENT_ID, e LEGAL_ONE_CLIENT_SECRET devem ser configuradas.")

    def _refresh_token_if_needed(self):
        if datetime.now() >= self._token_expiry - timedelta(seconds=60):
            logging.info("Token expirado ou próximo da expiração. Solicitando um novo token.")
            auth_url = "https://api.thomsonreuters.com/legalone/oauth?grant_type=client_credentials"
            try:
                response = requests.post(auth_url, auth=(self.client_id, self.client_secret))
                response.raise_for_status()
                data = response.json()
                self._token = data["access_token"]
                expires_in = int(data.get("expires_in", 1800))
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logging.info(f"Novo token obtido. Válido até: {self._token_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Falha crítica ao obter token de autenticação: {e}")
                raise

    def get_lawsuit_by_identifier(self, identifier_number: str) -> dict:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{self.base_url}/Lawsuits"
        
        # OTIMIZAÇÃO: Usando $expand para já trazer os participantes na mesma chamada.
        params = {
            "$filter": f"identifierNumber eq '{identifier_number}'",
            "$expand": "participants"
        }
        
        try:
            logging.info(f"Buscando processo com $filter em identifierNumber='{identifier_number}' e expandindo 'participants'")
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data and data.get("value"):
                return data["value"][0]
            logging.warning(f"Nenhum processo encontrado com o Número CNJ '{identifier_number}'")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar processo '{identifier_number}': {e}")
            raise

    def get_office_department_name(self, office_id: int) -> str:
        """NOVO: Busca o nome de um escritório/departamento pelo ID."""
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{self.base_url}/OfficesDepartments/{office_id}"
        try:
            logging.info(f"Buscando nome do escritório com ID: {office_id}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get("name")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar escritório ID '{office_id}': {e}")
            return None # Retorna None em caso de erro para não quebrar o fluxo

    def get_contact_name(self, contact_id: int) -> str:
        """NOVO: Busca o nome de um contato pelo ID."""
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{self.base_url}/Contacts/{contact_id}"
        try:
            logging.info(f"Buscando nome do contato com ID: {contact_id}")
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            return data.get("name")
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar contato ID '{contact_id}': {e}")
            return None

    # ... (método post_task permanece o mesmo) ...
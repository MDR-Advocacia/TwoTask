# file: app/services/legal_one_client.py

import requests
import os
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    def __init__(self):
        # A URL base para os RECURSOS da API (processos, tarefas, etc.)
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
            
            # CORREÇÃO: A URL de autenticação é fixa e não depende da self.base_url dos recursos.
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
        
        # Agora a URL de busca é construída corretamente a partir da base_url correta
        url = f"{self.base_url}/litigation/lawsuits"
        params = {"q": f'identifierNumber:"{identifier_number}"'}
        
        try:
            logging.info(f"Buscando processo com Número CNJ '{identifier_number}' na URL: {url}")
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            if data and data.get("items"):
                return data["items"][0]
            logging.warning(f"Nenhum processo encontrado com o Número CNJ '{identifier_number}'")
            return None
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar processo '{identifier_number}': {e}")
            raise

    # ... (outros métodos como post_task ficariam aqui) ...
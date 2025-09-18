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
            auth_url = f"{self.base_url}/legalone/oauth?grant_type=client_credentials"
            try:
                response = requests.post(auth_url, auth=(self.client_id, self.client_secret))
                response.raise_for_status()
                data = response.json()
                self._token = data["access_token"]
                
                # CORREÇÃO: Converte o valor de 'expires_in' para um inteiro.
                expires_in = int(data.get("expires_in", 1800)) 
                
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logging.info(f"Novo token obtido. Válido até: {self._token_expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            except requests.exceptions.RequestException as e:
                logging.error(f"Falha crítica ao obter token de autenticação: {e}")
                raise

    def post_task(self, task_payload: dict) -> dict:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        url = f"{self.base_url}/legalone/v1/api/rest/tasks"
        try:
            logging.info(f"Enviando requisição POST para {url}")
            response = requests.post(url, json=task_payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro na chamada à API do Legal One para criar tarefa: {e}")
            raise

    def get_lawsuit_by_identifier(self, identifier_number: str) -> dict:
        self._refresh_token_if_needed()
        headers = {"Authorization": f"Bearer {self._token}"}
        url = f"{self.base_url}/legalone/v1/api/rest/litigation/lawsuits"
        params = {"q": f'identifierNumber:"{identifier_number}"'}
        try:
            logging.info(f"Buscando processo com Número CNJ '{identifier_number}'")
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
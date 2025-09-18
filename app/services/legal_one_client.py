# file: app/services/legal_one_client.py

import requests
import os
import logging
from datetime import datetime, timedelta

# Configura um logger para nos dar visibilidade sobre o que o cliente está fazendo
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LegalOneApiClient:
    """
    Cliente de baixo nível, responsável por toda a comunicação HTTP
    com a API do Legal One.
    """

    def __init__(self):
        """
        Inicializa o cliente e carrega a configuração a partir de 
        variáveis de ambiente.
        """
        self.base_url = os.environ.get("LEGAL_ONE_BASE_URL")
        self.client_id = os.environ.get("LEGAL_ONE_CLIENT_ID")
        self.client_secret = os.environ.get("LEGAL_ONE_CLIENT_SECRET")
        
        self._token = None
        self._token_expiry = datetime.now()

        if not all([self.base_url, self.client_id, self.client_secret]):
            raise ValueError("As variáveis de ambiente LEGAL_ONE_BASE_URL, LEGAL_ONE_CLIENT_ID, e LEGAL_ONE_CLIENT_SECRET devem ser configuradas.")

    def _refresh_token_if_needed(self):
        """
        Verifica se o token atual está prestes a expirar (ou já expirou)
        e, se necessário, obtém um novo.
        """
        # Usamos um buffer de 60 segundos para renovar o token ANTES que ele expire.
        if datetime.now() >= self._token_expiry - timedelta(seconds=60):
            logging.info("Token expirado ou próximo da expiração. Solicitando um novo token.")
            
            # O endpoint de autenticação é separado do endpoint da API REST.
            auth_url = f"{self.base_url}/legalone/oauth?grant_type=client_credentials"
            
            try:
                response = requests.post(auth_url, auth=(self.client_id, self.client_secret))
                response.raise_for_status()  # Lança uma exceção para erros HTTP (4xx ou 5xx)
                
                data = response.json()
                self._token = data["access_token"]
                
                # Usamos o tempo de vida retornado pela API, com um padrão de 1800s (30 min)
                expires_in = data.get("expires_in", 1800) 
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                
                logging.info(f"Novo token obtido. Válido até: {self._token_expiry.strftime('%Y-%m-%d %H:%M:%S')}")

            except requests.exceptions.RequestException as e:
                logging.error(f"Falha crítica ao obter token de autenticação: {e}")
                # Re-lança a exceção para que a chamada que originou a tentativa falhe.
                raise

    def post_task(self, task_payload: dict, tenant_id: str) -> dict:
        """
        Envia a requisição de criação de tarefa para a API.
        
        Args:
            task_payload: Um dicionário representando o JSON a ser enviado.
            tenant_id: O ID do tenant, para ser passado nos cabeçalhos.

        Returns:
            A resposta da API em formato de dicionário.
        """
        self._refresh_token_if_needed()
        
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-Tenant-ID": tenant_id  # Exemplo de como um ID de tenant pode ser passado
        }
        
        url = f"{self.base_url}/legalone/v1/api/rest/tasks"
        
        try:
            logging.info(f"Enviando requisição POST para {url} para o tenant {tenant_id}")
            response = requests.post(url, json=task_payload, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Erro na chamada à API do Legal One para criar tarefa: {e}")
            # Em um cenário real, poderíamos inspecionar e.response.json() para mais detalhes do erro.
            raise

    def get_lawsuit_by_folder(self, folder_number: str, tenant_id: str) -> dict:
        """
        Busca um processo (lawsuit) no Legal One pelo número da pasta.
        
        Args:
            folder_number: O número do processo/pasta.
            tenant_id: O ID do tenant para a requisição.

        Returns:
            Os dados do processo encontrados.
        """
        self._refresh_token_if_needed()
        
        headers = {
            "Authorization": f"Bearer {self._token}",
            "X-Tenant-ID": tenant_id
        }
        
        # Conforme nossa análise, a busca é feita via query string 'q'
        url = f"{self.base_url}/legalone/v1/api/rest/litigation/lawsuits"
        params = {"q": f'folder:"{folder_number}"'}
        
        try:
            logging.info(f"Buscando processo com pasta '{folder_number}' para o tenant {tenant_id}")
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            # A API retorna uma lista de itens, mesmo buscando por um campo único
            if data and data.get("items"):
                return data["items"][0] # Retornamos o primeiro resultado encontrado
            
            # Se a lista de itens estiver vazia, significa que não foi encontrado
            logging.warning(f"Nenhum processo encontrado com a pasta '{folder_number}'")
            return None

        except requests.exceptions.RequestException as e:
            logging.error(f"Erro ao buscar processo '{folder_number}': {e}")
            raise
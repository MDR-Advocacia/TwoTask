# file: app/core/squad_manager.py

import requests
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO)

class SquadManager:
    """
    Gerencia o carregamento e o cache das configurações de SQUADS
    a partir de uma API externa.
    """
    _instance: Optional['SquadManager'] = None
    _squad_config: Dict[str, Any] = {}
    _last_load_time: Optional[datetime] = None
    CACHE_TTL = timedelta(days=1)

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SquadManager, cls).__new__(cls)
        return cls._instance

    def _is_cache_stale(self) -> bool:
        if not self._squad_config or not self._last_load_time:
            return True
        return datetime.now() > self._last_load_time + self.CACHE_TTL

    def _translate_supabase_data(self, data: list) -> dict:
        """
        Converte a estrutura de dados do Supabase para o formato
        interno esperado pela aplicação.
        """
        translated_squads = []
        for squad_data in data:
            leader_id = None
            # O líder pode ou não existir no objeto principal
            if squad_data.get("leader") and squad_data["leader"].get("id"):
                leader_id = squad_data["leader"]["id"]

            translated_members = []
            for member_data in squad_data.get("members", []):
                translated_members.append({
                    "user_id": member_data.get("id"),
                    "name": member_data.get("name")
                })
            
            # Adiciona o líder à lista de membros, se ele não estiver lá
            if leader_id and not any(m['user_id'] == leader_id for m in translated_members):
                 translated_members.append({
                    "user_id": leader_id,
                    "name": squad_data["leader"].get("name")
                })

            translated_squads.append({
                "squad_id": squad_data.get("id"),
                "squad_name": squad_data.get("name"),
                "squad_leader_id": leader_id,
                "members": translated_members
            })
        
        # Retorna no formato que o frontend e o orquestrador esperam
        return {"squads": translated_squads}


    def force_refresh(self) -> Dict[str, Any]:
        squads_url = os.environ.get("SQUADS_API_URL")
        anon_key = os.environ.get("SUPABASE_ANON_KEY")

        if not squads_url or not anon_key:
            error_msg = "As variáveis SQUADS_API_URL e SUPABASE_ANON_KEY devem ser configuradas."
            logging.error(error_msg)
            self._squad_config = {"error": error_msg}
            return self._squad_config
        
        headers = {"apikey": anon_key, "Authorization": f"Bearer {anon_key}"}
        
        logging.info(f"Buscando configuração de SQUADS em: {squads_url}")
        try:
            response = requests.get(squads_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Recebe a lista de dados brutos
            raw_data = response.json()
            
            # Traduz para o formato padronizado e armazena em cache
            self._squad_config = self._translate_supabase_data(raw_data)
            
            self._last_load_time = datetime.now()
            logging.info("Configuração de SQUADS carregada, traduzida e cacheada com sucesso.")
            return {"status": "success", "message": "Cache de SQUADS atualizado."}
        except requests.exceptions.RequestException as e:
            logging.error(f"Falha ao buscar dados da API de SQUADS: {e}")
            self._squad_config = {"error": str(e)}
            return {"status": "error", "message": str(e)}

    def get_config(self) -> Dict[str, Any]:
        if self._is_cache_stale():
            logging.info("Cache de SQUADS expirado ou vazio. Recarregando.")
            self.force_refresh()
        return self._squad_config

squad_manager = SquadManager()

def get_squad_manager() -> SquadManager:
    return squad_manager
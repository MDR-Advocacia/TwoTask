# app/services/squad_sync_service.py

import os
import logging
import json # Import json para o tratamento de erro
from uuid import UUID
import httpx
from sqlalchemy.orm import Session
from sqlalchemy import select, update

# Corrigido: Importar os modelos corretos
from app.models.rules import Squad, SquadMember

class SquadSyncService:
    """
    Serviço para sincronizar a estrutura de Squads a partir de uma API externa,
    atualizando o banco de dados local para refletir o estado atual.
    """
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = logging.getLogger(__name__)
        self.squads_api_url = os.environ.get("SQUADS_API_URL")

    async def _fetch_squads_from_api(self) -> list:
        """Busca os dados de squads da API configurada."""
        if not self.squads_api_url:
            self.logger.error("A variável de ambiente SQUADS_API_URL não está configurada.")
            raise ValueError("URL da API de Squads não definida.")

        async with httpx.AsyncClient() as client:
            try:
                self.logger.info(f"Buscando squads de: {self.squads_api_url}")
                response = await client.get(self.squads_api_url, timeout=30.0)
                response.raise_for_status()
                return response.json()
            except httpx.RequestError as e:
                self.logger.error(f"Erro ao fazer requisição para a API de Squads: {e}")
                raise
            except json.JSONDecodeError:
                self.logger.error("Falha ao decodificar a resposta JSON da API de Squads.")
                raise

    async def sync_squads(self):
        """
        Orquestra a sincronização completa, buscando dados da API e atualizando o banco.
        """
        self.logger.info("Iniciando processo de sincronização de squads...")
        try:
            squads_from_api = await self._fetch_squads_from_api()

            existing_squads = {s.external_id: s for s in self.db.execute(select(Squad)).scalars()}
            existing_members = {m.external_id: m for m in self.db.execute(select(SquadMember)).scalars()}
            
            # --- MUDANÇA IMPORTANTE AQUI ---
            # Vamos trabalhar com os IDs como strings, que é o que o SQLite entende.
            api_squad_ids = {s['id'] for s in squads_from_api}
            api_member_ids = set()

            for squad_data in squads_from_api:
                # O ID externo agora é tratado como uma string desde o início.
                squad_ext_id_str = squad_data['id']
                squad = existing_squads.get(squad_ext_id_str)

                if not squad:
                    squad = Squad(external_id=squad_ext_id_str)
                    self.db.add(squad)
                    existing_squads[squad_ext_id_str] = squad
                
                squad.name = squad_data['name']
                squad.sector = squad_data['sector']
                squad.is_active = True
                self.db.flush()

                for member_data in squad_data.get('members', []):
                    # O ID do membro também é uma string.
                    member_ext_id_str = member_data['id']
                    api_member_ids.add(member_ext_id_str)
                    member = existing_members.get(member_ext_id_str)

                    if not member:
                        member = SquadMember(external_id=member_ext_id_str)
                        self.db.add(member)
                    
                    member.name = member_data['name']
                    member.role = member_data.get('role')
                    member.is_leader = member_data.get('is_leader', False)
                    member.squad_id = squad.id
                    member.is_active = True

            # Lógica de desativação (soft delete)
            inactive_squad_ids = set(existing_squads.keys()) - api_squad_ids
            if inactive_squad_ids:
                stmt = update(Squad).where(Squad.external_id.in_(inactive_squad_ids)).values(is_active=False)
                self.db.execute(stmt)

            inactive_member_ids = set(existing_members.keys()) - api_member_ids
            if inactive_member_ids:
                stmt = update(SquadMember).where(SquadMember.external_id.in_(inactive_member_ids)).values(is_active=False)
                self.db.execute(stmt)

            self.db.commit()
            self.logger.info("Sincronização de squads via API concluída com sucesso.")

        except Exception as e:
            self.logger.error(f"Falha na sincronização de squads: {e}", exc_info=True)
            self.db.rollback()
            raise
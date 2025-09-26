# Conteúdo COMPLETO E CORRIGIDO para: app/services/metadata_sync_service.py

import logging
from sqlalchemy.orm import Session
from sqlalchemy import select, update

# Correção no import para alinhar com o Alembic
from app.models.legal_one import LegalOneOffice, LegalOneTaskType, LegalOneUser
from app.services.legal_one_client import LegalOneApiClient

class MetadataSyncService:
    """
    Serviço responsável por sincronizar metadados essenciais
    do Legal One para o banco de dados local.
    """

    def __init__(self, db_session: Session):
        self.db = db_session # Usando self.db, conforme seu padrão
        self.api_client = LegalOneApiClient()
        self.logger = logging.getLogger(__name__)
        # Helper para conversão segura que já existe no seu client
        self._to_int = self.api_client._to_int

    async def _sync_offices(self):
        """Sincroniza escritórios (allocatable areas)."""
        self.logger.info("Sincronizando escritórios...")
        try:
            areas_from_api = self.api_client.get_all_allocatable_areas()
            if not areas_from_api:
                self.logger.warning("Nenhum escritório encontrado na API.")
                return

            stmt = select(LegalOneOffice)
            existing_offices_map = {o.external_id: o for o in self.db.execute(stmt).scalars()}
            api_ids = {self._to_int(area.get('id')) for area in areas_from_api}

            count_add, count_update = 0, 0
            for area_data in areas_from_api:
                external_id = self._to_int(area_data.get("id"))
                if not external_id: continue

                office = existing_offices_map.get(external_id)
                if office:
                    if office.name != area_data.get("name") or office.path != area_data.get("path") or not office.is_active:
                        office.name = area_data.get("name")
                        office.path = area_data.get("path")
                        office.is_active = True
                        count_update += 1
                else:
                    new_office = LegalOneOffice(
                        external_id=external_id,
                        name=area_data.get("name"),
                        path=area_data.get("path")
                    )
                    self.db.add(new_office)
                    count_add += 1
            
            inactive_ids = set(existing_offices_map.keys()) - api_ids
            if inactive_ids:
                stmt = update(LegalOneOffice).where(LegalOneOffice.external_id.in_(inactive_ids)).values(is_active=False)
                self.db.execute(stmt)

            self.db.commit()
            self.logger.info(f"Sincronização de escritórios concluída. Adicionados: {count_add}, Atualizados: {count_update + len(inactive_ids)}.")
        except Exception as e:
            self.logger.error(f"Falha ao sincronizar escritórios: {e}", exc_info=True)
            self.db.rollback()
            raise

    async def _sync_task_types(self):
        """Sincroniza Tipos e Subtipos de Tarefa em um único modelo hierárquico."""
        self.logger.info("Sincronizando Tipos e Subtipos de Tarefa...")
        try:
            data = self.api_client.get_all_task_types_and_subtypes()
            types_from_api = data.get("types", [])
            subtypes_from_api = data.get("subtypes", [])

            stmt = select(LegalOneTaskType)
            existing_map = {tt.external_id: tt for tt in self.db.execute(stmt).scalars()}

            # Processa os tipos primeiro
            for type_data in types_from_api:
                external_id = self._to_int(type_data.get("id"))
                if not external_id: continue
                
                if external_id not in existing_map:
                    new_type = LegalOneTaskType(external_id=external_id, name=type_data.get("name"))
                    self.db.add(new_type)
                    existing_map[external_id] = new_type
                else:
                    existing_map[external_id].name = type_data.get("name")
                    existing_map[external_id].is_active = True # Reativa se necessário

            self.db.flush() # Garante que os tipos pais existam antes de associar subtipos

            # Coleta os IDs externos dos tipos pais para evitar que sejam tratados como subtipos
            parent_external_ids = {self._to_int(t.get("id")) for t in types_from_api if t.get("id")}

            # Processa os subtipos
            for subtype_data in subtypes_from_api:
                external_id = self._to_int(subtype_data.get("id"))
                parent_id = self._to_int(subtype_data.get("parentTypeId"))
                if not external_id or not parent_id: continue

                # CORREÇÃO: Ignora a atualização de um tipo pai como se fosse um subtipo
                if external_id in parent_external_ids:
                    continue

                parent_obj = existing_map.get(parent_id)
                if not parent_obj: continue # Pula se o pai não foi encontrado

                if external_id not in existing_map:
                    new_subtype = LegalOneTaskType(
                        external_id=external_id,
                        name=subtype_data.get("name"),
                        parent_id=parent_obj.id # Associa ao ID interno do pai
                    )
                    self.db.add(new_subtype)
                else:
                    existing_map[external_id].name = subtype_data.get("name")
                    existing_map[external_id].parent_id = parent_obj.id
                    existing_map[external_id].is_active = True
            
            self.db.commit()
            self.logger.info("Sincronização de Tipos e Subtipos de Tarefa concluída.")
        except Exception as e:
            self.logger.error(f"Falha ao sincronizar tipos de tarefa: {e}", exc_info=True)
            self.db.rollback()
            raise

    async def _sync_users(self):
        """Busca todos os usuários e atualiza o banco local."""
        self.logger.info("Iniciando sincronização de Usuários...")
        try:
            api_users = self.api_client.get_all_users()
            if not api_users:
                self.logger.warning("Nenhum usuário encontrado na API para sincronizar.")
                return

            stmt = select(LegalOneUser)
            existing_users_map = {u.external_id: u for u in self.db.execute(stmt).scalars()}
            api_ids = {self._to_int(user.get('id')) for user in api_users}

            count_add, count_update = 0, 0
            for user_data in api_users:
                external_id = self._to_int(user_data.get("id"))
                if not external_id: continue

                existing_user = existing_users_map.get(external_id)
                if existing_user:
                    # Atualiza campos que podem mudar
                    if (existing_user.name != user_data.get("name") or
                        existing_user.email != user_data.get("email") or
                        existing_user.is_active != user_data.get("isActive")):
                        existing_user.name = user_data.get("name")
                        existing_user.email = user_data.get("email")
                        existing_user.is_active = user_data.get("isActive")
                        count_update += 1
                else:
                    new_user = LegalOneUser(
                        external_id=external_id,
                        name=user_data.get("name"),
                        email=user_data.get("email"),
                        is_active=user_data.get("isActive", True)
                    )
                    self.db.add(new_user)
                    count_add += 1
            
            inactive_ids = set(existing_users_map.keys()) - api_ids
            if inactive_ids:
                stmt = update(LegalOneUser).where(LegalOneUser.external_id.in_(inactive_ids)).values(is_active=False)
                self.db.execute(stmt)
                count_update += len(inactive_ids)

            self.db.commit()
            self.logger.info(f"Sincronização de usuários concluída. Adicionados: {count_add}, Atualizados/Inativados: {count_update}.")

        except Exception as e:
            self.logger.error(f"Falha ao sincronizar usuários: {e}", exc_info=True)
            self.db.rollback() # Corrigido para self.db
            raise

    async def sync_all_metadata(self):
        """Orquestra a sincronização de todas as entidades de metadados."""
        self.logger.info("Iniciando ciclo completo de sincronização de metadados...")
        try:
            await self._sync_offices()
            await self._sync_task_types()
            await self._sync_users()
            self.logger.info("Ciclo completo de sincronização de metadados finalizado com sucesso.")
        except Exception as e:
            self.logger.error(f"O ciclo de sincronização de metadados falhou: {e}", exc_info=True)
            # A exceção já foi tratada e feito rollback no método específico, aqui apenas registramos o erro geral.
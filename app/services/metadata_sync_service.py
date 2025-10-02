# app/services/metadata_sync_service.py

import logging
from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneApiClient
from app.models.legal_one import (
    LegalOneOffice,
    LegalOneUser,
    LegalOneTaskType,
    LegalOneTaskSubType
)

logging.basicConfig(level=logging.INFO)

class MetadataSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.legal_one_client = LegalOneApiClient()
        self.logger = logging.getLogger(__name__)

    def sync_all_metadata(self):
        """Orquestra a sincronização de todos os metadados essenciais."""
        self.logger.info("Iniciando sincronização completa de metadados...")
        try:
            self.sync_offices()
            self.sync_users()
            self.sync_task_types_and_subtypes()
            self.logger.info("Sincronização completa de metadados concluída com sucesso.")
        except Exception as e:
            self.logger.error(f"Erro crítico durante a sincronização de metadados: {e}", exc_info=True)

    def sync_offices(self):
        """Sincroniza os escritórios do Legal One com o banco de dados local."""
        # (Este método permanece o mesmo - código omitido por brevidade)
        self.logger.info("Sincronizando escritórios (Offices)...")
        try:
            offices_data = self.legal_one_client.get_all_allocatable_areas()
            if not offices_data:
                self.logger.warning("Nenhum escritório alocável encontrado na API do Legal One.")
                return
            with self.db.begin_nested():
                existing_offices = {o.external_id: o for o in self.db.query(LegalOneOffice).all()}
                for office_data in offices_data:
                    external_id = office_data.get('id')
                    if not external_id:
                        continue
                    office = existing_offices.get(external_id)
                    if office:
                        office.name = office_data.get('name')
                        office.path = office_data.get('path')
                        office.is_active = True 
                    else:
                        new_office = LegalOneOffice(
                            external_id=external_id,
                            name=office_data.get('name'),
                            path=office_data.get('path'),
                            is_active=True
                        )
                        self.db.add(new_office)
                active_external_ids = {o['id'] for o in offices_data}
                for external_id, office in existing_offices.items():
                    if external_id not in active_external_ids:
                        office.is_active = False
            self.db.commit()
            self.logger.info("Sincronização de escritórios concluída.")
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Erro ao sincronizar escritórios: {e}", exc_info=True)


    def sync_users(self):
        """Sincroniza os usuários do Legal One com o banco de dados local."""
        # (Este método permanece o mesmo - código omitido por brevidade)
        self.logger.info("Sincronizando usuários (Users)...")
        try:
            users_data = self.legal_one_client.get_all_users()
            if not users_data:
                self.logger.warning("Nenhum usuário encontrado na API do Legal One.")
                return
            with self.db.begin_nested():
                existing_users = {u.external_id: u for u in self.db.query(LegalOneUser).all()}
                for user_data in users_data:
                    external_id = user_data.get('id')
                    if not external_id:
                        continue
                    user = existing_users.get(external_id)
                    if user:
                        user.name = user_data.get('name')
                        user.email = user_data.get('email')
                        user.is_active = user_data.get('isActive', False)
                    else:
                        new_user = LegalOneUser(
                            external_id=external_id,
                            name=user_data.get('name'),
                            email=user_data.get('email'),
                            is_active=user_data.get('isActive', False)
                        )
                        self.db.add(new_user)
                active_external_ids = {u['id'] for u in users_data if u.get('isActive')}
                for external_id, user in existing_users.items():
                    if external_id not in active_external_ids:
                        user.is_active = False
            self.db.commit()
            self.logger.info("Sincronização de usuários concluída.")
        except Exception as e:
            self.db.rollback()
            self.logger.error(f"Erro ao sincronizar usuários: {e}", exc_info=True)


    def sync_task_types_and_subtypes(self):
        """
        Sincroniza tipos e subtipos de tarefas com uma lógica hierárquica robusta.
        """
        self.logger.info("Iniciando sincronização de tipos e subtipos de tarefas...")
        try:
            # 1. Buscar todos os dados brutos da API
            self.logger.info("Buscando todos os tipos de tarefa (pais)...")
            parent_types_data = self.legal_one_client._paginated_catalog_loader(
                "/UpdateAppointmentTaskTypes",
                {"$filter": "isTaskType eq true", "$select": "id,name"}
            )
            self.logger.info(f"Encontrados {len(parent_types_data)} tipos de tarefa pai.")

            self.logger.info("Buscando todos os subtipos de tarefa (filhos)...")
            all_subtypes_data = self.legal_one_client._paginated_catalog_loader(
                "/UpdateAppointmentTaskSubtypes",
                {"$select": "id,name,parentTypeId"}
            )
            self.logger.info(f"Encontrados {len(all_subtypes_data)} subtipos de tarefa.")

            # 2. Organizar subtipos em um dicionário para acesso rápido
            subtypes_map = {}
            for sub_data in all_subtypes_data:
                parent_id = sub_data.get('parentTypeId')
                if parent_id:
                    if parent_id not in subtypes_map:
                        subtypes_map[parent_id] = []
                    subtypes_map[parent_id].append(sub_data)

            # 3. Construir os objetos e a hierarquia em uma única transação
            with self.db.begin() as transaction:
                self.logger.info("Limpando tabelas antigas...")
                self.db.query(LegalOneTaskSubType).delete()
                self.db.query(LegalOneTaskType).delete()

                parent_objects = []
                for parent_data in parent_types_data:
                    # Cria o objeto pai (LegalOneTaskType)
                    parent_obj = LegalOneTaskType(
                        external_id=parent_data['id'],
                        name=parent_data['name'],
                        is_active=True
                    )
                    
                    # Busca os filhos correspondentes no dicionário
                    child_data_list = subtypes_map.get(parent_data['id'], [])
                    
                    # Cria os objetos filhos e os anexa ao pai
                    for child_data in child_data_list:
                        child_obj = LegalOneTaskSubType(
                            external_id=child_data['id'],
                            name=child_data['name'],
                            parent_type_external_id=child_data['parentTypeId'],
                            is_active=True
                        )
                        parent_obj.subtypes.append(child_obj)
                    
                    parent_objects.append(parent_obj)

                self.logger.info(f"Adicionando {len(parent_objects)} tipos de tarefa pai com seus subtipos à sessão.")
                self.db.add_all(parent_objects)

            self.logger.info("Sincronização de tipos e subtipos concluída com sucesso.")
        except Exception as e:
            self.logger.error(f"Erro ao sincronizar tipos e subtipos: {e}", exc_info=True)
            # O 'with self.db.begin()' garante o rollback em caso de erro.
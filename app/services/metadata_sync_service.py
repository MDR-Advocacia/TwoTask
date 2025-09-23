# Conteúdo completo, final e correto para: app/services/metadata_sync_service.py

import logging
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.legal_one import LegalOneOffice, LegalOneTaskType
from app.services.legal_one_client import LegalOneApiClient

class MetadataSyncService:
    """
    Serviço responsável por sincronizar metadados essenciais
    do Legal One para o banco de dados local.
    """

    def __init__(self, db_session: Session):
        self.db = db_session
        self.api_client = LegalOneApiClient()
        self.logger = logging.getLogger(__name__)
        self._to_int = self.api_client._to_int # Reutiliza o conversor seguro do cliente

    async def sync_all_metadata(self):
        """
        Orquestra a sincronização de todos os tipos de metadados.
        Este é o principal ponto de entrada para o processo de sincronização.
        """
        self.logger.info("Iniciando a sincronização de metadados do Legal One...")
        try:
            await self._sync_offices()
            await self._sync_task_types()
            self.logger.info("Sincronização de metadados concluída com sucesso.")
        except Exception as e:
            self.logger.error(f"Falha crítica durante a sincronização de metadados: {e}", exc_info=True)
            self.db.rollback() # Garante que nenhuma alteração parcial seja salva
            raise

    async def _sync_offices(self):
        """
        Busca os escritórios (áreas alocáveis) da API e realiza o 'upsert'
        na tabela local `legal_one_offices`.
        """
        self.logger.info("Sincronizando escritórios...")
        api_offices = self.api_client.get_all_allocatable_areas()
        if not api_offices:
            self.logger.warning("Nenhum escritório encontrado na API para sincronizar.")
            return

        stmt = select(LegalOneOffice)
        existing_offices_map = {o.external_id: o for o in self.db.execute(stmt).scalars()}
        
        count_add, count_update = 0, 0
        for office_data in api_offices:
            external_id = self._to_int(office_data.get("id"))
            if not external_id: continue

            existing_office = existing_offices_map.get(external_id)
            if existing_office:
                if (existing_office.name != office_data.get("name") or 
                    existing_office.path != office_data.get("path")):
                    existing_office.name = office_data.get("name")
                    existing_office.path = office_data.get("path")
                    count_update += 1
            else:
                new_office = LegalOneOffice(
                    external_id=external_id,
                    name=office_data.get("name"),
                    path=office_data.get("path")
                )
                self.db.add(new_office)
                count_add += 1
        
        self.db.commit()
        self.logger.info(f"Sincronização de escritórios concluída. Adicionados: {count_add}, Atualizados: {count_update}.")

    async def _sync_task_types(self):
        """
        Busca os Tipos e Subtipos de Tarefa da API e realiza o 'upsert'
        na tabela local `legal_one_task_types`, preservando a hierarquia.
        """
        self.logger.info("Sincronizando Tipos e Subtipos de Tarefa...")
        api_data = self.api_client.get_all_task_types_and_subtypes()
        api_types = api_data.get("types", [])
        api_subtypes = api_data.get("subtypes", [])

        if not api_types:
            self.logger.warning("Nenhum Tipo de Tarefa principal encontrado na API.")
            return

        # Mapeia os registros existentes no DB por seu ID externo
        stmt = select(LegalOneTaskType)
        existing_types_map = {tt.external_id: tt for tt in self.db.execute(stmt).scalars()}
        
        count_add, count_update = 0, 0
        
        # --- PRIMEIRA PASSADA: Processa os Tipos (pais) ---
        self.logger.info("Processando Tipos (Pais)...")
        for type_data in api_types:
            external_id = self._to_int(type_data.get("id"))
            if not external_id: continue

            existing_type = existing_types_map.get(external_id)
            if existing_type:
                if existing_type.name != type_data.get("name"):
                    existing_type.name = type_data.get("name")
                    count_update += 1
            else:
                new_type = LegalOneTaskType(
                    external_id=external_id,
                    name=type_data.get("name"),
                    parent_id=None # Tipos Pais não têm pai
                )
                self.db.add(new_type)
                existing_types_map[external_id] = new_type # Adiciona ao mapa para a próxima passada
                count_add += 1

        # Salva os tipos pais para garantir que eles tenham IDs antes de processar os filhos
        self.db.commit()
        self.logger.info(f"Tipos (Pais) processados. Adicionados: {count_add}, Atualizados: {count_update}.")

        # --- SEGUNDA PASSADA: Processa os Subtipos (filhos) ---
        self.logger.info("Processando Subtipos (Filhos)...")
        count_add, count_update = 0, 0 # Reseta contadores
        
        # Precisamos de um mapa de external_id -> id_interno para os pais
        parent_internal_id_map = {p.external_id: p.id for p in existing_types_map.values()}

        for subtype_data in api_subtypes:
            external_id = self._to_int(subtype_data.get("id"))
            parent_external_id = self._to_int(subtype_data.get("parentTypeId"))
            if not external_id or not parent_external_id: continue
            
            # Encontra o ID interno do pai no nosso banco de dados
            parent_internal_id = parent_internal_id_map.get(parent_external_id)
            if not parent_internal_id:
                self.logger.warning(f"Subtipo ID externo {external_id} com pai órfão {parent_external_id}. Pulando.")
                continue

            existing_subtype = existing_types_map.get(external_id)
            if existing_subtype:
                if (existing_subtype.name != subtype_data.get("name") or 
                    existing_subtype.parent_id != parent_internal_id):
                    existing_subtype.name = subtype_data.get("name")
                    existing_subtype.parent_id = parent_internal_id
                    count_update += 1
            else:
                new_subtype = LegalOneTaskType(
                    external_id=external_id,
                    name=subtype_data.get("name"),
                    parent_id=parent_internal_id
                )
                self.db.add(new_subtype)
                count_add += 1
        
        self.db.commit()
        self.logger.info(f"Sincronização de Subtipos concluída. Adicionados: {count_add}, Atualizados: {count_update}.")
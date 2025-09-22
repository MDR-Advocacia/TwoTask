# Mova este código para um novo arquivo: app/services/metadata_sync_service.py

from sqlalchemy.orm import Session
from app.services.legal_one_client import LegalOneClient
from app.models.rules import LegalOneTaskType
import logging

logger = logging.getLogger(__name__)

class MetadataSyncService:
    def __init__(self, db_session: Session, l1_client: LegalOneClient):
        self.db = db_session
        self.l1_client = l1_client

    def sync_task_types(self) -> dict:
        """
        Busca os tipos de tarefa da API do Legal One e atualiza o banco de dados local.
        Utiliza uma estratégia de "upsert" para evitar duplicatas e manter os dados
        sincronizados.
        """
        logger.info("Iniciando a sincronização de tipos de tarefa do Legal One.")
        
        try:
            # 1. Busca os dados da API do Legal One
            response_data = self.l1_client.get("/SystemTables/General/TaskTypes")
            task_types_from_api = response_data.get('value', [])
            
            if not task_types_from_api:
                logger.warning("A API do Legal One não retornou tipos de tarefa.")
                return {"status": "warning", "message": "Nenhum tipo de tarefa encontrado."}

            # 2. Prepara os dados para o banco
            stats = {"created": 0, "updated": 0, "total_from_api": len(task_types_from_api)}
            
            for api_task_type in task_types_from_api:
                l1_id = str(api_task_type['id']) # Garante que o ID seja string
                
                # 3. Verifica se o tipo de tarefa já existe no nosso DB
                local_task_type = self.db.query(LegalOneTaskType).filter_by(l1_id=l1_id).first()
                
                # 4. Lógica de Upsert (Update ou Insert)
                if local_task_type:
                    # Se existe, atualiza
                    local_task_type.name = api_task_type.get('name')
                    local_task_type.parent_type = api_task_type.get('parentTypeId')
                    stats["updated"] += 1
                else:
                    # Se não existe, cria
                    new_task_type = LegalOneTaskType(
                        l1_id=l1_id,
                        name=api_task_type.get('name'),
                        parent_type=api_task_type.get('parentTypeId')
                        # 'subtype' não parece estar neste endpoint, então omitimos
                    )
                    self.db.add(new_task_type)
                    stats["created"] += 1
            
            self.db.commit()
            logger.info(f"Sincronização concluída. Criados: {stats['created']}, Atualizados: {stats['updated']}.")
            return {"status": "success", "details": stats}

        except Exception as e:
            logger.error(f"Erro durante a sincronização de tipos de tarefa: {e}", exc_info=True)
            self.db.rollback()
            return {"status": "error", "message": str(e)}
# Criar o arquivo: run_manual_sync.py (na raiz do projeto)

import asyncio
import logging
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Importa os componentes necessários da nossa aplicação
from app.db.session import SessionLocal
from app.services.metadata_sync_service import MetadataSyncService

# Configuração do logging para vermos o progresso detalhado
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s'
)

def run_sync():
    """
    Função principal que executa o processo completo de sincronização de metadados.
    """
    logger = logging.getLogger(__name__)
    logger.info("==========================================================")
    logger.info("= INICIANDO PROCESSO DE SINCRONIZAÇÃO MANUAL DE METADADOS =")
    logger.info("==========================================================")
    
    # Obtém uma nova sessão do banco de dados para esta operação
    db_session = SessionLocal()
    
    try:
        # Cria a instância do nosso serviço, injetando a sessão do DB
        sync_service = MetadataSyncService(db_session=db_session)
        
        # Executa o método principal de forma assíncrona
        asyncio.run(sync_service.sync_all_metadata())
        
        logger.info("----------------------------------------------------------")
        logger.info("✅ PROCESSO DE SINCRONIZAÇÃO CONCLUÍDO COM SUCESSO!")
        logger.info("----------------------------------------------------------")

    except Exception as e:
        logger.error("❌ Ocorreu um erro fatal durante a sincronização.", exc_info=True)
        logger.error("----------------------------------------------------------")
        logger.error("❌ PROCESSO DE SINCRONIZAÇÃO FALHOU.")
        logger.error("----------------------------------------------------------")
    finally:
        # Garante que a sessão do banco de dados seja fechada
        db_session.close()
        logger.info("Conexão com o banco de dados fechada.")


if __name__ == "__main__":
    run_sync()
# Conteúdo completo e corrigido para: test_sync_task_types.py

import json
import logging
from dotenv import load_dotenv

from app.services.legal_one_client import LegalOneApiClient

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_task_type_sync_test():
    """
    Executa um teste para buscar todos os Tipos e Subtipos de Tarefa da API.
    """
    logging.info("--- Iniciando teste de busca de Tipos e Subtipos de Tarefa ---")
    
    try:
        api_client = LegalOneApiClient()
        data = api_client.get_all_task_types_and_subtypes()
        
        # --- CORREÇÃO AQUI ---
        # Garante que 'data' é um dicionário antes de tentar acessar as chaves
        types = data.get("types", []) if isinstance(data, dict) else []
        subtypes = data.get("subtypes", []) if isinstance(data, dict) else []
        total_found = len(types) + len(subtypes)

        if total_found > 0:
            logging.info(f"✅ SUCESSO! A API retornou um total de {total_found} registros.")
            logging.info(f"   -> {len(types)} Tipos de Tarefa")
            logging.info(f"   -> {len(subtypes)} Subtipos de Tarefa")
            
            print("\n--- Amostra de TIPOS de tarefa recebidos: ---")
            print(json.dumps(types[:3], indent=4, ensure_ascii=False))
            
            print("\n--- Amostra de SUBTIPOS de tarefa recebidos: ---")
            print(json.dumps(subtypes[:3], indent=4, ensure_ascii=False))
            print("\n------------------------------------------------\n")
        else:
            logging.warning("⚠️ ATENÇÃO: Nenhum tipo ou subtipo de tarefa retornado.")

    except Exception as e:
        logging.error(f"❌ Ocorreu um erro fatal durante a execução do teste: {e}", exc_info=True)

if __name__ == '__main__':
    run_task_type_sync_test()
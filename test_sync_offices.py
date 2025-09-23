# Criar o arquivo: test_sync_offices.py (na raiz do projeto)

import os
import json
import logging
from dotenv import load_dotenv

# Importa o cliente da API que queremos testar
from app.services.legal_one_client import LegalOneApiClient

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Configuração básica do logging para vermos o que está acontecendo
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_office_sync_test():
    """
    Executa um teste para buscar todas as "Áreas Alocáveis" (Escritórios)
    da API do Legal One, validando a chamada e a paginação.
    """
    # Verifica se as credenciais da API estão carregadas
    if "LEGAL_ONE_CLIENT_ID" not in os.environ:
        logging.error("ERRO: As variáveis de ambiente não foram carregadas. Verifique seu arquivo .env.")
        return

    logging.info("--- Iniciando teste de busca de Áreas Alocáveis (Escritórios) ---")
    
    try:
        # 1. Instancia o cliente da API
        api_client = LegalOneApiClient()
        
        # 2. Chama o método que queremos testar
        allocatable_areas = api_client.get_all_allocatable_areas()
        
        # 3. Analisa e exibe o resultado
        if allocatable_areas:
            total_found = len(allocatable_areas)
            logging.info(f"✅ SUCESSO! A API retornou um total de {total_found} escritórios.")
            
            print("\n--- Amostra dos 5 primeiros escritórios recebidos: ---")
            # Imprime os 5 primeiros resultados em formato legível
            print(json.dumps(allocatable_areas[:5], indent=4, ensure_ascii=False))
            print("\n-----------------------------------------------------\n")
            
            # Validação final
            first_item = allocatable_areas[0]
            if "id" in first_item and "name" in first_item and "path" in first_item:
                logging.info("✅ Validação da estrutura passou! Os campos 'id', 'name' e 'path' estão presentes.")
            else:
                logging.warning("⚠️ ATENÇÃO: A estrutura dos dados parece incompleta. Verifique a amostra acima.")

        else:
            logging.warning("⚠️ ATENÇÃO: A chamada à API foi bem-sucedida, mas não retornou nenhum escritório.")
            logging.warning("   Isso pode ser normal ou indicar um problema com o filtro 'allocateData eq true'.")

    except Exception as e:
        logging.error(f"❌ Ocorreu um erro fatal durante a execução do teste: {e}", exc_info=True)

if __name__ == '__main__':
    run_office_sync_test()
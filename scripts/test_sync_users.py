# Criar o arquivo: test_sync_users.py (na raiz do projeto)

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

def run_user_sync_test():
    """
    Executa um teste para buscar todos os usuários da API do Legal One,
    validando a chamada, a paginação e a estrutura dos dados retornados.
    """
    # Verifica se as credenciais da API estão carregadas
    if "LEGAL_ONE_CLIENT_ID" not in os.environ:
        logging.error("ERRO: As variáveis de ambiente não foram carregadas. Verifique seu arquivo .env.")
        return

    logging.info("--- Iniciando teste de busca de Usuários ---")
    
    try:
        # 1. Instancia o cliente da API
        api_client = LegalOneApiClient()
        
        # 2. Chama o método que queremos testar
        users = api_client.get_all_users()
        
        # 3. Analisa e exibe o resultado
        if users:
            total_found = len(users)
            logging.info(f"✅ SUCESSO! A API retornou um total de {total_found} usuários.")
            
            # Filtra para mostrar apenas usuários ativos na amostra, se houver
            active_users_sample = [u for u in users if u.get('isActive')]
            if not active_users_sample:
                 active_users_sample = users # Se não houver ativos, mostra qualquer um

            print("\n--- Amostra de até 5 usuários recebidos (priorizando ativos): ---")
            # Imprime os 5 primeiros resultados em formato legível
            print(json.dumps(active_users_sample[:5], indent=4, ensure_ascii=False))
            print("\n------------------------------------------------------------------\n")
            
            # Validação final da estrutura
            first_user = users[0]
            expected_keys = ["id", "name", "email", "isActive"]
            if all(key in first_user for key in expected_keys):
                logging.info(f"✅ Validação da estrutura passou! Os campos {expected_keys} estão presentes.")
            else:
                missing_keys = [key for key in expected_keys if key not in first_user]
                logging.warning(f"⚠️ ATENÇÃO: A estrutura dos dados parece incompleta. Campos ausentes: {missing_keys}")

        else:
            logging.warning("⚠️ ATENÇÃO: A chamada à API foi bem-sucedida, mas não retornou nenhum usuário.")

    except Exception as e:
        logging.error(f"❌ Ocorreu um erro fatal durante a execução do teste: {e}", exc_info=True)

if __name__ == '__main__':
    run_user_sync_test()
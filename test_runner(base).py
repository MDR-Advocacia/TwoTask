# feat(runner): call correct enriched method and improve logging
# test_runner.py

import os
import json
import logging
from dotenv import load_dotenv
from app.services.legal_one_client import LegalOneApiClient

# Carrega as variáveis do arquivo .env
load_dotenv()

# Configuração do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_test():
    """
    Executa um teste para buscar e exibir os dados ENRIQUECIDOS de um processo.
    """
    # IMPORTANTE: Use um número de processo que exista no seu ambiente de testes.
    cnj_number_to_test = "0002309-61.2018.8.14.0013" 

    if "LEGAL_ONE_CLIENT_ID" not in os.environ:
        logging.error("ERRO: As variáveis de ambiente não foram carregadas. Verifique seu arquivo .env.")
        return

    logging.info(f"--- Iniciando teste de consulta ENRIQUECIDA para o processo CNJ: {cnj_number_to_test} ---")
    
    try:
        api_client = LegalOneApiClient()
        
        # --- CHAMADA CORRETA ---
        # Garantindo que estamos chamando o método que faz o trabalho extra.
        enriched_data = api_client.get_enriched_lawsuit_data(cnj_number_to_test)
        
        if enriched_data:
            print("\n--- ✅ Sucesso! Dados do Processo Enriquecido ---")
            print(json.dumps(enriched_data, indent=4, ensure_ascii=False))
            print("\n-------------------------------------------------\n")
            
            # Verificação final para sua tranquilidade
            if "responsibleOfficeName" in enriched_data and enriched_data["responsibleOfficeName"] != "Nome não encontrado":
                logging.info("SUCESSO: O campo 'responsibleOfficeName' foi encontrado e preenchido!")
            else:
                logging.warning("ATENÇÃO: O campo 'responsibleOfficeName' não foi encontrado ou o ID não corresponde a nenhum escritório no cache.")
        else:
            print(f"\n--- ⚠️ Atenção: Nenhum processo foi encontrado com o número {cnj_number_to_test} ---\n")

    except Exception as e:
        logging.error(f"Ocorreu um erro fatal durante a execução do teste: {e}", exc_info=True)

if __name__ == '__main__':
    run_test()
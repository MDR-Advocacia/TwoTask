# file: test_runner.py

import os
import json
import logging
from dotenv import load_dotenv
from app.services.legal_one_client import LegalOneApiClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_refined_query():
    load_dotenv()
    TEST_CNJ_NUMBER = "SEU_NUMERO_DE_PROCESSO_VALIDO_AQUI" 

    logging.info("Iniciando o teste de consulta REFINADA de processo...")

    try:
        client = LegalOneApiClient()
        logging.info(f"Buscando dados refinados para o processo CNJ: {TEST_CNJ_NUMBER}")
        
        # Chamando o novo método otimizado
        lawsuit_data = client.get_refined_lawsuit_data(
            identifier_number=TEST_CNJ_NUMBER
        )

        if lawsuit_data:
            logging.info("Dados refinados encontrados! Resposta da API:")
            pretty_json = json.dumps(lawsuit_data, indent=4, ensure_ascii=False)
            print(pretty_json)
        else:
            logging.warning("A consulta foi bem-sucedida, mas nenhum processo foi retornado.")

    except Exception as e:
        logging.error(f"Ocorreu um erro durante a execução do teste: {e}")

if __name__ == "__main__":
    run_refined_query()
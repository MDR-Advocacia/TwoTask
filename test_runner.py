# file: test_runner.py

import os
import json
import logging
from dotenv import load_dotenv

# Importa o nosso cliente de API já pronto
from app.services.legal_one_client import LegalOneApiClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def run_lawsuit_query():
    """
    Função para executar uma única consulta de processo e imprimir o resultado.
    """
    load_dotenv()

    # --- INFORMAÇÃO QUE VOCÊ PRECISA FORNECER ---
    # Coloque aqui o número de um processo real (CNJ) que exista na sua base de testes.
    TEST_CNJ_NUMBER = "0800248-67.2018.8.14.0023"  # <--- SUBSTITUA PELO SEU NÚMERO DE TESTE

    logging.info("Iniciando o teste de consulta de processo...")

    try:
        client = LegalOneApiClient()

        logging.info(f"Buscando dados para o processo CNJ: {TEST_CNJ_NUMBER}")
        # A chamada foi simplificada, não precisa mais do tenant_id
        lawsuit_data = client.get_lawsuit_by_identifier(
            identifier_number=TEST_CNJ_NUMBER
        )

        if lawsuit_data:
            logging.info("Processo encontrado! Dados recebidos da API:")
            pretty_json = json.dumps(lawsuit_data, indent=4, ensure_ascii=False)
            print(pretty_json)
        else:
            logging.warning("A consulta foi bem-sucedida, mas nenhum processo foi retornado para o número informado.")

    except Exception as e:
        logging.error(f"Ocorreu um erro durante a execução do teste: {e}")

if __name__ == "__main__":
    run_lawsuit_query()
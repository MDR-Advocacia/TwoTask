# inspect_lawsuit.py (Corrigido)

import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

# Importa o cliente da API (com o nome correto)
try:
    from app.services.legal_one_client import LegalOneApiClient
except ImportError:
    print("Erro: Não foi possível importar o LegalOneApiClient.")
    print("Verifique se a pasta 'app' existe no diretório atual.")
    sys.exit(1)

# --- Configuração ---
# COLOQUE AQUI UM CNJ VÁLIDO QUE TENHA OS CAMPOS PERSONALIZADOS PREENCHIDOS
CNJ_PARA_INSPECIONAR = "0662042-84.2019.8.04.0001"  # <--- CONFIRME ESTE CNJ
# --- Fim Configuração ---

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# Configuração básica do logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def inspect_lawsuit(cnj: str):
    """
    Busca um processo pelo CNJ e imprime todos os seus dados. (Versão Síncrona)
    """
    
    client = None
    try:
        client = LegalOneApiClient()
        logging.info("Cliente LegalOneApiClient inicializado com sucesso.")
        
    except ValueError as e:
        logging.error(f"Erro ao instanciar o LegalOneApiClient: {e}")
        logging.error("Verifique se as variáveis (LEGAL_ONE_CLIENT_ID, etc.) estão DENTRO do seu arquivo .env")
        return
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado na inicialização: {e}")
        return

    logging.info(f"Buscando processo com CNJ: {cnj}...")
    
    params = {
        "$filter": f"identifierNumber eq '{cnj}'",
        "$top": 1,
        "$expand": "customFields"  # Essencial para campos personalizados
    }
    
    try:
        # [MUDANÇA AQUI]
        # Usando o novo método que acabamos de adicionar ao cliente
        response_data = client.get_lawsuits(params=params)
        
        if response_data and response_data.get("value"):
            lawsuit = response_data["value"][0]
            print("\n--- PROCESSO ENCONTRADO ---")
            
            # Imprime o JSON formatado
            print(json.dumps(lawsuit, indent=2, ensure_ascii=False))
            
            print("\n--- FIM DOS DADOS ---")
            print("\n[ AÇÃO NECESSÁRIA ]")
            print("Procure no JSON acima pela seção 'customFields' e anote os 'customFieldId' para 'NPJ' e 'Data da Terceirização'.")

        else:
            logging.warning(f"Processo com CNJ {cnj} não encontrado.")
            
    except Exception as e:
        logging.error(f"Erro ao buscar CNJ {cnj}: {e}", exc_info=True)
    finally:
        # (O cliente síncrono não parece ter um método 'close' explícito,
        #  pois usa um requests.Session de classe, que é ok)
        pass


if __name__ == "__main__":
    if CNJ_PARA_INSPECIONAR == "0000000-00.0000.0.00.0000":
        logging.error("Erro: Por favor, edite o arquivo 'inspect_lawsuit.py' e defina o 'CNJ_PARA_INSPECIONAR'.")
    else:
        logging.info("Iniciando inspetor de processo (modo síncrono)...")
        inspect_lawsuit(CNJ_PARA_INSPECIONAR)
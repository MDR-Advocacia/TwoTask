# update_lawsuits.py (Versão Final Completa - Com Cache Otimizado e Correções Finais)

import pandas as pd # Import adicionado
import sys
import math
import time
import logging
import json
import re
from pathlib import Path
from dotenv import load_dotenv # Import load_dotenv
from typing import Dict, Any, Optional, List
from unidecode import unidecode # Import adicionado para normalização

# Importa o cliente da API
try:
    from app.services.legal_one_client import LegalOneApiClient
except ImportError:
    print("Erro: Não foi possível importar o LegalOneApiClient.")
    print("Verifique se a pasta 'app' existe no diretório atual.")
    sys.exit(1)

# --- Configuração ---
# Força o override para garantir que o .env seja lido
load_dotenv(override=True)
# [CORREÇÃO] Nome exato do arquivo da planilha
PLANILHA_PATH = Path(__file__).parent / "planilha_de_processos.xlsx.xlsx"

MAPA_COLUNAS = {
    # Coluna na Planilha : Nome interno
    "Processo": "cnj",
    "Escritório Responsável": "responsibleOfficePath",
    "Tipo de Ação": "actionTypeName",
    "Estado (UF)": "stateCode", # <-- CORRIGIDO para usar stateCode
    "Cidade": "cityName",
    "Nome do Objeto": "objectName", # Mantido
    "Valor da Causa": "claimValue",
    "Data da Terceirização": "custom_data_terceirizacao",
    "NPJ": "custom_npj"
}

# IDs dos Campos Personalizados
CUSTOM_FIELD_MAP = {
    "custom_npj": {"id": 3687, "type": "textValue"},
    "custom_data_terceirizacao": {"id": 3691, "type": "dateValue"}
}

DEFAULT_CURRENCY_CODE = "BRL"
RATE_LIMIT_DELAY = 0.7 # Delay entre chamadas PATCH
# --- Fim Configuração ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# --- Funções Utilitárias de Limpeza ---
def to_int(value: Any) -> Optional[int]:
    if value is None or (isinstance(value, float) and math.isnan(value)): return None
    try: return int(value)
    except (ValueError, TypeError): return None

def to_float(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, float) and math.isnan(value)): return None
    try: return float(value)
    except (ValueError, TypeError): return None

def to_iso_date(value: Any) -> Optional[str]:
    if value is None or pd.isna(value): return None
    try: return pd.to_datetime(value).strftime('%Y-%m-%d')
    except (ValueError, TypeError): return None

# [NORMALIZAÇÃO MELHORADA]
def normalize_text(text: Optional[Any]) -> str:
    """
    Converte para string, remove acentos, coloca em minúsculo,
    remove múltiplos espaços e espaços ao redor de '/'.
    Remove a maioria dos outros caracteres não alfanuméricos (exceto '/').
    """
    if text is None: return ""
    try:
        # 1. Converte para string e remove acentos
        text_str = unidecode(str(text))
        # 2. Minúsculo
        text_str = text_str.lower()
        # 3. Remove caracteres não alfanuméricos, exceto espaço e /
        #    (mantém hífens em nomes como guajara-mirim)
        text_str = re.sub(r"[^a-z0-9\s/-]", "", text_str)
        # 4. Remove espaços extras no início/fim e múltiplos espaços
        text_str = re.sub(r"\s+", " ", text_str).strip()
        # 5. Remove espaços ao redor de '/' -> " / " ou "/ " ou " /" se torna "/"
        text_str = re.sub(r"\s*/\s*", "/", text_str)
        return text_str
    except Exception as e:
        logging.error(f"Erro ao normalizar texto '{text}': {e}")
        return str(text).lower().strip() # Fallback simples
# --- Fim Funções Utilitárias ---


class LegalOneLookupService:
    """
    Encapsula o carregamento (com cache) e a consulta dos mapas de tradução.
    """
    def __init__(self, client: LegalOneApiClient):
        self.client = client # Garante que o cliente seja salvo
        self.state_map: Dict[str, int] = {}       # Chave: "RN" -> ID
        self.city_map: Dict[str, int] = {}        # Chave: "natal" -> ID
        self.action_type_map: Dict[str, int] = {} # Chave: "acao de cobranca" -> ID
        self.office_map: Dict[str, int] = {}      # Chave: "mdr advocacia/..." -> ID
        # [CORREÇÃO] Mapa de Objetos agora é nome -> id (plano)
        self.object_map: Dict[str, int] = {}

    def load_all_maps(self, df_states_codes: Optional[List[str]] = None):
        """
        Carrega mapas usando métodos cacheados. Carrega cidades seletivamente.
        """
        logging.info("Carregando mapas de tradução (lookups) com cache...")

        # 1. Escritórios (usa cache)
        try:
            areas = self.client.get_all_allocatable_areas_cached() # Usa _cached
            # Aplica normalização robusta na chave
            self.office_map = {normalize_text(a["path"]): a["id"] for a in areas if a.get("path")}
            logging.info(f"Carregado mapa com {len(self.office_map)} escritórios (cache).")
        except AttributeError:
             logging.error("Erro: Método 'get_all_allocatable_areas_cached' não encontrado no cliente."); raise
        except Exception as e:
            logging.error(f"Falha ao carregar mapa de escritórios: {e}")
            raise

        # 2. Tipos de Ação (usa cache e nome correto da função do cliente)
        try:
            # Chama o nome correto do método no cliente (que usa endpoint alternativo)
            actions = self.client.get_all_actions_cached() # Nome _cached correspondente
             # Aplica normalização robusta na chave
            self.action_type_map = {normalize_text(x["name"]): x["id"] for x in actions if x.get("name")}
            logging.info(f"Carregado mapa com {len(self.action_type_map)} tipos de ação (cache).")
        except AttributeError:
             logging.error("Erro: Método 'get_all_actions_cached' não encontrado no cliente."); raise
        except Exception as e:
            logging.error(f"Falha ao carregar mapa de tipos de ação: {e}")
            raise

        # 3. Objetos (Lista Plana, usa cache) - CORRIGIDO
        try:
            # Chama o método cacheado (que busca lista plana id, name)
            objs = self.client.get_all_objects_cached()
            self.object_map = {}
            for item in objs:
                item_id = item.get("id")
                item_name = item.get("name")
                # Não há mais parentId para processar
                if item_id and item_name:
                    # Aplica normalização robusta na chave
                    self.object_map[normalize_text(item_name)] = item_id
            logging.info(f"Carregado mapa plano com {len(self.object_map)} objetos (cache).")
        except AttributeError:
             logging.error("Erro: Método 'get_all_objects_cached' não encontrado no cliente."); raise
        except Exception as e:
            logging.error(f"Falha ao carregar mapa de objetos: {e}")
            # Pode não ser fatal

        # 4. Estados (UFs) (usa cache e stateCode)
        try:
            states = self.client.get_all_states_cached() # Usa _cached
            # Aplica normalização robusta na chave (stateCode)
            self.state_map = {normalize_text(s["stateCode"]): s["id"]
                              for s in states if s.get("stateCode")}
            logging.info(f"Carregado mapa com {len(self.state_map)} estados (chave = stateCode, cache).")
        except AttributeError:
             logging.error("Erro: Método 'get_all_states_cached' não encontrado no cliente."); raise
        except Exception as e:
            logging.error(f"Falha ao carregar mapa de estados: {e}")
            raise

        # 5. Cidades - SOMENTE dos estados necessários (usa cache por estado)
        self.city_map = {}
        if df_states_codes:
            needed_codes = {normalize_text(code) for code in df_states_codes if isinstance(code, str)}
            needed_state_ids = {state_id for code, state_id in self.state_map.items() if code in needed_codes}

            logging.info(f"Pré-carregando cidades para {len(needed_state_ids)} estados da planilha...")
            for state_id in needed_state_ids:
                try:
                    cities = self.client.get_cities_by_state_cached(state_id) # Usa _cached
                    for city in cities:
                        if city.get("name"):
                            # Aplica normalização robusta na chave
                            self.city_map[normalize_text(city["name"])] = city["id"]
                except AttributeError:
                     logging.error(f"Erro: Método 'get_cities_by_state_cached' não encontrado no cliente para state_id={state_id}.")
                     # Continua
                except Exception as e:
                    logging.error(f"Falha ao carregar cidades (cache) para state_id={state_id}: {e}")
            logging.info(f"Carregado mapa principal com {len(self.city_map)} cidades únicas (pré-carregadas, cache).")
        else:
            logging.warning("Nenhum código de estado válido na planilha. Nenhuma cidade pré-carregada.")

        logging.info("Mapas de tradução carregados.")

    # --- Getters ---
    # Busca por stateCode normalizado
    def get_state_id(self, code: str) -> Optional[int]:
        return self.state_map.get(normalize_text(code))

    # Com lazy load opcional e normalização robusta
    def get_city_id(self, name: str, state_code_for_lazy_load: Optional[str] = None) -> Optional[int]:
        city_name_norm = normalize_text(name)
        city_id = self.city_map.get(city_name_norm)

        if city_id is None and state_code_for_lazy_load:
            state_id = self.get_state_id(state_code_for_lazy_load) # Já normaliza
            if state_id:
                logging.info(f"Lazy loading cidades p/ estado '{state_code_for_lazy_load}' p/ encontrar '{name}' ({city_name_norm})...")
                try:
                    cities = self.client.get_cities_by_state_cached(state_id) # Usa cache
                    found_city = None
                    for city in cities:
                        current_city_name_norm = normalize_text(city.get("name"))
                        current_city_id = city.get("id")
                        if current_city_name_norm and current_city_id:
                             if current_city_name_norm not in self.city_map:
                                 self.city_map[current_city_name_norm] = current_city_id
                             if current_city_name_norm == city_name_norm:
                                 city_id = current_city_id
                                 found_city = city
                    if found_city: logging.info(f"Lazy load: Cidade '{name}' (ID: {city_id}) encontrada.")
                    else: logging.warning(f"Lazy load: Cidade '{name}' ({city_name_norm}) NÃO encontrada p/ '{state_code_for_lazy_load}'.")
                except AttributeError:
                     logging.error(f"Erro Lazy Load: Método 'get_cities_by_state_cached' não encontrado no cliente para state_id={state_id}.")
                except Exception as e: logging.error(f"Lazy load: Erro ao buscar cidades state_id={state_id}: {e}")
            else: logging.warning(f"Lazy load: Estado '{state_code_for_lazy_load}' não encontrado.")
        return city_id

    # Usa normalização
    def get_action_type_id(self, name: str) -> Optional[int]:
        return self.action_type_map.get(normalize_text(name))

    # Usa normalização
    def get_office_id(self, path: str) -> Optional[int]:
        return self.office_map.get(normalize_text(path))

    # [BUSCA OBJETO INTELIGENTE + NORMALIZAÇÃO] Retorna ID (int | None)
    def get_object_id(self, name: str) -> Optional[int]:
        """
        Busca o ID do objeto. Tenta o nome completo normalizado primeiro.
        Se falhar e o nome contiver '/', tenta buscar apenas a parte após o último '/'.
        """
        name_norm = normalize_text(name) # Normaliza a entrada da planilha
        object_id = self.object_map.get(name_norm) # Busca no mapa (chaves já normalizadas)

        if object_id is None and "/" in name_norm:
            parts = name_norm.split("/")
            last_part = parts[-1].strip() # A normalização já removeu espaços extras
            if last_part:
                logging.info(f"Objeto '{name}' ({name_norm}) não encontrado. Tentando fallback: '{last_part}'...")
                object_id = self.object_map.get(last_part) # Busca a última parte normalizada
                if object_id: logging.info(f"  -> Fallback bem-sucedido (ID: {object_id}).")
                # else: logging.warning(f"  -> Fallback falhou.") # Opcional

        return object_id
# --- Fim LegalOneLookupService ---


# [CORREÇÃO] Usa client.search_lawsuit_by_cnj
def find_lawsuit_id_by_cnj(client: LegalOneApiClient, cnj: str) -> Optional[int]:
    """
    Busca um processo no Legal One usando o CNJ (com fallback) e retorna seu ID.
    """
    logging.info(f"Buscando processo com CNJ: {cnj}...")
    try:
        lawsuit_data = client.search_lawsuit_by_cnj(cnj) # Chama método correto
        if lawsuit_data and lawsuit_data.get("id"):
            lawsuit_id = lawsuit_data["id"]
            logging.info(f"  -> Encontrado: ID {lawsuit_id}")
            return lawsuit_id
        else: return None # search_lawsuit_by_cnj já loga warning
    except AttributeError:
         logging.error(f"  -> Erro: Método 'search_lawsuit_by_cnj' não encontrado no cliente."); return None
    except Exception as e:
        logging.error(f"  -> Erro inesperado ao buscar CNJ {cnj}: {e}"); return None
# --- Fim find_lawsuit_id_by_cnj ---


# [CORREÇÃO] Simplifica lógica de Objeto, usa normalização implícita nos getters
def construct_payload(row: pd.Series, lookup: LegalOneLookupService) -> Dict[str, Any]:
    payload = {}
    custom_fields_payload = []
    log_prefix = f"Linha {row.name + 2} (CNJ: {row.get('cnj', 'N/A')}):"

    # Escritório Responsável
    if "responsibleOfficePath" in row and pd.notna(row["responsibleOfficePath"]):
        # Passa valor original, getter normaliza
        office_id = lookup.get_office_id(row["responsibleOfficePath"])
        if office_id: payload["responsibleOfficeId"] = office_id
        else: logging.warning(f"{log_prefix} Escritório não encontrado: '{row['responsibleOfficePath']}'")

    # Tipo de Ação
    if "actionTypeName" in row and pd.notna(row["actionTypeName"]):
        action_id = lookup.get_action_type_id(row["actionTypeName"]) # Getter normaliza
        if action_id: payload["actionTypeId"] = action_id
        else: logging.warning(f"{log_prefix} Tipo de Ação não encontrado: '{row['actionTypeName']}'")

    # Objeto (Tipo/Subtipo) - Usa getter inteligente
    if "objectName" in row and pd.notna(row["objectName"]):
        object_id = lookup.get_object_id(row["objectName"]) # Getter normaliza e faz fallback
        if object_id:
            payload["LitigationActionAppealProceduralIssueTypeId"] = object_id
        else: logging.warning(f"{log_prefix} Objeto não encontrado: '{row['objectName']}'")

    # Estado (stateId) - Usa stateCode
    current_state_code = None
    if "stateCode" in row and pd.notna(row["stateCode"]):
        current_state_code = str(row["stateCode"]).strip()
        state_id = lookup.get_state_id(current_state_code) # Getter normaliza
        if state_id: payload["stateId"] = state_id
        else: logging.warning(f"{log_prefix} Estado (Código) não encontrado: '{current_state_code}'")

    # Cidade (cityId) - Com lazy load habilitado
    if "cityName" in row and pd.notna(row["cityName"]):
        city_id = lookup.get_city_id(row["cityName"], state_code_for_lazy_load=current_state_code) # Getter normaliza
        if city_id: payload["cityId"] = city_id
        else: logging.warning(f"{log_prefix} Cidade não encontrada: '{row['cityName']}' (Estado: {current_state_code or 'N/A'})")

    # Valor da Causa
    claim_value = to_float(row.get("claimValue"))
    if claim_value is not None:
        payload["claimValue"] = {"value": claim_value, "code": DEFAULT_CURRENCY_CODE}

    # Campos Personalizados
    if CUSTOM_FIELD_MAP["custom_npj"]["id"] is not None:
        npj_val = row.get("custom_npj");
        if pd.notna(npj_val): custom_fields_payload.append({"customFieldId": CUSTOM_FIELD_MAP["custom_npj"]["id"], "textValue": str(npj_val).strip()})
    if CUSTOM_FIELD_MAP["custom_data_terceirizacao"]["id"] is not None:
        data_val = to_iso_date(row.get("custom_data_terceirizacao"));
        if data_val is not None: custom_fields_payload.append({"customFieldId": CUSTOM_FIELD_MAP["custom_data_terceirizacao"]["id"], "dateValue": data_val})
    if custom_fields_payload: payload["customFields"] = custom_fields_payload

    return payload
# --- Fim construct_payload ---

# --- update_lawsuit --- (Sem mudanças)
def update_lawsuit(client: LegalOneApiClient, lawsuit_id: int, payload: Dict[str, Any]) -> bool:
    logging.info(f"Atualizando processo ID: {lawsuit_id}...")
    try:
        # logging.debug(f"Payload PATCH ID {lawsuit_id}:\n{json.dumps(payload, indent=2)}")
        client.patch_lawsuit(lawsuit_id, payload)
        logging.info(f"  -> Sucesso ao atualizar ID {lawsuit_id}.")
        return True
    except Exception as e:
        logging.error(f"  -> FALHA ao atualizar ID {lawsuit_id}.")
        return False
# --- Fim update_lawsuit ---


# --- main --- (Passa lista de state codes para load_all_maps)
def main():
    try: client = LegalOneApiClient()
    except ValueError as e: logging.error(f"Erro ao instanciar cliente: {e}"); return
    logging.info("Cliente LegalOneApiClient inicializado.")

    if not PLANILHA_PATH.exists(): logging.error(f"Erro: Planilha não encontrada: {PLANILHA_PATH}"); return
    logging.info(f"Carregando planilha de: {PLANILHA_PATH}")
    try:
        if str(PLANILHA_PATH).lower().endswith(".csv"): df = pd.read_csv(PLANILHA_PATH, dtype=str)
        elif str(PLANILHA_PATH).lower().endswith((".xlsx", ".xls")): df = pd.read_excel(PLANILHA_PATH, dtype=str)
        else: logging.error(f"Erro: Formato não suportado: {PLANILHA_PATH}"); return
        cnj_col_name = next(k for k, v in MAPA_COLUNAS.items() if v == 'cnj')
        df.dropna(subset=[cnj_col_name], inplace=True)
        df = df[df[cnj_col_name].astype(str).str.strip() != '']
        if df.empty: logging.warning("Planilha vazia ou sem CNJs válidos."); return
    except Exception as e: logging.error(f"Erro ao ler/limpar planilha: {e}"); return

    try:
        colunas_necessarias = list(MAPA_COLUNAS.keys())
        colunas_faltantes = [col for col in colunas_necessarias if col not in df.columns]
        if colunas_faltantes: logging.error(f"Erro: Colunas não encontradas: {colunas_faltantes}"); return
        df_mapeado = df[colunas_necessarias].copy()
        df_mapeado.rename(columns=MAPA_COLUNAS, inplace=True)
    except Exception as e: logging.error(f"Erro ao mapear colunas: {e}"); return
    logging.info(f"Planilha carregada e mapeada. {len(df_mapeado)} linhas para processar.")

    states_from_sheet = None
    if "stateCode" in df_mapeado.columns:
        try:
            states_from_sheet = df_mapeado["stateCode"].dropna().astype(str).unique().tolist()
            logging.info(f"Encontrados {len(states_from_sheet)} códigos de estado únicos.")
        except Exception as e: logging.error(f"Erro ao extrair códigos de estado: {e}")
    else: logging.warning("Coluna 'stateCode' não encontrada.")

    try:
        lookup_service = LegalOneLookupService(client)
        lookup_service.load_all_maps(df_states_codes=states_from_sheet)
    except Exception as e: logging.error(f"Erro fatal ao carregar mapas: {e}. Abortando."); return

    logging.info("\n--- Iniciando processamento ---")
    sucessos, falhas_busca, falhas_update = 0, 0, 0
    total_rows = len(df_mapeado)
    for index, row in df_mapeado.iterrows():
        cnj = str(row.get("cnj", "")).strip()
        logging.info(f"Processando linha {index + 1}/{total_rows} - CNJ: {cnj or 'N/A'}")
        if not cnj: logging.warning(f"  -> CNJ vazio, pulando."); continue

        # Chama a função correta
        lawsuit_id = find_lawsuit_id_by_cnj(client, cnj)
        if lawsuit_id is None: falhas_busca += 1; continue

        payload_para_patch = construct_payload(row, lookup_service)
        if not payload_para_patch: logging.info(f"  -> Payload vazio. Pulando."); continue

        if update_lawsuit(client, lawsuit_id, payload_para_patch): sucessos += 1
        else: falhas_update += 1
        time.sleep(RATE_LIMIT_DELAY)

    logging.info("\n--- Processamento concluído ---")
    logging.info(f"Resultados: {sucessos} sucesso(s), {falhas_busca} falha(s) busca, {falhas_update} falha(s) update.")
# --- Fim main ---


if __name__ == "__main__":
    logging.info("Iniciando script de atualização de processos (modo síncrono)...")
    main()
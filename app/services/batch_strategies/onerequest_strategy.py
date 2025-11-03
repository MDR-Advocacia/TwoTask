# app/services/batch_strategies/onerequest_strategy.py
import logging
import asyncio
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution, BatchExecutionItem
from app.models.legal_one import LegalOneUser

from .base_strategy import BaseStrategy

# --- PONTO DE CONFIGURAÇÃO CENTRAL ---
# Mapeamento: "Nome do Setor": (taskSubtypeId, responsibleOfficeId)
SECTOR_TASK_MAPPING = {
    "BB Réu": (967, 15),
    "BB Recurso": (968, 19),
    "BB Encerramento": (1058, 20),
    "BB Autor": (969, 18)
    # Adicione outros mapeamentos conforme necessário
}
# --- DEFINIR VALORES PADRÃO CASO O MAPEAMENTO FALHE ---
DEFAULT_SUBTYPE_ID = 967 
DEFAULT_OFFICE_ID = 15   

DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente
TASK_TYPE_EXTERNAL_ID = 26  # ID Fixo para o "Tipo" da tarefa (ex: "Fluxo de Trabalho")

class OnerequestStrategy(BaseStrategy):
    """
    Estratégia para criar tarefas em lote a partir da fonte Onerequest.
    Recebe um payload rico (dict) para cada item.
    """

    def _parse_and_format_deadline(self, date_str: str) -> str:
        """
        Converte uma data de 'DD/MM/YYYY' para o formato ISO 8601 UTC (final do dia em Brasília).
        """
        try:
            local_deadline_date = datetime.strptime(date_str, "%d/%m/%Y")
            local_tz = ZoneInfo("America/Sao_Paulo")
            aware_deadline = datetime.combine(local_deadline_date.date(), time(23, 59, 59)).replace(tzinfo=local_tz)
            utc_deadline = aware_deadline.astimezone(timezone.utc)
            # Retorna no formato "YYYY-MM-DDTHH:mm:ssZ"
            return utc_deadline.isoformat().replace('+00:00', 'Z')
        except (ValueError, TypeError) as e:
            logging.error(f"Formato de data inválido: '{date_str}'. Erro: {e}")
            raise ValueError(f"Prazo inválido: '{date_str}'")

    def _get_responsible_user_id(self, full_name: str) -> int:
        """
        Busca o ID do Legal One para um usuário pelo nome completo.
        Lança ValueError se não encontrar ou encontrar múltiplos.
        """
        try:
            user = self.db.query(LegalOneUser).filter(
                LegalOneUser.full_name == full_name,
                LegalOneUser.is_active == True
            ).one()
            
            if not user.legal_one_id:
                raise ValueError(f"Usuário '{full_name}' encontrado, mas não possui 'legal_one_id' cadastrado.")
                
            return user.legal_one_id
        except NoResultFound:
            raise ValueError(f"Usuário '{full_name}' não encontrado ou inativo na base de dados local.")
        except MultipleResultsFound:
            raise ValueError(f"Múltiplos usuários ativos encontrados com o nome '{full_name}'.")
        except Exception as e:
            logging.error(f"Erro ao buscar usuário '{full_name}': {e}")
            raise

    def _get_task_and_office_ids(self, sector_name: str) -> tuple[int, int]:
        """
        Busca o Subtipo de Tarefa e o ID do Escritório com base no nome do setor.
        """
        mapping = SECTOR_TASK_MAPPING.get(sector_name)
        if not mapping:
            logging.warning(f"Setor '{sector_name}' não encontrado no mapeamento. Usando IDs padrão.")
            # Se um setor válido for obrigatório, descomente a linha abaixo:
            # raise ValueError(f"Setor '{sector_name}' inválido ou não mapeado.")
            return DEFAULT_SUBTYPE_ID, DEFAULT_OFFICE_ID
        
        return mapping # Retorna a tupla (taskSubtypeId, responsibleOfficeId)

    def _build_task_description(self, item_payload: dict) -> str:
        """
        Constrói a string de descrição da tarefa com base nas regras definidas.
        """
        prazo = item_payload.get("prazo", "N/A")
        titulo = item_payload.get("titulo", "")
        npj_direcionador = item_payload.get("npj_direcionador", "N/A")
        numero_solicitacao = item_payload.get("numero_solicitacao", "N/A")
        anotacao = item_payload.get("anotacao", "")
        texto_dmi = item_payload.get("texto_dmi", "")

        anotacao_formatada = f"Anotação: {anotacao}\n" if anotacao else ""

        description = (
            f"Prazo: {prazo}\n\n"
            f"{titulo}\n\n"
            f"NPJ Direcionador: {npj_direcionador}\n\n"
            f"---\n"
            f"OBSERVAÇÕES ONEREQUEST\n"
            f"Solicitação Nº: {numero_solicitacao}\n"
            f"{anotacao_formatada}"
            f"\n---\n"
            f"TEXTO DMI\n"
            f"{texto_dmi}"
        )
        return description.strip()


    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict: 
        logging.info(f"Processando lote 'Onerequest' com {len(request.processos)} itens.")
        success_count = 0
        failed_items = []
        
        start_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        for item_payload in request.processos:
            # Garantimos que item_payload é um dict
            if not isinstance(item_payload, dict):
                logging.error(f"Item inesperado no payload (não é um dict): {item_payload}")
                failed_items.append({"cnj": "N/A", "motivo": "Formato de item inválido (esperado dict)."})
                continue # Pula para o próximo item

            process_number = item_payload.get("numero_processo", "N/A") 
            log_item = BatchExecutionItem(process_number=process_number, execution_id=execution_log.id)
            
            try:
                # --- 1. Extração e Validação ---
                numero_processo = item_payload.get("numero_processo")
                responsavel_nome = item_payload.get("responsavel")
                prazo_str = item_payload.get("prazo")
                setor = item_payload.get("setor")

                if not numero_processo:
                    raise ValueError("Campo 'numero_processo' é obrigatório.")
                if not responsavel_nome:
                     raise ValueError("Campo 'responsavel' (nome) é obrigatório.")
                if not prazo_str:
                    raise ValueError("Campo 'prazo' é obrigatório.")
                if not setor:
                    raise ValueError("Campo 'setor' é obrigatório para mapeamento.")
                
                # --- 2. Busca e Mapeamento ---
                responsible_user_id = self._get_responsible_user_id(responsavel_nome)
                task_subtype_id, office_id = self._get_task_and_office_ids(setor)
                end_datetime_iso = self._parse_and_format_deadline(prazo_str)
                task_description = self._build_task_description(item_payload)

                # --- 3. Montagem do Payload da Tarefa ---
                task_payload = {
                    "task": {
                        "description": task_description,
                        "startDateTime": start_datetime_iso,
                        "endDateTime": end_datetime_iso,
                        "responsibleUserId": responsible_user_id,
                        "responsibleOfficeId": office_id,
                        "taskSubtypeExternalId": task_subtype_id,
                        "taskTypeExternalId": TASK_TYPE_EXTERNAL_ID,
                        "taskStatusId": DEFAULT_TASK_STATUS_ID
                    }
                }
                
                # --- 4. Execução (Busca, Criação e Vínculo) ---
                
                # Busca o processo no Legal One pelo CNJ
                lawsuit_data = self.client.search_lawsuit_by_cnj(numero_processo)
                if not lawsuit_data or not lawsuit_data.get('id'):
                    raise Exception(f"Processo (CNJ: {numero_processo}) não encontrado no Legal One.")
                
                lawsuit_id = lawsuit_data['id']
                
                # Cria a tarefa no Legal One
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa na API do Legal One (resposta inválida).")
                
                task_id = created_task['id']
                
                # Vincula a tarefa criada ao processo
                link_success = self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})
                if not link_success:
                    # Loga um aviso, mas não considera falha, pois a tarefa foi criada
                    logging.warning(f"Tarefa ID {task_id} criada, mas falha ao vincular ao processo ID {lawsuit_id}.")

                # --- 5. Registro de Sucesso ---
                log_item.status = "SUCESSO"
                log_item.created_task_id = task_id
                success_count += 1
                logging.info(f"Tarefa para CNJ {numero_processo} (Onerequest) processada. Task ID: {task_id}")

            except Exception as e:
                # --- 6. Registro de Falha ---
                error_msg = str(e)
                log_item.status = "FALHA"
                log_item.error_message = error_msg
                failed_items.append({"cnj": process_number, "motivo": error_msg})
                logging.error(f"Falha ao processar CNJ {process_number} (Onerequest): {error_msg}")
            
            finally:
                execution_log.items.append(log_item)
                await asyncio.sleep(0.1) # Throttling para não sobrecarregar a API
        
        logging.info(f"Processamento 'Onerequest' concluído: {success_count} sucessos, {len(failed_items)} falhas.")
        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
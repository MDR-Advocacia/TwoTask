# app/services/batch_strategies/onerequest_strategy.py
import logging
import asyncio
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

from app.api.v1.schemas import BatchTaskCreationRequest
from app.models.batch_execution import BatchExecution, BatchExecutionItem
# from app.models.legal_one import LegalOneUser # Não é mais usado

from .base_strategy import BaseStrategy

# --- PONTO DE CONFIGURAÇÃO CENTRAL ---
# AVISO: Verifique se estes IDs (Tipo, Subtipo) estão corretos
# para o seu ambiente Legal One.
SECTOR_TASK_MAPPING = {
    "BB Réu": (15, 967),
    "BB Autor": (18, 969),
    "BB Recurso": (19, 968),
    "BB Execução e Encerramento": (20, 1058)
    # Adicione outros mapeamentos
}
# --- DEFINIR VALORES PADRÃO CASO O MAPEAMENTO FALHE ---
DEFAULT_TYPE_ID = 15
DEFAULT_SUBTYPE_ID = 967 

DEFAULT_TASK_STATUS_ID = 0  # 0 = Pendente

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
            return utc_deadline.isoformat().replace('+00:00', 'Z')
        except (ValueError, TypeError) as e:
            logging.error(f"Formato de data inválido: '{date_str}'. Erro: {e}")
            raise ValueError(f"Prazo inválido: '{date_str}'")

    # _get_responsible_user_id removido

    def _get_task_type_ids(self, sector_name: str) -> tuple[int, int]:
        """
        Busca o Tipo e o Subtipo de Tarefa com base no nome do setor.
        """
        mapping = SECTOR_TASK_MAPPING.get(sector_name) 
        if not mapping:
            logging.warning(f"Setor '{sector_name}' não encontrado no mapeamento. Usando IDs padrão.")
            return DEFAULT_TYPE_ID, DEFAULT_SUBTYPE_ID
        
        return mapping # Retorna a tupla (typeId, subTypeId)

    def _build_task_description(self, item_payload: dict) -> str:
        """
        Constrói a string de descrição da tarefa com base nas regras definidas pelo usuário.
        Formato: [vencimento] | [titulo] | NPJ [npj_direcionador] | DMI [numero_solicitacao]
        """
        vencimento = item_payload.get("vencimento", "N/A") 
        titulo = item_payload.get("titulo", "N/A")
        npj_direcionador = item_payload.get("npj_direcionador", "N/A")
        numero_solicitacao = item_payload.get("numero_solicitacao", "N/A")

        description = f" PF: {vencimento} | {titulo} | NPJ: {npj_direcionador} | DMI: {numero_solicitacao}"

        API_LIMIT = 250
        if len(description) > API_LIMIT:
            logging.warning(f"Descrição da tarefa para {numero_solicitacao} excede 250 caracteres e será truncada.")
            description = description[:(API_LIMIT - 3)] + "..."

        return description.strip()

    # --- INÍCIO DA CORREÇÃO (Observação) ---
    def _build_task_notes(self, item_payload: dict) -> str:
        """
        Constrói a string de Observação (notes) da tarefa com 'anotacao' e 'texto_dmi'.
        """
        anotacao = item_payload.get("anotacao", "")
        texto_dmi = item_payload.get("texto_dmi", "")
        
        anotacao_formatada = f"ANOTAÇÃO ONEREQUEST:\n{anotacao}\n\n" if anotacao else ""
        dmi_formatado = f"TEXTO DMI:\n{texto_dmi}" if texto_dmi else ""
        
        task_notes = (anotacao_formatada + dmi_formatado).strip()
        
        # O limite para 'notes' costuma ser bem maior (ex: 4000+), 
        # mas adicionamos um truncamento de segurança. Ajuste se necessário.
        API_NOTES_LIMIT = 4000 
        if len(task_notes) > API_NOTES_LIMIT:
            logging.warning(f"Observação da tarefa excede {API_NOTES_LIMIT} caracteres e será truncada.")
            task_notes = task_notes[:(API_NOTES_LIMIT - 3)] + "..."
            
        return task_notes
    # --- FIM DA CORREÇÃO ---


    async def process_batch(self, request: BatchTaskCreationRequest, execution_log: BatchExecution) -> dict: 
        logging.info(f"Processando lote 'Onerequest' com {len(request.processos)} itens.")
        success_count = 0
        failed_items = []
        
        # --- INÍCIO DA CORREÇÃO (publishDate) ---
        # Definimos a "data atual" (data de publicação) uma vez para o lote.
        publish_datetime_iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        # --- FIM DA CORREÇÃO ---
        
        for item_model in request.processos:
            
            try:
                item_payload = item_model.model_dump(exclude_unset=True) 
            except AttributeError:
                item_payload = item_model.dict(exclude_unset=True) 

            if not isinstance(item_payload, dict):
                logging.error(f"Item inesperado no payload (não é um dict): {item_payload}")
                failed_items.append({"cnj": "N/A", "motivo": "Formato de item inválido (esperado dict)."})
                continue 

            process_number = item_payload.get("numero_processo", "N/A") 
            log_item = BatchExecutionItem(process_number=process_number, execution_id=execution_log.id)
            
            try:
                # --- 1. Extração e Validação ---
                numero_processo = item_payload.get("numero_processo")
                responsible_user_id = item_payload.get("id_responsavel")
                prazo_str = item_payload.get("prazo")
                vencimento_str = item_payload.get("vencimento") # Necessário para a descrição
                setor = item_payload.get("setor") 
                # 'anotacao' e 'texto_dmi' são extraídos nas funções de build

                if not numero_processo:
                    raise ValueError("Campo 'numero_processo' é obrigatório.")
                if not responsible_user_id:
                     raise ValueError("Campo 'id_responsavel' (ID) é obrigatório.")
                if not prazo_str:
                    raise ValueError("Campo 'prazo' (para agendamento) é obrigatório.")
                if not vencimento_str:
                     raise ValueError("Campo 'vencimento' (para descrição) é obrigatório.")
                if not setor:
                    raise ValueError("Campo 'setor' é obrigatório para mapeamento.")
                
                # --- 2. Busca e Mapeamento (PARTE 1) ---
                type_id, task_subtype_id = self._get_task_type_ids(setor)
                
                # Datas de início/término são baseadas em "prazo"
                end_datetime_iso = self._parse_and_format_deadline(prazo_str)
                start_datetime_iso = end_datetime_iso # startDateTime == endDateTime
                
                # Descrição é baseada em "vencimento"
                task_description = self._build_task_description(item_payload)
                
                # --- INÍCIO DA CORREÇÃO (Observação) ---
                # Observação é baseada em "anotacao" e "texto_dmi"
                task_notes = self._build_task_notes(item_payload)
                # --- FIM DA CORREÇÃO ---

                # --- 4. Execução (Busca) ---
                lawsuit_data = self.client.search_lawsuit_by_cnj(numero_processo)
                if not lawsuit_data or not lawsuit_data.get('id'):
                    raise Exception(f"Processo (CNJ: {numero_processo}) não encontrado no Legal One.")
                
                lawsuit_id = lawsuit_data['id']
                
                office_id = lawsuit_data.get('responsibleOfficeId')
                if not office_id:
                    raise Exception(f"Processo {numero_processo} encontrado, mas não possui 'responsibleOfficeId' (Escritório Responsável) definido no Legal One.")
                
                # --- 3. Montagem do Payload da Tarefa ---
                task_payload = {
                    "description": task_description,      
                    "startDateTime": start_datetime_iso,  
                    "endDateTime": end_datetime_iso,      
                    "publishDate": publish_datetime_iso, # <-- Campo obrigatório adicionado
                    "status": { "id": DEFAULT_TASK_STATUS_ID },
                    "typeId": type_id,                    
                    "subTypeId": task_subtype_id,         
                    "responsibleOfficeId": office_id,     
                    "originOfficeId": office_id,          
                    
                    "participants": [
                        {
                            "contact": {"id": responsible_user_id},
                            "isResponsible": True,
                            "isExecuter": True,
                            "isRequester": True
                        }
                    ]
                }
                
                # --- INÍCIO DA CORREÇÃO (Observação) ---
                # Adiciona o campo 'notes' apenas se ele não estiver vazio
                if task_notes:
                    task_payload['notes'] = task_notes
                # --- FIM DA CORREÇÃO ---
                
                # --- 4. Execução (CONTINUAÇÃO) ---
                created_task = self.client.create_task(task_payload)
                if not created_task or not created_task.get('id'):
                    raise Exception("Falha na criação da tarefa na API do Legal One (resposta inválida).")
                
                task_id = created_task['id']
                
                link_success = self.client.link_task_to_lawsuit(task_id, {"linkType": "Litigation", "linkId": lawsuit_id})
                if not link_success:
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
                await asyncio.sleep(0.1) 
        
        logging.info(f"Processamento 'Onerequest' concluído: {success_count} sucessos, {len(failed_items)} falhas.")
        return {"sucesso": success_count, "falhas": len(failed_items), "detalhes_falhas": failed_items}
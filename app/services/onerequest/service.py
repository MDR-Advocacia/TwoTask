"""Serviço operador do OneRequest (Fase 2).

Listagem com farol/KPIs + filtros (paginada), edição do tratamento e
agendamento da tarefa no Legal One. O agendamento REUSA os helpers da
`OnerequestStrategy` (mesma lógica do batch externo) e materializa a cascata
de resolução do processo (CNJ → [NPJ, pós-probe] → AGUARDANDO_PROCESSO).
Ver docs/onerequest-integracao-plano.md §6 e §7.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.legal_one import LegalOneUser
from app.models.onerequest import (
    OnerequestSolicitacao,
    STATUS_SISTEMA_ABERTO,
    STATUS_TRATAMENTO_AGENDADO,
    STATUS_TRATAMENTO_AGUARDANDO_PROCESSO,
    STATUS_TRATAMENTO_ERRO,
)
from app.services.batch_strategies.onerequest_strategy import (
    DEFAULT_TASK_STATUS_ID,
    SECTOR_TASK_MAPPING,
    OnerequestStrategy,
)
from app.services.legal_one_client import LegalOneApiClient

logger = logging.getLogger(__name__)

# Indica que o numero_processo capturado pela RPA não dá pra usar no L1.
_DIRTY_PROC_HINTS = ("não", "nao", "erro", "ausente", "encontrado", "informado", "api", "n/a")


def _proc_utilizavel(numero_processo: Optional[str]) -> bool:
    if not numero_processo:
        return False
    s = str(numero_processo).strip()
    if not s:
        return False
    low = s.lower()
    return not any(h in low for h in _DIRTY_PROC_HINTS)


def _parse_prazo(prazo: Optional[str]) -> Optional[date]:
    if not prazo:
        return None
    try:
        return datetime.strptime(prazo.strip(), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def _farol(prazo_date: Optional[date], hoje: date) -> str:
    """Espelha a lógica de farol do OneRequest legado (server.py:index)."""
    if prazo_date is None:
        return "cinza"
    if prazo_date < hoje:
        return "cinza"  # vencida
    if prazo_date == hoje:
        return "vermelho"
    if (prazo_date - hoje).days == 1:
        return "amarelo"
    if prazo_date.weekday() >= 5:  # sáb/dom
        return "roxo"
    return "verde"


class OnerequestService:
    def __init__(self, db: Session):
        self.db = db

    # ──────────────────────────────────────────────────────────────────
    # Listagem (paginada) com farol + KPIs
    # ──────────────────────────────────────────────────────────────────
    def list_solicitacoes(
        self,
        *,
        status_sistema: Optional[str] = STATUS_SISTEMA_ABERTO,
        status_tratamento: Optional[str] = None,
        responsavel_user_id: Optional[int] = None,
        busca: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        q = self.db.query(OnerequestSolicitacao)
        if status_sistema:
            q = q.filter(OnerequestSolicitacao.status_sistema == status_sistema)
        if status_tratamento:
            q = q.filter(OnerequestSolicitacao.status_tratamento == status_tratamento)
        if responsavel_user_id:
            q = q.filter(OnerequestSolicitacao.responsavel_user_id == responsavel_user_id)
        if busca:
            termo = f"%{busca.strip()}%"
            q = q.filter(
                or_(
                    OnerequestSolicitacao.numero_solicitacao.ilike(termo),
                    OnerequestSolicitacao.numero_processo.ilike(termo),
                    OnerequestSolicitacao.titulo.ilike(termo),
                )
            )

        hoje = date.today()

        # Passo 1: (id, prazo) de TODO o conjunto filtrado pra farol/KPIs/ordenação.
        leves = q.with_entities(
            OnerequestSolicitacao.id, OnerequestSolicitacao.prazo
        ).all()
        kpis = {"vencidas": 0, "hoje": 0, "amanha": 0, "fds": 0, "futuras": 0}
        enriquecidos = []
        for _id, prazo in leves:
            pdate = _parse_prazo(prazo)
            farol = _farol(pdate, hoje)
            if farol == "cinza":
                kpis["vencidas"] += 1 if pdate is not None and pdate < hoje else 0
            elif farol == "vermelho":
                kpis["hoje"] += 1
            elif farol == "amarelo":
                kpis["amanha"] += 1
            elif farol == "roxo":
                kpis["fds"] += 1
            elif farol == "verde":
                kpis["futuras"] += 1
            # ordena por prazo asc; sem data vai pro fim
            enriquecidos.append((_id, pdate or date.max))

        total = len(enriquecidos)
        enriquecidos.sort(key=lambda x: x[1])
        page_ids = [i for (i, _d) in enriquecidos[offset : offset + limit]]

        # Passo 2: linhas completas só da página, preservando a ordem.
        page_map = {
            row.id: row
            for row in self.db.query(OnerequestSolicitacao)
            .filter(OnerequestSolicitacao.id.in_(page_ids))
            .all()
        }
        page_rows = [page_map[i] for i in page_ids if i in page_map]

        # Resolve nome do responsável em lote.
        user_ids = {r.responsavel_user_id for r in page_rows if r.responsavel_user_id}
        nomes = {}
        if user_ids:
            nomes = {
                u.id: u.name
                for u in self.db.query(LegalOneUser.id, LegalOneUser.name).filter(
                    LegalOneUser.id.in_(user_ids)
                )
            }

        items = []
        for r in page_rows:
            items.append(
                {
                    "id": r.id,
                    "numero_solicitacao": r.numero_solicitacao,
                    "titulo": r.titulo,
                    "npj_direcionador": r.npj_direcionador,
                    "prazo": r.prazo,
                    "texto_dmi": r.texto_dmi,
                    "numero_processo": r.numero_processo,
                    "proc_utilizavel": _proc_utilizavel(r.numero_processo),
                    "polo": r.polo,
                    "recebido_em": r.recebido_em.isoformat() if r.recebido_em else None,
                    "status_sistema": r.status_sistema,
                    "status_tratamento": r.status_tratamento,
                    "responsavel_user_id": r.responsavel_user_id,
                    "responsavel_nome": nomes.get(r.responsavel_user_id),
                    "setor": r.setor,
                    "data_agendamento": r.data_agendamento,
                    "anotacao": r.anotacao,
                    "created_task_id": r.created_task_id,
                    "linked_lawsuit_id": r.linked_lawsuit_id,
                    "last_error": r.last_error,
                    "farol": _farol(_parse_prazo(r.prazo), hoje),
                }
            )

        return {"total": total, "kpis": kpis, "items": items}

    def get(self, solicitacao_id: int) -> Optional[OnerequestSolicitacao]:
        return (
            self.db.query(OnerequestSolicitacao)
            .filter(OnerequestSolicitacao.id == solicitacao_id)
            .first()
        )

    # ──────────────────────────────────────────────────────────────────
    # Edição do tratamento
    # ──────────────────────────────────────────────────────────────────
    def update_tratamento(self, solicitacao: OnerequestSolicitacao, dados: dict) -> OnerequestSolicitacao:
        for campo in ("responsavel_user_id", "setor", "data_agendamento", "anotacao", "status_tratamento"):
            if campo in dados and dados[campo] is not None:
                setattr(solicitacao, campo, dados[campo])
        self.db.commit()
        self.db.refresh(solicitacao)
        return solicitacao

    # ──────────────────────────────────────────────────────────────────
    # Agendamento no Legal One (reusa helpers da OnerequestStrategy)
    # ──────────────────────────────────────────────────────────────────
    def agendar(
        self,
        solicitacao: OnerequestSolicitacao,
        client: LegalOneApiClient,
        current_user: LegalOneUser,
    ) -> dict:
        """
        Cria a tarefa no L1 pra uma solicitação tratada. Retorna
        {ok, status_tratamento, created_task_id?, mensagem}.

        Cascata de resolução do processo (§7):
          1. CNJ utilizável -> search_lawsuit_by_cnj.
          2. (TODO pós-probe) CNJ ausente + NPJ -> busca por NPJ no L1.
          3. Nada resolve -> AGUARDANDO_PROCESSO (não é erro).
        """
        # Validação dos campos de tratamento (mensagens claras pro operador).
        faltando = []
        if not solicitacao.responsavel_user_id:
            faltando.append("responsável")
        if not solicitacao.setor:
            faltando.append("setor")
        if not solicitacao.data_agendamento:
            faltando.append("data de agendamento")
        if faltando:
            return {
                "ok": False,
                "status_tratamento": solicitacao.status_tratamento,
                "mensagem": f"Preencha antes de agendar: {', '.join(faltando)}.",
            }

        responsavel = (
            self.db.query(LegalOneUser)
            .filter(LegalOneUser.id == solicitacao.responsavel_user_id)
            .first()
        )
        if not responsavel or not responsavel.external_id:
            return {
                "ok": False,
                "status_tratamento": solicitacao.status_tratamento,
                "mensagem": "Responsável sem external_id no Legal One.",
            }

        # ── Cascata de resolução do processo ──────────────────────────
        if not _proc_utilizavel(solicitacao.numero_processo):
            # Etapa 2 (NPJ) virá após o probe ao vivo confirmar o campo do L1.
            solicitacao.status_tratamento = STATUS_TRATAMENTO_AGUARDANDO_PROCESSO
            solicitacao.last_error = "Sem CNJ utilizável; aguardando processo (resolução por NPJ pendente)."
            self.db.commit()
            return {
                "ok": False,
                "status_tratamento": solicitacao.status_tratamento,
                "mensagem": "Sem CNJ utilizável. Marcado como AGUARDANDO_PROCESSO.",
            }

        try:
            strat = OnerequestStrategy(self.db, client)
            type_id, subtype_id = strat._get_task_type_ids(solicitacao.setor)
            end_iso = strat._parse_and_format_deadline(solicitacao.data_agendamento)

            payload_para_textos = {
                "vencimento": solicitacao.prazo,
                "titulo": solicitacao.titulo,
                "npj_direcionador": solicitacao.npj_direcionador,
                "numero_solicitacao": solicitacao.numero_solicitacao,
                "anotacao": solicitacao.anotacao,
                "texto_dmi": solicitacao.texto_dmi,
            }
            description = strat._build_task_description(payload_para_textos)
            notes = strat._build_task_notes(payload_para_textos)

            lawsuit = client.search_lawsuit_by_cnj(solicitacao.numero_processo)
            if not lawsuit or not lawsuit.get("id"):
                solicitacao.status_tratamento = STATUS_TRATAMENTO_AGUARDANDO_PROCESSO
                solicitacao.last_error = (
                    f"Processo (CNJ {solicitacao.numero_processo}) não encontrado no Legal One."
                )
                self.db.commit()
                return {
                    "ok": False,
                    "status_tratamento": solicitacao.status_tratamento,
                    "mensagem": "Processo não encontrado no L1. Marcado como AGUARDANDO_PROCESSO.",
                }

            lawsuit_id = lawsuit["id"]
            office_id = lawsuit.get("responsibleOfficeId")
            if not office_id:
                raise Exception(f"Processo {solicitacao.numero_processo} sem responsibleOfficeId.")

            publish_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            task_payload = {
                "description": description,
                "startDateTime": end_iso,
                "endDateTime": end_iso,
                "publishDate": publish_iso,
                "status": {"id": DEFAULT_TASK_STATUS_ID},
                "typeId": type_id,
                "subTypeId": subtype_id,
                "responsibleOfficeId": office_id,
                "originOfficeId": office_id,
                "participants": [
                    {
                        "contact": {"id": responsavel.external_id},
                        "isResponsible": True,
                        "isExecuter": True,
                        "isRequester": True,
                    }
                ],
            }
            if notes:
                task_payload["notes"] = notes

            created = client.create_task(task_payload)
            if not created or not created.get("id"):
                raise Exception("Falha na criação da tarefa (resposta inválida da API).")
            task_id = created["id"]

            if not client.link_task_to_lawsuit(
                task_id, {"linkType": "Litigation", "linkId": lawsuit_id}
            ):
                logger.warning("Tarefa %s criada mas falha ao vincular ao processo %s.", task_id, lawsuit_id)

            solicitacao.created_task_id = task_id
            solicitacao.linked_lawsuit_id = lawsuit_id
            solicitacao.status_tratamento = STATUS_TRATAMENTO_AGENDADO
            solicitacao.last_error = None
            solicitacao.scheduled_by_user_id = current_user.id
            solicitacao.scheduled_by_email = current_user.email
            solicitacao.scheduled_by_nome = current_user.name
            solicitacao.scheduled_at = datetime.now(timezone.utc)
            self.db.commit()
            return {
                "ok": True,
                "status_tratamento": solicitacao.status_tratamento,
                "created_task_id": task_id,
                "mensagem": "Tarefa criada no Legal One com sucesso.",
            }

        except Exception as e:
            erro = str(e)
            solicitacao.status_tratamento = STATUS_TRATAMENTO_ERRO
            solicitacao.last_error = erro
            self.db.commit()
            logger.error(
                "Falha ao agendar OneRequest (DMI %s): %s", solicitacao.numero_solicitacao, erro
            )
            return {
                "ok": False,
                "status_tratamento": solicitacao.status_tratamento,
                "mensagem": f"Erro ao agendar: {erro}",
            }

    @staticmethod
    def setores_disponiveis() -> list[str]:
        return list(SECTOR_TASK_MAPPING.keys())

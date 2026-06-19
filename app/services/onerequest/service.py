"""Serviço operador do OneRequest (Fase 2).

Listagem com farol/KPIs + filtros (paginada), edição do tratamento e
agendamento da tarefa no Legal One. O agendamento REUSA os helpers da
`OnerequestStrategy` (mesma lógica do batch externo) e materializa a cascata
de resolução do processo (CNJ → [NPJ, pós-probe] → AGUARDANDO_PROCESSO).
Ver docs/onerequest-integracao-plano.md §6 e §7.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.legal_one import LegalOneUser
from app.models.onerequest import (
    OnerequestAnotacao,
    OnerequestSolicitacao,
    STATUS_SISTEMA_ABERTO,
    STATUS_TRATAMENTO_AGENDADO,
    STATUS_TRATAMENTO_AGUARDANDO_PROCESSO,
    STATUS_TRATAMENTO_ERRO,
    STATUS_TRATAMENTO_IGNORADO,
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


# ── Legal One web (deep-links) ─────────────────────────────────────────
L1_WEB_BASE_URL = "https://mdradvocacia.novajus.com.br"
L1_BLOCKING_STATUS_IDS = {0, 4}  # Pendente, Iniciado = "em aberto"
L1_STATUS_LABELS_FULL = {
    0: "Pendente",
    1: "Cumprido",
    2: "Não cumprido",
    3: "Cancelado",
    4: "Iniciado",
    5: "Reagendado",
}


def _l1_lawsuit_url(lawsuit_id: int) -> str:
    return f"{L1_WEB_BASE_URL}/processos/processos/DetailsCompromissosTarefas/{int(lawsuit_id)}"


def _l1_task_url(task_id, lawsuit_id) -> str:
    from urllib.parse import quote

    return_path = (
        f"/processos/processos/DetailsCompromissosTarefas/{int(lawsuit_id)}"
        "?ajaxnavigation=true&renderOnlySection=True"
    )
    return (
        f"{L1_WEB_BASE_URL}/agenda/tarefas/DetailsCompromissoTarefa/{int(task_id)}"
        f"?parentId={int(lawsuit_id)}&tipoContexto=1&hasNavigation=True"
        f"&currentPage=1&returnUrl={quote(return_path, safe='')}"
    )


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
        farol: Optional[str] = None,
        sem_responsavel: Optional[bool] = None,
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
        if sem_responsavel:
            # "Novas" = ainda SEM RESPONSÁVEL (não distribuídas), excluindo as
            # marcadas como sem providência. No painel antigo, atribuir
            # responsável = distribuir a DMI.
            q = q.filter(
                OnerequestSolicitacao.responsavel_user_id.is_(None),
                OnerequestSolicitacao.status_tratamento != STATUS_TRATAMENTO_IGNORADO,
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
            farol_row = _farol(pdate, hoje)
            if farol_row == "cinza":
                kpis["vencidas"] += 1 if pdate is not None and pdate < hoje else 0
            elif farol_row == "vermelho":
                kpis["hoje"] += 1
            elif farol_row == "amarelo":
                kpis["amanha"] += 1
            elif farol_row == "roxo":
                kpis["fds"] += 1
            elif farol_row == "verde":
                kpis["futuras"] += 1
            # ordena por prazo asc; sem data vai pro fim
            enriquecidos.append((_id, pdate or date.max, farol_row))

        if farol:
            enriquecidos = [e for e in enriquecidos if e[2] == farol]
        total = len(enriquecidos)
        enriquecidos.sort(key=lambda x: x[1])
        page_ids = [i for (i, _d, _f) in enriquecidos[offset : offset + limit]]

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

        Cascata de resolução do processo (§7) — NÃO exige CNJ:
          1. CNJ utilizável -> search_lawsuit_by_cnj.
          2. NPJ -> contains(notes/title) da pasta no L1 (a casa grava o NPJ
             nas notas/título do cadastro da pasta).
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

            # Resolução do processo: CNJ -> NPJ(notes/title). Não exige CNJ.
            lawsuit = self.resolver_lawsuit(solicitacao, client)
            if not lawsuit or not lawsuit.get("id"):
                solicitacao.status_tratamento = STATUS_TRATAMENTO_AGUARDANDO_PROCESSO
                solicitacao.last_error = (
                    "Processo não encontrado no Legal One por CNJ nem por NPJ. Aguardando processo."
                )
                self.db.commit()
                return {
                    "ok": False,
                    "status_tratamento": solicitacao.status_tratamento,
                    "mensagem": "Processo não encontrado no L1 (CNJ/NPJ). Marcado como AGUARDANDO_PROCESSO.",
                }

            lawsuit_id = lawsuit["id"]
            office_id = lawsuit.get("responsibleOfficeId")
            if not office_id:
                raise Exception(f"Processo {lawsuit_id} sem responsibleOfficeId no L1.")

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

    # ──────────────────────────────────────────────────────────────────
    # Anotações (log de auditoria por DMI)
    # ──────────────────────────────────────────────────────────────────
    def list_anotacoes(self, solicitacao_id: int) -> list[dict]:
        rows = (
            self.db.query(OnerequestAnotacao)
            .filter(OnerequestAnotacao.solicitacao_id == solicitacao_id)
            .order_by(OnerequestAnotacao.created_at.desc())
            .all()
        )
        return [
            {
                "id": a.id,
                "texto": a.texto,
                "autor_nome": a.autor_nome,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]

    def add_anotacao(self, solicitacao_id: int, texto: str, autor: LegalOneUser) -> dict:
        anot = OnerequestAnotacao(
            solicitacao_id=solicitacao_id,
            texto=texto.strip(),
            autor_user_id=autor.id,
            autor_nome=autor.name,
        )
        self.db.add(anot)
        self.db.commit()
        self.db.refresh(anot)
        return {
            "id": anot.id,
            "texto": anot.texto,
            "autor_nome": anot.autor_nome,
            "created_at": anot.created_at.isoformat() if anot.created_at else None,
        }

    # ──────────────────────────────────────────────────────────────────
    # Legal One: resolução do processo + tarefas na pasta (sob demanda)
    # ──────────────────────────────────────────────────────────────────
    def _resolver_por_npj(self, client: LegalOneApiClient, npj: Optional[str]) -> Optional[dict]:
        """Resolve a pasta pelo NPJ do BB, gravado nas NOTAS (ou título) do
        cadastro da pasta no L1. Filtra por contains(notes|title, <dígitos>).
        Confirmado empiricamente: NPJ vive em `notes` (maioria) e às vezes
        `title`; `contains` funciona no /Lawsuits (substringof não)."""
        core = re.sub(r"\D", "", (npj or "").split("-")[0])
        if len(core) < 7:
            return None
        for field in ("notes", "title"):
            try:
                res = client._paginated_catalog_loader(
                    "/Lawsuits",
                    {
                        "$filter": f"contains({field},'{core}')",
                        "$select": "id,identifierNumber,responsibleOfficeId,folder",
                        "$top": 5,
                    },
                )
            except Exception as e:
                logger.warning("OneRequest: busca por NPJ em %s falhou: %s", field, e)
                continue
            if res:
                return res[0]
        return None

    def resolver_lawsuit(
        self, solicitacao: OnerequestSolicitacao, client: LegalOneApiClient
    ) -> Optional[dict]:
        """Resolve a pasta no L1 e cacheia o lawsuit_id. Cascata: CNJ -> NPJ
        (notes/title). Retorna o dict do processo (id, responsibleOfficeId, ...)
        ou None. NÃO exige CNJ."""
        if solicitacao.linked_lawsuit_id:
            try:
                return client.get_lawsuit_by_id(solicitacao.linked_lawsuit_id)
            except Exception:
                return {"id": solicitacao.linked_lawsuit_id}

        law = None
        if _proc_utilizavel(solicitacao.numero_processo):
            try:
                law = client.search_lawsuit_by_cnj(solicitacao.numero_processo)
            except Exception as e:
                logger.warning("Falha ao resolver por CNJ %s: %s", solicitacao.numero_processo, e)
                law = None
        if not (law and law.get("id")):
            law = self._resolver_por_npj(client, solicitacao.npj_direcionador)

        if law and law.get("id"):
            solicitacao.linked_lawsuit_id = law["id"]
            self.db.commit()
            return law
        return None

    def tarefas_na_pasta(
        self, solicitacao: OnerequestSolicitacao, client: LegalOneApiClient
    ) -> dict:
        """Tarefas pendentes/concluídas na pasta do processo no L1 (sob demanda)."""
        law = self.resolver_lawsuit(solicitacao, client)
        lid = law.get("id") if law else None
        if not lid:
            return {
                "lawsuit_id": None,
                "l1_url": None,
                "pendentes": [],
                "concluidas": [],
                "resolvido": False,
                "check_failed": False,
            }
        url = _l1_lawsuit_url(lid)
        try:
            tasks = client.find_tasks_for_lawsuit(lid, top=30)
        except Exception as e:
            logger.warning("Falha ao buscar tarefas da pasta %s: %s", lid, e)
            return {
                "lawsuit_id": lid,
                "l1_url": url,
                "pendentes": [],
                "concluidas": [],
                "resolvido": True,
                "check_failed": True,
            }
        pendentes, concluidas = [], []
        for t in tasks:
            sid = t.get("statusId")
            if sid is None and isinstance(t.get("status"), dict):
                sid = t["status"].get("id")
            item = {
                "task_id": t.get("id"),
                "description": t.get("description"),
                "status_id": sid,
                "status_label": L1_STATUS_LABELS_FULL.get(sid, str(sid)),
                "end_date_time": t.get("endDateTime"),
                "l1_url": _l1_task_url(t.get("id"), lid),
            }
            (pendentes if sid in L1_BLOCKING_STATUS_IDS else concluidas).append(item)
        return {
            "lawsuit_id": lid,
            "l1_url": url,
            "pendentes": pendentes,
            "concluidas": concluidas[:10],
            "resolvido": True,
            "check_failed": False,
        }

    def estado(self) -> dict:
        """Heartbeat da última ingestão + contagem de abertas (pro aviso da UI)."""
        from app.services.app_settings import get_setting

        last = get_setting("onerequest_last_ingest_at")
        abertas = (
            self.db.query(OnerequestSolicitacao)
            .filter(OnerequestSolicitacao.status_sistema == STATUS_SISTEMA_ABERTO)
            .count()
        )
        return {"last_ingest_at": last, "abertas": abertas}

    @staticmethod
    def setores_disponiveis() -> list[str]:
        return list(SECTOR_TASK_MAPPING.keys())

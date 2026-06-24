"""Endpoints do módulo OneRequest.

Por enquanto (Fase 1) só o `intake_router`: ingresso dos dados que o MOTOR RPA
externo empurra. Autenticado por API key no header `X-Onerequest-Api-Key`
(env `ONEREQUEST_INTAKE_API_KEY`), SEM JWT — mesmo padrão do intake de Prazos
Iniciais e do Classificador. Registrado sem `protected_dependencies` em main.py.

A UI do operador (listagem/tratamento/agendar) e o acompanhamento de status no
L1 entram em fases seguintes — ver `docs/onerequest-integracao-plano.md`.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_permission
from app.core.config import settings
from app.core.dependencies import get_api_client, get_db
from app.models.legal_one import LegalOneUser
from app.services.legal_one_client import LegalOneApiClient
from app.services.onerequest import suggestions
from app.services.onerequest.intake_service import OnerequestIntakeService
from app.services.onerequest.service import OnerequestService

logger = logging.getLogger(__name__)

intake_router = APIRouter(prefix="/onerequest", tags=["OneRequest (Intake)"])


def _validate_intake_api_key(
    x_onerequest_api_key: Optional[str] = Header(
        default=None, alias="X-Onerequest-Api-Key"
    ),
) -> str:
    """
    Autentica o motor RPA externo por header `X-Onerequest-Api-Key`.

    Aceita múltiplas chaves em `ONEREQUEST_INTAKE_API_KEY` (separadas por
    vírgula) pra rotação sem downtime. Se nenhuma chave estiver configurada,
    o endpoint fica explicitamente bloqueado (503) — evita rota aberta em
    produção por esquecimento de config.
    """
    valid_keys = settings.onerequest_intake_api_keys
    if not valid_keys:
        logger.error("ONEREQUEST_INTAKE_API_KEY não configurada — intake rejeitado.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoint de intake do OneRequest não configurado.",
        )
    if not x_onerequest_api_key or x_onerequest_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida ou ausente no header X-Onerequest-Api-Key.",
        )
    return x_onerequest_api_key


# ── Schemas ────────────────────────────────────────────────────────────
class IntakeNumerosRequest(BaseModel):
    numeros: List[str] = Field(
        ...,
        description=(
            "Snapshot COMPLETO dos números de DMI abertos no portal do BB "
            "(ex.: '2026/0000000001'). O Flow faz o diff de novos/respondidos."
        ),
    )


class IntakeNumerosResponse(BaseModel):
    recebidos: int
    novos: int
    respondidos: int
    reabertos: int


class PendentesDetalheResponse(BaseModel):
    total: int
    numeros: List[str]


class IntakeDetalheItem(BaseModel):
    numero_solicitacao: str
    titulo: Optional[str] = None
    npj_direcionador: Optional[str] = None
    prazo: Optional[str] = None
    texto_dmi: Optional[str] = None
    numero_processo: Optional[str] = None
    polo: Optional[str] = None


class IntakeDetalhesRequest(BaseModel):
    itens: List[IntakeDetalheItem]


class IntakeDetalhesResponse(BaseModel):
    atualizados: int
    nao_encontrados: List[str]


# ── Endpoints ──────────────────────────────────────────────────────────
@intake_router.post(
    "/intake/numeros",
    response_model=IntakeNumerosResponse,
    summary="Sincroniza o snapshot de números de DMI abertos no portal do BB",
)
def intake_numeros(
    payload: IntakeNumerosRequest,
    db: Session = Depends(get_db),
    _: str = Depends(_validate_intake_api_key),
):
    service = OnerequestIntakeService(db)
    return service.sync_numeros(payload.numeros)


@intake_router.get(
    "/intake/pendentes-detalhe",
    response_model=PendentesDetalheResponse,
    summary="Lista os números abertos que ainda precisam de detalhamento",
)
def intake_pendentes_detalhe(
    db: Session = Depends(get_db),
    _: str = Depends(_validate_intake_api_key),
):
    service = OnerequestIntakeService(db)
    numeros = service.pendentes_detalhe()
    return PendentesDetalheResponse(total=len(numeros), numeros=numeros)


@intake_router.post(
    "/intake/detalhes",
    response_model=IntakeDetalhesResponse,
    summary="Atualiza os detalhes capturados das DMIs (título/NPJ/prazo/processo)",
)
def intake_detalhes(
    payload: IntakeDetalhesRequest,
    db: Session = Depends(get_db),
    _: str = Depends(_validate_intake_api_key),
):
    service = OnerequestIntakeService(db)
    return service.upsert_detalhes(payload.itens)


# ════════════════════════════════════════════════════════════════════════
# Router do OPERADOR (UI de tratamento) — JWT + permissão dedicada.
# Gateado por `onerequest` (default false → entra travado, só admin enxerga;
# admin libera por usuário na tela de Usuários & Permissões).
# Registrado COM protected_dependencies em main.py.
# ════════════════════════════════════════════════════════════════════════
router = APIRouter(prefix="/onerequest", tags=["OneRequest"])

_perm = Depends(require_permission("onerequest"))


class SolicitacaoOut(BaseModel):
    id: int
    numero_solicitacao: str
    titulo: Optional[str] = None
    npj_direcionador: Optional[str] = None
    prazo: Optional[str] = None
    texto_dmi: Optional[str] = None
    numero_processo: Optional[str] = None
    proc_utilizavel: bool = False
    polo: Optional[str] = None
    recebido_em: Optional[str] = None
    status_sistema: str
    status_tratamento: str
    responsavel_user_id: Optional[int] = None
    responsavel_nome: Optional[str] = None
    setor: Optional[str] = None
    data_agendamento: Optional[str] = None
    anotacao: Optional[str] = None
    created_task_id: Optional[int] = None
    linked_lawsuit_id: Optional[int] = None
    last_error: Optional[str] = None
    farol: str
    # Status no L1 (cacheado pelo botão "Atualizar status L1").
    l1_checked_at: Optional[str] = None
    l1_dmi_task_id: Optional[int] = None
    l1_dmi_status_id: Optional[int] = None
    l1_dmi_status_label: Optional[str] = None
    l1_dmi_respondida: bool = False
    l1_dmi_encontrada: bool = False
    l1_pendentes_count: Optional[int] = None
    l1_sem_pendencia: Optional[bool] = None
    l1_task_url: Optional[str] = None


class ListResponse(BaseModel):
    total: int
    kpis: Dict[str, int]
    items: List[SolicitacaoOut]


class OptionsResponse(BaseModel):
    setores: List[str]


class UpdateTratamentoRequest(BaseModel):
    responsavel_user_id: Optional[int] = None
    setor: Optional[str] = None
    data_agendamento: Optional[str] = None
    anotacao: Optional[str] = None
    status_tratamento: Optional[str] = None


class UpdateResponse(BaseModel):
    ok: bool
    id: int
    status_tratamento: str


class AgendarResponse(BaseModel):
    ok: bool
    status_tratamento: str
    created_task_id: Optional[int] = None
    mensagem: str


@router.get(
    "/solicitacoes",
    response_model=ListResponse,
    summary="Lista solicitações (DMIs) com farol/KPIs, paginada",
    dependencies=[_perm],
)
def listar_solicitacoes(
    status_sistema: Optional[str] = Query(None),
    status_tratamento: Optional[str] = Query(None),
    responsavel_user_id: Optional[int] = Query(None),
    busca: Optional[str] = Query(None),
    farol: Optional[str] = Query(None, description="Filtra por farol: cinza|vermelho|amarelo|roxo|verde"),
    sem_responsavel: Optional[bool] = Query(None, description="Apenas DMIs sem responsável (não distribuídas)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = OnerequestService(db)
    return service.list_solicitacoes(
        status_sistema=status_sistema or None,
        status_tratamento=status_tratamento,
        responsavel_user_id=responsavel_user_id,
        busca=busca,
        farol=farol,
        sem_responsavel=sem_responsavel,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/options",
    response_model=OptionsResponse,
    summary="Opções pro formulário (setores disponíveis)",
    dependencies=[_perm],
)
def opcoes():
    return OptionsResponse(setores=OnerequestService.setores_disponiveis())


class EstadoResponse(BaseModel):
    last_ingest_at: Optional[str] = None
    abertas: int


@router.get(
    "/estado",
    response_model=EstadoResponse,
    summary="Estado do módulo: data da última ingestão + total de abertas",
    dependencies=[_perm],
)
def estado(db: Session = Depends(get_db)):
    return OnerequestService(db).estado()


@router.patch(
    "/solicitacoes/{solicitacao_id}",
    response_model=UpdateResponse,
    summary="Atualiza o tratamento de uma solicitação",
    dependencies=[_perm],
)
def atualizar_tratamento(
    solicitacao_id: int,
    payload: UpdateTratamentoRequest,
    db: Session = Depends(get_db),
):
    service = OnerequestService(db)
    row = service.get(solicitacao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    row = service.update_tratamento(row, payload.model_dump(exclude_unset=True))
    return UpdateResponse(ok=True, id=row.id, status_tratamento=row.status_tratamento)


@router.post(
    "/solicitacoes/{solicitacao_id}/agendar",
    response_model=AgendarResponse,
    summary="Cria a tarefa no Legal One para a solicitação tratada",
    dependencies=[_perm],
)
def agendar_solicitacao(
    solicitacao_id: int,
    db: Session = Depends(get_db),
    client: LegalOneApiClient = Depends(get_api_client),
    current_user: LegalOneUser = Depends(get_current_user),
):
    service = OnerequestService(db)
    row = service.get(solicitacao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return service.agendar(row, client, current_user)


# ── Sugestão (motor de pré-preenchimento) ──────────────────────────────
class SugestaoResponse(BaseModel):
    setor: Optional[str] = None
    setor_confianca: Optional[str] = None
    responsavel_user_id: Optional[int] = None
    responsavel_nome: Optional[str] = None
    responsavel_confianca: Optional[int] = None
    data_agendamento: Optional[str] = None


@router.get(
    "/solicitacoes/{solicitacao_id}/sugestao",
    response_model=SugestaoResponse,
    summary="Sugestão de setor/responsável/data (motor parametrizado)",
    dependencies=[_perm],
)
def sugestao(solicitacao_id: int, db: Session = Depends(get_db)):
    service = OnerequestService(db)
    row = service.get(solicitacao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return suggestions.sugerir(db, titulo=row.titulo, polo=row.polo, prazo=row.prazo)


# ── Tarefas na pasta (Legal One, sob demanda) ──────────────────────────
class L1TaskItem(BaseModel):
    task_id: Optional[int] = None
    description: Optional[str] = None
    status_id: Optional[int] = None
    status_label: Optional[str] = None
    end_date_time: Optional[str] = None
    l1_url: Optional[str] = None


class L1TarefasResponse(BaseModel):
    lawsuit_id: Optional[int] = None
    l1_url: Optional[str] = None
    pendentes: List[L1TaskItem]
    concluidas: List[L1TaskItem]
    resolvido: bool
    check_failed: bool


@router.get(
    "/solicitacoes/{solicitacao_id}/l1-tarefas",
    response_model=L1TarefasResponse,
    summary="Tarefas pendentes/concluídas na pasta do processo no Legal One",
    dependencies=[_perm],
)
def l1_tarefas(
    solicitacao_id: int,
    db: Session = Depends(get_db),
    client: LegalOneApiClient = Depends(get_api_client),
):
    service = OnerequestService(db)
    row = service.get(solicitacao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return service.tarefas_na_pasta(row, client)


# ── Status no Legal One (sob demanda) ──────────────────────────────────
class StatusL1Response(BaseModel):
    checked_at: Optional[str] = None
    resolvido: bool = False
    lawsuit_id: Optional[int] = None
    l1_url: Optional[str] = None
    # Sinal A: a tarefa da DMI (match por número da solicitação).
    dmi_task_id: Optional[int] = None
    dmi_task_url: Optional[str] = None
    dmi_status_id: Optional[int] = None
    dmi_status_label: Optional[str] = None
    dmi_respondida: bool = False
    dmi_encontrada: bool = False
    # Sinal B: pendências na pasta.
    pendentes_count: Optional[int] = None
    sem_pendencia: Optional[bool] = None


@router.post(
    "/solicitacoes/{solicitacao_id}/status-l1",
    response_model=StatusL1Response,
    summary="Checa no Legal One se a tarefa da DMI foi respondida (Cumprida) e se a pasta tem pendência",
    dependencies=[_perm],
)
def status_l1(
    solicitacao_id: int,
    db: Session = Depends(get_db),
    client: LegalOneApiClient = Depends(get_api_client),
):
    service = OnerequestService(db)
    row = service.get(solicitacao_id)
    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    return service.verificar_status_l1(row, client)


# ── Anotações (log de auditoria) ───────────────────────────────────────
class AnotacaoItem(BaseModel):
    id: int
    texto: str
    autor_nome: Optional[str] = None
    created_at: Optional[str] = None


class AnotacaoCreate(BaseModel):
    texto: str


@router.get(
    "/solicitacoes/{solicitacao_id}/anotacoes",
    response_model=List[AnotacaoItem],
    summary="Histórico de anotações da DMI",
    dependencies=[_perm],
)
def listar_anotacoes(solicitacao_id: int, db: Session = Depends(get_db)):
    return OnerequestService(db).list_anotacoes(solicitacao_id)


@router.post(
    "/solicitacoes/{solicitacao_id}/anotacoes",
    response_model=AnotacaoItem,
    status_code=201,
    summary="Adiciona uma anotação (log de auditoria) à DMI",
    dependencies=[_perm],
)
def criar_anotacao(
    solicitacao_id: int,
    payload: AnotacaoCreate,
    db: Session = Depends(get_db),
    current_user: LegalOneUser = Depends(get_current_user),
):
    service = OnerequestService(db)
    if not service.get(solicitacao_id):
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")
    if not (payload.texto or "").strip():
        raise HTTPException(status_code=400, detail="Anotação vazia.")
    return service.add_anotacao(solicitacao_id, payload.texto, current_user)

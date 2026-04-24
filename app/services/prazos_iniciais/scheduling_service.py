from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.legal_one import LegalOneTaskSubType
from app.models.prazo_inicial import (
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_IN_REVIEW,
    INTAKE_STATUS_SCHEDULE_ERROR,
    INTAKE_STATUS_SCHEDULED,
    SUGESTAO_REVIEW_APPROVED,
    SUGESTAO_REVIEW_EDITED,
    SUGESTAO_REVIEW_PENDING,
    SUGESTAO_REVIEW_REJECTED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.services.legal_one_client import LegalOneApiClient
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)

logger = logging.getLogger(__name__)

# Limite rigoroso do campo `description` na API de Tarefa do L1. Acima
# disso o servidor responde 400. Mesmo limite usado no módulo
# Publicações (publication_search_service.py).
_L1_DESCRIPTION_MAX_CHARS = 250


VALID_CONFIRM_REVIEW_STATUSES = {
    SUGESTAO_REVIEW_APPROVED,
    SUGESTAO_REVIEW_EDITED,
}


@dataclass(frozen=True)
class ConfirmedSuggestionInput:
    suggestion_id: int
    created_task_id: Optional[int] = None
    review_status: Optional[str] = None


class PrazosIniciaisSchedulingService:
    def __init__(
        self,
        db: Session,
        l1_client: Optional[LegalOneApiClient] = None,
    ):
        self.db = db
        self.queue_service = PrazosIniciaisLegacyTaskQueueService(db)
        # Lazy: instancia o client L1 apenas quando for preciso criar task,
        # pra nao exigir auth OAuth em testes que nao agendam.
        self._l1_client = l1_client

    @property
    def l1_client(self) -> LegalOneApiClient:
        if self._l1_client is None:
            self._l1_client = LegalOneApiClient()
        return self._l1_client

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _load_intake(self, intake_id: int) -> Optional[PrazoInicialIntake]:
        return (
            self.db.query(PrazoInicialIntake)
            .options(joinedload(PrazoInicialIntake.sugestoes))
            .filter(PrazoInicialIntake.id == intake_id)
            .first()
        )

    # ──────────────────────────────────────────────
    # Criação de tarefa no Legal One (Onda 1)
    # ──────────────────────────────────────────────

    def _resolve_parent_type_id(self, subtype_external_id: int) -> Optional[int]:
        """
        Resolve o `typeId` (tipo-pai do SubType) a partir do catálogo local
        de L1 — populado pelos syncs do `legal_one_catalog_service`.
        """
        subtype = (
            self.db.query(LegalOneTaskSubType)
            .options(joinedload(LegalOneTaskSubType.parent_type))
            .filter(LegalOneTaskSubType.external_id == int(subtype_external_id))
            .first()
        )
        if subtype and subtype.parent_type:
            return subtype.parent_type.external_id
        return None

    def _build_l1_task_payload(
        self,
        *,
        sugestao: PrazoInicialSugestao,
        intake: PrazoInicialIntake,
    ) -> dict[str, Any]:
        """
        Constrói o payload de criação de Tarefa no L1 a partir da sugestão
        (já casada com template via classifier) e do intake pai.

        Campos obrigatórios do L1:
            - description, priority, startDateTime, endDateTime, publishDate
            - typeId, subTypeId
            - status, responsibleOfficeId, originOfficeId
            - participants (com responsável)

        Pré-condições que a sugestão precisa atender; se falhar, levanta
        ValueError explícito pra que o confirm_intake_scheduling aborte
        atomicamente sem enfileirar cancelamento da legada.
        """
        if not sugestao.task_subtype_id:
            raise ValueError(
                f"Sugestão {sugestao.id} sem task_subtype_id. "
                "Template não casou — verifique prazo_inicial_task_templates."
            )
        if not sugestao.responsavel_sugerido_id:
            raise ValueError(
                f"Sugestão {sugestao.id} sem responsável sugerido. "
                "Template precisa ter responsible_user_external_id preenchido."
            )
        if not sugestao.data_final_calculada:
            raise ValueError(
                f"Sugestão {sugestao.id} sem data_final_calculada. "
                "Prazo não foi calculado — revise a classificação."
            )

        type_id = self._resolve_parent_type_id(sugestao.task_subtype_id)
        if not type_id:
            raise ValueError(
                f"Tipo-pai do subTypeId={sugestao.task_subtype_id} não encontrado "
                "no catálogo local — sincronize o catálogo de tasks do L1."
            )

        # Data final da sugestão (Date) vira "YYYY-MM-DDT23:59:00Z" no L1.
        due_date: date = sugestao.data_final_calculada
        due_iso = f"{due_date.isoformat()}T23:59:00Z"

        # publishDate: L1 exige quando SubTypeId está preenchido. Usa a data
        # base da sugestão (origem do prazo) ou cai na due_date.
        base_date: date = sugestao.data_base or due_date
        publish_iso = f"{base_date.isoformat()}T00:00:00Z"

        # Preserva description/notes/priority já renderizados pelo template
        # via _apply_template_to_sugestao. Se não houver, gera fallback
        # seguro (tarefa ainda assim cria — mas fica genérica).
        rendered = dict(sugestao.payload_proposto or {})
        description = (rendered.get("description") or "").strip()
        if not description:
            description = f"{sugestao.tipo_prazo} · CNJ {intake.cnj_number or '?'}"
        if len(description) > _L1_DESCRIPTION_MAX_CHARS:
            description = description[: _L1_DESCRIPTION_MAX_CHARS - 1].rstrip() + "…"

        notes = rendered.get("notes")
        priority = rendered.get("priority") or "Normal"

        office_id = intake.office_id

        payload: dict[str, Any] = {
            "description": description,
            "priority": priority,
            "startDateTime": due_iso,
            "endDateTime": due_iso,
            "publishDate": publish_iso,
            "status": {"id": 0},
            "typeId": int(type_id),
            "subTypeId": int(sugestao.task_subtype_id),
            "participants": [
                {
                    "contact": {"id": int(sugestao.responsavel_sugerido_id)},
                    "isResponsible": True,
                    "isExecuter": True,
                    "isRequester": True,
                }
            ],
        }
        if notes:
            payload["notes"] = notes
        if office_id:
            payload["responsibleOfficeId"] = int(office_id)
            payload["originOfficeId"] = int(office_id)
        return payload

    def _create_task_in_legal_one(
        self,
        *,
        sugestao: PrazoInicialSugestao,
        intake: PrazoInicialIntake,
    ) -> int:
        """
        Cria a tarefa no L1 e vincula ao processo (quando há lawsuit_id).
        Retorna o task_id. Em falha, levanta exceção.
        """
        payload = self._build_l1_task_payload(sugestao=sugestao, intake=intake)
        logger.info(
            "prazos_iniciais.create_task: intake=%s sugestao=%s subType=%s cnj=%s",
            intake.id, sugestao.id, sugestao.task_subtype_id, intake.cnj_number,
        )
        created = self.l1_client.create_task(payload)
        if not created or not created.get("id"):
            # Mensagem humanizada do L1 quando disponível (ex: "Campos
            # obrigatórios não enviados: Data de publicação"). Fallback
            # pro genérico com identificador da sugestão.
            l1_detail = self.l1_client.format_last_create_task_error()
            raise RuntimeError(
                l1_detail
                or f"Legal One recusou a criação da tarefa (sugestão #{sugestao.id})."
            )
        task_id = int(created["id"])

        # Vínculo ao processo (se houver). Sem lawsuit_id, a tarefa fica
        # avulsa no L1 — cenário raro mas legítimo (intake sem match CNJ).
        if intake.lawsuit_id:
            try:
                self.l1_client.link_task_to_lawsuit(
                    task_id,
                    {"linkType": "Litigation", "linkId": int(intake.lawsuit_id)},
                )
            except Exception as exc:  # noqa: BLE001
                # Task foi criada mas não linkou — log warning e segue.
                # Não reverte pois criar a task sem vínculo é menos ruim
                # que zerar a task recém-criada.
                logger.warning(
                    "prazos_iniciais.link_task falhou (task_id=%s lawsuit=%s): %s",
                    task_id, intake.lawsuit_id, exc,
                )
        return task_id

    def confirm_intake_scheduling(
        self,
        *,
        intake_id: int,
        confirmed_suggestions: Optional[list[ConfirmedSuggestionInput]],
        confirmed_by_email: str,
        enqueue_legacy_task_cancellation: bool = True,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        create_tasks_in_l1: bool = True,
    ) -> dict:
        intake = self._load_intake(intake_id)
        if intake is None:
            raise ValueError("Intake não encontrado.")

        allowed_statuses = {
            INTAKE_STATUS_IN_REVIEW,
            INTAKE_STATUS_CLASSIFIED,
            INTAKE_STATUS_SCHEDULED,
            INTAKE_STATUS_SCHEDULE_ERROR,
        }
        if intake.status not in allowed_statuses:
            raise RuntimeError(
                f"Confirmação permitida apenas em EM_REVISAO / CLASSIFICADO / AGENDADO / ERRO_AGENDAMENTO. Status atual: {intake.status}."
            )

        by_id = {s.id: s for s in intake.sugestoes or []}
        now = self._utcnow()

        if confirmed_suggestions:
            selected: list[tuple[PrazoInicialSugestao, ConfirmedSuggestionInput]] = []
            for entry in confirmed_suggestions:
                sugestao = by_id.get(entry.suggestion_id)
                if sugestao is None:
                    raise ValueError(
                        f"Sugestão {entry.suggestion_id} não pertence ao intake {intake_id}."
                    )
                selected.append((sugestao, entry))
        else:
            selected = [
                (s, ConfirmedSuggestionInput(suggestion_id=s.id))
                for s in intake.sugestoes or []
                if s.review_status != SUGESTAO_REVIEW_REJECTED
            ]

        if not selected:
            raise RuntimeError(
                "Nenhuma sugestão elegível para confirmar o agendamento deste intake."
            )

        # ── FASE 1 — valida review_status de todas antes de tocar no L1 ──
        # Falha cedo em erro estrutural (sem review_status válido).
        for sugestao, entry in selected:
            target_status = entry.review_status or sugestao.review_status or SUGESTAO_REVIEW_PENDING
            if target_status == SUGESTAO_REVIEW_PENDING:
                target_status = SUGESTAO_REVIEW_APPROVED
            if target_status not in VALID_CONFIRM_REVIEW_STATUSES:
                raise ValueError(
                    f"review_status inválido para confirmação: {target_status!r}."
                )

        # ── FASE 2 — cria as tasks no L1 ATOMICAMENTE ──
        # Política Onda 1 (definida com a TI do MDR):
        #   - Se qualquer criação falhar, interrompe a leva inteira.
        #   - Sugestões que já tiverem created_task_id (vindo do frontend ou
        #     de uma tentativa anterior) NÃO são recriadas — idempotência.
        #   - Em caso de falha, intake vira ERRO_AGENDAMENTO, error_message
        #     guarda contexto, e a fila de cancelamento da task legada
        #     NÃO é enfileirada (evita cenário pior: cancela antiga e não
        #     cria nova → processo órfão).
        l1_created_ids: list[int] = []  # só novos, pra log
        if create_tasks_in_l1:
            try:
                for sugestao, entry in selected:
                    # Prioridade: se o caller já passou created_task_id, usa
                    # (compat com quem criava via outro caminho); senão, se
                    # a sugestão já tem task persistido, também respeita.
                    preset = entry.created_task_id
                    if preset is not None:
                        sugestao.created_task_id = int(preset)
                        continue
                    if sugestao.created_task_id is not None:
                        continue
                    # Cria no L1 de verdade
                    task_id = self._create_task_in_legal_one(
                        sugestao=sugestao, intake=intake,
                    )
                    sugestao.created_task_id = task_id
                    l1_created_ids.append(task_id)
            except Exception as exc:  # noqa: BLE001
                # Rollback lógico: reverte os review_status que ainda não
                # mexemos (FASE 3 não rodou) e marca intake como erro.
                # As sugestões que JÁ tinham created_task_id ficam — se
                # uma task de fato foi criada no L1 antes do erro, ela
                # existe lá; não dá pra deletar "pela metade".
                self.db.rollback()
                intake = self._load_intake(intake_id)  # recarrega pós-rollback
                if intake is not None:
                    intake.status = INTAKE_STATUS_SCHEDULE_ERROR
                    intake.error_message = (
                        f"Falha ao criar tarefa no Legal One: {str(exc)[:500]}"
                    )
                    self.db.commit()
                logger.exception(
                    "prazos_iniciais.confirm_intake_scheduling: falhou ao criar "
                    "task no L1 (intake_id=%s, criadas_antes_do_erro=%s): %s",
                    intake_id, l1_created_ids, exc,
                )
                raise RuntimeError(
                    f"Falha ao criar tarefa no Legal One (intake {intake_id}): {exc}"
                ) from exc

        # ── FASE 3 — persiste review_status e promove intake ──
        # Só chega aqui se a FASE 2 completou sem exceção.
        confirmed_ids: list[int] = []
        created_task_ids: list[int] = []
        for sugestao, entry in selected:
            target_status = entry.review_status or sugestao.review_status or SUGESTAO_REVIEW_PENDING
            if target_status == SUGESTAO_REVIEW_PENDING:
                target_status = SUGESTAO_REVIEW_APPROVED

            sugestao.review_status = target_status
            sugestao.reviewed_by_email = confirmed_by_email
            sugestao.reviewed_at = now
            if sugestao.created_task_id is not None:
                created_task_ids.append(int(sugestao.created_task_id))
            confirmed_ids.append(sugestao.id)

        intake.status = INTAKE_STATUS_SCHEDULED
        intake.error_message = None

        queue_item = None
        if enqueue_legacy_task_cancellation:
            queue_item = self.queue_service.sync_item_from_intake(
                intake,
                commit=False,
                legacy_task_type_external_id=legacy_task_type_external_id,
                legacy_task_subtype_external_id=legacy_task_subtype_external_id,
            )

        self.db.commit()
        self.db.refresh(intake)
        if queue_item is not None:
            self.db.refresh(queue_item)

        return {
            "intake": intake,
            "confirmed_suggestion_ids": confirmed_ids,
            "created_task_ids": created_task_ids,
            "legacy_task_cancellation_item": (
                self.queue_service._item_to_dict(queue_item) if queue_item else None
            ),
        }

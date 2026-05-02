from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session, joinedload

from app.models.legal_one import LegalOneTaskSubType
from app.models.prazo_inicial import (
    INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE,
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
from app.core.config import settings
from app.services.legal_one_client import (
    LegalOneApiClient,
    LegalOneGedUploadError,
)
from app.services.prazos_iniciais import storage as pdf_storage
from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
)
from app.services.prazos_iniciais.ged_rpa_upload_service import GedRpaUploadService
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

    # ──────────────────────────────────────────────
    # Upload do PDF da habilitação no GED (Onda 3)
    # ──────────────────────────────────────────────

    def _upload_habilitacao_to_ged(
        self,
        intake: PrazoInicialIntake,
    ) -> int:
        """
        Upload do PDF da habilitação no GED do L1 vinculado ao processo.
        Retorna o `document_id`. Levanta LegalOneGedUploadError em falha.

        Idempotente: se `intake.ged_document_id` já existe, retorna ele
        sem fazer nada (evita duplicar upload em retries).

        Pré-condições:
          - `intake.lawsuit_id` preenchido (o GED L1 exige vínculo)
          - `intake.pdf_path` apontando pra arquivo físico ainda presente
        """
        if intake.ged_document_id:
            return int(intake.ged_document_id)

        if not intake.lawsuit_id:
            raise LegalOneGedUploadError(
                f"Intake {intake.id} não tem lawsuit_id — GED requer vínculo a processo."
            )
        if not intake.pdf_path:
            raise LegalOneGedUploadError(
                f"Intake {intake.id} sem pdf_path (retido: {intake.pdf_bytes} bytes). "
                "Arquivo já foi limpo ou nunca chegou."
            )

        try:
            absolute = pdf_storage.resolve_pdf_path(intake.pdf_path)
        except ValueError as exc:
            raise LegalOneGedUploadError(
                f"pdf_path inválido do intake {intake.id}: {exc}"
            ) from exc

        if not absolute.exists():
            raise LegalOneGedUploadError(
                f"PDF físico não encontrado em {absolute} (intake {intake.id})."
            )

        file_bytes = absolute.read_bytes()
        if not file_bytes:
            raise LegalOneGedUploadError(
                f"Arquivo PDF vazio (intake {intake.id}, path={intake.pdf_path})."
            )

        # A API ECM ficou preservada em branch propria, mas o caminho ativo
        # agora sobe a habilitacao pela interface web do Legal One via RPA.
        archive_name = (
            f"Habilitação — {intake.cnj_number}.pdf" if intake.cnj_number
            else f"Habilitação intake #{intake.id}.pdf"
        )
        description = (
            f"Habilitação nos autos (intake Flow #{intake.id}) — "
            f"CNJ {intake.cnj_number or '?'}"
        )

        try:
            result = GedRpaUploadService().upload_document(
                intake_id=int(intake.id),
                lawsuit_id=int(intake.lawsuit_id),
                cnj_number=intake.cnj_number,
                pdf_path=absolute,
                archive_name=archive_name,
                description=description,
                type_id=settings.prazos_iniciais_ged_type_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise LegalOneGedUploadError(
                f"Falha no RPA de upload GED: {exc}"
            ) from exc

        document_id = int(result["document_id"])
        logger.info(
            "GED RPA upload OK: intake=%s lawsuit=%s document_id=%s size=%d run_dir=%s",
            intake.id,
            intake.lawsuit_id,
            document_id,
            len(file_bytes),
            result.get("run_dir"),
        )
        return document_id

    def _cleanup_local_pdf(self, intake: PrazoInicialIntake) -> None:
        """
        Deleta o PDF local e zera `pdf_path` + `pdf_bytes`. Chamado logo
        após upload GED bem-sucedido. Best-effort — se a deleção falhar,
        loga mas não quebra o fluxo (cron de cleanup pega depois).
        """
        if not intake.pdf_path:
            return
        try:
            pdf_storage.delete_pdf(intake.pdf_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Falha ao apagar PDF local do intake %s (%s): %s",
                intake.id, intake.pdf_path, exc,
            )
            return
        intake.pdf_path = None
        intake.pdf_bytes = None

    def confirm_intake_scheduling(
        self,
        *,
        intake_id: int,
        confirmed_suggestions: Optional[list[ConfirmedSuggestionInput]],
        confirmed_by_email: str,
        confirmed_by_user_id: Optional[int] = None,
        confirmed_by_name: Optional[str] = None,
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
                    # Template "no-op" (pin014): sugestao casou template
                    # marcado pra finalizar caso sem providencia. Pula a
                    # criacao no L1 — o intake ainda sobe habilitacao e
                    # cancela a legacy task no dispatch_treatment_web.
                    if (sugestao.payload_proposto or {}).get("skip_task_creation"):
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

        # ── FASE 2.5 — DESACOPLADO (Onda 3 #5) ──
        # GED upload + cleanup do PDF local migrou pra
        # `dispatch_treatment_web` (chamado manualmente da Tratamento Web ou
        # automaticamente pelo worker periódico). Aqui só marcamos
        # `dispatch_pending=True` no fim da FASE 3 — o disparo acontece
        # depois, em transação separada.

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

        # Template "no-op" (pin014): se TODAS as sugestoes confirmadas
        # vieram de template marcado pra finalizar sem providencia (sem
        # task criada no L1), o intake termina como
        # CONCLUIDO_SEM_PROVIDENCIA — mesmo terminal do "Finalizar sem
        # providencia" manual, separa em relatorios "tasks criadas" de
        # "no-ops". Mistura (algumas sugestoes com task + algumas no-op)
        # mantem AGENDADO porque pelo menos 1 task foi criada no L1.
        all_no_op = all(
            (s.created_task_id is None)
            and bool((s.payload_proposto or {}).get("skip_task_creation"))
            for s, _ in selected
        )
        intake.status = (
            INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE
            if all_no_op
            else INTAKE_STATUS_SCHEDULED
        )
        intake.error_message = None
        # Registra QUEM tratou finalisticamente o intake (pin011)
        intake.treated_by_user_id = confirmed_by_user_id
        intake.treated_by_email = confirmed_by_email
        intake.treated_by_name = confirmed_by_name
        intake.treated_at = now

        # Onda 3 #5 — Disparo desacoplado: GED + enqueue cancel acontecem
        # depois, via `dispatch_treatment_web`. Marca pendente aqui.
        # O parâmetro `enqueue_legacy_task_cancellation` é mantido na
        # assinatura por compat, mas vira no-op aqui (o disparo é sempre
        # diferido). Se alguém setar False explicitamente, ainda assim
        # marcamos pendente — o operador decide depois se aciona.
        intake.dispatch_pending = True
        intake.dispatched_at = None
        intake.dispatch_error_message = None

        self.db.commit()
        self.db.refresh(intake)

        return {
            "intake": intake,
            "confirmed_suggestion_ids": confirmed_ids,
            "created_task_ids": created_task_ids,
            "legacy_task_cancellation_item": None,  # diferido — Onda 3 #5
        }

    # ──────────────────────────────────────────────
    # Finalizar sem providência (Caminho A)
    # ──────────────────────────────────────────────
    # Caso operacional: operador analisou o processo e determinou que
    # o banco NÃO precisa tomar nenhuma providência (ex.: sentença de
    # improcedência já transitada, extinção sem resolução do mérito,
    # processo arquivado). O fluxo é:
    #   1. Sobe habilitação no GED do L1 (reusa Onda 3 — idempotente).
    #   2. Apaga PDF local.
    #   3. Marca intake como CONCLUIDO_SEM_PROVIDENCIA.
    #   4. Enfileira cancelamento da task legada "Agendar Prazos".
    # NÃO cria nenhuma task nova no L1.

    # Status elegíveis pra finalizar sem providência. AGENDADO fica de
    # fora — se já tem task criada, finalizar sem providência seria
    # inconsistente (a task existiria sem cobrir a publicação original).
    _FINALIZE_WITHOUT_PROVIDENCE_ALLOWED_STATUSES = frozenset({
        INTAKE_STATUS_IN_REVIEW,
        INTAKE_STATUS_CLASSIFIED,
        INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
        INTAKE_STATUS_SCHEDULE_ERROR,
        INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE,  # idempotente
    })

    def finalize_without_scheduling(
        self,
        *,
        intake_id: int,
        confirmed_by_email: str,
        confirmed_by_user_id: Optional[int] = None,
        confirmed_by_name: Optional[str] = None,
        notes: Optional[str] = None,
        enqueue_legacy_task_cancellation: bool = True,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    ) -> dict:
        """
        Finaliza o intake sem criar tarefa no L1. Sobe habilitação pro
        GED, cancela a task legada, marca intake como
        CONCLUIDO_SEM_PROVIDENCIA.

        Idempotente: se já está nesse status, reexecuta os passos que
        ainda não terminaram (GED upload via `ged_document_id`, cleanup
        local via `pdf_path`, enfileiramento da legada).

        Levanta ValueError se intake não existe, RuntimeError se o
        status atual não permite essa operação ou se o GED falhar.
        """
        intake = self._load_intake(intake_id)
        if intake is None:
            raise ValueError("Intake não encontrado.")

        if intake.status not in self._FINALIZE_WITHOUT_PROVIDENCE_ALLOWED_STATUSES:
            raise RuntimeError(
                "Finalizar sem providência só é permitido nos status "
                f"{sorted(self._FINALIZE_WITHOUT_PROVIDENCE_ALLOWED_STATUSES)}. "
                f"Status atual: {intake.status}."
            )

        if not intake.lawsuit_id:
            raise RuntimeError(
                "Intake sem lawsuit_id — GED do L1 exige vínculo a processo. "
                "Reprocesse o CNJ antes ou cancele o intake."
            )

        # ── Fase 1 — DESACOPLADO (Onda 3 #5) ──
        # GED upload migrou pra `dispatch_treatment_web`. Aqui só
        # transicionamos o status + marcamos `dispatch_pending=True`.

        # ── Fase 2 — Status + metadados de auditoria ──
        now = self._utcnow()
        intake.status = INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE
        intake.error_message = None
        # Registra QUEM tratou finalisticamente o intake (pin011)
        intake.treated_by_user_id = confirmed_by_user_id
        intake.treated_by_email = confirmed_by_email
        intake.treated_by_name = confirmed_by_name
        intake.treated_at = now
        # Anexa notas de auditoria em metadata_json sem sobrescrever
        # o que já tem lá (metadata livre da automação externa).
        if notes:
            meta = dict(intake.metadata_json or {})
            finalize_log = meta.setdefault("finalize_without_providence", [])
            if isinstance(finalize_log, list):
                finalize_log.append({
                    "at": now.isoformat(),
                    "by": confirmed_by_email,
                    "notes": notes[:500],
                })
                intake.metadata_json = meta

        # ── Fase 3 — Marca pendente de disparo (Onda 3 #5) ──
        # Fila de cancelamento da legada migrou pra `dispatch_treatment_web`.
        intake.dispatch_pending = True
        intake.dispatched_at = None
        intake.dispatch_error_message = None

        self.db.commit()
        self.db.refresh(intake)

        logger.info(
            "intake %s finalizado sem providencia por %s — dispatch_pending=True",
            intake_id, confirmed_by_email,
        )

        return {
            "intake": intake,
            "legacy_task_cancellation_item": None,  # diferido — Onda 3 #5
        }

    # ──────────────────────────────────────────────
    # Onda 3 #5 — Disparo desacoplado: Tratamento Web
    # ──────────────────────────────────────────────
    # Após o operador confirmar (ou finalizar sem providência) o intake
    # no HITL, o status vai pra AGENDADO/CONCLUIDO_SEM_PROVIDENCIA com
    # `dispatch_pending=True`. O disparo de GED + cancel da legada
    # acontece aqui — chamado:
    #   • Manualmente, via botão "Disparar agora" na Tratamento Web
    #   • Automaticamente, via worker periódico (Onda 3 #6) com batch_limit
    #
    # Idempotente: GED upload pula se `ged_document_id` já existe;
    # enqueue cancel é idempotente via queue_service.sync_item_from_intake.
    # Se algum passo falhar, mantém `dispatch_pending=True` e grava o erro
    # em `dispatch_error_message` pra retry posterior.

    def dispatch_treatment_web(
        self,
        *,
        intake_id: int,
        legacy_task_type_external_id: int = DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        legacy_task_subtype_external_id: int = DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    ) -> dict:
        """Executa o disparo desacoplado: GED upload + enqueue cancel.

        Pré-condições:
          - intake.dispatch_pending == True (caso contrário, no-op)
          - intake.lawsuit_id setado (GED exige vínculo a processo)
          - intake.status em {AGENDADO, CONCLUIDO_SEM_PROVIDENCIA} —
            os únicos terminais que disparam tratamento web

        Comportamento:
          - GED upload (idempotente via ged_document_id)
          - Cleanup do PDF local após GED
          - Enqueue na fila de cancelamento da legada (force_queue=True)
          - Marca dispatch_pending=False, dispatched_at=now
          - Em erro: dispatch_pending fica True, dispatch_error_message
            recebe o motivo, exception é re-levantada
        """
        intake = self._load_intake(intake_id)
        if intake is None:
            raise ValueError("Intake não encontrado.")

        if not intake.dispatch_pending:
            # Idempotente: já disparado.
            return {
                "intake": intake,
                "legacy_task_cancellation_item": None,
                "skipped": True,
                "reason": "dispatch_pending=False (já disparado)",
            }

        if intake.status not in (
            INTAKE_STATUS_SCHEDULED,
            INTAKE_STATUS_COMPLETED_WITHOUT_PROVIDENCE,
        ):
            raise RuntimeError(
                "Disparo só é permitido em AGENDADO ou "
                f"CONCLUIDO_SEM_PROVIDENCIA. Status atual: {intake.status}."
            )

        if not intake.lawsuit_id:
            raise RuntimeError(
                "Intake sem lawsuit_id — GED do L1 exige vínculo a processo."
            )

        # ── Fase 1 — Upload GED (idempotente) ──
        try:
            if not intake.ged_document_id:
                document_id = self._upload_habilitacao_to_ged(intake)
                intake.ged_document_id = int(document_id)
                intake.ged_uploaded_at = self._utcnow()
                self._cleanup_local_pdf(intake)
                self.db.commit()
        except LegalOneGedUploadError as exc:
            self.db.rollback()
            intake = self._load_intake(intake_id)
            if intake is not None:
                intake.dispatch_error_message = (
                    f"GED upload falhou: {str(exc)[:500]}"
                )
                self.db.commit()
            logger.exception(
                "dispatch_treatment_web: GED falhou (intake_id=%s): %s",
                intake_id, exc,
            )
            raise RuntimeError(
                f"Falha no upload da habilitação no GED do Legal One: {exc}"
            ) from exc

        # ── Fase 2 — Enqueue cancel da legada (idempotente) ──
        try:
            queue_item = self.queue_service.sync_item_from_intake(
                intake,
                commit=False,
                legacy_task_type_external_id=legacy_task_type_external_id,
                legacy_task_subtype_external_id=legacy_task_subtype_external_id,
                force_queue=True,
            )
        except Exception as exc:  # noqa: BLE001
            self.db.rollback()
            intake = self._load_intake(intake_id)
            if intake is not None:
                intake.dispatch_error_message = (
                    f"Enqueue cancel falhou: {str(exc)[:500]}"
                )
                self.db.commit()
            logger.exception(
                "dispatch_treatment_web: enqueue cancel falhou (intake_id=%s): %s",
                intake_id, exc,
            )
            raise RuntimeError(
                f"Falha ao enfileirar cancelamento da legada: {exc}"
            ) from exc

        # ── Fase 3 — Marca como disparado ──
        intake.dispatch_pending = False
        intake.dispatched_at = self._utcnow()
        intake.dispatch_error_message = None

        self.db.commit()
        self.db.refresh(intake)
        if queue_item is not None:
            self.db.refresh(queue_item)

        logger.info(
            "dispatch_treatment_web ok (intake_id=%s, ged=%s, legacy_queue=%s)",
            intake_id,
            intake.ged_document_id,
            queue_item.id if queue_item else None,
        )

        return {
            "intake": intake,
            "legacy_task_cancellation_item": (
                self.queue_service._item_to_dict(queue_item) if queue_item else None
            ),
            "skipped": False,
        }

"""
Camada de domínio do fluxo "Agendar Prazos Iniciais".

Regras principais:
  * Criação idempotente por `external_id` — reenvios retornam o registro
    já existente em vez de duplicar.
  * Resolução do processo no Legal One: tentamos descobrir `lawsuit_id`
    e `office_id` pelo CNJ, e o estado do intake avança para
    `PRONTO_PARA_CLASSIFICAR` (ou `PROCESSO_NAO_ENCONTRADO`).
  * Resolução é chamada em background a partir do endpoint (não bloqueia
    a resposta ao cliente externo).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.models.legal_one import LegalOneOffice
from app.models.prazo_inicial import (
    INTAKE_SOURCE_EXTERNAL_API,
    INTAKE_STATUS_DEVOLUCAO_PENDING,
    INTAKE_STATUS_LAWSUIT_NOT_FOUND,
    INTAKE_STATUS_READY_TO_CLASSIFY,
    INTAKE_STATUS_RECEIVED,
    INTAKE_STATUSES_REINGEST_ALLOWED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.models.prazo_inicial_pedido import PrazoInicialPedido
from app.services.legal_one_client import LegalOneApiClient
from app.services.prazos_iniciais.storage import StoredPdf, save_pdf

logger = logging.getLogger(__name__)

# Normalização defensiva — o L1 exige só dígitos em buscas OData.
_CNJ_VALID_CHARS = "0123456789"


@dataclass(frozen=True)
class IntakeCreationResult:
    """Retorno do `create_intake` — sinaliza se é criação nova ou reenvio."""

    intake: PrazoInicialIntake
    already_existed: bool
    # True quando o reenvio caiu no caminho de reingest (atualizou PDF,
    # capa e integra do registro existente). False em criacao 1a vez OU
    # em reenvio idempotente puro (status pos-classificacao).
    reingested: bool = False


def normalize_cnj(raw: str) -> str:
    """
    Mantém só dígitos do CNJ (aceita com ou sem máscara).
    Raises ValueError se o resultado ficar vazio ou com tamanho inesperado.
    """
    if raw is None:
        raise ValueError("CNJ vazio.")
    cleaned = "".join(c for c in str(raw) if c in _CNJ_VALID_CHARS)
    # CNJ padrão brasileiro tem 20 dígitos. Aceitamos 15–25 pra tolerar
    # truncamentos/variações regionais, mas recusamos vazio.
    if not cleaned or len(cleaned) < 15 or len(cleaned) > 25:
        raise ValueError(
            f"CNJ inválido após normalização: '{raw}' → '{cleaned}'"
        )
    return cleaned


class IntakeService:
    """Operações sobre `PrazoInicialIntake` (criação, resolução, consulta)."""

    def __init__(self, db: Session):
        self.db = db

    # ─── Criação (chamado pelo endpoint de intake) ────────────────────

    def get_by_external_id(self, external_id: str) -> Optional[PrazoInicialIntake]:
        return (
            self.db.query(PrazoInicialIntake)
            .filter(PrazoInicialIntake.external_id == external_id)
            .first()
        )

    def create_intake(
        self,
        *,
        external_id: str,
        cnj_number: str,
        capa_json: dict,
        integra_json: dict,
        metadata_json: Optional[dict],
        pdf_bytes: Optional[bytes] = None,
        pdf_filename_original: Optional[str] = None,
        source: str = INTAKE_SOURCE_EXTERNAL_API,
        source_provider_name: Optional[str] = None,
        submitted_by_user_id: Optional[int] = None,
        submitted_by_email: Optional[str] = None,
        submitted_by_name: Optional[str] = None,
        pdf_extraction_failed: bool = False,
        extractor_used: Optional[str] = None,
        extraction_confidence: Optional[str] = None,
        habilitacao_pdf_bytes: Optional[bytes] = None,
        habilitacao_pdf_filename_original: Optional[str] = None,
        skip_pdf_storage: bool = False,
    ) -> IntakeCreationResult:
        """
        Cria um novo intake de forma idempotente. Se `external_id` já
        existe, retorna o registro existente com `already_existed=True`
        e **não** regrava o PDF.

        O CNJ é normalizado aqui. A resolução do `lawsuit_id` no L1 é
        disparada separadamente (em background) pelo endpoint.

        `pdf_bytes` é o "PDF principal" do intake — habilitação no fluxo
        EXTERNAL_API, processo na íntegra no fluxo USER_UPLOAD. Quando
        `skip_pdf_storage=True` (USER_UPLOAD com extração ok), o PDF
        do processo NÃO é gravado pra economizar disco — só os metadados
        de hash/tamanho ficam pra auditoria. `habilitacao_pdf_bytes` é
        sempre preservado em campo separado quando enviado.
        """
        existing = self.get_by_external_id(external_id)
        if existing is not None:
            logger.info(
                "Intake idempotente: external_id=%s já existe (id=%d)",
                external_id, existing.id,
            )
            return IntakeCreationResult(intake=existing, already_existed=True)

        normalized_cnj = normalize_cnj(cnj_number)

        # PDF principal: grava (e mantém) ou só calcula hash + descarta.
        pdf_path: Optional[str] = None
        pdf_sha256: Optional[str] = None
        pdf_size: Optional[int] = None
        if pdf_bytes is not None:
            if skip_pdf_storage:
                # USER_UPLOAD com extração bem-sucedida — guardamos só
                # hash/tamanho pra auditoria; o conteúdo já não é útil
                # depois da extração.
                from app.services.prazos_iniciais.storage import (
                    validate_pdf_bytes,
                )
                import hashlib as _hashlib

                validate_pdf_bytes(pdf_bytes)
                pdf_sha256 = _hashlib.sha256(pdf_bytes).hexdigest()
                pdf_size = len(pdf_bytes)
            else:
                stored: StoredPdf = save_pdf(pdf_bytes)
                pdf_path = stored.relative_path
                pdf_sha256 = stored.sha256
                pdf_size = stored.size_bytes

        # Habilitação separada (sempre preservada — vai pro GED + AJUS).
        habilitacao_path: Optional[str] = None
        habilitacao_sha256: Optional[str] = None
        habilitacao_size: Optional[int] = None
        if habilitacao_pdf_bytes is not None:
            stored_hab: StoredPdf = save_pdf(habilitacao_pdf_bytes)
            habilitacao_path = stored_hab.relative_path
            habilitacao_sha256 = stored_hab.sha256
            habilitacao_size = stored_hab.size_bytes

        submitted_at = (
            datetime.now(timezone.utc) if submitted_by_user_id is not None else None
        )

        intake = PrazoInicialIntake(
            external_id=external_id,
            cnj_number=normalized_cnj,
            capa_json=capa_json,
            integra_json=integra_json,
            metadata_json=metadata_json,
            pdf_path=pdf_path,
            pdf_sha256=pdf_sha256,
            pdf_bytes=pdf_size,
            pdf_filename_original=pdf_filename_original,
            status=INTAKE_STATUS_RECEIVED,
            source=source,
            source_provider_name=source_provider_name,
            submitted_by_user_id=submitted_by_user_id,
            submitted_by_email=submitted_by_email,
            submitted_by_name=submitted_by_name,
            submitted_at=submitted_at,
            pdf_extraction_failed=pdf_extraction_failed,
            extractor_used=extractor_used,
            extraction_confidence=extraction_confidence,
            habilitacao_pdf_path=habilitacao_path,
            habilitacao_pdf_sha256=habilitacao_sha256,
            habilitacao_pdf_bytes=habilitacao_size,
            habilitacao_pdf_filename_original=habilitacao_pdf_filename_original,
        )
        self.db.add(intake)
        self.db.commit()
        self.db.refresh(intake)
        logger.info(
            "Intake criado: id=%d, external_id=%s, cnj=%s",
            intake.id, external_id, normalized_cnj,
        )

        # ── Enfileiramento automático no AJUS (módulo paralelo) ──
        # Cada intake recebido vira um candidato a andamento na fila
        # AJUS, usando o cod_andamento default cadastrado pela admin.
        # Idempotente (UNIQUE em intake_id). Falhas aqui NÃO afetam
        # criação do intake — só logam warning. Se faltar config
        # (cod default ou env vars), AjusQueueService devolve None e
        # o intake segue normal.
        try:
            from app.services.ajus.queue_service import AjusQueueService
            ajus = AjusQueueService(self.db)
            ajus.enqueue_for_intake(intake)
        except Exception:  # noqa: BLE001
            logger.exception(
                "AJUS enqueue: falha não-fatal ao enfileirar intake %d "
                "(seguindo sem AJUS).",
                intake.id,
            )

        # ── Enfileiramento na fila de classificação AJUS (Chunk 1) ──
        # Processo cai automaticamente na fila de classificação de capa
        # (Matéria + Risco vêm dos defaults; UF do CNJ; Comarca da
        # Jurisdição/vara). Operador pode editar antes do dispatch
        # via runner Playwright (Chunk 2). Idempotente em CNJ.
        try:
            from app.services.ajus.classificacao_service import (
                AjusClassificacaoService,
            )
            classif = AjusClassificacaoService(self.db)
            classif.enqueue_from_intake(intake)
        except Exception:  # noqa: BLE001
            logger.exception(
                "AJUS classif enqueue: falha não-fatal ao enfileirar "
                "intake %d (seguindo sem classificação).",
                intake.id,
            )

        return IntakeCreationResult(intake=intake, already_existed=False)

    # ─── Reingest (atualizacao incremental do mesmo external_id) ──────

    def reingest_intake(
        self,
        *,
        intake: PrazoInicialIntake,
        cnj_number: str,
        capa_json: dict,
        integra_json: dict,
        metadata_json: Optional[dict],
        pdf_bytes: Optional[bytes] = None,
        pdf_filename_original: Optional[str] = None,
    ) -> IntakeCreationResult:
        """
        Atualiza intake EXISTENTE com novo PDF + capa + integra. Usado
        pelo POST /intake quando a automacao externa reenvia o mesmo
        external_id de um intake que ainda nao foi classificado/agendado.

        Pre-condicao: intake.status DEVE estar em
        INTAKE_STATUSES_REINGEST_ALLOWED (caller do endpoint valida).

        Fluxo:
        - Salva PDF novo no storage (gera novo path/uuid).
        - **NAO apaga o PDF antigo do disco** — operador 2026-05-06:
          "nao apague nenhuma habilitacao, vamo salvar tudo". O path
          antigo fica como arquivo orfao; operador faz cleanup manual
          do estoque depois.
        - Atualiza pdf_path, capa_json, integra_json, metadata_json,
          cnj_number (caso venha normalizado diferente).
        - Apaga sugestoes/pedidos/patrocinio antigos (cascade — caso
          de ERRO_CLASSIFICACAO com sugestoes parciais persistidas).
          Eh seguro porque os status atualizaveis nao geram trabalho
          HITL persistido.
        - Reseta lawsuit_id, error_message, classification_batch_id —
          re-resolve do zero como se fosse intake novo.
        - Status volta pra RECEBIDO pra o fluxo de
          resolucao+classificacao re-acontecer.
        - Mantem id, external_id, received_at — preserva rastreabilidade.

        Returns:
            IntakeCreationResult com `already_existed=True` e
            `reingested=True`.
        """
        from datetime import datetime as _dt, timezone as _tz

        normalized_cnj = normalize_cnj(cnj_number)

        # PDF novo: salva sem mexer no antigo (a regra "nao apagar
        # habilitacao" se aplica aqui — preservacao total).
        new_pdf_path: Optional[str] = None
        new_pdf_sha256: Optional[str] = None
        new_pdf_size: Optional[int] = None
        if pdf_bytes is not None:
            stored: StoredPdf = save_pdf(pdf_bytes)
            new_pdf_path = stored.relative_path
            new_pdf_sha256 = stored.sha256
            new_pdf_size = stored.size_bytes
            logger.info(
                "Reingest intake %d: PDF novo salvo em %s (anterior em "
                "pdf_path=%r e habilitacao_pdf_path=%r preservados).",
                intake.id, new_pdf_path,
                intake.pdf_path,
                getattr(intake, "habilitacao_pdf_path", None),
            )

        # Apaga sugestoes/pedidos/patrocinio antigos (cascade no banco
        # via FK ondelete=CASCADE).
        deleted_sugestoes = (
            self.db.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .delete(synchronize_session=False)
        )
        deleted_pedidos = (
            self.db.query(PrazoInicialPedido)
            .filter(PrazoInicialPedido.intake_id == intake.id)
            .delete(synchronize_session=False)
        )
        # Patrocinio (pin018): unique por intake_id, apaga via cascade
        # quando atualizar capa (pode ter dados velhos invalidados).
        try:
            from app.models.prazo_inicial_patrocinio import PrazoInicialPatrocinio
            deleted_patrocinio = (
                self.db.query(PrazoInicialPatrocinio)
                .filter(PrazoInicialPatrocinio.intake_id == intake.id)
                .delete(synchronize_session=False)
            )
        except Exception:  # noqa: BLE001
            deleted_patrocinio = 0

        # Atualiza campos do intake.
        intake.cnj_number = normalized_cnj
        intake.capa_json = capa_json
        intake.integra_json = integra_json
        intake.metadata_json = metadata_json
        if new_pdf_path is not None:
            intake.pdf_path = new_pdf_path
            intake.pdf_sha256 = new_pdf_sha256
            intake.pdf_bytes = new_pdf_size
            intake.pdf_filename_original = pdf_filename_original
            # Em EXTERNAL_API o pdf_path JA EH a habilitacao. Se uma
            # rotina anterior tinha promovido pra habilitacao_pdf_path,
            # zera o campo agora — a habilitacao "ativa" volta pra
            # pdf_path com o arquivo novo (e o antigo fica orfao).
            intake.habilitacao_pdf_path = None
            intake.habilitacao_pdf_sha256 = None
            intake.habilitacao_pdf_bytes = None
            intake.habilitacao_pdf_filename_original = None

        # Reset de campos derivados — fluxo recomeca do zero.
        intake.status = INTAKE_STATUS_RECEIVED
        intake.error_message = None
        intake.lawsuit_id = None
        intake.office_id = None
        intake.natureza_processo = None
        intake.produto = None
        intake.agravo_processo_origem_cnj = None
        intake.agravo_decisao_agravada_resumo = None
        intake.classification_batch_id = None
        # Agregados da classificacao
        intake.valor_total_pedido = None
        intake.valor_total_estimado = None
        intake.aprovisionamento_sugerido = None
        intake.probabilidade_exito_global = None
        intake.analise_estrategica = None
        # Dispatch / treated — nao deveriam estar setados em status
        # atualizavel, mas zera por seguranca defensiva.
        intake.dispatch_pending = False
        intake.dispatched_at = None
        intake.dispatch_error_message = None
        # received_at fica como esta (rastreabilidade do 1o recebimento).
        # Adiciona uma marca de re-recebimento no metadata pra audit.
        meta = dict(intake.metadata_json or {})
        reingest_log = meta.setdefault("_reingest_log", [])
        if isinstance(reingest_log, list):
            reingest_log.append({
                "at": _dt.now(_tz.utc).isoformat(),
                "previous_status": intake.status,
                "deleted_sugestoes": int(deleted_sugestoes),
                "deleted_pedidos": int(deleted_pedidos),
                "deleted_patrocinio": int(deleted_patrocinio),
                "old_pdf_path": (
                    intake.pdf_path
                    if new_pdf_path is None
                    else "preservado_no_disco"
                ),
            })
            intake.metadata_json = meta

        self.db.commit()
        self.db.refresh(intake)

        logger.info(
            "Reingest intake %d (external_id=%s, cnj=%s): "
            "sugestoes_apagadas=%d, pedidos_apagados=%d, "
            "patrocinio_apagado=%d. Status -> RECEBIDO.",
            intake.id, intake.external_id, normalized_cnj,
            deleted_sugestoes, deleted_pedidos, deleted_patrocinio,
        )

        # AJUS classif enqueue eh idempotente em CNJ — re-chama por
        # seguranca caso o intake nunca tenha sido enfileirado (ex.:
        # falha na 1a recepcao). Fila AJUS de andamentos NAO eh
        # re-enfileirada (UNIQUE em intake_id evita duplicar; o item
        # antigo segue valido).
        try:
            from app.services.ajus.classificacao_service import (
                AjusClassificacaoService,
            )
            classif = AjusClassificacaoService(self.db)
            classif.enqueue_from_intake(intake)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Reingest: falha nao-fatal ao re-enfileirar AJUS classif "
                "do intake %d.", intake.id,
            )

        return IntakeCreationResult(
            intake=intake, already_existed=True, reingested=True,
        )

    # ─── Refresh do PDF em intake pos-HITL ────────────────────────────

    def refresh_intake_pdf(
        self,
        *,
        intake: PrazoInicialIntake,
        pdf_bytes: bytes,
        pdf_filename_original: Optional[str] = None,
    ) -> PrazoInicialIntake:
        """
        Atualiza APENAS o PDF de habilitacao de um intake existente,
        preservando 100% do trabalho HITL ja feito (capa, integra,
        sugestoes, classificacao, status, dispatch, GED, treated_by,
        etc.). Usado pelo POST /intake quando a origem reenvia o mesmo
        external_id de um intake JA classificado/agendado.

        Caso de uso (operador 2026-05-06): "saneamento dos delete dos
        casos passados" — o `pdf_cleanup_worker` antigo apagou
        habilitacoes em EXTERNAL_API. Com a origem reenviando tudo,
        esse metodo restaura o PDF pra que o AJUS dispatch volte a
        ter anexo, sem zerar o trabalho do HITL.

        Comportamento:
        - Salva PDF novo no storage (gera novo uuid/path).
        - Atualiza `habilitacao_pdf_path` (campo dedicado — funciona
          em EXTERNAL_API e USER_UPLOAD). Em EXTERNAL_API tipico
          pos-cleanup, `pdf_path` esta None e `habilitacao_pdf_path`
          tambem; aqui populamos `habilitacao_pdf_path` direto.
        - Path antigo (se houver) **NAO eh apagado do disco** (regra
          "salvar tudo" — feedback_nao_apagar_habilitacao.md). Operador
          gerencia o estoque manualmente depois.
        - Adiciona entrada em `metadata_json._pdf_refresh_log[]` pra
          auditoria.

        Caveat: se `intake.ged_document_id` ja esta setado, o PDF que
        ja foi pro GED do L1 NAO eh atualizado por essa rotina —
        precisaria de re-upload separado. Aqui so o storage local
        recebe a versao nova, que sera usada pelo proximo AJUS dispatch.
        """
        from datetime import datetime as _dt, timezone as _tz

        stored: StoredPdf = save_pdf(pdf_bytes)
        old_habilitacao_path = getattr(intake, "habilitacao_pdf_path", None)
        old_pdf_path = intake.pdf_path

        intake.habilitacao_pdf_path = stored.relative_path
        intake.habilitacao_pdf_sha256 = stored.sha256
        intake.habilitacao_pdf_bytes = stored.size_bytes
        intake.habilitacao_pdf_filename_original = pdf_filename_original

        # Audit log no metadata.
        meta = dict(intake.metadata_json or {})
        refresh_log = meta.setdefault("_pdf_refresh_log", [])
        if isinstance(refresh_log, list):
            refresh_log.append({
                "at": _dt.now(_tz.utc).isoformat(),
                "intake_status_when_refreshed": intake.status,
                "new_path": stored.relative_path,
                "new_sha256": stored.sha256,
                "new_bytes": stored.size_bytes,
                "previous_habilitacao_path": old_habilitacao_path,
                "previous_pdf_path": old_pdf_path,
                "ged_document_id": intake.ged_document_id,
            })
            intake.metadata_json = meta

        self.db.commit()
        self.db.refresh(intake)

        logger.info(
            "PDF refresh intake %d (status=%s, ged=%s): habilitacao_pdf_path "
            "%r -> %r. PDF antigo preservado no disco.",
            intake.id, intake.status, intake.ged_document_id,
            old_habilitacao_path, intake.habilitacao_pdf_path,
        )
        return intake

    # ─── Devolução automática (pin019) ────────────────────────────────

    def create_devolucao_intake(
        self,
        *,
        external_id: str,
        cnj_number: str,
        motivo: Optional[str] = None,
    ) -> IntakeCreationResult:
        """
        Cria um intake de DEVOLUÇÃO. Fluxo enxuto:
        - Sem capa, integra ou PDF (a automação externa já decidiu pelo
          CNJ que o caso não é nosso).
        - Status = DEVOLUCAO_PENDENTE.
        - Cria registro `prazo_inicial_patrocinio` já APROVADO com
          decisao=OUTRO_ESCRITORIO + suspeita_devolucao=true.
        - Enfileira na fila AJUS usando o cod_andamento marcado com
          `is_devolucao=true` (não o default).
        - Resolução do lawsuit no L1 fica a cargo do endpoint (background
          task) — operador precisa do lawsuit pra excluir manualmente
          do L1 no momento da devolução.

        Idempotente por `external_id`.
        """
        from datetime import datetime, timezone as _tz

        from app.models.ajus import AjusCodAndamento
        from app.models.prazo_inicial_patrocinio import (
            PATROCINIO_DECISAO_OUTRO,
            PATROCINIO_REVIEW_APPROVED,
            PrazoInicialPatrocinio,
        )

        existing = self.get_by_external_id(external_id)
        if existing is not None:
            logger.info(
                "Devolução idempotente: external_id=%s já existe (id=%d)",
                external_id, existing.id,
            )
            return IntakeCreationResult(intake=existing, already_existed=True)

        normalized_cnj = normalize_cnj(cnj_number)

        intake = PrazoInicialIntake(
            external_id=external_id,
            cnj_number=normalized_cnj,
            capa_json={},
            integra_json={},
            metadata_json={
                "fluxo": "devolucao_automatica",
                "motivo": motivo,
            },
            pdf_path=None,
            pdf_sha256=None,
            pdf_bytes=None,
            pdf_filename_original=None,
            status=INTAKE_STATUS_DEVOLUCAO_PENDING,
            source=INTAKE_SOURCE_EXTERNAL_API,
        )
        self.db.add(intake)
        self.db.flush()  # garante intake.id antes do patrocinio FK

        # Patrocínio já aprovado pela automação externa.
        patrocinio = PrazoInicialPatrocinio(
            intake_id=intake.id,
            decisao=PATROCINIO_DECISAO_OUTRO,
            suspeita_devolucao=True,
            motivo_suspeita=motivo,
            polo_passivo_confirmado=True,
            confianca="alta",
            fundamentacao=(
                "Devolução solicitada pela automação externa (outro "
                "advogado já habilitado pelo Banco Master)."
            ),
            review_status=PATROCINIO_REVIEW_APPROVED,
            reviewed_at=datetime.now(_tz.utc),
        )
        self.db.add(patrocinio)
        self.db.commit()
        self.db.refresh(intake)
        logger.info(
            "Intake DEVOLUCAO criado: id=%d, external_id=%s, cnj=%s, motivo=%r",
            intake.id, external_id, normalized_cnj, motivo,
        )

        # Enfileiramento AJUS com cod_andamento marcado is_devolucao.
        try:
            from app.services.ajus.queue_service import AjusQueueService
            cod_devolucao = (
                self.db.query(AjusCodAndamento)
                .filter(
                    AjusCodAndamento.is_devolucao.is_(True),
                    AjusCodAndamento.is_active.is_(True),
                )
                .one_or_none()
            )
            if cod_devolucao is None:
                logger.warning(
                    "Devolução[intake=%d]: nenhum AjusCodAndamento ativo "
                    "com is_devolucao=true cadastrado. Item NÃO enfileirado. "
                    "Operador precisa cadastrar em /ajus/cod-andamento.",
                    intake.id,
                )
            else:
                ajus = AjusQueueService(self.db)
                ajus.enqueue_for_intake(intake, cod_andamento=cod_devolucao)
        except Exception:  # noqa: BLE001
            logger.exception(
                "Devolução[intake=%d]: falha não-fatal ao enfileirar AJUS "
                "(operador pode reenviar manualmente).",
                intake.id,
            )

        return IntakeCreationResult(intake=intake, already_existed=False)

    # ─── Resolução do lawsuit no L1 (background task) ─────────────────

    def resolve_lawsuit_for_intake(self, intake_id: int) -> None:
        """
        Tenta resolver o processo no Legal One a partir do CNJ e
        atualiza o estado do intake. Não levanta — falhas ficam
        registradas em `error_message` para exibição na UI.

        Esta função é chamada como background_task pelo endpoint de
        intake. Usa seu próprio Session pra não compartilhar com a
        request que já terminou.
        """
        with SessionLocal() as db:
            intake = db.get(PrazoInicialIntake, intake_id)
            if intake is None:
                logger.error("resolve_lawsuit: intake %d não encontrado", intake_id)
                return
            # Pin019: pra DEVOLUÇÃO, só preenche lawsuit_id/office_id e
            # mantém o status DEVOLUCAO_PENDENTE — não vai pra classificação.
            is_devolucao = intake.status == INTAKE_STATUS_DEVOLUCAO_PENDING
            if not is_devolucao and intake.status not in (
                INTAKE_STATUS_RECEIVED,
                INTAKE_STATUS_LAWSUIT_NOT_FOUND,
            ):
                logger.info(
                    "resolve_lawsuit: intake %d em estado %s — pulando",
                    intake_id, intake.status,
                )
                return

            try:
                client = LegalOneApiClient()
                results = client.search_lawsuits_by_cnj_numbers([intake.cnj_number])
                lawsuit = results.get(intake.cnj_number)
            except Exception as exc:
                intake.error_message = f"Erro ao consultar L1: {exc}"
                db.commit()
                logger.exception(
                    "Erro ao resolver CNJ no L1 (intake %d, cnj %s)",
                    intake_id, intake.cnj_number,
                )
                return

            if not lawsuit:
                # Pra DEVOLUÇÃO: NÃO sobrescreve status (continua
                # PENDENTE pra dispatch AJUS rolar mesmo sem lawsuit).
                # Só registra o aviso. Operador resolve manualmente.
                if is_devolucao:
                    intake.error_message = (
                        f"Processo com CNJ {intake.cnj_number} não "
                        f"encontrado no Legal One — pode ser exclusão "
                        f"manual ainda não realizada."
                    )
                else:
                    intake.status = INTAKE_STATUS_LAWSUIT_NOT_FOUND
                    intake.error_message = (
                        f"Processo com CNJ {intake.cnj_number} não encontrado no Legal One."
                    )
                db.commit()
                logger.warning(
                    "Intake %d: CNJ %s não encontrado no L1 (devolucao=%s)",
                    intake_id, intake.cnj_number, is_devolucao,
                )
                return

            lawsuit_id = lawsuit.get("id")
            responsible_office_id = _extract_office_id(db, lawsuit)

            intake.lawsuit_id = lawsuit_id
            intake.office_id = responsible_office_id
            # Devolução: PRESERVA status DEVOLUCAO_PENDENTE; classificação
            # normal: avança pra READY_TO_CLASSIFY.
            if not is_devolucao:
                intake.status = INTAKE_STATUS_READY_TO_CLASSIFY
            intake.error_message = None
            db.commit()
            logger.info(
                "Intake %d resolvido: lawsuit_id=%s, office_id=%s",
                intake_id, lawsuit_id, responsible_office_id,
            )

            # Auto-enfileiramento na fila do Tratamento Web
            # Assim que o lawsuit_id e resolvido, o intake ja vai pra fila
            # de cancelamento da legada "Agendar Prazos" (status PENDENTE).
            # O DISPARO do cancel e 100% manual (worker periodico desligado
            # via settings.prazos_iniciais_legacy_task_cancellation_enabled
            # = False) - operador clica "Processar selecionados" no
            # Tratamento Web. Ver memoria project_dispatch_treatment_web_decoupling.
            # Pin019: fluxo de DEVOLUÇÃO não cria task legada nem
            # entra em "Tratamento Web" (cancel legada) — o operador
            # vai apenas excluir manualmente do L1 e o sistema dispara
            # andamento de devolução AJUS.
            if not is_devolucao:
                try:
                    from app.services.prazos_iniciais.legacy_task_queue_service import (
                        PrazosIniciaisLegacyTaskQueueService,
                    )
                    queue_svc = PrazosIniciaisLegacyTaskQueueService(db)
                    queue_svc.sync_item_from_intake(intake, force_queue=True)
                    logger.info(
                        "Intake %d enfileirado no Tratamento Web (cancel legada).",
                        intake_id,
                    )
                except Exception:  # noqa: BLE001
                    # Falha aqui nao pode interromper o fluxo - operador pode
                    # enfileirar manualmente depois pelo Tratamento Web. Loga
                    # e segue: o intake ja esta PRONTO_PARA_CLASSIFICAR e a
                    # classificacao roda independente da fila de cancel.
                    logger.exception(
                        "Falha nao-fatal ao enfileirar intake %d no Tratamento Web "
                        "(seguindo sem fila - operador pode enfileirar manual).",
                        intake_id,
                    )


def _extract_office_id(db: Session, lawsuit: dict[str, Any]) -> Optional[int]:
    """
    Tenta descobrir o `office_id` (external_id do LegalOneOffice) a
    partir do payload do processo. A estrutura do Legal One varia por
    versão/cliente, então testamos caminhos conhecidos na ordem.
    """
    # Caminho 1: responsibleOfficeId / responsibleOffice.id
    for key in ("responsibleOfficeId", "officeId"):
        value = lawsuit.get(key)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    for key in ("responsibleOffice", "office"):
        nested = lawsuit.get(key) or {}
        if isinstance(nested, dict):
            value = nested.get("id") or nested.get("externalId")
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass

    # Caminho 2: folder.responsibleOffice.id
    folder = lawsuit.get("folder") or {}
    if isinstance(folder, dict):
        nested = folder.get("responsibleOffice") or folder.get("office") or {}
        value = nested.get("id") if isinstance(nested, dict) else None
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass

    # Caminho 3: areas[*] — nome/id do escritório via tabela local.
    area_names = lawsuit.get("areas") or []
    if area_names:
        for area in area_names:
            name = area.get("name") if isinstance(area, dict) else None
            if not name:
                continue
            office = (
                db.query(LegalOneOffice)
                .filter(LegalOneOffice.name == name)
                .first()
            )
            if office:
                return office.external_id

    return None

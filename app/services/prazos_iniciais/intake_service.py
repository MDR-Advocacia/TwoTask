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

from app.db.session import SessionLocal
from app.models.legal_one import LegalOneOffice
from app.models.prazo_inicial import (
    INTAKE_STATUS_LAWSUIT_NOT_FOUND,
    INTAKE_STATUS_READY_TO_CLASSIFY,
    INTAKE_STATUS_RECEIVED,
    PrazoInicialIntake,
)
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
        pdf_bytes: bytes,
        pdf_filename_original: Optional[str],
    ) -> IntakeCreationResult:
        """
        Cria um novo intake de forma idempotente. Se `external_id` já
        existe, retorna o registro existente com `already_existed=True`
        e **não** regrava o PDF.

        O CNJ é normalizado aqui. A resolução do `lawsuit_id` no L1 é
        disparada separadamente (em background) pelo endpoint.
        """
        existing = self.get_by_external_id(external_id)
        if existing is not None:
            logger.info(
                "Intake idempotente: external_id=%s já existe (id=%d)",
                external_id, existing.id,
            )
            return IntakeCreationResult(intake=existing, already_existed=True)

        normalized_cnj = normalize_cnj(cnj_number)

        stored: StoredPdf = save_pdf(pdf_bytes)

        intake = PrazoInicialIntake(
            external_id=external_id,
            cnj_number=normalized_cnj,
            capa_json=capa_json,
            integra_json=integra_json,
            metadata_json=metadata_json,
            pdf_path=stored.relative_path,
            pdf_sha256=stored.sha256,
            pdf_bytes=stored.size_bytes,
            pdf_filename_original=pdf_filename_original,
            status=INTAKE_STATUS_RECEIVED,
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
            if intake.status not in (
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
                intake.status = INTAKE_STATUS_LAWSUIT_NOT_FOUND
                intake.error_message = (
                    f"Processo com CNJ {intake.cnj_number} não encontrado no Legal One."
                )
                db.commit()
                logger.warning(
                    "Intake %d: CNJ %s não encontrado no L1",
                    intake_id, intake.cnj_number,
                )
                return

            lawsuit_id = lawsuit.get("id")
            responsible_office_id = _extract_office_id(db, lawsuit)

            intake.lawsuit_id = lawsuit_id
            intake.office_id = responsible_office_id
            intake.status = INTAKE_STATUS_READY_TO_CLASSIFY
            intake.error_message = None
            db.commit()
            logger.info(
                "Intake %d resolvido: lawsuit_id=%s, office_id=%s",
                intake_id, lawsuit_id, responsible_office_id,
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

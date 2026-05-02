"""
Reaplicacao em lote de templates em sugestoes ja materializadas.

Caso de uso: operador cadastra (ou edita) um template novo depois que
varios intakes ja foram classificados — eles ficaram em
AGUARDANDO_CONFIG_TEMPLATE (template_match=not_found) ou em
EM_REVISAO/CLASSIFICADO com mapeamento antigo. Reaplicar = re-rodar
`match_templates` em cima das sugestoes existentes, sem chamar a IA
de novo (barato e rapido).

Diferente do `Reclassificar` (apaga sugestoes/pedidos e volta intake
pra PRONTO_PARA_CLASSIFICAR pra entrar no proximo batch da IA),
aqui mantemos a classificacao da IA e so atualizamos os campos L1
da sugestao (task_subtype_id, responsavel, payload renderizado).

Salvaguardas:
- Sugestao com `created_task_id` NOT NULL: pula (task ja existe no
  L1, nao da pra trocar template sem deletar a task).
- Sugestao com `review_status='editado'`: pula (operador ajustou na
  mao, respeita).
- Multiplos templates casando a mesma sugestao: aplica o PRIMEIRO
  (estavel por id asc). Operador que quer multiplas sugestoes pra
  mesma classificacao deve usar Reclassificar (chama IA de novo, ai
  o classifier materializa N sugestoes corretamente).

Status do intake e promovido de AGUARDANDO_CONFIG_TEMPLATE pra
CLASSIFICADO quando TODAS as sugestoes do intake passam a ter
template casado (task_subtype_id NOT NULL OU skip_task_creation no
payload). Operador confirma na tela como sempre.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session, selectinload

from app.models.prazo_inicial import (
    INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
    INTAKE_STATUS_CLASSIFIED,
    SUGESTAO_REVIEW_EDITED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate
from app.services.prazos_iniciais.template_matching_service import match_templates

logger = logging.getLogger(__name__)


# Status nos quais faz sentido reaplicar templates. Terminais (AGENDADO,
# CONCLUIDO, CONCLUIDO_SEM_PROVIDENCIA, GED_ENVIADO, CANCELADO) e os
# transientes pre-classificacao (RECEBIDO, PRONTO_PARA_CLASSIFICAR,
# EM_CLASSIFICACAO) sao bloqueados — fora do dominio de reapply.
REAPPLY_ALLOWED_STATUSES = frozenset({
    INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
    INTAKE_STATUS_CLASSIFIED,
    "EM_REVISAO",
})


@dataclass
class ReapplyMetrics:
    """Contadores devolvidos pelo service (e pelo endpoint dry-run)."""
    intakes_processed: int = 0
    intakes_promoted: int = 0  # AGUARDANDO_CONFIG_TEMPLATE -> CLASSIFICADO
    sugestoes_updated: int = 0  # mapeamento L1 reescrito
    sugestoes_skipped_already_in_l1: int = 0  # created_task_id NOT NULL
    sugestoes_skipped_edited: int = 0  # review_status=editado
    sugestoes_no_match: int = 0  # 0 templates casaram (mantida como esta)
    intake_ids_processed: list[int] = field(default_factory=list)
    intake_ids_promoted: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "intakes_processed": self.intakes_processed,
            "intakes_promoted": self.intakes_promoted,
            "sugestoes_updated": self.sugestoes_updated,
            "sugestoes_skipped_already_in_l1": self.sugestoes_skipped_already_in_l1,
            "sugestoes_skipped_edited": self.sugestoes_skipped_edited,
            "sugestoes_no_match": self.sugestoes_no_match,
            "intake_ids_processed": self.intake_ids_processed,
            "intake_ids_promoted": self.intake_ids_promoted,
        }


def reapply_templates_bulk(
    db: Session,
    *,
    status_in: list[str],
    office_ids: Optional[list[int]] = None,
    tipos_prazo: Optional[list[str]] = None,
    dry_run: bool = False,
) -> ReapplyMetrics:
    """
    Re-roda `match_templates` em cima das sugestoes existentes dos
    intakes filtrados. Em dry_run, calcula as metricas sem persistir
    (db.rollback no fim) — util pro preview de impacto.

    Args:
        status_in: lista de status de intake elegiveis. Validado contra
            REAPPLY_ALLOWED_STATUSES; status fora levanta ValueError.
        office_ids: filtro opcional por office_id do intake.
        tipos_prazo: filtro opcional por tipo_prazo das sugestoes — so
            sugestoes desses tipos sao tocadas (intakes mistos podem
            ficar parcialmente atualizados).
        dry_run: se True, calcula tudo mas faz rollback no fim.

    Returns:
        ReapplyMetrics com contadores pra UI mostrar.
    """
    # Validacao de status — falha cedo com mensagem util.
    invalid = [s for s in status_in if s not in REAPPLY_ALLOWED_STATUSES]
    if invalid:
        raise ValueError(
            f"Status invalido(s) pra reaplicar templates: {invalid}. "
            f"Permitidos: {sorted(REAPPLY_ALLOWED_STATUSES)}."
        )

    metrics = ReapplyMetrics()

    q = (
        db.query(PrazoInicialIntake)
        .options(selectinload(PrazoInicialIntake.sugestoes))
        .filter(PrazoInicialIntake.status.in_(status_in))
    )
    if office_ids:
        q = q.filter(PrazoInicialIntake.office_id.in_(office_ids))

    intakes = q.all()

    for intake in intakes:
        metrics.intakes_processed += 1
        metrics.intake_ids_processed.append(intake.id)

        # Aplica em cada sugestao elegivel.
        for sugestao in intake.sugestoes or []:
            if tipos_prazo and sugestao.tipo_prazo not in tipos_prazo:
                continue
            if sugestao.created_task_id is not None:
                metrics.sugestoes_skipped_already_in_l1 += 1
                continue
            if sugestao.review_status == SUGESTAO_REVIEW_EDITED:
                metrics.sugestoes_skipped_edited += 1
                continue

            templates = match_templates(
                db,
                tipo_prazo=sugestao.tipo_prazo,
                subtipo=sugestao.subtipo,
                office_external_id=intake.office_id,
                natureza_processo=intake.natureza_processo,
            )
            if not templates:
                metrics.sugestoes_no_match += 1
                continue

            # Aplica o primeiro template casado (estavel por id asc no
            # match_templates). Casos de N templates casando ficam de
            # fora do reapply — operador usa Reclassificar pra isso.
            _apply_template_to_existing_sugestao(
                sugestao=sugestao,
                template=templates[0],
                intake=intake,
            )
            metrics.sugestoes_updated += 1

        # Promocao de status: se TODAS as sugestoes do intake agora
        # tem mapeamento L1 ou skip_task_creation, sai do limbo
        # AGUARDANDO_CONFIG_TEMPLATE pra CLASSIFICADO. Operador
        # confirma na tela como sempre.
        if intake.status == INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG:
            all_resolved = all(
                _sugestao_has_template_or_skip(s)
                for s in (intake.sugestoes or [])
            )
            if all_resolved and (intake.sugestoes or []):
                intake.status = INTAKE_STATUS_CLASSIFIED
                intake.error_message = None
                metrics.intakes_promoted += 1
                metrics.intake_ids_promoted.append(intake.id)

    if dry_run:
        db.rollback()
    else:
        db.commit()

    logger.info(
        "reapply_templates_bulk: processed=%d updated=%d promoted=%d "
        "skipped_l1=%d skipped_edited=%d no_match=%d dry_run=%s",
        metrics.intakes_processed,
        metrics.sugestoes_updated,
        metrics.intakes_promoted,
        metrics.sugestoes_skipped_already_in_l1,
        metrics.sugestoes_skipped_edited,
        metrics.sugestoes_no_match,
        dry_run,
    )
    return metrics


def _sugestao_has_template_or_skip(sugestao: PrazoInicialSugestao) -> bool:
    """True se a sugestao casa template (task_subtype_id NOT NULL) OU
    veio de template no-op (payload.skip_task_creation=True)."""
    if sugestao.task_subtype_id is not None:
        return True
    payload = sugestao.payload_proposto or {}
    return bool(payload.get("skip_task_creation"))


def _apply_template_to_existing_sugestao(
    *,
    sugestao: PrazoInicialSugestao,
    template: PrazoInicialTaskTemplate,
    intake: PrazoInicialIntake,
) -> None:
    """
    Versao do `_apply_template_to_sugestao` do classifier adaptada pra
    reapply: NAO recebe `bloco` original (a IA ja foi e voltou). Os
    placeholders {audiencia_endereco}, {julgamento_tipo}, {recurso},
    {objeto}, {assunto} sao recuperados do `payload_proposto` quando
    presentes; ausentes viram string vazia (defaultdict).

    Sobrescreve task_subtype_id, responsavel_sugerido_id e regenera
    `payload_proposto` preservando metadados nao-template (observacoes
    da IA, motivo_sem_prazo, etc.).
    """
    skip = bool(getattr(template, "skip_task_creation", False))
    if skip:
        # Template no-op: zera mapeamento L1 (caso a sugestao tivesse
        # vindo de outro template antes) e marca skip no payload.
        sugestao.task_subtype_id = None
        sugestao.responsavel_sugerido_id = None
    else:
        sugestao.task_subtype_id = template.task_subtype_external_id
        sugestao.responsavel_sugerido_id = template.responsible_user_external_id

    # Preserva metadados do payload original (observacoes_ia,
    # motivo_sem_prazo, tipo_audiencia, etc.); sobrescreve apenas as
    # chaves de template.
    payload: dict[str, Any] = dict(sugestao.payload_proposto or {})
    payload["template_id"] = template.id
    payload["template_name"] = template.name
    payload["priority"] = template.priority
    payload["due_business_days"] = template.due_business_days
    payload["due_date_reference"] = template.due_date_reference
    payload["template_match"] = (
        "specific" if template.office_external_id is not None else "global"
    )
    # Limpa flag stale se o template anterior era no-op e o atual nao e.
    if skip:
        payload["skip_task_creation"] = True
    else:
        payload.pop("skip_task_creation", None)
    # template_match=not_found vira sinal de "sem template casado" — se
    # agora casamos um, derruba o flag.
    if payload.get("template_match") == "not_found":
        payload.pop("template_match", None)

    render_ctx = _build_reapply_render_context(
        intake=intake, sugestao=sugestao, template=template, payload=payload,
    )
    if template.description_template:
        payload["description"] = _render_template(
            template.description_template, render_ctx,
        )
    if template.notes_template:
        payload["notes"] = _render_template(template.notes_template, render_ctx)

    sugestao.payload_proposto = payload or None


def _build_reapply_render_context(
    *,
    intake: PrazoInicialIntake,
    sugestao: PrazoInicialSugestao,
    template: PrazoInicialTaskTemplate,
    payload: dict[str, Any],
) -> dict[str, str]:
    """
    Espelha `_build_render_context` do classifier mas pesca os campos
    block-specific do `payload_proposto` (que o classifier persistiu
    quando materializou a sugestao). Campos ausentes viram "" via
    defaultdict no `_render_template`.
    """
    def _iso(value: Any) -> str:
        return value.isoformat() if value is not None else ""

    ctx: dict[str, str] = {
        "cnj": intake.cnj_number or "",
        "tipo_prazo": sugestao.tipo_prazo or "",
        "subtipo": sugestao.subtipo or "",
        "data_base": _iso(sugestao.data_base),
        "data_final": _iso(sugestao.data_final_calculada),
        "prazo_dias": (
            str(sugestao.prazo_dias) if sugestao.prazo_dias is not None else ""
        ),
        "prazo_tipo": sugestao.prazo_tipo or "",
        "audiencia_data": _iso(sugestao.audiencia_data),
        "audiencia_hora": _iso(sugestao.audiencia_hora),
        "audiencia_link": sugestao.audiencia_link or "",
        # Block-specific recuperados do payload original.
        "objeto": str(payload.get("objeto", "") or ""),
        "assunto": str(payload.get("assunto", "") or ""),
        "audiencia_tipo": str(payload.get("tipo_audiencia", "") or ""),
        "audiencia_endereco": str(payload.get("endereco", "") or ""),
        "julgamento_tipo": str(payload.get("tipo_julgamento", "") or ""),
        "julgamento_data": _iso(sugestao.data_base) if sugestao.tipo_prazo == "JULGAMENTO" else "",
        "recurso": str(payload.get("recurso", "") or ""),
    }
    return ctx


def _render_template(text: str, ctx: dict[str, str]) -> str:
    """Mesmo helper do classifier — aceita placeholders ausentes (vira
    string vazia via defaultdict) em vez de levantar KeyError."""
    safe = defaultdict(str, ctx)
    try:
        return text.format_map(safe)
    except Exception:  # noqa: BLE001
        # Template malformado (ex.: chave nao fechada): devolve o texto
        # original cru pra nao quebrar o reapply em massa.
        return text

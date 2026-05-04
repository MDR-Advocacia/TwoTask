"""Resolve o assistente da squad de um responsavel.

Usado no agendamento de tarefas (prazos iniciais + publicacoes) quando
o template tem `target_role='assistente'`. Decisao de arquitetura
documentada em memory/project_squads_assistente.md.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.legal_one import LegalOneTaskSubType, LegalOneUser
from app.models.rules import Squad, SquadMember

logger = logging.getLogger(__name__)


class AssistantResolutionResult:
    """Resultado tipado pra UI ter contexto do que aconteceu."""

    __slots__ = ("user_external_id", "squad_id", "squad_name", "fallback_reason")

    def __init__(
        self,
        user_external_id: int,
        squad_id: Optional[int] = None,
        squad_name: Optional[str] = None,
        fallback_reason: Optional[str] = None,
    ) -> None:
        self.user_external_id = user_external_id
        self.squad_id = squad_id
        self.squad_name = squad_name
        # Quando preenchido, a UI pode exibir aviso (ex.: "User X nao tem
        # squad — usado ele mesmo como assistente"). None = resolucao limpa.
        self.fallback_reason = fallback_reason


def resolve_assistant(
    db: Session,
    *,
    responsible_user_external_id: int,
    task_subtype_external_id: Optional[int] = None,
    office_external_id: Optional[int] = None,
) -> AssistantResolutionResult:
    """
    Resolve o assistente do responsavel.

    Tie-break (em ordem):
      1. Se o user e' membro de uma unica squad ativa, usa essa.
      2. Se e' membro de varias, escolhe a squad cujo `office_external_id`
         casa com o `office_external_id` informado (vem do intake/sugestao
         no momento do agendamento). Esse e' o balizador no MDR — squads
         sao por escritorio responsavel.
      3. Se ainda assim sobrar mais de uma (mesmo office, multiplas squads
         do user) ou se nenhuma casar, retorna a primeira por id e marca
         `fallback_reason='multiple_squads_ambiguous'`.

    `task_subtype_external_id` e' aceito por compat (chamadas antigas) mas
    nao e' mais usado no tie-break — domain agora opera por escritorio.

    Edge cases (decididos com user em 2026-05-04):
      - User nao e' membro de nenhuma squad → fallback pro proprio user
        com `fallback_reason='user_not_in_any_squad'`. Loga warn.
      - Squad escolhida nao tem assistente cadastrado → levanta
        `ValueError` com mensagem humana (caller mostra erro ao operador).
      - Assistente da squad e' o proprio responsavel → retorna ele mesmo
        sem fallback_reason (caso valido — auto-atribuido).
    """
    del task_subtype_external_id  # mantido na assinatura por compat
    user = (
        db.query(LegalOneUser)
        .filter(LegalOneUser.external_id == responsible_user_external_id)
        .one_or_none()
    )
    if user is None:
        raise ValueError(
            f"Responsavel {responsible_user_external_id} nao encontrado "
            "no catalogo do Legal One. Sincronize o catalogo via "
            "MetadataSyncService."
        )

    member_rows = (
        db.query(SquadMember)
        .join(Squad, SquadMember.squad_id == Squad.id)
        .filter(
            SquadMember.legal_one_user_id == user.id,
            Squad.is_active.is_(True),
        )
        .all()
    )

    if not member_rows:
        logger.warning(
            "squad_assistant.fallback user=%s reason=user_not_in_any_squad",
            responsible_user_external_id,
        )
        return AssistantResolutionResult(
            user_external_id=responsible_user_external_id,
            fallback_reason="user_not_in_any_squad",
        )

    candidate_squads = [row.squad for row in member_rows]
    chosen_squad: Optional[Squad] = None
    fallback_reason: Optional[str] = None

    if len(candidate_squads) == 1:
        chosen_squad = candidate_squads[0]
    else:
        if office_external_id is not None:
            squads_in_office = [
                s for s in candidate_squads
                if s.office_external_id == office_external_id
            ]
            if len(squads_in_office) == 1:
                chosen_squad = squads_in_office[0]
            elif len(squads_in_office) > 1:
                chosen_squad = sorted(squads_in_office, key=lambda s: s.id)[0]
                fallback_reason = "multiple_squads_ambiguous"

        if chosen_squad is None:
            chosen_squad = sorted(candidate_squads, key=lambda s: s.id)[0]
            fallback_reason = "multiple_squads_ambiguous"

    # Procura assistente na squad escolhida
    assistant_member = (
        db.query(SquadMember)
        .filter(
            SquadMember.squad_id == chosen_squad.id,
            SquadMember.is_assistant.is_(True),
        )
        .one_or_none()
    )

    if assistant_member is None:
        raise ValueError(
            f"Squad '{chosen_squad.name}' (id={chosen_squad.id}) nao tem "
            "assistente cadastrado. Cadastre em /admin/squads ou troque "
            "o responsavel da tarefa."
        )

    assistant_user = (
        db.query(LegalOneUser)
        .filter(LegalOneUser.id == assistant_member.legal_one_user_id)
        .one_or_none()
    )
    if assistant_user is None:
        raise ValueError(
            f"Squad '{chosen_squad.name}' (id={chosen_squad.id}) tem "
            f"assistente registrado (member_id={assistant_member.id}) mas "
            "o user nao existe mais no catalogo. Re-sincronize ou ajuste "
            "a squad."
        )

    return AssistantResolutionResult(
        user_external_id=int(assistant_user.external_id),
        squad_id=chosen_squad.id,
        squad_name=chosen_squad.name,
        fallback_reason=fallback_reason,
    )

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


def resolve_target(
    db: Session,
    *,
    target_role: str,
    responsible_user_external_id: int,
    target_squad_id: Optional[int] = None,
    task_subtype_external_id: Optional[int] = None,
    office_external_id: Optional[int] = None,
    commit: bool = False,
) -> AssistantResolutionResult:
    """
    Resolve quem recebe a tarefa baseado no template (`target_role`,
    `target_squad_id`). Cobre 4 cenarios:

    - target_role='principal', target_squad_id=None: retorna o
      `responsible_user_external_id` direto (responsavel padrao).
    - target_role='assistente', target_squad_id=None: assistente da
      squad PRINCIPAL do responsavel (`resolve_assistant` atual).
    - target_role='principal', target_squad_id=X: leader da squad de
      suporte X.
    - target_role='assistente', target_squad_id=X: assistente da squad
      de suporte X (round-robin).

    `commit=True` avanca o `last_assigned_at` no membro escolhido.
    """
    # Cenario 1: principal sem squad de suporte → responsavel padrao
    if target_role == "principal" and target_squad_id is None:
        return AssistantResolutionResult(
            user_external_id=int(responsible_user_external_id),
        )

    # Cenarios 3 e 4: squad de suporte explicita
    if target_squad_id is not None:
        return _resolve_in_squad(
            db,
            squad_id=int(target_squad_id),
            target_role=target_role,
            commit=commit,
        )

    # Cenario 2: assistente da squad principal (logica atual)
    return resolve_assistant(
        db,
        responsible_user_external_id=responsible_user_external_id,
        task_subtype_external_id=task_subtype_external_id,
        office_external_id=office_external_id,
        commit=commit,
    )


def _resolve_in_squad(
    db: Session,
    *,
    squad_id: int,
    target_role: str,
    commit: bool,
) -> AssistantResolutionResult:
    """Pega leader (target_role='principal') ou proximo assistente em
    round-robin (target_role='assistente') da squad informada. Usado pra
    squads de suporte (kind='support')."""
    squad = db.query(Squad).filter(Squad.id == squad_id).one_or_none()
    if squad is None:
        raise ValueError(f"Squad {squad_id} nao encontrada.")
    if not squad.is_active:
        raise ValueError(f"Squad '{squad.name}' (id={squad_id}) esta inativa.")

    if target_role == "principal":
        leader = (
            db.query(SquadMember)
            .filter(SquadMember.squad_id == squad_id, SquadMember.is_leader.is_(True))
            .one_or_none()
        )
        if leader is None:
            raise ValueError(
                f"Squad '{squad.name}' (id={squad_id}) nao tem lider cadastrado."
            )
        user = (
            db.query(LegalOneUser)
            .filter(LegalOneUser.id == leader.legal_one_user_id)
            .one_or_none()
        )
        if user is None:
            raise ValueError(
                f"Lider da squad '{squad.name}' nao existe mais no catalogo. "
                "Re-sincronize ou ajuste a squad."
            )
        return AssistantResolutionResult(
            user_external_id=int(user.external_id),
            squad_id=squad.id,
            squad_name=squad.name,
        )

    # target_role='assistente' → round-robin
    from datetime import datetime, timezone
    member = (
        db.query(SquadMember)
        .filter(SquadMember.squad_id == squad_id, SquadMember.is_assistant.is_(True))
        .order_by(
            SquadMember.last_assigned_at.asc().nullsfirst(),
            SquadMember.id.asc(),
        )
        .first()
    )
    if member is None:
        raise ValueError(
            f"Squad '{squad.name}' (id={squad_id}) nao tem assistente cadastrado."
        )
    if commit:
        member.last_assigned_at = datetime.now(timezone.utc)
        db.flush()
    user = (
        db.query(LegalOneUser)
        .filter(LegalOneUser.id == member.legal_one_user_id)
        .one_or_none()
    )
    if user is None:
        raise ValueError(
            f"Assistente da squad '{squad.name}' nao existe mais no catalogo."
        )
    return AssistantResolutionResult(
        user_external_id=int(user.external_id),
        squad_id=squad.id,
        squad_name=squad.name,
    )


def resolve_assistant(
    db: Session,
    *,
    responsible_user_external_id: int,
    task_subtype_external_id: Optional[int] = None,
    office_external_id: Optional[int] = None,
    commit: bool = False,
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
            # Apenas squads PRINCIPAIS — pra resolver assistente do
            # responsavel principal nao pode considerar squads de
            # suporte que o mesmo user talvez participe.
            Squad.kind == "principal",
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

    # Round-robin entre assistentes ativos da squad: pega o que ficou mais
    # tempo sem receber (last_assigned_at NULLS FIRST). Quando `commit=True`,
    # atualiza last_assigned_at = now() pra avancar a fila — operadores
    # subsequentes pegam o proximo da rotacao. Em preview (commit=False), so'
    # retorna sem mexer no estado.
    from datetime import datetime, timezone

    assistant_member = (
        db.query(SquadMember)
        .filter(
            SquadMember.squad_id == chosen_squad.id,
            SquadMember.is_assistant.is_(True),
        )
        .order_by(
            SquadMember.last_assigned_at.asc().nullsfirst(),
            SquadMember.id.asc(),
        )
        .first()
    )

    if assistant_member is None:
        raise ValueError(
            f"Squad '{chosen_squad.name}' (id={chosen_squad.id}) nao tem "
            "assistente cadastrado. Cadastre em /admin/squads ou troque "
            "o responsavel da tarefa."
        )

    if commit:
        assistant_member.last_assigned_at = datetime.now(timezone.utc)
        db.flush()

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

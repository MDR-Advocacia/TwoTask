from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models.legal_one import LegalOneUser
from app.models.prazo_inicial import (
    INTAKE_STATUS_IN_REVIEW,
    INTAKE_STATUS_SCHEDULED,
    SUGESTAO_REVIEW_EDITED,
    SUGESTAO_REVIEW_PENDING,
    SUGESTAO_REVIEW_REJECTED,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.models.prazo_inicial_legacy_task_queue import (
    QUEUE_STATUS_COMPLETED,
    QUEUE_STATUS_PENDING,
    PrazoInicialLegacyTaskCancellationItem,
)
from app.services.prazos_iniciais.legacy_task_queue_service import (
    PrazosIniciaisLegacyTaskQueueService,
)
from app.services.prazos_iniciais.scheduling_service import (
    PrazosIniciaisSchedulingService,
)
from main import app


@pytest.fixture
def admin_user(db_session: Session) -> LegalOneUser:
    user = LegalOneUser(
        external_id=777001,
        name="Admin PIN Queue",
        email="pin-queue-admin@example.com",
        is_active=True,
        role="admin",
        can_use_prazos_iniciais=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_client(
    client: TestClient, admin_user: LegalOneUser
) -> Generator[TestClient, None, None]:
    def _fake_user():
        return admin_user

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        yield client
    finally:
        del app.dependency_overrides[get_current_user]


def _persist_intake_with_suggestions(db_session: Session) -> PrazoInicialIntake:
    intake = PrazoInicialIntake(
        external_id="pin-queue-1",
        cnj_number="00728373020268050001",
        lawsuit_id=68506,
        office_id=61,
        capa_json={"tribunal": "TJBA"},
        integra_json={"blocos": []},
        status=INTAKE_STATUS_IN_REVIEW,
    )
    db_session.add(intake)
    db_session.flush()

    db_session.add_all(
        [
            PrazoInicialSugestao(
                intake_id=intake.id,
                tipo_prazo="CONTESTAR",
                review_status=SUGESTAO_REVIEW_PENDING,
                payload_proposto={"description": "Abrir contestação"},
            ),
            PrazoInicialSugestao(
                intake_id=intake.id,
                tipo_prazo="AUDIENCIA",
                subtipo="conciliacao",
                review_status=SUGESTAO_REVIEW_REJECTED,
                payload_proposto={"description": "Audiência rejeitada"},
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(intake)
    return intake


def test_confirm_endpoint_marks_intake_as_scheduled_and_enqueues_queue_item(
    auth_client: TestClient,
    db_session: Session,
    admin_user: LegalOneUser,
    monkeypatch,
):
    intake = _persist_intake_with_suggestions(db_session)
    sugestao = intake.sugestoes[0]

    monkeypatch.setattr(
        PrazosIniciaisLegacyTaskQueueService,
        "process_pending_items",
        lambda self, **kwargs: {"processed_count": 0, "items": []},
    )

    response = auth_client.post(
        f"/api/v1/prazos-iniciais/intakes/{intake.id}/confirmar-agendamento",
        json={
            "suggestions": [
                {
                    "suggestion_id": sugestao.id,
                    "created_task_id": 191842,
                    "review_status": SUGESTAO_REVIEW_EDITED,
                }
            ]
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["intake"]["status"] == INTAKE_STATUS_SCHEDULED
    assert data["confirmed_suggestion_ids"] == [sugestao.id]
    assert data["created_task_ids"] == [191842]
    assert data["legacy_task_cancellation_item"]["queue_status"] == QUEUE_STATUS_PENDING
    assert data["legacy_task_cancellation_item"]["lawsuit_id"] == 68506
    assert data["legacy_task_cancellation_item"]["legacy_task_type_external_id"] == 33
    assert data["legacy_task_cancellation_item"]["legacy_task_subtype_external_id"] == 1283

    db_session.expire_all()
    intake_db = db_session.get(PrazoInicialIntake, intake.id)
    sugestao_db = db_session.get(PrazoInicialSugestao, sugestao.id)
    queue_item = (
        db_session.query(PrazoInicialLegacyTaskCancellationItem)
        .filter(PrazoInicialLegacyTaskCancellationItem.intake_id == intake.id)
        .first()
    )
    assert intake_db is not None
    assert intake_db.status == INTAKE_STATUS_SCHEDULED
    assert sugestao_db is not None
    assert sugestao_db.created_task_id == 191842
    assert sugestao_db.review_status == SUGESTAO_REVIEW_EDITED
    assert sugestao_db.reviewed_by_email == admin_user.email
    assert queue_item is not None
    assert queue_item.queue_status == QUEUE_STATUS_PENDING


def test_confirm_service_defaults_to_all_non_rejected_suggestions(db_session: Session):
    intake = _persist_intake_with_suggestions(db_session)

    service = PrazosIniciaisSchedulingService(db_session)
    result = service.confirm_intake_scheduling(
        intake_id=intake.id,
        confirmed_suggestions=None,
        confirmed_by_email="queue@example.com",
    )

    assert result["confirmed_suggestion_ids"] == [intake.sugestoes[0].id]
    queue_item = result["legacy_task_cancellation_item"]
    assert queue_item is not None
    assert queue_item["queue_status"] == QUEUE_STATUS_PENDING

    db_session.expire_all()
    approved = db_session.get(PrazoInicialSugestao, intake.sugestoes[0].id)
    rejected = db_session.get(PrazoInicialSugestao, intake.sugestoes[1].id)
    assert approved is not None
    assert approved.review_status != SUGESTAO_REVIEW_PENDING
    assert rejected is not None
    assert rejected.review_status == SUGESTAO_REVIEW_REJECTED


def test_queue_service_processes_pending_item_and_marks_it_completed(db_session: Session):
    intake = _persist_intake_with_suggestions(db_session)
    intake.status = INTAKE_STATUS_SCHEDULED
    db_session.commit()
    db_session.refresh(intake)

    queue_service = PrazosIniciaisLegacyTaskQueueService(db_session)
    item = queue_service.sync_item_from_intake(intake)
    assert item is not None
    assert item.queue_status == QUEUE_STATUS_PENDING

    fake_cancellation_service = MagicMock()
    fake_cancellation_service.cancel_task.return_value = {
        "success": True,
        "reason": "already_in_target_status",
        "task_id": 279829,
        "runner_state": "completed",
        "runner_item_status": "already_cancelled",
    }

    queue_service = PrazosIniciaisLegacyTaskQueueService(
        db_session,
        cancellation_service=fake_cancellation_service,
    )
    summary = queue_service.process_pending_items(limit=10)

    assert summary["processed_count"] == 1
    processed_item = summary["items"][0]["item"]
    assert processed_item["queue_status"] == QUEUE_STATUS_COMPLETED
    assert processed_item["cancelled_task_id"] == 279829

    db_session.expire_all()
    item_db = db_session.get(PrazoInicialLegacyTaskCancellationItem, item.id)
    assert item_db is not None
    assert item_db.queue_status == QUEUE_STATUS_COMPLETED
    assert item_db.cancelled_task_id == 279829

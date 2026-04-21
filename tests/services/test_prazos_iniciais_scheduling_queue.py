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


# ── Onda B/A: circuit breaker, métricas, ações operadoras ──────────────


from app.services.prazos_iniciais.legacy_task_circuit_breaker import (
    get_circuit_breaker,
)
from app.models.prazo_inicial_legacy_task_queue import (
    QUEUE_STATUS_FAILED,
)


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    get_circuit_breaker().reset()
    yield
    get_circuit_breaker().reset()


_enqueue_counter = {"n": 0}


def _enqueue_pending_item(db_session: Session) -> PrazoInicialLegacyTaskCancellationItem:
    _enqueue_counter["n"] += 1
    n = _enqueue_counter["n"]
    intake = PrazoInicialIntake(
        external_id=f"pin-queue-cb-{n}",
        cnj_number=f"0072837302026805{n:04d}",
        lawsuit_id=68506 + n,
        office_id=61,
        capa_json={"tribunal": "TJBA"},
        integra_json={"blocos": []},
        status=INTAKE_STATUS_SCHEDULED,
    )
    db_session.add(intake)
    db_session.commit()
    db_session.refresh(intake)

    queue_service = PrazosIniciaisLegacyTaskQueueService(db_session)
    item = queue_service.sync_item_from_intake(intake)
    assert item is not None
    return item


def test_circuit_breaker_trips_after_repeated_auth_failures(
    db_session: Session, monkeypatch
):
    # Cria 3 itens pendentes pra alimentar o breaker até estourar o threshold (=3).
    items = [_enqueue_pending_item(db_session) for _ in range(3)]
    assert len(items) == 3

    monkeypatch.setattr(
        "app.core.config.settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds",
        0.0,
    )

    fake_cancellation_service = MagicMock()
    fake_cancellation_service.cancel_task.return_value = {
        "success": False,
        "reason": "auth_failure",
        "task_id": None,
        "runner_state": "failed",
        "runner_item_status": "error",
        "runner_error": "Redirected to /signon",
    }

    queue_service = PrazosIniciaisLegacyTaskQueueService(
        db_session,
        cancellation_service=fake_cancellation_service,
    )
    summary = queue_service.process_pending_items(limit=10)

    # Deve ter processado pelo menos 1 item antes de tripar (não exigimos
    # exatamente 3 — o breaker pode tripar e quebrar o loop).
    assert summary["circuit_breaker_tripped"] is False
    assert summary["circuit_breaker_tripped_during_tick"] is True
    assert summary["failure_count"] >= 1

    # Próximo tick (sem intake_id) deve ser pulado pelo breaker.
    summary2 = queue_service.process_pending_items(limit=10)
    assert summary2["circuit_breaker_tripped"] is True
    assert summary2["processed_count"] == 0


def test_circuit_breaker_does_not_trip_for_business_failures(
    db_session: Session, monkeypatch
):
    items = [_enqueue_pending_item(db_session) for _ in range(3)]
    assert len(items) == 3

    monkeypatch.setattr(
        "app.core.config.settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds",
        0.0,
    )

    fake_cancellation_service = MagicMock()
    # task_not_found = falha de dado — não deve alimentar o breaker.
    fake_cancellation_service.cancel_task.return_value = {
        "success": False,
        "reason": "task_not_found",
        "task_id": None,
        "runner_state": None,
        "runner_item_status": None,
        "runner_error": None,
    }

    queue_service = PrazosIniciaisLegacyTaskQueueService(
        db_session,
        cancellation_service=fake_cancellation_service,
    )
    summary = queue_service.process_pending_items(limit=10)

    assert summary["circuit_breaker_tripped"] is False
    assert summary["circuit_breaker_tripped_during_tick"] is False
    assert summary["failure_count"] == 3
    assert get_circuit_breaker().is_tripped() is False


def test_intake_scoped_calls_bypass_circuit_breaker(db_session: Session, monkeypatch):
    item = _enqueue_pending_item(db_session)

    # Tripa o breaker manualmente.
    cb = get_circuit_breaker()
    for _ in range(10):
        cb.record_failure("auth_failure")
    assert cb.is_tripped() is True

    fake_cancellation_service = MagicMock()
    fake_cancellation_service.cancel_task.return_value = {
        "success": True,
        "reason": "cancelled",
        "task_id": 279829,
        "runner_state": "completed",
        "runner_item_status": "cancelled",
    }

    monkeypatch.setattr(
        "app.core.config.settings.prazos_iniciais_legacy_task_cancel_rate_limit_seconds",
        0.0,
    )

    queue_service = PrazosIniciaisLegacyTaskQueueService(
        db_session,
        cancellation_service=fake_cancellation_service,
    )
    # Chamada com intake_id (background task pós-confirmação) deve ignorar
    # o breaker e processar o item mesmo assim.
    summary = queue_service.process_pending_items(limit=1, intake_id=item.intake_id)
    assert summary["processed_count"] == 1


def test_reprocess_item_resets_failed_to_pending(db_session: Session):
    item = _enqueue_pending_item(db_session)
    item.queue_status = QUEUE_STATUS_FAILED
    item.last_error = "boom"
    item.last_reason = "auth_failure"
    db_session.commit()

    queue_service = PrazosIniciaisLegacyTaskQueueService(db_session)
    payload = queue_service.reprocess_item(item.id)

    assert payload is not None
    assert payload["queue_status"] == QUEUE_STATUS_PENDING
    assert payload["last_error"] is None
    assert payload["last_reason"] is None


def test_cancel_item_marks_status_as_cancelled(db_session: Session):
    item = _enqueue_pending_item(db_session)
    queue_service = PrazosIniciaisLegacyTaskQueueService(db_session)
    payload = queue_service.cancel_item(item.id)

    assert payload is not None
    assert payload["queue_status"] == "CANCELADO"
    assert payload["last_reason"] == "manually_cancelled"


def test_aggregate_metrics_returns_status_totals_and_circuit_breaker(
    db_session: Session,
):
    items = [_enqueue_pending_item(db_session) for _ in range(2)]
    assert len(items) == 2

    queue_service = PrazosIniciaisLegacyTaskQueueService(db_session)
    metrics = queue_service.aggregate_metrics(hours=24)

    assert metrics["window_hours"] == 24
    assert metrics["totals_by_status"].get(QUEUE_STATUS_PENDING) == 2
    assert metrics["circuit_breaker"]["tripped"] is False
    assert metrics["circuit_breaker"]["threshold"] >= 1
    assert metrics["circuit_breaker"]["counted_reasons"]


def test_metrics_endpoint_returns_payload(
    auth_client: TestClient,
    db_session: Session,
):
    _enqueue_pending_item(db_session)

    response = auth_client.get(
        "/api/v1/prazos-iniciais/legacy-task-cancel-queue/metrics"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "totals_by_status" in body
    assert "circuit_breaker" in body
    assert "last_tick" in body


def test_reprocess_endpoint_resets_failed_item(
    auth_client: TestClient, db_session: Session
):
    item = _enqueue_pending_item(db_session)
    item.queue_status = QUEUE_STATUS_FAILED
    item.last_error = "boom"
    db_session.commit()

    response = auth_client.post(
        f"/api/v1/prazos-iniciais/legacy-task-cancel-queue/items/{item.id}/reprocessar"
    )
    assert response.status_code == 200, response.text
    assert response.json()["item"]["queue_status"] == QUEUE_STATUS_PENDING


def test_cancel_endpoint_marks_pending_item_as_cancelled(
    auth_client: TestClient, db_session: Session
):
    item = _enqueue_pending_item(db_session)
    response = auth_client.post(
        f"/api/v1/prazos-iniciais/legacy-task-cancel-queue/items/{item.id}/cancelar"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["item"]["queue_status"] == "CANCELADO"
    assert body["item"]["last_reason"] == "manually_cancelled"


def test_csv_export_returns_csv_with_header(
    auth_client: TestClient, db_session: Session
):
    _enqueue_pending_item(db_session)

    response = auth_client.get(
        "/api/v1/prazos-iniciais/legacy-task-cancel-queue/export.csv"
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    body = response.text.lstrip("\ufeff")
    first_line = body.splitlines()[0]
    assert "id" in first_line
    assert "queue_status" in first_line
    assert "cnj_number" in first_line


def test_list_endpoint_supports_intake_id_and_cnj_filters(
    auth_client: TestClient, db_session: Session
):
    item = _enqueue_pending_item(db_session)
    # Garante que tem CNJ pra testar o filtro substring.
    assert item.cnj_number

    response_intake = auth_client.get(
        f"/api/v1/prazos-iniciais/legacy-task-cancel-queue?intake_id={item.intake_id}"
    )
    assert response_intake.status_code == 200, response_intake.text
    body_intake = response_intake.json()
    assert body_intake["total"] == 1

    cnj_fragment = item.cnj_number[:8]
    response_cnj = auth_client.get(
        f"/api/v1/prazos-iniciais/legacy-task-cancel-queue?cnj_number={cnj_fragment}"
    )
    assert response_cnj.status_code == 200, response_cnj.text
    assert response_cnj.json()["total"] >= 1

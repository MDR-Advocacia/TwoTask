from __future__ import annotations

from typing import Any, Optional

from app.services.prazos_iniciais.legacy_task_cancellation_service import (
    DEFAULT_CANCELLED_STATUS_ID,
    DEFAULT_CANCELLED_STATUS_TEXT,
    DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS,
    DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
    DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
    LegacyTaskCancellationService,
)


class DummyLegalOneClient:
    def __init__(
        self,
        *,
        lawsuit: Optional[dict[str, Any]] = None,
        tasks: Optional[list[dict[str, Any]]] = None,
        task_by_id: Optional[dict[int, dict[str, Any]]] = None,
        relationships_by_task_id: Optional[dict[int, list[dict[str, Any]]]] = None,
    ):
        self.lawsuit = lawsuit
        self.tasks = tasks or []
        self.task_by_id = task_by_id or {}
        self.relationships_by_task_id = relationships_by_task_id or {}
        self.last_find_args: Optional[dict[str, Any]] = None
        self.last_search_cnj: Optional[str] = None
        self.last_get_task_id: Optional[int] = None

    def search_lawsuit_by_cnj(self, cnj_number: str) -> Optional[dict[str, Any]]:
        self.last_search_cnj = cnj_number
        return self.lawsuit

    def find_tasks_for_lawsuit(
        self,
        lawsuit_id: int,
        *,
        type_id: Optional[int] = None,
        subtype_id: Optional[int] = None,
        status_ids: Optional[list[int]] = None,
        top: int = 50,
    ) -> list[dict[str, Any]]:
        self.last_find_args = {
            "lawsuit_id": lawsuit_id,
            "type_id": type_id,
            "subtype_id": subtype_id,
            "status_ids": status_ids,
            "top": top,
        }
        return list(self.tasks)

    def get_task_by_id(self, task_id: int) -> dict[str, Any]:
        self.last_get_task_id = task_id
        return self.task_by_id[task_id]

    def get_task_relationships(self, task_id: int) -> list[dict[str, Any]]:
        return list(self.relationships_by_task_id.get(task_id, []))


def test_cancel_task_selects_newest_pending_candidate_and_runs_runner(monkeypatch):
    client = DummyLegalOneClient(
        lawsuit={
            "id": 68506,
            "identifierNumber": "0072837-30.2026.8.05.0001",
        },
        tasks=[
            {
                "id": 279001,
                "statusId": 0,
                "description": "Verificar Prazos e Habilitacao - Banco Master",
                "creationDate": "2026-04-20T08:31:48.6441091-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            },
            {
                "id": 279829,
                "statusId": 0,
                "description": "TESTE ROBO - AGENDAR PRAZOS",
                "creationDate": "2026-04-20T16:17:31.0713039-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            },
        ],
    )
    service = LegacyTaskCancellationService(client=client)
    captured: dict[str, Any] = {}

    def fake_run_runner(self, *, paths, runner_items, max_attempts):
        captured["paths"] = paths
        captured["runner_items"] = runner_items
        captured["max_attempts"] = max_attempts
        return {
            "state": "completed",
            "process_exit_code": 0,
            "items": [
                {
                    "status": "cancelled",
                    "response": {
                        "verifiedStatusId": "3",
                        "verifiedStatusText": DEFAULT_CANCELLED_STATUS_TEXT,
                    },
                }
            ],
        }

    monkeypatch.setattr(
        LegacyTaskCancellationService,
        "_run_runner",
        fake_run_runner,
    )

    result = service.cancel_task(cnj_number="0072837-30.2026.8.05.0001")

    assert result["success"] is True
    assert result["reason"] == "cancelled"
    assert result["task_id"] == 279829
    assert result["lawsuit_id"] == 68506
    assert result["current_status_id"] == 0
    assert result["target_status_id"] == DEFAULT_CANCELLED_STATUS_ID
    assert result["runner_item_status"] == "cancelled"
    assert result["selected_task"]["id"] == 279829

    assert client.last_search_cnj == "0072837-30.2026.8.05.0001"
    assert client.last_find_args == {
        "lawsuit_id": 68506,
        "type_id": DEFAULT_LEGACY_TASK_TYPE_EXTERNAL_ID,
        "subtype_id": DEFAULT_LEGACY_TASK_SUBTYPE_EXTERNAL_ID,
        "status_ids": list(DEFAULT_LEGACY_TASK_CANDIDATE_STATUS_IDS),
        "top": 25,
    }

    assert captured["max_attempts"] == 2
    assert captured["runner_items"][0]["taskId"] == 279829
    assert captured["runner_items"][0]["targetStatusId"] == DEFAULT_CANCELLED_STATUS_ID
    assert captured["runner_items"][0]["targetStatusText"] == DEFAULT_CANCELLED_STATUS_TEXT
    assert "EditCompromissoTarefa/279829" in captured["runner_items"][0]["editUrl"]


def test_cancel_task_returns_task_not_found_when_no_candidate_exists():
    client = DummyLegalOneClient(
        lawsuit={
            "id": 68506,
            "identifierNumber": "0072837-30.2026.8.05.0001",
        },
        tasks=[],
    )
    service = LegacyTaskCancellationService(client=client)

    result = service.cancel_task(cnj_number="0072837-30.2026.8.05.0001")

    assert result["success"] is False
    assert result["reason"] == "task_not_found"
    assert result["task_id"] is None
    assert result["lawsuit_id"] == 68506
    assert result["runner_state"] is None
    assert result["runner_item_status"] is None


def test_cancel_task_short_circuits_when_task_is_already_cancelled(monkeypatch):
    task_id = 279829
    client = DummyLegalOneClient(
        task_by_id={
            task_id: {
                "id": task_id,
                "statusId": DEFAULT_CANCELLED_STATUS_ID,
                "description": "TESTE ROBO - AGENDAR PRAZOS",
                "creationDate": "2026-04-20T16:17:31.0713039-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            }
        },
        relationships_by_task_id={
            task_id: [{"linkId": 68506, "linkType": "Litigation"}]
        },
    )
    service = LegacyTaskCancellationService(client=client)

    def fail_if_runner_is_called(*args, **kwargs):  # pragma: no cover - defensive
        raise AssertionError("Runner nao deveria ser executado para task ja cancelada.")

    monkeypatch.setattr(
        LegacyTaskCancellationService,
        "_run_runner",
        fail_if_runner_is_called,
    )

    result = service.cancel_task(task_id=task_id)

    assert result["success"] is True
    assert result["reason"] == "already_in_target_status"
    assert result["task_id"] == task_id
    assert result["lawsuit_id"] == 68506
    assert result["current_status_id"] == DEFAULT_CANCELLED_STATUS_ID
    assert result["runner_state"] == "completed"
    assert result["runner_item_status"] == "already_cancelled"
    assert result["process_exit_code"] == 0
    assert client.last_get_task_id == task_id


def test_cancel_task_classifies_runner_failure_as_layout_drift(monkeypatch):
    client = DummyLegalOneClient(
        lawsuit={"id": 68506, "identifierNumber": "0072837-30.2026.8.05.0001"},
        tasks=[
            {
                "id": 279829,
                "statusId": 0,
                "description": "TESTE ROBO - AGENDAR PRAZOS",
                "creationDate": "2026-04-20T16:17:31.0713039-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            }
        ],
    )
    service = LegacyTaskCancellationService(client=client)

    def fake_run_runner(self, *, paths, runner_items, max_attempts):
        return {
            "state": "failed",
            "process_exit_code": 1,
            "items": [
                {
                    "status": "error",
                    "error": "Timeout 30000ms exceeded waiting for selector \"#Status\"",
                }
            ],
        }

    monkeypatch.setattr(
        LegacyTaskCancellationService,
        "_run_runner",
        fake_run_runner,
    )

    result = service.cancel_task(cnj_number="0072837-30.2026.8.05.0001")

    # "timeout" vence "layout_drift" na classificação (ordem das categorias):
    # infra > dado, pro circuit breaker acionar primeiro.
    assert result["success"] is False
    assert result["reason"] == "timeout"


def test_cancel_task_classifies_runner_failure_as_auth_when_redirected(monkeypatch):
    client = DummyLegalOneClient(
        lawsuit={"id": 68506, "identifierNumber": "0072837-30.2026.8.05.0001"},
        tasks=[
            {
                "id": 279829,
                "statusId": 0,
                "description": "TESTE ROBO - AGENDAR PRAZOS",
                "creationDate": "2026-04-20T16:17:31.0713039-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            }
        ],
    )
    service = LegacyTaskCancellationService(client=client)

    def fake_run_runner(self, *, paths, runner_items, max_attempts):
        return {
            "state": "failed",
            "items": [
                {
                    "status": "error",
                    "error": "Redirected to /signon after navigation (session expired).",
                }
            ],
        }

    monkeypatch.setattr(
        LegacyTaskCancellationService,
        "_run_runner",
        fake_run_runner,
    )

    result = service.cancel_task(cnj_number="0072837-30.2026.8.05.0001")

    assert result["success"] is False
    assert result["reason"] == "auth_failure"


def test_cancel_task_classifies_pure_layout_drift_without_timeout(monkeypatch):
    client = DummyLegalOneClient(
        lawsuit={"id": 68506, "identifierNumber": "0072837-30.2026.8.05.0001"},
        tasks=[
            {
                "id": 279829,
                "statusId": 0,
                "description": "TESTE ROBO - AGENDAR PRAZOS",
                "creationDate": "2026-04-20T16:17:31.0713039-03:00",
                "typeId": 33,
                "subTypeId": 1283,
            }
        ],
    )
    service = LegacyTaskCancellationService(client=client)

    def fake_run_runner(self, *, paths, runner_items, max_attempts):
        return {
            "state": "failed",
            "items": [
                {
                    "status": "error",
                    "error": "Campo não encontrado: select#StatusId element is not visible",
                }
            ],
        }

    monkeypatch.setattr(
        LegacyTaskCancellationService,
        "_run_runner",
        fake_run_runner,
    )

    result = service.cancel_task(cnj_number="0072837-30.2026.8.05.0001")

    assert result["success"] is False
    assert result["reason"] == "layout_drift"

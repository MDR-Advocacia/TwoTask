import asyncio
from types import SimpleNamespace

from app.services.batch_strategies.spreadsheet_strategy import SpreadsheetStrategy
from app.services.legal_one_client import LegalOneApiClient


class DummyDB:
    def __init__(self):
        self.commit_calls = 0

    def commit(self):
        self.commit_calls += 1


class DummyClient:
    def __init__(self, search_result=None):
        self.search_result = search_result
        self.search_calls = []
        self.created_payloads = []
        self.link_calls = []

    def search_lawsuit_by_cnj(self, cnj_number: str):
        self.search_calls.append(cnj_number)
        return self.search_result

    def create_task(self, task_payload):
        self.created_payloads.append(task_payload)
        return {"id": 321}

    def link_task_to_lawsuit(self, task_id: int, link_payload):
        self.link_calls.append((task_id, link_payload))
        return True


def _build_caches():
    office = SimpleNamespace(external_id=11, path="Escritorio Centro")
    user = SimpleNamespace(external_id=22, name="Maria")
    parent_type = SimpleNamespace(external_id=33)
    subtype = SimpleNamespace(external_id=44, name="Subtipo Teste", parent_type=parent_type)
    return {
        "offices": {"escritorio centro": office},
        "users": {"maria": user},
        "subtypes": {"subtipo teste": subtype},
    }


def _build_row_data():
    return {
        "ESCRITORIO": "Escritorio Centro",
        "CNJ": "0001234-56.2026.8.26.0001",
        "PUBLISH_DATE": "2026-03-18",
        "SUBTIPO": "Subtipo Teste",
        "EXECUTANTE": "Maria",
        "PRAZO": "2026-03-20",
        "DATA_TAREFA": "2026-03-20",
        "HORARIO": "10:30",
        "OBSERVACAO": "Observacao de teste",
        "DESCRICAO": "Descricao complementar",
    }


def _build_log_item():
    return SimpleNamespace(
        status="PENDENTE",
        fingerprint=None,
        created_task_id=None,
        error_message=None,
    )


def test_search_lawsuits_by_cnj_numbers_reuses_fallback_only_for_missing(monkeypatch):
    monkeypatch.setenv("LEGAL_ONE_BASE_URL", "https://example.test")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_ID", "client")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_SECRET", "secret")
    client = LegalOneApiClient()

    calls = []

    def fake_search(endpoint, cnj_numbers):
        calls.append((endpoint, list(cnj_numbers)))
        if endpoint == "/Lawsuits":
            return {
                "CNJ-1": {"id": 1, "identifierNumber": "CNJ-1", "responsibleOfficeId": 10},
            }
        return {
            "CNJ-2": {"id": 2, "identifierNumber": "CNJ-2", "responsibleOfficeId": 20},
        }

    monkeypatch.setattr(client, "_search_process_endpoint_by_cnj_numbers", fake_search)

    result = client.search_lawsuits_by_cnj_numbers(["CNJ-1", "CNJ-2", "CNJ-1", "  "])

    assert result == {
        "CNJ-1": {"id": 1, "identifierNumber": "CNJ-1", "responsibleOfficeId": 10},
        "CNJ-2": {"id": 2, "identifierNumber": "CNJ-2", "responsibleOfficeId": 20},
    }
    assert calls == [
        ("/Lawsuits", ["CNJ-1", "CNJ-2"]),
        ("/Litigations", ["CNJ-2"]),
    ]


def test_process_single_item_uses_prefetched_lookup_without_new_search():
    db = DummyDB()
    client = DummyClient()
    strategy = SpreadsheetStrategy(db, client)
    row_data = _build_row_data()
    log_item = _build_log_item()

    result = asyncio.run(
        strategy.process_single_item(
            log_item,
            row_data,
            _build_caches(),
            known_fingerprints=set(),
            lawsuit_lookup={
                "0001234-56.2026.8.26.0001": {
                    "id": 777,
                    "identifierNumber": "0001234-56.2026.8.26.0001",
                    "responsibleOfficeId": 55,
                }
            },
            prefetched_cnj_numbers={"0001234-56.2026.8.26.0001"},
        )
    )

    assert result is True
    assert client.search_calls == []
    assert client.created_payloads[0]["responsibleOfficeId"] == 55
    assert client.link_calls == [(321, {"linkType": "Litigation", "linkId": 777})]
    assert log_item.status == "SUCESSO"
    assert client.created_payloads[0]["startDateTime"] == "2026-03-20T13:30:00Z"
    assert client.created_payloads[0]["endDateTime"] == "2026-03-20T13:30:00Z"


def test_process_single_item_falls_back_to_single_lookup_when_not_prefetched():
    db = DummyDB()
    client = DummyClient(
        search_result={
            "id": 888,
            "identifierNumber": "0001234-56.2026.8.26.0001",
            "responsibleOfficeId": 66,
        }
    )
    strategy = SpreadsheetStrategy(db, client)
    row_data = _build_row_data()
    log_item = _build_log_item()

    result = asyncio.run(
        strategy.process_single_item(
            log_item,
            row_data,
            _build_caches(),
            known_fingerprints=set(),
            lawsuit_lookup={},
            prefetched_cnj_numbers=set(),
        )
    )

    assert result is True
    assert client.search_calls == ["0001234-56.2026.8.26.0001"]
    assert client.link_calls == [(321, {"linkType": "Litigation", "linkId": 888})]


def test_parse_and_format_date_to_utc_accepts_time_string_with_seconds():
    strategy = SpreadsheetStrategy(db=None, client=None)

    result = strategy._parse_and_format_date_to_utc("31/03/2026", "08:00:00")

    assert result == "2026-03-31T11:00:00Z"


def test_process_single_item_respects_stringified_excel_time_cells():
    db = DummyDB()
    client = DummyClient(
        search_result={
            "id": 999,
            "identifierNumber": "0001234-56.2026.8.26.0001",
            "responsibleOfficeId": 77,
        }
    )
    strategy = SpreadsheetStrategy(db, client)
    row_data = _build_row_data()
    row_data["DATA_TAREFA"] = "2026-03-31 00:00:00"
    row_data["HORARIO"] = "08:00:00"
    log_item = _build_log_item()

    result = asyncio.run(
        strategy.process_single_item(
            log_item,
            row_data,
            _build_caches(),
            known_fingerprints=set(),
            lawsuit_lookup={},
            prefetched_cnj_numbers=set(),
        )
    )

    assert result is True
    assert client.created_payloads[0]["startDateTime"] == "2026-03-31T11:00:00Z"
    assert client.created_payloads[0]["endDateTime"] == "2026-03-31T11:00:00Z"

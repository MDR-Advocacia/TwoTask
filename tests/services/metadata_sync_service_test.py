from app.services.legal_one_client import LegalOneApiClient


def test_get_all_allocatable_areas_does_not_truncate_first_page(monkeypatch):
    monkeypatch.setenv("LEGAL_ONE_BASE_URL", "https://example.test")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_ID", "client")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_SECRET", "secret")
    client = LegalOneApiClient()

    captured = {}

    def fake_paginated_loader(endpoint, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return [
            {"id": 30, "name": "Area antiga", "path": "MDR / Banco A", "allocateData": True},
            {"id": 61, "name": "Area nova", "path": "MDR / Banco Master / Reu", "allocateData": True},
            {"id": 62, "name": "Area nao alocavel", "path": "MDR / Banco Master", "allocateData": False},
        ]

    monkeypatch.setattr(client, "_paginated_catalog_loader", fake_paginated_loader)

    result = client.get_all_allocatable_areas()

    assert captured["endpoint"] == "/areas"
    assert captured["params"] == {"$select": "id,name,path,allocateData", "$orderby": "id"}
    assert result == [
        {"id": 30, "name": "Area antiga", "path": "MDR / Banco A", "allocateData": True},
        {"id": 61, "name": "Area nova", "path": "MDR / Banco Master / Reu", "allocateData": True},
    ]

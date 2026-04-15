from types import SimpleNamespace

from app.services.batch_strategies.spreadsheet_strategy import SpreadsheetStrategy


def test_resolve_row_context_matches_office_with_accent_and_spacing_variations():
    strategy = SpreadsheetStrategy(db=None, client=None)
    office = SimpleNamespace(external_id=11, path="MDR Advocacia / \u00c1rea operacional / Banco Master / R\u00e9u")
    user = SimpleNamespace(external_id=22, name="Mar\u00eda Silva")
    parent_type = SimpleNamespace(external_id=33)
    subtype = SimpleNamespace(external_id=44, name="Audi\u00eancia", parent_type=parent_type)

    caches = {
        "offices": {strategy._normalize_lookup_value(office.path): office},
        "users": {strategy._normalize_lookup_value(user.name): user},
        "subtypes": {strategy._normalize_lookup_value(subtype.name): subtype},
    }
    row_data = {
        "ESCRITORIO": "  MDR Advocacia/Area operacional / Banco Master/ Reu  ",
        "CNJ": "0001234-56.2026.8.26.0001",
        "PUBLISH_DATE": "18/03/2026",
        "SUBTIPO": "Audiencia",
        "EXECUTANTE": "Maria Silva",
        "PRAZO": "20/03/2026",
        "DATA_TAREFA": "20/03/2026",
        "HORARIO": "10:30",
        "OBSERVACAO": "Teste",
        "DESCRICAO": "Teste",
    }

    context = strategy._resolve_row_context(row_data, caches)

    assert context["office"] is office
    assert context["user"] is user
    assert context["sub_type"] is subtype

"""Testes do campo `sistema_mencionado` no response_schema da IA (fase 4).

Cobre:
  - Valor uppercase valido passa direto
  - Valor lowercase normaliza pra uppercase
  - Valor fora do enum vira null + warning
  - Ausente / null -> sistema_mencionado=None sem warning
  - Outros campos do schema continuam funcionando (regression)
"""

from app.services.classifier.response_schema import validate_response


def _base_payload():
    """Payload minimo valido (categoria preenchida)."""
    return {"categoria": "Sentença"}


def test_sistema_mencionado_valido_uppercase():
    p = _base_payload()
    p["sistema_mencionado"] = "SISBAJUD"
    clean = validate_response(p)
    assert clean.sistema_mencionado == "SISBAJUD"
    assert not any("sistema_mencionado" in w for w in clean.warnings)


def test_sistema_mencionado_lowercase_normaliza():
    p = _base_payload()
    p["sistema_mencionado"] = "renajud"
    clean = validate_response(p)
    assert clean.sistema_mencionado == "RENAJUD"


def test_sistema_mencionado_invalido_descarta_com_warning():
    p = _base_payload()
    p["sistema_mencionado"] = "BACEN_FAKE"
    clean = validate_response(p)
    assert clean.sistema_mencionado is None
    assert any(
        "sistema_mencionado" in w and "BACEN_FAKE" in w for w in clean.warnings
    )


def test_sistema_mencionado_null_default():
    p = _base_payload()
    # Nao seta sistema_mencionado
    clean = validate_response(p)
    assert clean.sistema_mencionado is None
    assert not any("sistema_mencionado" in w for w in clean.warnings)


def test_sistema_mencionado_explicit_null():
    p = _base_payload()
    p["sistema_mencionado"] = None
    clean = validate_response(p)
    assert clean.sistema_mencionado is None
    assert not any("sistema_mencionado" in w for w in clean.warnings)


def test_todos_sistemas_validos_no_enum():
    """Cobre o enum fechado: todos os 7 valores passam."""
    for sistema in ["SISBAJUD", "RENAJUD", "INFOJUD", "SNIPER", "CCS", "CNIB", "OUTRO"]:
        p = _base_payload()
        p["sistema_mencionado"] = sistema
        clean = validate_response(p)
        assert clean.sistema_mencionado == sistema, f"falhou pra {sistema}"


def test_outros_campos_continuam_funcionando():
    """Regression: a adicao do sistema_mencionado nao quebrou os outros
    campos do schema."""
    p = {
        "categoria": "Sentença",
        "subcategoria": "Sentença Procedente",
        "polo": "passivo",
        "confianca": "alta",
        "justificativa": "teste",
        "sistema_mencionado": "SISBAJUD",
    }
    clean = validate_response(p)
    assert clean.categoria == "Sentença"
    assert clean.subcategoria == "Sentença Procedente"
    assert clean.polo == "passivo"
    assert clean.confianca == "alta"
    assert clean.sistema_mencionado == "SISBAJUD"

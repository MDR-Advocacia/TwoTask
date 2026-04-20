"""
Testes da Fase 1 do fluxo "Agendar Prazos Iniciais".

Cobrem o caminho feliz (POST /intake cria registro + grava PDF), a
idempotência (reenvio com mesmo external_id não duplica) e as rejeições
principais (API key inválida, PDF inválido, CNJ malformado).
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.prazo_inicial import (
    INTAKE_STATUS_RECEIVED,
    PrazoInicialIntake,
)
from app.services.prazos_iniciais import storage as storage_module
from app.services.prazos_iniciais.intake_service import (
    IntakeService,
    normalize_cnj,
)


# ── Fixtures locais ────────────────────────────────────────────────────


TEST_API_KEY = "test-intake-key"


@pytest.fixture(autouse=True)
def _configure_settings(tmp_path, monkeypatch):
    """Aponta storage_path para tmp e injeta uma API key de teste."""
    monkeypatch.setattr(
        settings, "prazos_iniciais_storage_path", str(tmp_path / "pin_storage")
    )
    monkeypatch.setattr(settings, "prazos_iniciais_api_key", TEST_API_KEY)
    monkeypatch.setattr(settings, "prazos_iniciais_max_pdf_mb", 5)
    yield


@pytest.fixture(autouse=True)
def _mute_lawsuit_resolution(monkeypatch):
    """
    O endpoint dispara `resolve_lawsuit_for_intake` em background. Nos
    testes neutralizamos porque não temos L1 real.
    """
    monkeypatch.setattr(
        IntakeService,
        "resolve_lawsuit_for_intake",
        lambda self, intake_id: None,
    )
    yield


def _valid_pdf_bytes() -> bytes:
    # Minimal válido pra passar no magic-check: header %PDF + algum trailer.
    return b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _valid_payload(external_id: str | None = None) -> dict:
    return {
        "external_id": external_id or f"ext-{uuid.uuid4().hex[:8]}",
        "cnj_number": "1000123-45.2026.8.26.0100",
        "capa": {
            "tribunal": "TJSP",
            "vara": "3ª Vara Cível - Foro Central",
            "classe": "Procedimento Comum Cível",
            "polo_ativo": [{"nome": "Fulano de Tal", "documento": "123.456.789-00"}],
            "polo_passivo": [
                {"nome": "Banco Master S.A.", "documento": "33.923.798/0001-00"}
            ],
        },
        "integra_json": {"blocos": []},
        "metadata": {"source": "teste"},
    }


def _post_intake(
    client: TestClient,
    payload: dict,
    pdf_bytes: bytes | None = None,
    api_key: str | None = TEST_API_KEY,
):
    files = {
        "habilitacao": (
            "habilitacao.pdf",
            io.BytesIO(pdf_bytes if pdf_bytes is not None else _valid_pdf_bytes()),
            "application/pdf",
        ),
    }
    headers = {"X-Intake-Api-Key": api_key} if api_key else {}
    return client.post(
        "/api/v1/prazos-iniciais/intake",
        headers=headers,
        data={"payload": json.dumps(payload)},
        files=files,
    )


# ── Testes do serviço (unit) ───────────────────────────────────────────


def test_normalize_cnj_strips_mask():
    assert normalize_cnj("1000123-45.2026.8.26.0100") == "10001234520268260100"


def test_normalize_cnj_rejects_empty():
    with pytest.raises(ValueError):
        normalize_cnj("")
    with pytest.raises(ValueError):
        normalize_cnj("abc")


def test_save_pdf_rejects_non_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings, "prazos_iniciais_storage_path", str(tmp_path / "pin")
    )
    with pytest.raises(storage_module.PdfValidationError):
        storage_module.save_pdf(b"not a pdf at all")


def test_save_pdf_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings, "prazos_iniciais_storage_path", str(tmp_path / "pin")
    )
    stored = storage_module.save_pdf(_valid_pdf_bytes())
    assert Path(stored.absolute_path).exists()
    assert stored.size_bytes == len(_valid_pdf_bytes())
    assert len(stored.sha256) == 64


# ── Testes do endpoint (integração) ────────────────────────────────────


def test_intake_happy_path(client: TestClient, db_session: Session):
    payload = _valid_payload()
    response = _post_intake(client, payload)
    assert response.status_code == 202, response.text

    body = response.json()
    assert body["already_existed"] is False
    assert body["status"] == INTAKE_STATUS_RECEIVED
    assert body["pdf_stored_path"]

    intake = db_session.get(PrazoInicialIntake, body["intake_id"])
    assert intake is not None
    assert intake.external_id == payload["external_id"]
    # CNJ foi normalizado (só dígitos)
    assert intake.cnj_number == "10001234520268260100"
    assert intake.pdf_bytes == len(_valid_pdf_bytes())
    assert intake.pdf_sha256
    assert intake.status == INTAKE_STATUS_RECEIVED


def test_intake_is_idempotent_by_external_id(
    client: TestClient, db_session: Session
):
    payload = _valid_payload(external_id="stable-ext-id")
    first = _post_intake(client, payload)
    assert first.status_code == 202

    # Segundo POST com mesmo external_id (PDF diferente, até) — não deve duplicar.
    different_pdf = _valid_pdf_bytes() + b"\n% extra"
    second = _post_intake(client, payload, pdf_bytes=different_pdf)
    assert second.status_code == 202

    body1 = first.json()
    body2 = second.json()
    assert body2["already_existed"] is True
    assert body1["intake_id"] == body2["intake_id"]

    # Garante que só existe um registro pra esse external_id
    count = (
        db_session.query(PrazoInicialIntake)
        .filter(PrazoInicialIntake.external_id == "stable-ext-id")
        .count()
    )
    assert count == 1


def test_intake_rejects_missing_api_key(client: TestClient):
    response = _post_intake(client, _valid_payload(), api_key=None)
    assert response.status_code == 401


def test_intake_rejects_wrong_api_key(client: TestClient):
    response = _post_intake(client, _valid_payload(), api_key="wrong-key")
    assert response.status_code == 401


def test_intake_rejects_invalid_pdf(client: TestClient):
    response = _post_intake(
        client, _valid_payload(), pdf_bytes=b"not a pdf content"
    )
    assert response.status_code == 422
    assert "PDF" in response.text


def test_intake_rejects_invalid_cnj(client: TestClient):
    payload = _valid_payload()
    payload["cnj_number"] = "abc"  # vai falhar no normalize_cnj
    response = _post_intake(client, payload)
    assert response.status_code == 422


def test_intake_rejects_malformed_payload_json(client: TestClient):
    files = {
        "habilitacao": (
            "habilitacao.pdf",
            io.BytesIO(_valid_pdf_bytes()),
            "application/pdf",
        ),
    }
    response = client.post(
        "/api/v1/prazos-iniciais/intake",
        headers={"X-Intake-Api-Key": TEST_API_KEY},
        data={"payload": "this is not json"},
        files=files,
    )
    assert response.status_code == 422

"""
Testes dos endpoints CRUD de `prazo_inicial_task_templates`.

Cobrem:
  - Validação de tipo_prazo, subtipo (regras por tipo), priority e
    due_date_reference.
  - Validação de FKs (office / task_subtype / responsible_user).
  - UniqueConstraint → 409.
  - Soft-delete via DELETE (is_active=False).
  - PATCH parcial mantendo consistência de chave.
  - Listagem com filtros (inclui convenções especiais subtipo='' e
    office_external_id=0 para NULL).

Auth: sobrescreve `get_current_user` pra retornar um admin. Com role=admin,
o `require_permission("prazos_iniciais")` faz bypass (ver app/core/auth.py).
"""

from __future__ import annotations

from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from app.core.auth import get_current_user
from app.models.legal_one import LegalOneOffice, LegalOneTaskSubType, LegalOneUser
from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db_session: Session) -> LegalOneUser:
    """
    Usuário admin persistido no banco de teste. Usado pra responder ao
    override de `get_current_user`. Role=admin faz bypass do
    require_permission, então mesmo sem setar can_use_prazos_iniciais a
    auth passa.
    """
    user = LegalOneUser(
        external_id=123456,
        name="Admin Teste",
        email="admin@example.com",
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
    """TestClient com get_current_user retornando o admin."""

    def _fake_user():
        return admin_user

    app.dependency_overrides[get_current_user] = _fake_user
    try:
        yield client
    finally:
        del app.dependency_overrides[get_current_user]


@pytest.fixture
def legal_one_refs(db_session: Session) -> dict:
    """Cria 1 office, 1 task_subtype, 1 user — FKs referenciáveis nos testes."""
    # task_type precisa existir antes do task_subtype (FK).
    from app.models.legal_one import LegalOneTaskType

    tt = LegalOneTaskType(
        external_id=500, name="Contestação", is_active=True
    )
    db_session.add(tt)
    db_session.flush()

    office = LegalOneOffice(
        external_id=42, name="SP", path="MDR > SP", is_active=True
    )
    subtype = LegalOneTaskSubType(
        external_id=9001,
        name="Abrir prazo para contestar",
        is_active=True,
        parent_type_external_id=500,
    )
    user = LegalOneUser(
        external_id=8001,
        name="Responsável",
        email="resp@example.com",
        is_active=True,
    )
    db_session.add_all([office, subtype, user])
    db_session.commit()
    return {
        "office_external_id": office.external_id,
        "task_subtype_external_id": subtype.external_id,
        "responsible_user_external_id": user.external_id,
    }


def _base_body(refs: dict, **override) -> dict:
    """Body válido mínimo pra create."""
    body = {
        "name": "tpl 1",
        "tipo_prazo": "CONTESTAR",
        "subtipo": None,
        "office_external_id": None,
        "task_subtype_external_id": refs["task_subtype_external_id"],
        "responsible_user_external_id": refs["responsible_user_external_id"],
        "priority": "Normal",
        "due_business_days": 3,
        "due_date_reference": "data_base",
        "description_template": None,
        "notes_template": None,
        "is_active": True,
    }
    body.update(override)
    return body


# ─── Create ──────────────────────────────────────────────────────────


class TestCreateTemplate:
    def test_creates_valid_global_template(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates", json=_base_body(legal_one_refs)
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["tipo_prazo"] == "CONTESTAR"
        assert data["subtipo"] is None
        assert data["office_external_id"] is None
        assert data["is_active"] is True
        # Nomes resolvidos (enriquecimento pra UI).
        assert data["task_subtype_name"] == "Abrir prazo para contestar"
        assert data["responsible_user_name"] == "Responsável"

    def test_creates_specific_office_template(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                office_external_id=legal_one_refs["office_external_id"],
            ),
        )
        assert r.status_code == 201, r.text
        data = r.json()
        assert data["office_external_id"] == 42
        assert data["office_name"] == "SP"

    def test_rejects_unknown_tipo_prazo(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, tipo_prazo="INVALIDO"),
        )
        assert r.status_code == 422
        assert "tipo_prazo inválido" in r.json()["detail"]

    def test_rejects_subtipo_in_contestar(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, tipo_prazo="CONTESTAR", subtipo="qualquer"
            ),
        )
        assert r.status_code == 422
        assert "subtipo só é permitido" in r.json()["detail"]

    def test_rejects_wrong_subtipo_for_audiencia(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, tipo_prazo="AUDIENCIA", subtipo="invalida"
            ),
        )
        assert r.status_code == 422
        assert "subtipo inválido para AUDIENCIA" in r.json()["detail"]

    def test_accepts_valid_subtipo_for_audiencia(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, tipo_prazo="AUDIENCIA", subtipo="conciliacao"
            ),
        )
        assert r.status_code == 201, r.text

    def test_accepts_null_subtipo_for_audiencia(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, tipo_prazo="AUDIENCIA", subtipo=None
            ),
        )
        assert r.status_code == 201, r.text

    def test_rejects_wrong_subtipo_for_julgamento(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, tipo_prazo="JULGAMENTO", subtipo="procedente"
            ),
        )
        assert r.status_code == 422
        assert "subtipo inválido para JULGAMENTO" in r.json()["detail"]

    def test_rejects_invalid_priority(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, priority="URGENTE"),
        )
        assert r.status_code == 422
        assert "priority inválida" in r.json()["detail"]

    def test_rejects_invalid_due_date_reference(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, due_date_reference="custom"),
        )
        assert r.status_code == 422
        assert "due_date_reference inválida" in r.json()["detail"]

    def test_rejects_unknown_task_subtype_external_id(
        self, auth_client, legal_one_refs
    ):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, task_subtype_external_id=999999),
        )
        assert r.status_code == 422
        assert "task_subtype_external_id não encontrado" in r.json()["detail"]

    def test_rejects_unknown_responsible_user(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, responsible_user_external_id=999999),
        )
        assert r.status_code == 422

    def test_rejects_unknown_office(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, office_external_id=999999),
        )
        assert r.status_code == 422
        assert "office_external_id não encontrado" in r.json()["detail"]

    def test_duplicate_key_returns_409(self, auth_client, legal_one_refs):
        body = _base_body(legal_one_refs)
        r1 = auth_client.post("/api/v1/prazos-iniciais/templates", json=body)
        assert r1.status_code == 201
        r2 = auth_client.post("/api/v1/prazos-iniciais/templates", json=body)
        assert r2.status_code == 409
        assert "Já existe template" in r2.json()["detail"]


# ─── List / Get ──────────────────────────────────────────────────────


class TestListTemplates:
    def test_list_empty(self, auth_client):
        r = auth_client.get("/api/v1/prazos-iniciais/templates")
        assert r.status_code == 200
        assert r.json() == {"total": 0, "items": []}

    def test_list_filter_by_tipo_prazo(self, auth_client, legal_one_refs):
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, name="a", tipo_prazo="CONTESTAR"),
        )
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, name="b", tipo_prazo="LIMINAR"),
        )
        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates", params={"tipo_prazo": "LIMINAR"}
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "b"

    def test_list_filter_subtipo_empty_means_null(
        self, auth_client, legal_one_refs
    ):
        """subtipo='' (string vazia) → filtra templates com subtipo=NULL."""
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                name="aud-null",
                tipo_prazo="AUDIENCIA",
                subtipo=None,
            ),
        )
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                name="aud-conc",
                tipo_prazo="AUDIENCIA",
                subtipo="conciliacao",
            ),
        )
        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates",
            params={"tipo_prazo": "AUDIENCIA", "subtipo": ""},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "aud-null"

    def test_list_filter_office_zero_means_global(
        self, auth_client, legal_one_refs
    ):
        """office_external_id=0 → só templates globais (office NULL)."""
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                name="global",
                office_external_id=None,
            ),
        )
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                name="sp",
                office_external_id=legal_one_refs["office_external_id"],
            ),
        )
        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates", params={"office_external_id": 0}
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "global"

    def test_list_filter_is_active(self, auth_client, legal_one_refs):
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, name="ativo"),
        )
        r2 = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs,
                name="inativo",
                tipo_prazo="LIMINAR",
                is_active=False,
            ),
        )
        assert r2.status_code == 201

        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates", params={"is_active": False}
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "inativo"

    def test_get_by_id(self, auth_client, legal_one_refs):
        created = auth_client.post(
            "/api/v1/prazos-iniciais/templates", json=_base_body(legal_one_refs)
        ).json()
        r = auth_client.get(f"/api/v1/prazos-iniciais/templates/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_get_404(self, auth_client):
        r = auth_client.get("/api/v1/prazos-iniciais/templates/99999")
        assert r.status_code == 404


# ─── Update ──────────────────────────────────────────────────────────


class TestUpdateTemplate:
    def test_partial_update_name_only(self, auth_client, legal_one_refs):
        created = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, name="antes"),
        ).json()
        r = auth_client.patch(
            f"/api/v1/prazos-iniciais/templates/{created['id']}",
            json={"name": "depois"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "depois"
        assert r.json()["tipo_prazo"] == "CONTESTAR"  # inalterado

    def test_cannot_set_subtipo_on_contestar_via_patch(
        self, auth_client, legal_one_refs
    ):
        created = auth_client.post(
            "/api/v1/prazos-iniciais/templates", json=_base_body(legal_one_refs)
        ).json()
        r = auth_client.patch(
            f"/api/v1/prazos-iniciais/templates/{created['id']}",
            json={"subtipo": "tentativa"},
        )
        assert r.status_code == 422
        assert "subtipo só é permitido" in r.json()["detail"]

    def test_patch_conflicts_with_existing_key(
        self, auth_client, legal_one_refs
    ):
        a = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(
                legal_one_refs, name="A", tipo_prazo="CONTESTAR"
            ),
        ).json()
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_base_body(legal_one_refs, name="B", tipo_prazo="LIMINAR"),
        )

        # Muda A pra LIMINAR → colide com B.
        r = auth_client.patch(
            f"/api/v1/prazos-iniciais/templates/{a['id']}",
            json={"tipo_prazo": "LIMINAR"},
        )
        assert r.status_code == 409
        assert "Outro template já ocupa" in r.json()["detail"]

    def test_patch_not_found(self, auth_client):
        r = auth_client.patch(
            "/api/v1/prazos-iniciais/templates/99999", json={"name": "x"}
        )
        assert r.status_code == 404


# ─── Soft delete ─────────────────────────────────────────────────────


class TestDeleteTemplate:
    def test_soft_delete_sets_is_active_false(
        self, auth_client, legal_one_refs, db_session
    ):
        created = auth_client.post(
            "/api/v1/prazos-iniciais/templates", json=_base_body(legal_one_refs)
        ).json()

        r = auth_client.delete(f"/api/v1/prazos-iniciais/templates/{created['id']}")
        assert r.status_code == 200
        assert r.json()["is_active"] is False

        # Registro continua no banco.
        still_there = (
            db_session.query(PrazoInicialTaskTemplate)
            .filter(PrazoInicialTaskTemplate.id == created["id"])
            .first()
        )
        assert still_there is not None
        assert still_there.is_active is False

    def test_delete_404(self, auth_client):
        r = auth_client.delete("/api/v1/prazos-iniciais/templates/99999")
        assert r.status_code == 404


# ─── Auth ────────────────────────────────────────────────────────────


class TestAuth:
    def test_unauthenticated_request_returns_401(self, client, legal_one_refs):
        """
        Sem override de get_current_user, o TestClient sem Authorization
        header deve receber 401.
        """
        r = client.get("/api/v1/prazos-iniciais/templates")
        assert r.status_code == 401

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as _models  # noqa: F401 - registers all tables on Base.metadata
from app.db.session import Base
from app.models.legal_one import (
    LegalOneOffice,
    LegalOneTaskSubType,
    LegalOneTaskType,
    LegalOneUser,
)
from app.models.task_template import TaskTemplate
from app.services.legal_one_client import LegalOneApiClient
from app.services.metadata_sync_service import MetadataSyncService


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


def test_sync_task_types_preserves_subtypes_referenced_by_templates(monkeypatch):
    monkeypatch.setenv("LEGAL_ONE_BASE_URL", "https://example.test")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_ID", "client")
    monkeypatch.setenv("LEGAL_ONE_CLIENT_SECRET", "secret")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_session = TestingSessionLocal()
    try:
        db_session.add_all(
            [
                LegalOneOffice(external_id=61, name="Office", is_active=True),
                LegalOneUser(external_id=10, name="User", email="user@example.test", is_active=True),
                LegalOneTaskType(external_id=1, name="Tipo antigo", is_active=True),
                LegalOneTaskType(external_id=3, name="Tipo removido", is_active=True),
                LegalOneTaskSubType(
                    external_id=334,
                    name="Subtipo antigo",
                    parent_type_external_id=1,
                    is_active=True,
                ),
                LegalOneTaskSubType(
                    external_id=335,
                    name="Subtipo removido",
                    parent_type_external_id=1,
                    is_active=True,
                ),
                TaskTemplate(
                    name="Template com subtipo existente",
                    category="Manifestacao das Partes",
                    office_external_id=61,
                    task_subtype_external_id=334,
                    responsible_user_external_id=10,
                    priority="Normal",
                    due_business_days=3,
                ),
            ]
        )
        db_session.commit()
        subtype_id_before = (
            db_session.query(LegalOneTaskSubType.id)
            .filter(LegalOneTaskSubType.external_id == 334)
            .one()[0]
        )

        class FakeLegalOneClient:
            def _paginated_catalog_loader(self, endpoint, params=None):
                if endpoint == "/UpdateAppointmentTaskTypes":
                    return [
                        {"id": 1, "name": "Tipo atualizado"},
                        {"id": 2, "name": "Tipo novo"},
                    ]
                if endpoint == "/UpdateAppointmentTaskSubtypes":
                    return [
                        {"id": 334, "name": "Subtipo atualizado", "parentTypeId": 1},
                        {"id": 999, "name": "Subtipo novo", "parentTypeId": 2},
                    ]
                return []

        service = MetadataSyncService(db_session)
        service.legal_one_client = FakeLegalOneClient()

        assert service.sync_task_types_and_subtypes() is True

        referenced_subtype = (
            db_session.query(LegalOneTaskSubType)
            .filter(LegalOneTaskSubType.external_id == 334)
            .one()
        )
        assert referenced_subtype.id == subtype_id_before
        assert referenced_subtype.name == "Subtipo atualizado"
        assert referenced_subtype.is_active is True

        template = (
            db_session.query(TaskTemplate)
            .filter(TaskTemplate.task_subtype_external_id == 334)
            .one()
        )
        assert template.task_subtype.external_id == 334

        removed_subtype = (
            db_session.query(LegalOneTaskSubType)
            .filter(LegalOneTaskSubType.external_id == 335)
            .one()
        )
        assert removed_subtype.is_active is False
        assert (
            db_session.query(LegalOneTaskType)
            .filter(LegalOneTaskType.external_id == 3)
            .one()
            .is_active
            is False
        )
        assert (
            db_session.query(LegalOneTaskSubType)
            .filter(LegalOneTaskSubType.external_id == 999)
            .count()
            == 1
        )
    finally:
        db_session.close()
        engine.dispose()

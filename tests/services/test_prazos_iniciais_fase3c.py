"""
Testes da Fase 3c — `natureza_processo` e `produto`.

Cobrem:

1. Schema — `natureza_processo` roteia `blocos_aplicaveis()`:
   * AGRAVO_INSTRUMENTO → só `contrarrazoes` conta (os demais blocos são
     ignorados mesmo se a IA devolver aplica=True por engano).
   * COMUM / JUIZADO / OUTRO → os 5 blocos clássicos + sem_determinacao;
     `contrarrazoes` é ignorado se vier aplica=True.

2. Template matching com `natureza_aplicavel`:
   * Template com natureza NULL casa em qualquer natureza.
   * Template com natureza=X só casa em intakes dessa natureza.
   * Sem override de natureza: genérico e específico coexistem no mesmo
     (tipo, subtipo).
   * Intake sem natureza (pré-3c): só genéricos (natureza NULL).
   * Combinação com office override E natureza diferente: buckets
     separados preservam ambos os templates.

3. Classifier service:
   * Persiste `natureza_processo` e `produto` no intake.
   * Passa `natureza_processo` pro `match_templates` (teste integrado
     via `apply_batch_results`).
   * Ramo AGRAVO_INSTRUMENTO → só gera sugestões pra CONTRARRAZOES.

4. Endpoints:
   * GET /enums retorna tipos, naturezas e produtos em ordem alfabética.
   * POST /templates aceita `natureza_aplicavel` válido, rejeita inválido.
   * 409 só dispara quando (tipo, subtipo, natureza, office) colide —
     mesma chave com natureza diferente pode coexistir.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any, Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from app.core.auth import get_current_user
from app.models.legal_one import (
    LegalOneOffice,
    LegalOneTaskSubType,
    LegalOneTaskType,
    LegalOneUser,
)
from app.models.prazo_inicial import (
    INTAKE_STATUS_AWAITING_TEMPLATE_CONFIG,
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_IN_CLASSIFICATION,
    INTAKE_STATUS_READY_TO_CLASSIFY,
    PIN_BATCH_STATUS_APPLIED,
    PrazoInicialBatch,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.classifier.prazos_iniciais_classifier import (
    PrazosIniciaisBatchClassifier,
)
from app.services.classifier.prazos_iniciais_schema import (
    NATUREZA_AGRAVO_INSTRUMENTO,
    NATUREZA_COMUM,
    NATUREZA_JUIZADO,
    NATUREZA_OUTRO,
    NATUREZAS_VALIDAS,
    PRODUTOS_VALIDOS,
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_CONTRARRAZOES,
    TIPO_PRAZO_LIMINAR,
    TIPOS_PRAZO_VALIDOS,
    PrazoInicialClassificationResponse,
)
from app.services.prazos_iniciais.template_matching_service import match_templates


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════


def _empty_response_dict(natureza: str = "COMUM", produto: str | None = None) -> dict:
    """Resposta com tudo zerado — inclui os campos da Fase 3c."""
    return {
        "produto": produto,
        "natureza_processo": natureza,
        "sem_determinacao": False,
        "contestar": {"aplica": False, "justificativa": ""},
        "liminar": {"aplica": False, "justificativa": ""},
        "manifestacao_avulsa": {"aplica": False, "justificativa": ""},
        "audiencia": {"aplica": False, "justificativa": ""},
        "julgamento": {"aplica": False, "justificativa": ""},
        "contrarrazoes": {"aplica": False, "justificativa": ""},
        "confianca_geral": "alta",
    }


def _wrap_in_batch_result(custom_id: str, response_payload: Any) -> dict:
    return {
        "custom_id": custom_id,
        "result": {
            "type": "succeeded",
            "message": {
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            response_payload
                            if isinstance(response_payload, str)
                            else json.dumps(response_payload)
                        ),
                    }
                ],
            },
        },
    }


def _persist_intake(
    db: Session,
    *,
    external_id: str = "ext-1",
    status: str = INTAKE_STATUS_READY_TO_CLASSIFY,
    office_id: int | None = None,
) -> PrazoInicialIntake:
    intake = PrazoInicialIntake(
        external_id=external_id,
        cnj_number="00000000000000000000",
        capa_json={"tribunal": "TJSP"},
        integra_json={"blocos": []},
        status=status,
        office_id=office_id,
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    return intake


def _mk_template(
    db: Session,
    *,
    tipo_prazo: str,
    subtipo: str | None = None,
    natureza_aplicavel: str | None = None,
    office_external_id: int | None = None,
    task_subtype_external_id: int = 9001,
    responsible_user_external_id: int = 8001,
    name: str | None = None,
    is_active: bool = True,
) -> PrazoInicialTaskTemplate:
    t = PrazoInicialTaskTemplate(
        name=name or f"tpl-{tipo_prazo}-{subtipo}-{natureza_aplicavel}-{office_external_id}",
        tipo_prazo=tipo_prazo,
        subtipo=subtipo,
        natureza_aplicavel=natureza_aplicavel,
        office_external_id=office_external_id,
        task_subtype_external_id=task_subtype_external_id,
        responsible_user_external_id=responsible_user_external_id,
        is_active=is_active,
    )
    db.add(t)
    db.flush()
    return t


# ═════════════════════════════════════════════════════════════════════
# Schema — routing por natureza_processo
# ═════════════════════════════════════════════════════════════════════


class TestSchemaNaturezaRouter:
    def test_default_natureza_is_comum_when_missing(self):
        """Schema sem `natureza_processo` cai no default defensivo COMUM."""
        payload = _empty_response_dict()
        # remove o campo pra simular IA esquecendo de emitir.
        del payload["natureza_processo"]
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        assert resp.natureza_processo == NATUREZA_COMUM

    def test_comum_uses_six_classic_blocks(self):
        payload = _empty_response_dict(natureza=NATUREZA_COMUM)
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }
        # contrarrazoes vindo True é ignorado no ramo COMUM.
        payload["contrarrazoes"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "ruído do modelo",
        }
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        tipos = {tipo for tipo, _ in resp.blocos_aplicaveis()}
        assert TIPO_PRAZO_CONTESTAR in tipos
        assert TIPO_PRAZO_CONTRARRAZOES not in tipos

    def test_agravo_only_contrarrazoes_counts(self):
        """No ramo Agravo, blocos clássicos vindo True são ignorados."""
        payload = _empty_response_dict(natureza=NATUREZA_AGRAVO_INSTRUMENTO)
        payload["contrarrazoes"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "recurso": "Agravo nº 123",
            "justificativa": "Intime-se para contrarrazões",
        }
        # ruído: contestar também vindo True.
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "ruído",
        }
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        pares = resp.blocos_aplicaveis()
        tipos = [tipo for tipo, _ in pares]
        assert tipos == [TIPO_PRAZO_CONTRARRAZOES]

    def test_agravo_sem_determinacao_emits_marker_only(self):
        # Fase 4 split: `sem_determinacao=True` legado é normalizado pra
        # `sem_prazo_em_aberto=True` no validator. Marker emitido vira
        # SEM_PRAZO_EM_ABERTO.
        payload = _empty_response_dict(natureza=NATUREZA_AGRAVO_INSTRUMENTO)
        payload["sem_determinacao"] = True
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        pares = resp.blocos_aplicaveis()
        assert len(pares) == 1
        tipo, _bloco = pares[0]
        assert tipo == "SEM_PRAZO_EM_ABERTO"


# ═════════════════════════════════════════════════════════════════════
# Template matching com natureza_aplicavel
# ═════════════════════════════════════════════════════════════════════


class TestMatchingByNatureza:
    def test_template_generico_casa_em_qualquer_natureza(self, db_session):
        t = _mk_template(db_session, tipo_prazo="CONTESTAR", natureza_aplicavel=None)
        db_session.commit()
        # COMUM.
        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_COMUM,
        )
        assert [x.id for x in r] == [t.id]
        # JUIZADO.
        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_JUIZADO,
        )
        assert [x.id for x in r] == [t.id]

    def test_template_especifico_nao_casa_em_outra_natureza(self, db_session):
        _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
        )
        db_session.commit()
        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_JUIZADO,
        )
        assert r == []

    def test_generico_e_especifico_coexistem_sem_override(self, db_session):
        """
        Diferente do office, não há override por natureza. Se existem
        `natureza=NULL` e `natureza=COMUM` para o mesmo (tipo,subtipo),
        AMBOS casam em intakes COMUM.
        """
        generico = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=None,
            name="generico",
        )
        especifico = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
            task_subtype_external_id=9002,
            name="comum",
        )
        db_session.commit()
        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_COMUM,
        )
        ids = {x.id for x in r}
        assert ids == {generico.id, especifico.id}

    def test_intake_sem_natureza_so_casa_genericos(self, db_session):
        generico = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=None,
        )
        _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
            task_subtype_external_id=9002,
        )
        db_session.commit()
        # intake pré-3c: natureza_processo=None.
        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            natureza_processo=None,
        )
        assert [x.id for x in r] == [generico.id]

    def test_office_override_acontece_dentro_da_mesma_natureza(self, db_session):
        """
        Office override opera POR bucket (tipo, subtipo, natureza). Então
        específico de office na natureza X NÃO descarta global na
        natureza Y.
        """
        # Bucket (CONTESTAR, NULL, COMUM): específico office=42 + global NULL.
        t_comum_sp = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
            office_external_id=42,
            task_subtype_external_id=1001,
            name="comum-sp",
        )
        _mk_template(  # mesma natureza + office=NULL → descartado.
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
            office_external_id=None,
            task_subtype_external_id=1002,
            name="comum-global",
        )
        # Bucket (CONTESTAR, NULL, NULL): só global → preservado.
        t_generico = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=None,
            office_external_id=None,
            task_subtype_external_id=1003,
            name="generico",
        )
        db_session.commit()

        r = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
            natureza_processo=NATUREZA_COMUM,
        )
        ids = {x.id for x in r}
        # Esperado: específico-comum-sp + genérico (natureza=NULL). O
        # comum-global é dropado pelo office override dentro do bucket
        # (CONTESTAR, NULL, COMUM).
        assert ids == {t_comum_sp.id, t_generico.id}

    def test_contrarrazoes_casa_por_natureza(self, db_session):
        """CONTRARRAZOES (ramo AGRAVO) tem template específico por natureza."""
        t = _mk_template(
            db_session,
            tipo_prazo="CONTRARRAZOES",
            natureza_aplicavel=NATUREZA_AGRAVO_INSTRUMENTO,
        )
        db_session.commit()
        r = match_templates(
            db_session,
            tipo_prazo="CONTRARRAZOES",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_AGRAVO_INSTRUMENTO,
        )
        assert [x.id for x in r] == [t.id]
        # Não deve casar em COMUM.
        r = match_templates(
            db_session,
            tipo_prazo="CONTRARRAZOES",
            subtipo=None,
            office_external_id=None,
            natureza_processo=NATUREZA_COMUM,
        )
        assert r == []


# ═════════════════════════════════════════════════════════════════════
# Classifier — persistência e branching
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_ai_client():
    client = MagicMock(spec=AnthropicClassifierClient)
    client.model = "claude-sonnet-4-6"
    client.max_tokens = 4096
    return client


@pytest.fixture
def classifier_factory(fake_ai_client):
    def _make(db: Session) -> PrazosIniciaisBatchClassifier:
        return PrazosIniciaisBatchClassifier(db=db, ai_client=fake_ai_client)
    return _make


class TestClassifierPersistsNaturezaProduto:
    def test_apply_batch_persists_natureza_and_produto(
        self, db_session, classifier_factory, fake_ai_client
    ):
        intake = _persist_intake(db_session, external_id="3c-persist")
        intake.status = INTAKE_STATUS_IN_CLASSIFICATION
        db_session.commit()

        batch = PrazoInicialBatch(
            anthropic_batch_id="msgbatch_3c_persist",
            status="PRONTO",
            total_records=1,
            intake_ids=[intake.id],
            results_url="https://example.com/results",
            model_used="claude-sonnet-4-6",
        )
        db_session.add(batch)
        db_session.commit()

        payload = _empty_response_dict(
            natureza=NATUREZA_JUIZADO, produto="NEGATIVACAO_INDEVIDA"
        )
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }

        async def _fake_get(_url):
            return [_wrap_in_batch_result(f"intake-{intake.id}", payload)]

        fake_ai_client.get_batch_results = _fake_get
        classifier = classifier_factory(db_session)

        summary = asyncio.run(classifier.apply_batch_results(batch))
        assert summary["succeeded"] == 1

        db_session.refresh(intake)
        assert intake.natureza_processo == NATUREZA_JUIZADO
        assert intake.produto == "NEGATIVACAO_INDEVIDA"

    def test_agravo_only_generates_contrarrazoes_sugestoes(
        self, db_session, classifier_factory, fake_ai_client
    ):
        intake = _persist_intake(db_session, external_id="3c-agravo", office_id=42)
        intake.status = INTAKE_STATUS_IN_CLASSIFICATION
        db_session.commit()

        # Cadastra template CONTRARRAZOES genérico pra o intake casar.
        _mk_template(
            db_session,
            tipo_prazo="CONTRARRAZOES",
            natureza_aplicavel=NATUREZA_AGRAVO_INSTRUMENTO,
        )
        db_session.commit()

        batch = PrazoInicialBatch(
            anthropic_batch_id="msgbatch_3c_agravo",
            status="PRONTO",
            total_records=1,
            intake_ids=[intake.id],
            results_url="https://example.com/results",
            model_used="claude-sonnet-4-6",
        )
        db_session.add(batch)
        db_session.commit()

        # Modelo erroneamente marca contestar=True também — deve ser filtrado.
        payload = _empty_response_dict(natureza=NATUREZA_AGRAVO_INSTRUMENTO)
        payload["contrarrazoes"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "recurso": "Agravo nº 123",
            "justificativa": "Intime-se para contrarrazões",
        }
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "ruído",
        }

        async def _fake_get(_url):
            return [_wrap_in_batch_result(f"intake-{intake.id}", payload)]

        fake_ai_client.get_batch_results = _fake_get
        classifier = classifier_factory(db_session)

        summary = asyncio.run(classifier.apply_batch_results(batch))
        assert summary["succeeded"] == 1

        sugestoes = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .all()
        )
        # Só CONTRARRAZOES, apesar do ruído em `contestar`.
        assert [s.tipo_prazo for s in sugestoes] == [TIPO_PRAZO_CONTRARRAZOES]
        s = sugestoes[0]
        assert s.payload_proposto.get("recurso") == "Agravo nº 123"

        db_session.refresh(intake)
        # Template casou → intake vai pra CLASSIFICADO, não
        # AGUARDANDO_CONFIG_TEMPLATE.
        assert intake.status == INTAKE_STATUS_CLASSIFIED

    def test_classifier_passes_natureza_into_matching(
        self, db_session, classifier_factory, fake_ai_client
    ):
        """
        Intake JUIZADO só deve casar templates com
        natureza_aplicavel=JUIZADO ou NULL; template COMUM deve ser ignorado.
        """
        intake = _persist_intake(db_session, external_id="3c-juizado", office_id=42)
        intake.status = INTAKE_STATUS_IN_CLASSIFICATION
        db_session.commit()

        t_juizado = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_JUIZADO,
            task_subtype_external_id=1101,
            name="juizado-contestar",
        )
        _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            natureza_aplicavel=NATUREZA_COMUM,
            task_subtype_external_id=1102,
            name="comum-contestar",
        )
        db_session.commit()

        batch = PrazoInicialBatch(
            anthropic_batch_id="msgbatch_3c_juiz",
            status="PRONTO",
            total_records=1,
            intake_ids=[intake.id],
            results_url="https://example.com/results",
            model_used="claude-sonnet-4-6",
        )
        db_session.add(batch)
        db_session.commit()

        payload = _empty_response_dict(natureza=NATUREZA_JUIZADO)
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se (juizado)",
        }

        async def _fake_get(_url):
            return [_wrap_in_batch_result(f"intake-{intake.id}", payload)]

        fake_ai_client.get_batch_results = _fake_get
        classifier = classifier_factory(db_session)

        asyncio.run(classifier.apply_batch_results(batch))
        sugestoes = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .all()
        )
        # Um único template casou (o JUIZADO). O COMUM foi filtrado.
        assert len(sugestoes) == 1
        assert sugestoes[0].task_subtype_id == t_juizado.task_subtype_external_id


# ═════════════════════════════════════════════════════════════════════
# Endpoints — /enums e CRUD de templates com natureza_aplicavel
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def admin_user(db_session: Session) -> LegalOneUser:
    user = LegalOneUser(
        external_id=424242,
        name="Admin 3c",
        email="admin3c@example.com",
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


@pytest.fixture
def legal_one_refs(db_session: Session) -> dict:
    tt = LegalOneTaskType(external_id=700, name="Contestar 3c", is_active=True)
    db_session.add(tt)
    db_session.flush()
    office = LegalOneOffice(
        external_id=77, name="SP-3c", path="MDR > SP-3c", is_active=True
    )
    subtype = LegalOneTaskSubType(
        external_id=9077,
        name="Abrir prazo 3c",
        is_active=True,
        parent_type_external_id=700,
    )
    user = LegalOneUser(
        external_id=8077,
        name="Resp 3c",
        email="resp3c@example.com",
        is_active=True,
    )
    db_session.add_all([office, subtype, user])
    db_session.commit()
    return {
        "office_external_id": office.external_id,
        "task_subtype_external_id": subtype.external_id,
        "responsible_user_external_id": user.external_id,
    }


def _template_body(refs: dict, **override) -> dict:
    body = {
        "name": "tpl",
        "tipo_prazo": "CONTESTAR",
        "subtipo": None,
        "natureza_aplicavel": None,
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


class TestEnumsEndpoint:
    def test_returns_all_enum_lists(self, auth_client):
        r = auth_client.get("/api/v1/prazos-iniciais/enums")
        assert r.status_code == 200, r.text
        data = r.json()
        assert set(data["tipos_prazo"]) == set(TIPOS_PRAZO_VALIDOS)
        assert set(data["naturezas"]) == set(NATUREZAS_VALIDAS)
        assert set(data["produtos"]) == set(PRODUTOS_VALIDOS)
        # Sanidade dos subtipos e auxiliares.
        assert "conciliacao" in data["subtipos_audiencia"]
        assert "merito" in data["subtipos_julgamento"]
        assert "Normal" in data["priorities"]
        assert "data_base" in data["due_date_references"]

    def test_lists_are_sorted(self, auth_client):
        r = auth_client.get("/api/v1/prazos-iniciais/enums")
        data = r.json()
        assert data["tipos_prazo"] == sorted(data["tipos_prazo"])
        assert data["naturezas"] == sorted(data["naturezas"])
        assert data["produtos"] == sorted(data["produtos"])


class TestTemplatesCrudWithNatureza:
    def test_create_with_valid_natureza(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(legal_one_refs, natureza_aplicavel="COMUM"),
        )
        assert r.status_code == 201, r.text
        assert r.json()["natureza_aplicavel"] == "COMUM"

    def test_rejects_invalid_natureza(self, auth_client, legal_one_refs):
        r = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(legal_one_refs, natureza_aplicavel="INVALIDA"),
        )
        assert r.status_code == 422
        assert "natureza_aplicavel inválida" in r.json()["detail"]

    def test_same_tipo_office_different_naturezas_coexist(
        self, auth_client, legal_one_refs
    ):
        """
        (CONTESTAR, NULL, COMUM, NULL) e (CONTESTAR, NULL, JUIZADO, NULL)
        são linhas DIFERENTES na UNIQUE — ambas podem existir.
        """
        r1 = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="comum", natureza_aplicavel="COMUM"
            ),
        )
        r2 = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="juizado", natureza_aplicavel="JUIZADO"
            ),
        )
        assert r1.status_code == 201, r1.text
        assert r2.status_code == 201, r2.text

    def test_same_key_including_natureza_is_allowed(
        self, auth_client, legal_one_refs
    ):
        """
        Pós-pin005: duas entradas com mesma (tipo, subtipo, natureza, office)
        são permitidas — cada template vira uma sugestão separada no HITL.
        """
        body = _template_body(
            legal_one_refs, name="dup", natureza_aplicavel="COMUM"
        )
        r1 = auth_client.post("/api/v1/prazos-iniciais/templates", json=body)
        r2 = auth_client.post("/api/v1/prazos-iniciais/templates", json=body)
        assert r1.status_code == 201
        assert r2.status_code == 201, r2.text
        assert r1.json()["id"] != r2.json()["id"]

    def test_filter_list_by_natureza(self, auth_client, legal_one_refs):
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="comum", natureza_aplicavel="COMUM"
            ),
        )
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="juizado", natureza_aplicavel="JUIZADO"
            ),
        )
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="generico", natureza_aplicavel=None
            ),
        )
        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates",
            params={"natureza_aplicavel": "COMUM"},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "comum"

        # '' filtra genéricos (natureza NULL).
        r = auth_client.get(
            "/api/v1/prazos-iniciais/templates",
            params={"natureza_aplicavel": ""},
        )
        data = r.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "generico"

    def test_patch_can_change_natureza(self, auth_client, legal_one_refs):
        created = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, natureza_aplicavel=None, name="primeiro"
            ),
        ).json()
        r = auth_client.patch(
            f"/api/v1/prazos-iniciais/templates/{created['id']}",
            json={"natureza_aplicavel": "AGRAVO_INSTRUMENTO"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["natureza_aplicavel"] == "AGRAVO_INSTRUMENTO"

    def test_patch_can_share_full_key(self, auth_client, legal_one_refs):
        """
        Pós-pin005: PATCH que faz A coincidir com B na chave (tipo, subtipo,
        natureza, office) é aceito. Dois templates passam a gerar duas
        sugestões no HITL.
        """
        a = auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="a", natureza_aplicavel="COMUM"
            ),
        ).json()
        auth_client.post(
            "/api/v1/prazos-iniciais/templates",
            json=_template_body(
                legal_one_refs, name="b", natureza_aplicavel="JUIZADO"
            ),
        )
        r = auth_client.patch(
            f"/api/v1/prazos-iniciais/templates/{a['id']}",
            json={"natureza_aplicavel": "JUIZADO"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["natureza_aplicavel"] == "JUIZADO"

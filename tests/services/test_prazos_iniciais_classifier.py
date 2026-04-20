"""
Testes da Fase 3a do fluxo "Agendar Prazos Iniciais".

Cobrem três camadas, sem chamadas reais à Anthropic:

* Schema Pydantic (`PrazoInicialClassificationResponse`) — validação,
  enforcement de `sem_determinacao` vs blocos aplicáveis e helper
  `blocos_aplicaveis()`.
* Calculadora de prazo — dias úteis com feriados nacionais (móveis e
  fixos), dias corridos com prorrogação de vencimento.
* Classifier — parsing de JSON cru (vindo do batch), materialização de N
  sugestões por intake e tratamento de erro quando o JSON é inválido.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.models.prazo_inicial import (
    INTAKE_STATUS_CLASSIFICATION_ERROR,
    INTAKE_STATUS_CLASSIFIED,
    INTAKE_STATUS_IN_CLASSIFICATION,
    INTAKE_STATUS_READY_TO_CLASSIFY,
    PIN_BATCH_STATUS_APPLIED,
    PrazoInicialBatch,
    PrazoInicialIntake,
    PrazoInicialSugestao,
)
from app.services.classifier.ai_client import AnthropicClassifierClient
from app.services.classifier.prazos_iniciais_classifier import (
    PrazosIniciaisBatchClassifier,
)
from app.services.classifier.prazos_iniciais_schema import (
    TIPO_PRAZO_AUDIENCIA,
    TIPO_PRAZO_CONTESTAR,
    TIPO_PRAZO_JULGAMENTO,
    TIPO_PRAZO_LIMINAR,
    TIPO_PRAZO_MANIFESTACAO_AVULSA,
    TIPO_PRAZO_SEM_DETERMINACAO,
    PrazoInicialClassificationResponse,
)
from app.services.prazos_iniciais.prazo_calculator import (
    calcular_prazo_final,
    calcular_prazo_seguro,
    feriados_nacionais,
    is_business_day,
    proximo_dia_util,
)


# ═════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_ai_client():
    """
    Stub do AnthropicClassifierClient que evita validar a API key e nunca
    faz chamada de rede de fato. Os testes que precisarem de comportamento
    específico monkey-patcham métodos individuais.
    """
    client = MagicMock(spec=AnthropicClassifierClient)
    client.model = "claude-sonnet-4-6"
    client.max_tokens = 4096
    return client


@pytest.fixture
def classifier_factory(fake_ai_client):
    """Cria classificadores com o stub injetado."""
    def _make(db) -> PrazosIniciaisBatchClassifier:
        return PrazosIniciaisBatchClassifier(db=db, ai_client=fake_ai_client)
    return _make


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════


def _empty_response_dict() -> dict:
    """Resposta com tudo zerado — base para os testes de schema/classifier."""
    return {
        "sem_determinacao": False,
        "contestar": {"aplica": False, "justificativa": ""},
        "liminar": {"aplica": False, "justificativa": ""},
        "manifestacao_avulsa": {"aplica": False, "justificativa": ""},
        "audiencia": {"aplica": False, "justificativa": ""},
        "julgamento": {"aplica": False, "justificativa": ""},
        "confianca_geral": "alta",
    }


def _wrap_in_batch_result(custom_id: str, response_payload: Any) -> dict:
    """Mimetiza o formato JSONL devolvido pela Messages Batches API."""
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
    db, *, external_id: str = "ext-1", status: str = INTAKE_STATUS_READY_TO_CLASSIFY
) -> PrazoInicialIntake:
    intake = PrazoInicialIntake(
        external_id=external_id,
        cnj_number="00000000000000000000",
        capa_json={"tribunal": "TJSP"},
        integra_json={"blocos": []},
        status=status,
    )
    db.add(intake)
    db.commit()
    db.refresh(intake)
    return intake


# ═════════════════════════════════════════════════════════════════════
# Schema
# ═════════════════════════════════════════════════════════════════════


class TestSchema:
    def test_minimal_valid_response_parses(self):
        resp = PrazoInicialClassificationResponse.model_validate(_empty_response_dict())
        assert resp.sem_determinacao is False
        assert resp.contestar.aplica is False
        assert resp.confianca_geral == "alta"

    def test_clear_fields_when_aplica_false(self):
        """Bloco com aplica=False ignora prazo_dias/prazo_tipo/data_base."""
        payload = _empty_response_dict()
        payload["contestar"] = {
            "aplica": False,
            "prazo_dias": 30,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "",
        }
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        assert resp.contestar.prazo_dias is None
        assert resp.contestar.prazo_tipo is None
        assert resp.contestar.data_base is None

    def test_sem_determinacao_conflict_resolves_to_blocos(self):
        """Conflito: sem_determinacao=true + contestar.aplica=true → vence o bloco."""
        payload = _empty_response_dict()
        payload["sem_determinacao"] = True
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        assert resp.sem_determinacao is False
        assert resp.contestar.aplica is True

    def test_blocos_aplicaveis_returns_only_active(self):
        payload = _empty_response_dict()
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }
        payload["audiencia"] = {
            "aplica": True,
            "data": "2026-05-12",
            "hora": "14:00",
            "tipo": "conciliacao",
            "link": None,
            "endereco": None,
            "justificativa": "Audiência de conciliação",
        }
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        pares = resp.blocos_aplicaveis()
        tipos = {tipo for tipo, _ in pares}
        assert tipos == {TIPO_PRAZO_CONTESTAR, TIPO_PRAZO_AUDIENCIA}

    def test_blocos_aplicaveis_emits_sem_determinacao_when_no_blocks(self):
        payload = _empty_response_dict()
        payload["sem_determinacao"] = True
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        pares = resp.blocos_aplicaveis()
        assert len(pares) == 1
        assert pares[0][0] == TIPO_PRAZO_SEM_DETERMINACAO

    def test_confianca_normalized_with_accent(self):
        payload = _empty_response_dict()
        payload["confianca_geral"] = "Média"
        resp = PrazoInicialClassificationResponse.model_validate(payload)
        assert resp.confianca_geral == "media"


# ═════════════════════════════════════════════════════════════════════
# Calculadora de prazo
# ═════════════════════════════════════════════════════════════════════


class TestPrazoCalculator:
    def test_holidays_2026_includes_fixed_and_movable(self):
        """Páscoa 2026 = 5/abr; sexta-feira santa = 3/abr; corpus christi = 4/jun."""
        feriados = feriados_nacionais(2026)
        assert date(2026, 1, 1) in feriados   # Confraternização
        assert date(2026, 4, 21) in feriados  # Tiradentes
        assert date(2026, 5, 1) in feriados   # Trabalho
        assert date(2026, 11, 20) in feriados  # Consciência Negra
        assert date(2026, 12, 25) in feriados  # Natal
        # Móveis em torno da Páscoa 2026 (5/abr).
        assert date(2026, 4, 3) in feriados   # Sexta-feira da Paixão
        assert date(2026, 6, 4) in feriados   # Corpus Christi
        # Carnaval 2026 = 16/17 fev.
        assert date(2026, 2, 16) in feriados
        assert date(2026, 2, 17) in feriados

    def test_is_business_day_weekend(self):
        # 18/04/2026 = sábado.
        assert is_business_day(date(2026, 4, 18)) is False
        assert is_business_day(date(2026, 4, 19)) is False
        # 20/04/2026 = segunda.
        assert is_business_day(date(2026, 4, 20)) is True

    def test_proximo_dia_util_skips_holiday_and_weekend(self):
        # Tiradentes (terça 21/04/2026) → próximo útil é 22/04 (quarta).
        assert proximo_dia_util(date(2026, 4, 21)) == date(2026, 4, 22)
        # Sexta-feira santa (3/abr/2026) → próximo útil é 6/abr (segunda).
        assert proximo_dia_util(date(2026, 4, 3)) == date(2026, 4, 6)

    def test_corrido_simple(self):
        # 22/04 + 5 corridos = 27/04 (segunda).
        assert calcular_prazo_final(date(2026, 4, 22), 5, "corrido") == date(
            2026, 4, 27
        )

    def test_corrido_falls_on_weekend_postpones_to_business_day(self):
        # 17/04/2026 (sex) + 1 corrido = 18/04 (sáb) → prorroga pra 20/04 (seg).
        assert calcular_prazo_final(date(2026, 4, 17), 1, "corrido") == date(
            2026, 4, 20
        )

    def test_util_15_days_from_a_monday(self):
        """
        Termo inicial: segunda 23/03/2026 (intimação).
        Dia 1 da contagem: terça 24/03 (primeiro dia útil seguinte — CPC 224 §3).
        Contando 15 dias úteis a partir de 24/03:
          24,25,26,27 (mar) → 4
          30,31 (mar) → 6
          01,02 (abr) → 8
          *03/04 sexta-feira santa — pula*
          06,07,08,09,10 (abr) → 13
          13,14 (abr) → 15
        Vencimento: terça 14/04/2026.
        """
        result = calcular_prazo_final(date(2026, 3, 23), 15, "util")
        assert result == date(2026, 4, 14)

    def test_util_skips_weekend_at_start(self):
        # Termo inicial: sexta 17/04 → primeiro dia útil é segunda 20/04.
        # 5 dias úteis: 20, 22 (21 é feriado), 23, 24, 27 → vence 27/04.
        result = calcular_prazo_final(date(2026, 4, 17), 5, "util")
        assert result == date(2026, 4, 27)

    def test_calcular_prazo_seguro_with_missing_inputs(self):
        # Publicação qua 22/04 → dia 1 = qui 23/04.
        # 15 dias úteis pulando feriado de 1º/05 → vence qui 14/05/2026.
        assert calcular_prazo_seguro(None, 15, "util") is None
        assert calcular_prazo_seguro(date(2026, 4, 22), None, "util") is None
        assert calcular_prazo_seguro(date(2026, 4, 22), 15, "invalido") is None
        assert calcular_prazo_seguro(date(2026, 4, 22), 15, "util") == date(
            2026, 5, 14
        )


# ═════════════════════════════════════════════════════════════════════
# Classifier (parsing + materialização)
# ═════════════════════════════════════════════════════════════════════


class TestExtractResponse:
    def test_succeeded_with_clean_json(self):
        item = _wrap_in_batch_result("intake-1", _empty_response_dict())
        resp = PrazosIniciaisBatchClassifier._extract_response(item)
        assert isinstance(resp, PrazoInicialClassificationResponse)
        assert resp.sem_determinacao is False

    def test_succeeded_with_markdown_fence(self):
        wrapped = "```json\n" + json.dumps(_empty_response_dict()) + "\n```"
        item = _wrap_in_batch_result("intake-1", wrapped)
        resp = PrazosIniciaisBatchClassifier._extract_response(item)
        assert resp.confianca_geral == "alta"

    def test_errored_item_raises(self):
        item = {
            "custom_id": "intake-1",
            "result": {"type": "errored", "error": {"message": "rate limit"}},
        }
        with pytest.raises(Exception, match="rate limit"):
            PrazosIniciaisBatchClassifier._extract_response(item)

    def test_invalid_json_raises(self):
        item = _wrap_in_batch_result("intake-1", "not json {")
        with pytest.raises(Exception, match="JSON"):
            PrazosIniciaisBatchClassifier._extract_response(item)

    def test_schema_violation_raises(self):
        # Faltando o bloco obrigatório `julgamento`.
        bad = _empty_response_dict()
        del bad["julgamento"]
        item = _wrap_in_batch_result("intake-1", bad)
        with pytest.raises(Exception, match="schema"):
            PrazosIniciaisBatchClassifier._extract_response(item)


class TestMaterializeSugestoes:
    def test_single_block_creates_one_sugestao_with_calculated_date(
        self, db_session, classifier_factory
    ):
        intake = _persist_intake(db_session)
        classifier = classifier_factory(db_session)

        payload = _empty_response_dict()
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se a parte requerida.",
        }
        response = PrazoInicialClassificationResponse.model_validate(payload)

        criadas = classifier._materialize_sugestoes(intake, response)
        db_session.commit()

        assert criadas == 1
        sugestoes = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .all()
        )
        assert len(sugestoes) == 1
        s = sugestoes[0]
        assert s.tipo_prazo == TIPO_PRAZO_CONTESTAR
        assert s.prazo_dias == 15
        assert s.prazo_tipo == "util"
        assert s.data_base == date(2026, 4, 22)
        # Verifica que a calculadora foi acionada.
        assert s.data_final_calculada is not None
        assert s.data_final_calculada > s.data_base
        assert s.task_type_id is None  # ainda sem taxonomia
        assert s.task_subtype_id is None
        assert s.confianca == "alta"

    def test_multiple_applicable_blocks_create_multiple_sugestoes(
        self, db_session, classifier_factory
    ):
        intake = _persist_intake(db_session, external_id="ext-multi")
        classifier = classifier_factory(db_session)

        payload = _empty_response_dict()
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }
        payload["liminar"] = {
            "aplica": True,
            "prazo_dias": 5,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "objeto": "Suspensão de cobrança",
            "justificativa": "Tutela deferida",
        }
        payload["audiencia"] = {
            "aplica": True,
            "data": "2026-05-12",
            "hora": "14:00",
            "tipo": "conciliacao",
            "link": "https://meet.google.com/abc",
            "endereco": None,
            "justificativa": "Designada",
        }
        response = PrazoInicialClassificationResponse.model_validate(payload)
        classifier._materialize_sugestoes(intake, response)
        db_session.commit()

        sugestoes = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .order_by(PrazoInicialSugestao.id)
            .all()
        )
        tipos = [s.tipo_prazo for s in sugestoes]
        assert tipos == [TIPO_PRAZO_CONTESTAR, TIPO_PRAZO_LIMINAR, TIPO_PRAZO_AUDIENCIA]

        liminar = next(s for s in sugestoes if s.tipo_prazo == TIPO_PRAZO_LIMINAR)
        assert liminar.subtipo == "Suspensão de cobrança"
        assert liminar.payload_proposto["objeto"] == "Suspensão de cobrança"

        audiencia = next(s for s in sugestoes if s.tipo_prazo == TIPO_PRAZO_AUDIENCIA)
        assert audiencia.audiencia_data == date(2026, 5, 12)
        assert audiencia.audiencia_hora == time(14, 0)
        assert audiencia.audiencia_link == "https://meet.google.com/abc"
        assert audiencia.subtipo == "conciliacao"

    def test_julgamento_persists_data_in_data_base(
        self, db_session, classifier_factory
    ):
        intake = _persist_intake(db_session, external_id="ext-julg")
        classifier = classifier_factory(db_session)

        payload = _empty_response_dict()
        payload["julgamento"] = {
            "aplica": True,
            "tipo": "merito",
            "data": "2026-03-30",
            "justificativa": "Improcedente",
        }
        response = PrazoInicialClassificationResponse.model_validate(payload)
        classifier._materialize_sugestoes(intake, response)
        db_session.commit()

        sugestao = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .one()
        )
        assert sugestao.tipo_prazo == TIPO_PRAZO_JULGAMENTO
        assert sugestao.subtipo == "merito"
        assert sugestao.data_base == date(2026, 3, 30)

    def test_sem_determinacao_creates_single_marker_sugestao(
        self, db_session, classifier_factory
    ):
        intake = _persist_intake(db_session, external_id="ext-sem")
        classifier = classifier_factory(db_session)

        payload = _empty_response_dict()
        payload["sem_determinacao"] = True
        response = PrazoInicialClassificationResponse.model_validate(payload)
        classifier._materialize_sugestoes(intake, response)
        db_session.commit()

        sugestoes = (
            db_session.query(PrazoInicialSugestao)
            .filter(PrazoInicialSugestao.intake_id == intake.id)
            .all()
        )
        assert len(sugestoes) == 1
        s = sugestoes[0]
        assert s.tipo_prazo == TIPO_PRAZO_SEM_DETERMINACAO
        assert s.payload_proposto["sem_determinacao"] is True


class TestApplyBatchResults:
    """
    Os métodos do classifier são `async`. Como o projeto não usa
    pytest-asyncio, executamos as coroutines via `asyncio.run` direto no
    teste (mantém a função de teste síncrona).
    """

    def test_apply_marks_intake_classified_and_creates_sugestoes(
        self, db_session, classifier_factory, fake_ai_client
    ):
        intake = _persist_intake(db_session, external_id="apply-ok")
        intake.status = INTAKE_STATUS_IN_CLASSIFICATION
        db_session.commit()

        batch = PrazoInicialBatch(
            anthropic_batch_id="msgbatch_test",
            status="PRONTO",
            total_records=1,
            intake_ids=[intake.id],
            results_url="https://example.com/results",
            model_used="claude-sonnet-4-6",
        )
        db_session.add(batch)
        db_session.commit()

        classifier = classifier_factory(db_session)

        payload = _empty_response_dict()
        payload["contestar"] = {
            "aplica": True,
            "prazo_dias": 15,
            "prazo_tipo": "util",
            "data_base": "2026-04-22",
            "justificativa": "Cite-se",
        }
        fake_results = [_wrap_in_batch_result(f"intake-{intake.id}", payload)]

        async def _fake_get(_url):
            return fake_results

        fake_ai_client.get_batch_results = _fake_get

        summary = asyncio.run(classifier.apply_batch_results(batch))

        assert summary["succeeded"] == 1
        assert summary["failed"] == 0
        assert summary["total_sugestoes"] == 1

        db_session.refresh(intake)
        db_session.refresh(batch)
        assert intake.status == INTAKE_STATUS_CLASSIFIED
        assert batch.status == PIN_BATCH_STATUS_APPLIED

    def test_apply_marks_intake_error_when_json_invalid(
        self, db_session, classifier_factory, fake_ai_client
    ):
        intake = _persist_intake(db_session, external_id="apply-err")
        intake.status = INTAKE_STATUS_IN_CLASSIFICATION
        db_session.commit()

        batch = PrazoInicialBatch(
            anthropic_batch_id="msgbatch_err",
            status="PRONTO",
            total_records=1,
            intake_ids=[intake.id],
            results_url="https://example.com/results",
            model_used="claude-sonnet-4-6",
        )
        db_session.add(batch)
        db_session.commit()

        classifier = classifier_factory(db_session)
        fake_results = [
            _wrap_in_batch_result(f"intake-{intake.id}", "completely broken {")
        ]

        async def _fake_get(_url):
            return fake_results

        fake_ai_client.get_batch_results = _fake_get

        summary = asyncio.run(classifier.apply_batch_results(batch))
        assert summary["succeeded"] == 0
        assert summary["failed"] == 1

        db_session.refresh(intake)
        assert intake.status == INTAKE_STATUS_CLASSIFICATION_ERROR
        assert intake.error_message
        assert "JSON" in intake.error_message

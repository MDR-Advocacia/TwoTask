"""
Testes do `template_matching_service` do fluxo "Agendar Prazos Iniciais".

Cobrem as quatro regras de casamento fixadas com o usuário em 2026-04-20:

1. `is_active=True` sempre é exigido.
2. `tipo_prazo` casa por valor exato.
3. `subtipo`:
   - Com subtipo no intake (AUDIENCIA/JULGAMENTO): casa exato OU template
     com subtipo=NULL (wildcard).
   - Sem subtipo: só templates com subtipo=NULL.
4. `office_external_id`: específico (office=X) SOBREPÕE global (office=NULL)
   na MESMA combinação (tipo_prazo, subtipo). Combinações diferentes
   coexistem sem interferir.
"""

from __future__ import annotations

import pytest

from app.models.prazo_inicial_task_template import PrazoInicialTaskTemplate
from app.services.prazos_iniciais.template_matching_service import (
    _apply_specific_over_global,
    match_templates,
)


# ─── Helpers ─────────────────────────────────────────────────────────


def _mk_template(
    db,
    *,
    tipo_prazo: str,
    subtipo: str | None = None,
    office_external_id: int | None = None,
    task_subtype_external_id: int = 9001,
    responsible_user_external_id: int = 8001,
    name: str | None = None,
    is_active: bool = True,
    priority: str = "Normal",
    due_business_days: int = 3,
    due_date_reference: str = "data_base",
) -> PrazoInicialTaskTemplate:
    """
    Cria e persiste um template. Os defaults de FK são valores arbitrários
    (9001 / 8001) — os testes de matching não dependem da integridade
    referencial no L1, só da presença dos registros na tabela.
    """
    t = PrazoInicialTaskTemplate(
        name=name or f"tpl-{tipo_prazo}-{subtipo}-{office_external_id}",
        tipo_prazo=tipo_prazo,
        subtipo=subtipo,
        office_external_id=office_external_id,
        task_subtype_external_id=task_subtype_external_id,
        responsible_user_external_id=responsible_user_external_id,
        priority=priority,
        due_business_days=due_business_days,
        due_date_reference=due_date_reference,
        is_active=is_active,
    )
    db.add(t)
    db.flush()
    return t


# ─── Testes ─────────────────────────────────────────────────────────


class TestMatchTemplates:
    def test_returns_empty_when_no_templates_configured(self, db_session):
        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        assert result == []

    def test_inactive_templates_are_ignored(self, db_session):
        _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
            is_active=False,
        )
        db_session.commit()
        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        assert result == []

    def test_exact_tipo_prazo_match(self, db_session):
        a = _mk_template(db_session, tipo_prazo="CONTESTAR")
        _mk_template(db_session, tipo_prazo="LIMINAR")
        db_session.commit()
        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        assert [t.id for t in result] == [a.id]

    def test_subtipo_exact_and_wildcard_both_apply_when_intake_has_subtipo(
        self, db_session
    ):
        """
        Para AUDIENCIA/conciliacao: devem casar templates com
        subtipo='conciliacao' E templates com subtipo=NULL (wildcard).
        """
        exact = _mk_template(
            db_session, tipo_prazo="AUDIENCIA", subtipo="conciliacao"
        )
        wildcard = _mk_template(db_session, tipo_prazo="AUDIENCIA", subtipo=None)
        # outra audiência (instrucao) não deve casar.
        _mk_template(db_session, tipo_prazo="AUDIENCIA", subtipo="instrucao")
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="AUDIENCIA",
            subtipo="conciliacao",
            office_external_id=None,
        )
        ids = {t.id for t in result}
        assert ids == {exact.id, wildcard.id}

    def test_no_subtipo_intake_only_matches_null_templates(self, db_session):
        """
        Para CONTESTAR (sem subtipo no intake): só templates com
        subtipo=NULL. Template com subtipo='algo' não deve casar.
        """
        ok = _mk_template(db_session, tipo_prazo="CONTESTAR", subtipo=None)
        _mk_template(db_session, tipo_prazo="CONTESTAR", subtipo="nunca_casa")
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        assert [t.id for t in result] == [ok.id]

    def test_specific_office_overrides_global_on_same_combo(self, db_session):
        """
        Para (CONTESTAR, subtipo=NULL) com office=42: se existe
        específico E global, só o específico deve sobrar.
        """
        specific = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
        )
        _mk_template(  # global — deve ser descartado.
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
        )
        assert [t.id for t in result] == [specific.id]

    def test_global_applies_when_no_specific_in_same_combo(self, db_session):
        """Intake de office=42 mas só há template global → ele vale."""
        tg = _mk_template(
            db_session,
            tipo_prazo="LIMINAR",
            subtipo=None,
            office_external_id=None,
        )
        # específico de outro office não interfere.
        _mk_template(
            db_session,
            tipo_prazo="LIMINAR",
            subtipo=None,
            office_external_id=99,
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="LIMINAR",
            subtipo=None,
            office_external_id=42,
        )
        assert [t.id for t in result] == [tg.id]

    def test_intake_without_office_only_picks_global(self, db_session):
        """
        Intake sem office (office_external_id=None) → só templates com
        office=NULL. Específicos são ignorados mesmo se ativos.
        """
        tg = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=None,
        )
        assert [t.id for t in result] == [tg.id]

    def test_specific_wildcard_and_global_exact_coexist_in_audiencia(
        self, db_session
    ):
        """
        Combinação AUDIENCIA/conciliacao + office=42:
          - template A: (AUDIENCIA, 'conciliacao', NULL)  — global exato
          - template B: (AUDIENCIA, NULL, 42)             — específico wildcard
          - template C: (AUDIENCIA, 'conciliacao', 42)    — específico exato

        Buckets (tipo, subtipo):
          (AUDIENCIA, 'conciliacao') → tem C (específico) → descarta A (global)
          (AUDIENCIA, None)          → só tem B → B mantém
        Resultado esperado: {B, C}.
        """
        a_global_exact = _mk_template(
            db_session,
            tipo_prazo="AUDIENCIA",
            subtipo="conciliacao",
            office_external_id=None,
        )
        b_specific_wild = _mk_template(
            db_session,
            tipo_prazo="AUDIENCIA",
            subtipo=None,
            office_external_id=42,
        )
        c_specific_exact = _mk_template(
            db_session,
            tipo_prazo="AUDIENCIA",
            subtipo="conciliacao",
            office_external_id=42,
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="AUDIENCIA",
            subtipo="conciliacao",
            office_external_id=42,
        )
        ids = {t.id for t in result}
        # a_global_exact é descartado (mesmo bucket do específico c).
        assert ids == {b_specific_wild.id, c_specific_exact.id}

    def test_multiple_specific_in_same_combo_all_kept(self, db_session):
        """
        Dois templates específicos ativos na mesma combinação → ambos
        viram sugestões (ex: "abrir prazo" + "pedir cópia ao correspondente").
        """
        t1 = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
            task_subtype_external_id=1001,
            name="abrir prazo",
        )
        t2 = _mk_template(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
            task_subtype_external_id=1002,
            name="copia correspondente",
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="CONTESTAR",
            subtipo=None,
            office_external_id=42,
        )
        assert {t.id for t in result} == {t1.id, t2.id}

    def test_stable_ordering_by_id_asc(self, db_session):
        t1 = _mk_template(
            db_session,
            tipo_prazo="LIMINAR",
            office_external_id=None,
            name="one",
        )
        t2 = _mk_template(
            db_session,
            tipo_prazo="LIMINAR",
            office_external_id=None,
            task_subtype_external_id=9002,
            name="two",
        )
        db_session.commit()

        result = match_templates(
            db_session,
            tipo_prazo="LIMINAR",
            subtipo=None,
            office_external_id=None,
        )
        assert [t.id for t in result] == [t1.id, t2.id]


class TestApplySpecificOverGlobalUnit:
    """Testes unitários da função de bucket, sem ir ao banco."""

    @staticmethod
    def _fake(id_: int, tipo: str, subtipo: str | None, office: int | None):
        obj = PrazoInicialTaskTemplate(
            name=f"f{id_}",
            tipo_prazo=tipo,
            subtipo=subtipo,
            office_external_id=office,
            task_subtype_external_id=1,
            responsible_user_external_id=1,
        )
        obj.id = id_  # simula persistência
        return obj

    def test_different_combos_do_not_interfere(self):
        # (CONTESTAR, NULL) — tem específico. (LIMINAR, NULL) — só global.
        templates = [
            self._fake(1, "CONTESTAR", None, 42),
            self._fake(2, "CONTESTAR", None, None),
            self._fake(3, "LIMINAR", None, None),
        ]
        kept = _apply_specific_over_global(templates)
        assert {t.id for t in kept} == {1, 3}

    def test_no_specific_keeps_globals(self):
        templates = [
            self._fake(1, "CONTESTAR", None, None),
            self._fake(2, "CONTESTAR", None, None),
        ]
        kept = _apply_specific_over_global(templates)
        assert {t.id for t in kept} == {1, 2}

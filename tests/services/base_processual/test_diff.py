"""Tests do diff_hash + changed_fields do Base Processual."""

from decimal import Decimal

from app.services.base_processual.diff import (
    SIGNIFICANT_FIELDS,
    compute_changed_fields,
    compute_diff_hash,
)


class TestDiffHash:
    def test_determinism(self):
        norm = {"situacao_processo": "Ativo", "valor_causa": Decimal("1500.00")}
        h1 = compute_diff_hash(norm)
        h2 = compute_diff_hash(norm)
        assert h1 == h2
        assert len(h1) == 64

    def test_significant_change(self):
        a = {"situacao_processo": "Ativo"}
        b = {"situacao_processo": "Suspenso"}
        assert compute_diff_hash(a) != compute_diff_hash(b)

    def test_valor_change(self):
        a = {"valor_causa": Decimal("0")}
        b = {"valor_causa": Decimal("1500.00")}
        assert compute_diff_hash(a) != compute_diff_hash(b)

    def test_volatile_field_ignored_dias(self):
        a = {"situacao_processo": "Ativo", "dias_ult_atualizacao": 1}
        b = {"situacao_processo": "Ativo", "dias_ult_atualizacao": 999}
        assert compute_diff_hash(a) == compute_diff_hash(b)

    def test_volatile_field_ignored_data_andamento(self):
        a = {"situacao_processo": "Ativo", "data_ult_andamento": "2026-05-07"}
        b = {"situacao_processo": "Ativo", "data_ult_andamento": "2026-05-08"}
        assert compute_diff_hash(a) == compute_diff_hash(b)

    def test_decimal_vs_string_match(self):
        # Cenario: snapshot anterior persistido como string (JSON), novo
        # snapshot como Decimal. Hash deve ser igual pra nao gerar falso ATUALIZADO.
        a = {"valor_causa": Decimal("1500.00")}
        b = {"valor_causa": "1500.00"}
        assert compute_diff_hash(a) == compute_diff_hash(b)

    def test_partes_json_change(self):
        a = {"autores_json": [{"nome": "Joao", "documento": "111"}]}
        b = {"autores_json": [{"nome": "Maria", "documento": "222"}]}
        assert compute_diff_hash(a) != compute_diff_hash(b)

    def test_partes_json_same_content(self):
        a = {"autores_json": [{"nome": "Joao", "documento": "111"}]}
        b = {"autores_json": [{"nome": "Joao", "documento": "111"}]}
        assert compute_diff_hash(a) == compute_diff_hash(b)

    def test_none_vs_missing(self):
        # campo None e campo ausente devem hashar igual
        a = {"situacao_processo": "Ativo", "valor_causa": None}
        b = {"situacao_processo": "Ativo"}
        assert compute_diff_hash(a) == compute_diff_hash(b)


class TestChangedFields:
    def test_basic(self):
        before = {"situacao_processo": "Ativo", "valor_causa": 0}
        after = {"situacao_processo": "Suspenso", "valor_causa": 1500}
        changed = compute_changed_fields(before, after)
        assert "situacao_processo" in changed
        assert "valor_causa" in changed
        assert changed["situacao_processo"]["de"] == "Ativo"
        assert changed["situacao_processo"]["para"] == "Suspenso"
        assert changed["valor_causa"]["de"] == 0
        assert changed["valor_causa"]["para"] == 1500

    def test_no_change(self):
        before = {"situacao_processo": "Ativo"}
        after = {"situacao_processo": "Ativo"}
        assert compute_changed_fields(before, after) == {}

    def test_volatile_ignored(self):
        before = {"dias_ult_atualizacao": 1}
        after = {"dias_ult_atualizacao": 999}
        # dias_ult_atualizacao nao esta em SIGNIFICANT_FIELDS -> nao reporta
        assert compute_changed_fields(before, after) == {}

    def test_responsavel_change(self):
        before = {"usuario_responsavel": "Joao"}
        after = {"usuario_responsavel": "Maria"}
        changed = compute_changed_fields(before, after)
        assert changed == {"usuario_responsavel": {"de": "Joao", "para": "Maria"}}

    def test_partes_json_change_reported(self):
        before = {"autores_json": [{"nome": "A", "documento": "1"}]}
        after = {"autores_json": [{"nome": "B", "documento": "2"}]}
        changed = compute_changed_fields(before, after)
        assert "autores_json" in changed


class TestSignificantFields:
    def test_contains_critical(self):
        assert "situacao_processo" in SIGNIFICANT_FIELDS
        assert "valor_causa" in SIGNIFICANT_FIELDS
        assert "usuario_responsavel" in SIGNIFICANT_FIELDS
        assert "ult_andamento" in SIGNIFICANT_FIELDS
        assert "autores_json" in SIGNIFICANT_FIELDS
        assert "polo" in SIGNIFICANT_FIELDS
        assert "comarca" in SIGNIFICANT_FIELDS

    def test_excludes_volatile(self):
        assert "dias_ult_atualizacao" not in SIGNIFICANT_FIELDS
        assert "data_ult_andamento" not in SIGNIFICANT_FIELDS
        assert "data_cadastro_acao" not in SIGNIFICANT_FIELDS
        assert "usuario_cadastro_acao" not in SIGNIFICANT_FIELDS

    def test_no_internal_fields(self):
        # campos do model que sao gerencia interna nao devem entrar no diff
        for forbidden in ("id", "created_at", "updated_at", "presenca_status",
                          "first_seen_upload_id", "last_seen_upload_id",
                          "current_snapshot_id"):
            assert forbidden not in SIGNIFICANT_FIELDS

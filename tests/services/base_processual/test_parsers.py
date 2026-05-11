"""Tests dos parsers tolerantes do XLSX de Base Processual."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services.base_processual.parsers import (
    format_cnj_mask,
    normalize_str,
    parse_bool_sim_nao,
    parse_cnj_digits,
    parse_date_br,
    parse_date_only_br,
    parse_decimal_br,
    parse_int,
    parse_partes_bloco,
)


class TestParseDecimalBr:
    @pytest.mark.parametrize(
        "input_,expected",
        [
            (None, None),
            ("", None),
            (" ", None),
            ("R$ ", None),
            ("0", Decimal("0")),
            (0, Decimal("0")),
            (0.0, Decimal("0.0")),
            ("1500", Decimal("1500")),
            ("1500.00", Decimal("1500.00")),
            ("1.500,00", Decimal("1500.00")),
            ("R$ 1.500,00", Decimal("1500.00")),
            ("R$ 12.345,67", Decimal("12345.67")),
            ("1234,56", Decimal("1234.56")),
            ("-1500", Decimal("-1500")),
            ("R$ -1.500,00", Decimal("-1500.00")),
        ],
    )
    def test_variants(self, input_, expected):
        assert parse_decimal_br(input_) == expected

    def test_decimal_passthrough(self):
        d = Decimal("1500.55")
        assert parse_decimal_br(d) == d

    def test_garbage(self):
        assert parse_decimal_br("abc") is None
        assert parse_decimal_br("R$ ,") is None


class TestParseDateBr:
    def test_full(self):
        assert parse_date_br("07/05/2026 18:04:32") == datetime(2026, 5, 7, 18, 4, 32)

    def test_only_date(self):
        assert parse_date_br("07/05/2026") == datetime(2026, 5, 7, 0, 0, 0)

    def test_null_convention(self):
        assert parse_date_br("00/00/0000 00:00:00") is None
        assert parse_date_br("00/00/0000") is None

    def test_blank(self):
        assert parse_date_br("") is None
        assert parse_date_br(None) is None

    def test_passthrough_datetime(self):
        d = datetime(2025, 1, 2, 3, 4, 5)
        assert parse_date_br(d) == d

    def test_passthrough_date(self):
        d = date(2025, 6, 7)
        assert parse_date_br(d) == datetime(2025, 6, 7)

    def test_invalid(self):
        assert parse_date_br("nope") is None
        assert parse_date_br("32/13/2025") is None

    def test_date_only(self):
        assert parse_date_only_br("07/05/2026") == date(2026, 5, 7)

    def test_date_only_null(self):
        assert parse_date_only_br("00/00/0000") is None


class TestParseCnj:
    def test_digits_only(self):
        assert (
            parse_cnj_digits("0010575-91.2025.8.26.0228") == "00105759120258260228"
        )

    def test_blank(self):
        assert parse_cnj_digits("") is None
        assert parse_cnj_digits(None) is None
        assert parse_cnj_digits("   ") is None

    def test_only_punctuation(self):
        # so' caracteres nao-digito -> None
        assert parse_cnj_digits("-./") is None

    def test_mask(self):
        assert (
            format_cnj_mask("00105759120258260228") == "0010575-91.2025.8.26.0228"
        )

    def test_mask_too_short(self):
        assert format_cnj_mask("123") == "123"

    def test_mask_none(self):
        assert format_cnj_mask(None) is None


class TestParseBool:
    @pytest.mark.parametrize(
        "input_,expected",
        [
            ("Sim", True),
            ("sim", True),
            ("SIM", True),
            ("yes", True),
            ("1", True),
            ("Não", False),
            ("Nao", False),
            ("nao", False),
            ("NAO", False),
            ("no", False),
            ("0", False),
            ("", None),
            (None, None),
            ("talvez", None),
            ("?", None),
        ],
    )
    def test_variants(self, input_, expected):
        assert parse_bool_sim_nao(input_) is expected


class TestPartesBloco:
    def test_single(self):
        result = parse_partes_bloco("Nome: João Silva\nCNPJCPF: 123.456.789-00")
        assert result == [{"nome": "João Silva", "documento": "123.456.789-00"}]

    def test_multiple(self):
        text = "Nome: Maria\nCNPJCPF: 111\n\nNome: Pedro\nCNPJCPF: 222"
        result = parse_partes_bloco(text)
        assert len(result) == 2
        assert result[0]["nome"] == "Maria"
        assert result[1]["nome"] == "Pedro"

    def test_empty_doc(self):
        result = parse_partes_bloco("Nome: João\nCNPJCPF: ")
        assert result == [{"nome": "João", "documento": None}]

    def test_empty_input(self):
        assert parse_partes_bloco("") == []
        assert parse_partes_bloco(None) == []
        assert parse_partes_bloco("   ") == []

    def test_fallback_unknown_format(self):
        result = parse_partes_bloco("APENAS UM NOME SOLTO")
        assert result == [{"nome": "APENAS UM NOME SOLTO", "documento": None}]

    def test_real_export_format(self):
        # formato exato visto na planilha real do operador
        text = (
            "Nome: Banco Master S/A (Matriz) -  Em Liquidação Extrajudicial\n"
            "CNPJCPF: 33.923.798/0001-00"
        )
        result = parse_partes_bloco(text)
        assert len(result) == 1
        assert "Banco Master" in result[0]["nome"]
        assert result[0]["documento"] == "33.923.798/0001-00"


class TestNormalize:
    def test_strip(self):
        assert normalize_str("  abc  ") == "abc"

    def test_empty(self):
        assert normalize_str("") is None
        assert normalize_str("   ") is None

    def test_nan(self):
        assert normalize_str("nan") is None
        assert normalize_str("NaN") is None

    def test_int_to_str(self):
        assert normalize_str(123) == "123"


class TestParseInt:
    def test_str(self):
        assert parse_int("123") == 123

    def test_int_passthrough(self):
        assert parse_int(123) == 123

    def test_float(self):
        assert parse_int(1.5) == 1

    def test_bool_rejected(self):
        # bool e' subclass de int — rejeitamos pra evitar True virar 1 silenciosamente
        assert parse_int(True) is None
        assert parse_int(False) is None

    def test_blank(self):
        assert parse_int("") is None
        assert parse_int(None) is None

    def test_invalid(self):
        assert parse_int("abc") is None
        assert parse_int("1.5") is None  # str de float — int() rejeita

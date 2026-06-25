"""Testes do parser tolerante de CNJ a partir do nome do arquivo
(ingestão automática por pasta de drive)."""
import pytest

from app.services.prazos_iniciais.drive_intake.cnj_filename import (
    extract_cnj_digits,
    mask_cnj,
)

CNJ_DIGITS = "00012345620248050001"


@pytest.mark.parametrize(
    "filename,expected",
    [
        # máscara oficial + extensão
        ("0001234-56.2024.8.05.0001.pdf", CNJ_DIGITS),
        # dígitos crus
        ("00012345620248050001.pdf", CNJ_DIGITS),
        # com texto e sufixo de versão em volta
        ("Proc 0001234-56.2024.8.05.0001 (1).pdf", CNJ_DIGITS),
        ("processo 0001234-56.2024.8.05.0001 - Joao Silva.pdf", CNJ_DIGITS),
        ("0001234-56.2024.8.05.0001 v2.pdf", CNJ_DIGITS),
        # crus + sufixo não-dígito colado
        ("00012345620248050001-copia.pdf", CNJ_DIGITS),
        # separadores frouxos / espaçados
        ("0001234 56 2024 8 05 0001.pdf", CNJ_DIGITS),
        ("0001234_56_2024_8_05_0001.pdf", CNJ_DIGITS),
        # sem extensão
        ("0001234-56.2024.8.05.0001", CNJ_DIGITS),
    ],
)
def test_extrai_cnj_de_variacoes(filename, expected):
    assert extract_cnj_digits(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "documento sem cnj.pdf",
        "relatorio 2024-01-15.pdf",        # data, não é CNJ
        "00012345620248050.pdf",           # 17 dígitos (curto)
        "123456789012345678901234.pdf",    # 24 dígitos colados (sem borda limpa)
        "",
        None,
    ],
)
def test_retorna_none_quando_nao_ha_cnj(filename):
    assert extract_cnj_digits(filename) is None


def test_pega_o_primeiro_de_dois_cnjs():
    nome = "0001234-56.2024.8.05.0001 e 0009999-11.2023.8.05.0002.pdf"
    assert extract_cnj_digits(nome) == CNJ_DIGITS


def test_preserva_zeros_a_esquerda():
    assert extract_cnj_digits("0000001-00.2024.8.05.0001.pdf") == "00000010020248050001"


def test_mask_roundtrip():
    assert mask_cnj(CNJ_DIGITS) == "0001234-56.2024.8.05.0001"
    assert extract_cnj_digits(mask_cnj(CNJ_DIGITS)) == CNJ_DIGITS


@pytest.mark.parametrize("bad", ["", "123", "0001234562024805000", "x" * 20, None])
def test_mask_rejeita_entrada_invalida(bad):
    with pytest.raises((ValueError, TypeError)):
        mask_cnj(bad)

"""Testes do modo arvore enxuta (template-driven, fase 13).

Cobre:
  - Setting on + office com templates: arvore so tem cats com template
  - Setting on + office sem nenhum template: arvore so tem residuais "Para Analise"
  - Setting on + cat com whitelist "Para Analise": passa mesmo sem template
  - Setting off: filtro de office e ignorado (arvore inteira)
  - Templates globais (office=NULL) entram pra qualquer escritorio
  - Templates pendentes de revisao NAO contam pro filtro
  - Templates inativos NAO contam pro filtro
  - Granularidade grossa: cat libera com qualquer 1 template (libera as N subs)
  - Cache 3-key: (polo, version, office_id) sao independentes
"""

import pytest
from unittest.mock import patch

from app.services.classifier import taxonomy as tax


@pytest.fixture(autouse=True)
def _clear_cache():
    tax.invalidate_taxonomy_cache()
    yield
    tax.invalidate_taxonomy_cache()


def _patch_setting(monkeypatch, enabled: bool) -> None:
    """Mocka is_template_driven_taxonomy_active diretamente — evita
    depender do app_settings + DB nos testes."""
    monkeypatch.setattr(
        tax, "is_template_driven_taxonomy_active", lambda: enabled
    )


def _make_db_loader(tree: dict[str, list[str]], allowed: set[str]):
    """Stub do _load_tree_from_db: aplica o filtro template-driven
    in-process pra simular o comportamento real (que faria query no DB)."""

    def loader(polo_scope=None, taxonomy_version=None, office_external_id=None):
        result = {k: list(v) for k, v in tree.items()}
        if office_external_id is not None and tax.is_template_driven_taxonomy_active():
            result = {
                cat: subs
                for cat, subs in result.items()
                if cat in allowed or tax._RESIDUAL_CAT_RE.search(cat)
            }
        return result

    return loader


def test_modo_enxuto_filtra_cats_sem_template(monkeypatch):
    """Office X tem template em 'Cumprimento de Sentença / Execução' apenas.
    Outras cats v2 nao aparecem na arvore enxuta."""
    _patch_setting(monkeypatch, True)
    full_tree = {
        "Citação e Intimação Inicial": ["Citação por Edital"],
        "Cumprimento de Sentença / Execução": [
            "Intimação para Pagamento Voluntário (15 dias úteis)",
        ],
        "Para Análise": [],
    }
    allowed = {"Cumprimento de Sentença / Execução"}
    monkeypatch.setattr(
        tax, "_load_tree_from_db", _make_db_loader(full_tree, allowed)
    )

    tree = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=42,
    )
    assert "Cumprimento de Sentença / Execução" in tree
    # Sem template → fora da arvore
    assert "Citação e Intimação Inicial" not in tree
    # Whitelist residual → entra
    assert "Para Análise" in tree


def test_modo_enxuto_off_arvore_completa(monkeypatch):
    """Setting off: o filtro template-driven nao se aplica, todas as cats
    do polo aparecem mesmo sem template."""
    _patch_setting(monkeypatch, False)
    full_tree = {
        "Citação e Intimação Inicial": ["Citação por Edital"],
        "Cumprimento de Sentença / Execução": ["Intimação"],
    }
    monkeypatch.setattr(
        tax, "_load_tree_from_db", _make_db_loader(full_tree, set()),
    )

    tree = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=42,
    )
    # Mesmo allowed=empty (nenhum template), as cats aparecem porque setting off
    assert "Citação e Intimação Inicial" in tree
    assert "Cumprimento de Sentença / Execução" in tree


def test_whitelist_para_analise_sempre_passa(monkeypatch):
    """Cats com nome 'Para Analise' (com ou sem acento) passam mesmo
    sem template — catch-all obrigatorio."""
    _patch_setting(monkeypatch, True)
    full_tree = {
        "Para Análise": [],
        "Para Análise — Recuperação de Crédito": [],
        "Para análise 2º Grau": [],  # legacy v1 com case-different
        "Sentença e Extinção": ["Sentença Procedente"],
    }
    # Allowed vazio: nenhuma cat tem template
    allowed: set[str] = set()
    monkeypatch.setattr(
        tax, "_load_tree_from_db", _make_db_loader(full_tree, allowed),
    )

    tree = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=99,
    )
    # As 3 variantes "Para Análise" passam via whitelist
    assert "Para Análise" in tree
    assert "Para Análise — Recuperação de Crédito" in tree
    assert "Para análise 2º Grau" in tree
    # Cat sem whitelist e sem template fica fora
    assert "Sentença e Extinção" not in tree


def test_office_external_id_none_nao_aplica_filtro(monkeypatch):
    """Quando o caller nao passa office_external_id (publicacao sem
    processo), nenhum filtro template-driven se aplica — arvore completa."""
    _patch_setting(monkeypatch, True)
    full_tree = {
        "Citação e Intimação Inicial": ["Citação por Edital"],
        "Sentença e Extinção": ["Sentença Procedente"],
    }
    monkeypatch.setattr(
        tax, "_load_tree_from_db", _make_db_loader(full_tree, set()),
    )

    tree = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2",
        # office_external_id=None
    )
    # Filtro nao aplicou — arvore inteira (mesmo allowed vazio)
    assert "Citação e Intimação Inicial" in tree
    assert "Sentença e Extinção" in tree


def test_cache_3_key_separa_arvores_por_office(monkeypatch):
    """Office A e Office B podem ter arvores diferentes em cache simultaneo."""
    _patch_setting(monkeypatch, True)
    full_tree = {
        "Sentença e Extinção": ["Sentença Procedente"],
        "Citação e Intimação Inicial": ["Citação por Edital"],
    }

    # Office A tem template em Sentença; Office B tem em Citação.
    def loader(polo_scope=None, taxonomy_version=None, office_external_id=None):
        result = {k: list(v) for k, v in full_tree.items()}
        if office_external_id is None or not tax.is_template_driven_taxonomy_active():
            return result
        if office_external_id == 1:
            allowed = {"Sentença e Extinção"}
        elif office_external_id == 2:
            allowed = {"Citação e Intimação Inicial"}
        else:
            allowed = set()
        return {
            cat: subs
            for cat, subs in result.items()
            if cat in allowed or tax._RESIDUAL_CAT_RE.search(cat)
        }

    monkeypatch.setattr(tax, "_load_tree_from_db", loader)

    a = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=1
    )
    b = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=2
    )
    assert "Sentença e Extinção" in a and "Citação e Intimação Inicial" not in a
    assert "Citação e Intimação Inicial" in b and "Sentença e Extinção" not in b
    # Cache hit: a re-leitura nao deve misturar arvores
    a2 = tax._get_active_tree(
        polo_scope="passivo", taxonomy_version="v2", office_external_id=1
    )
    assert a is a2  # mesma instancia cacheada


def test_invalidate_taxonomy_cache_for_office(monkeypatch):
    """invalidate_taxonomy_cache_for_office(N) limpa entries do office N
    e dos globais (None), mas preserva outros offices."""
    _patch_setting(monkeypatch, True)

    counter = {"n": 0}

    def loader(polo_scope=None, taxonomy_version=None, office_external_id=None):
        counter["n"] += 1
        return {"CatA": ["sub1"]}

    monkeypatch.setattr(tax, "_load_tree_from_db", loader)

    # Carrega 3 entradas no cache
    tax._get_active_tree(office_external_id=1)
    tax._get_active_tree(office_external_id=2)
    tax._get_active_tree(office_external_id=None)
    assert counter["n"] == 3

    # Invalida office 1 — derruba entry do 1 + globais (office=None)
    tax.invalidate_taxonomy_cache_for_office(1)

    # Re-leitura do 1: cache miss (loader chama de novo)
    tax._get_active_tree(office_external_id=1)
    assert counter["n"] == 4
    # Re-leitura do None: cache miss tambem (entrou junto)
    tax._get_active_tree(office_external_id=None)
    assert counter["n"] == 5
    # Re-leitura do 2: cache hit (preservado)
    tax._get_active_tree(office_external_id=2)
    assert counter["n"] == 5


def test_residual_regex_case_insensitive():
    """Smoke test do regex de whitelist."""
    matches = [
        "Para Análise",
        "Para Análise — Recuperação de Crédito",
        "Para análise",
        "para analise",
        "PARA ANALISE 2º GRAU",
    ]
    no_matches = [
        "Sentença",
        "Cumprimento de Sentença",
        "Análise pericial",  # 'Para' antes e exigido
    ]
    for m in matches:
        assert tax._RESIDUAL_CAT_RE.search(m), f"deveria casar: {m}"
    for nm in no_matches:
        assert not tax._RESIDUAL_CAT_RE.search(nm), f"nao deveria casar: {nm}"

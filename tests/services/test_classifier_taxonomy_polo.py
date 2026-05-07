"""Testes do classifier polo+version aware (fase 4 da taxonomy/v2).

Cobre:
  - _get_active_tree filtra por polo_scope e taxonomy_version
  - validate_classification rejeita cat v2 errada pro polo
  - repair_classification respeita o escopo (nao "conserta" pra fora)
  - cache do _get_active_tree e independente por (polo, version)
  - get_active_taxonomy_version le do env quando app_settings indisponivel

Os testes usam monkeypatch em _load_tree_from_db pra simular o DB com
arvores controladas (sem precisar de fixture postgres).
"""

import pytest

from app.services.classifier import taxonomy as tax


@pytest.fixture(autouse=True)
def _clear_cache():
    """Limpa cache antes de cada teste — varios deles configuram trees
    diferentes via monkeypatch e o cache vazaria entre testes."""
    tax.invalidate_taxonomy_cache()
    yield
    tax.invalidate_taxonomy_cache()


def _make_loader(trees: dict[tuple, dict[str, list[str]]]):
    """Factory de loader stub. Retorna uma funcao que mimica
    _load_tree_from_db consultando `trees` pela chave (polo, version)."""

    def _loader(polo_scope=None, taxonomy_version=None):
        return trees.get((polo_scope, taxonomy_version))

    return _loader


def test_get_active_tree_filtra_por_polo(monkeypatch):
    """polo_scope='ativo' nao retorna cats que pertencem so ao 'passivo'."""
    trees = {
        ("ativo", "v2"): {"Acordo, Pagamento e Depósito": ["Acordo homologado"]},
        ("passivo", "v2"): {"Sentença e Extinção": ["Sentença Procedente"]},
    }
    monkeypatch.setattr(tax, "_load_tree_from_db", _make_loader(trees))

    ativo = tax._get_active_tree(polo_scope="ativo", taxonomy_version="v2")
    passivo = tax._get_active_tree(polo_scope="passivo", taxonomy_version="v2")

    assert "Acordo, Pagamento e Depósito" in ativo
    assert "Sentença e Extinção" not in ativo
    assert "Sentença e Extinção" in passivo
    assert "Acordo, Pagamento e Depósito" not in passivo


def test_validate_classification_rejeita_cat_v2_no_polo_errado(monkeypatch):
    trees = {
        ("ativo", "v2"): {"Acordo, Pagamento e Depósito": ["Acordo homologado"]},
        ("passivo", "v2"): {"Sentença e Extinção": ["Sentença Procedente"]},
    }
    monkeypatch.setattr(tax, "_load_tree_from_db", _make_loader(trees))

    # cat valida no polo certo
    assert tax.validate_classification(
        "Acordo, Pagamento e Depósito",
        "Acordo homologado",
        polo_scope="ativo",
        taxonomy_version="v2",
    )
    # mesma cat no polo errado deve falhar
    assert not tax.validate_classification(
        "Acordo, Pagamento e Depósito",
        "Acordo homologado",
        polo_scope="passivo",
        taxonomy_version="v2",
    )


def test_validate_classification_default_v1_preserva_comportamento_legado(monkeypatch):
    """Sem polo/version explicitos, valida contra v1 (default da fase 4 +
    fallback hardcoded em CLASSIFICATION_TREE quando DB indisponivel)."""
    monkeypatch.setattr(tax, "_load_tree_from_db", lambda **_: None)
    # Nenhuma cat passada na v1 hardcoded:
    assert tax.validate_classification(
        "Sentença", "Sentença Procedente", taxonomy_version="v1"
    )
    # cat v2 nao deve casar quando filtramos por v1:
    assert not tax.validate_classification(
        "Acordo, Pagamento e Depósito",
        "Acordo homologado",
        taxonomy_version="v1",
    )


def test_repair_classification_nao_atravessa_polos(monkeypatch):
    """Quando o caller passa polo_scope, o repair nao tenta achar a cat
    em outra arvore. Cat fora do polo permanece como veio (fica invalida
    mas nao e silenciosamente movida)."""
    trees = {
        ("ativo", "v2"): {"Acordo, Pagamento e Depósito": ["Acordo homologado"]},
        ("passivo", "v2"): {"Sentença e Extinção": ["Sentença Procedente"]},
    }
    monkeypatch.setattr(tax, "_load_tree_from_db", _make_loader(trees))

    # Cat pertence ao 'passivo' mas estamos restritos a 'ativo' — nao vira
    # outra coisa nem normaliza pra 'passivo'.
    cat, sub = tax.repair_classification(
        "Sentença e Extinção",
        "Sentença Procedente",
        polo_scope="ativo",
        taxonomy_version="v2",
    )
    assert (cat, sub) == ("Sentença e Extinção", "Sentença Procedente")
    # Confirmacao via validate: combinacao nao e valida no polo restrito
    assert not tax.validate_classification(
        cat, sub, polo_scope="ativo", taxonomy_version="v2",
    )


def test_cache_separado_por_chave(monkeypatch):
    """Cada (polo, version) tem entrada propria no cache — mudar a tree
    de uma chave nao invalida outra.

    Verifico isso checando que duas leituras com (polo='ativo', v2) e
    (polo='passivo', v2) resultam em arvores distintas armazenadas."""
    calls = {"n": 0}
    trees = {
        ("ativo", "v2"): {"CatAtivo": ["SubA"]},
        ("passivo", "v2"): {"CatPassivo": ["SubP"]},
    }

    def loader(polo_scope=None, taxonomy_version=None):
        calls["n"] += 1
        return trees.get((polo_scope, taxonomy_version))

    monkeypatch.setattr(tax, "_load_tree_from_db", loader)

    a1 = tax._get_active_tree(polo_scope="ativo", taxonomy_version="v2")
    p1 = tax._get_active_tree(polo_scope="passivo", taxonomy_version="v2")
    a2 = tax._get_active_tree(polo_scope="ativo", taxonomy_version="v2")  # cache hit
    p2 = tax._get_active_tree(polo_scope="passivo", taxonomy_version="v2")  # cache hit

    assert a1 is a2  # mesmo objeto cacheado
    assert p1 is p2
    assert "CatAtivo" in a1 and "CatPassivo" not in a1
    assert "CatPassivo" in p1 and "CatAtivo" not in p1
    # Loader chamado so 2x (uma por chave); 3a/4a chamadas vieram do cache
    assert calls["n"] == 2


def test_get_active_taxonomy_version_default_v1(monkeypatch):
    """Sem env e sem app_settings, retorna 'v1'."""
    monkeypatch.delenv("TAXONOMY_ACTIVE_VERSION", raising=False)
    monkeypatch.setattr(
        "app.services.app_settings.get_setting",
        lambda key, default=None: default,
    )
    assert tax.get_active_taxonomy_version() == "v1"


def test_get_active_taxonomy_version_env_override(monkeypatch):
    """app_settings sem valor + env setado -> usa env."""
    monkeypatch.setenv("TAXONOMY_ACTIVE_VERSION", "v2")
    monkeypatch.setattr(
        "app.services.app_settings.get_setting",
        lambda key, default=None: default,
    )
    assert tax.get_active_taxonomy_version() == "v2"


def test_get_active_taxonomy_version_app_settings_prioridade(monkeypatch):
    """app_settings com valor tem precedencia sobre env."""
    monkeypatch.setenv("TAXONOMY_ACTIVE_VERSION", "v1")
    monkeypatch.setattr(
        "app.services.app_settings.get_setting",
        lambda key, default=None: "v2" if key == "taxonomy_active_version" else default,
    )
    assert tax.get_active_taxonomy_version() == "v2"

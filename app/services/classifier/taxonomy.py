"""
Árvore de classificações de publicações judiciais.

Migration tax001 (2026-05-04) moveu a árvore pra DB. Esta constante
hardcoded vira **fallback** caso o DB esteja vazio (boot inicial pre-seed,
ou erro de carregamento). Em produção normal a árvore vem do DB com cache
TTL=60s — `_get_active_tree()` resolve.

Pra editar a taxonomia em prod: use a UI Admin (tab Taxonomia) que
opera via classification_categories/classification_subcategories.

Versionamento (tax005, tax006, 2026-05-07):
  - Cada cat/sub no DB tem `taxonomy_version` ('v1' | 'v2') e cat tem
    `polo_scope` ('ativo' | 'passivo' | 'ambos').
  - Funções de consulta aceitam `polo_scope` e `taxonomy_version` pra
    filtrar a arvore retornada.
  - Default = 'v1' sem filtro de polo: preserva comportamento pre-v2.
  - `get_active_taxonomy_version()` le `TAXONOMY_ACTIVE_VERSION` do env
    (provisional ate o toggle global em app_settings — fase 11).
"""

import logging
import os
import re
import threading
import time
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
# Cache indexado por (polo_scope, taxonomy_version, office_external_id).
# Quando alguma posicao e None, significa "sem filtro nesse eixo".
_CacheKey = tuple[Optional[str], Optional[str], Optional[int]]
_TREE_CACHE: dict[_CacheKey, dict[str, list[str]]] = {}
_TREE_CACHE_AT: dict[_CacheKey, float] = {}
_TREE_CACHE_LOCK = threading.Lock()

# Regex pra whitelist de categorias residuais "Para Analise" — sempre
# entram na arvore mesmo no modo enxuto (template-driven), pra garantir
# que a IA tem catch-all quando a publicacao nao casa com nenhuma cat
# que tenha template configurado pro escritorio.
_RESIDUAL_CAT_RE = re.compile(r"para\s+an[\u00e1a]lise", re.IGNORECASE)


def is_template_driven_taxonomy_active() -> bool:
    """Le o setting global `template_driven_taxonomy` (default True).

    Quando True (default), a arvore aplicavel a um escritorio so inclui
    categorias que tem AO MENOS UM template ativo desse escritorio (ou
    global, com office_external_id=NULL). Granularidade GROSSA: a
    presenca de qualquer template na cat libera a categoria inteira
    (todas as suas subcategorias) pra IA — assim o operador nao perde
    visibilidade quando aparece uma sub sem template.

    Categorias residuais ("Para Analise") sempre entram na arvore via
    whitelist, mesmo que nao tenham template — necessario pra a IA ter
    catch-all quando a publicacao nao casa com nenhuma cat permitida.

    Setting pode ser desligado pelo admin caso queira voltar pra arvore
    completa (modo legacy). Migration tax009 seedeia true."""
    try:
        from app.services.app_settings import get_setting
        v = (get_setting("template_driven_taxonomy") or "true").strip().lower()
        return v in ("true", "1", "yes", "on")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Taxonomy: falha lendo template_driven_taxonomy, assumindo True: %s",
            exc,
        )
        return True


def get_active_taxonomy_version() -> str:
    """Versao da taxonomia ativa globalmente.

    Resolucao em cascata:
      1. app_settings['taxonomy_active_version'] (DB, com cache 60s)
      2. env TAXONOMY_ACTIVE_VERSION (override pra dev/staging)
      3. default 'v1' (preserva comportamento pre-v2)

    O endpoint admin (PATCH /admin/taxonomy/settings) escreve no
    app_settings; o env continua util pra testes locais sem mexer no
    DB. Mudanca via endpoint invalida cache do app_settings + cache
    de taxonomia automaticamente (chama invalidate_taxonomy_cache no
    handler)."""
    try:
        from app.services.app_settings import get_setting
        db_value = get_setting("taxonomy_active_version")
        if db_value:
            return db_value.strip().lower()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Taxonomy: falha lendo app_settings, caindo no env: %s", exc,
        )
    return (os.getenv("TAXONOMY_ACTIVE_VERSION") or "v1").strip().lower()


def invalidate_taxonomy_cache() -> None:
    """Força o próximo `_get_active_tree` a recarregar do DB. Usado pelo
    endpoint de mutação (criar/editar/inativar categoria) pra que a
    mudança apareça imediatamente em vez de esperar o TTL."""
    with _TREE_CACHE_LOCK:
        _TREE_CACHE.clear()
        _TREE_CACHE_AT.clear()


def invalidate_taxonomy_cache_for_office(office_external_id: Optional[int]) -> None:
    """Invalida apenas as entradas de cache que envolvem o escritorio
    informado (ou globais, com office=None). Chamado pelos endpoints
    CRUD de task_templates pra que a arvore enxuta reflita imediatamente
    a criacao/edicao/desativacao de um template, sem esperar TTL."""
    with _TREE_CACHE_LOCK:
        keys_to_drop = [
            k for k in _TREE_CACHE.keys()
            if k[2] == office_external_id or k[2] is None
        ]
        for k in keys_to_drop:
            _TREE_CACHE.pop(k, None)
            _TREE_CACHE_AT.pop(k, None)


def _load_template_allowed_cats(
    db,
    office_external_id: int,
    taxonomy_version: Optional[str] = None,
) -> set[str]:
    """Set de category names que tem AO MENOS UM template ativo pro
    escritorio X ou global (office IS NULL), nao pendente de revisao.

    Granularidade grossa (decisao com user, fase 13): a presenca de
    qualquer template na cat libera a cat INTEIRA — todas as subs
    aparecem na arvore. Sub-level filtering ficaria muito restritivo
    e tiraria visibilidade do operador quando aparece sub nao prevista.
    """
    from app.models.task_template import TaskTemplate
    q = (
        db.query(TaskTemplate.category)
        .distinct()
        .filter(TaskTemplate.is_active.is_(True))
        .filter(TaskTemplate.needs_taxonomy_review.is_(False))
        .filter(
            (TaskTemplate.office_external_id == office_external_id)
            | (TaskTemplate.office_external_id.is_(None))
        )
    )
    if taxonomy_version is not None:
        q = q.filter(TaskTemplate.taxonomy_version == taxonomy_version)
    return {row[0] for row in q.all() if row[0]}


def _load_tree_from_db(
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> dict[str, list[str]] | None:
    """Lê classification_categories/subcategories e monta o dict legacy.
    Retorna None se DB vazio ou erro (caller faz fallback).

    Filtros:
      - polo_scope: 'ativo' | 'passivo' | 'ambos' | None (sem filtro).
        'ambos' inclui cats marcadas como 'ambos' (legacy v1).
      - taxonomy_version: 'v1' | 'v2' | None (sem filtro).
      - office_external_id: quando passado E o setting
        `template_driven_taxonomy` esta ativo, filtra a arvore
        pra so incluir categorias com pelo menos um template ativo
        do escritorio (ou global). Cats residuais "Para Analise"
        sempre entram via whitelist."""
    try:
        from app.db.session import SessionLocal
        from app.models.classification_taxonomy import (
            ClassificationCategory, ClassificationSubcategory,
        )
        with SessionLocal() as db:
            q = (
                db.query(ClassificationCategory)
                .filter(ClassificationCategory.is_active.is_(True))
            )
            if polo_scope is not None:
                # Quando o caller pede 'ativo'/'passivo', tambem aceita
                # cats marcadas como 'ambos' (legacy v1 vale pros dois).
                if polo_scope in ("ativo", "passivo"):
                    q = q.filter(
                        ClassificationCategory.polo_scope.in_([polo_scope, "ambos"])
                    )
                else:
                    q = q.filter(ClassificationCategory.polo_scope == polo_scope)
            if taxonomy_version is not None:
                q = q.filter(
                    ClassificationCategory.taxonomy_version == taxonomy_version
                )
            cats = q.order_by(
                ClassificationCategory.display_order, ClassificationCategory.name
            ).all()
            if not cats:
                return None
            tree: dict[str, list[str]] = {}
            for c in cats:
                subs = [
                    s.name for s in c.subcategories
                    if s.is_active and (
                        taxonomy_version is None
                        or s.taxonomy_version == taxonomy_version
                    )
                ]
                tree[c.name] = subs

            # Filtro template-driven (modo arvore enxuta): so inclui
            # cats que tem template OU casam com a whitelist residual.
            if (
                office_external_id is not None
                and is_template_driven_taxonomy_active()
            ):
                allowed = _load_template_allowed_cats(
                    db,
                    office_external_id=office_external_id,
                    taxonomy_version=taxonomy_version,
                )
                tree = {
                    cat: subs
                    for cat, subs in tree.items()
                    if cat in allowed or _RESIDUAL_CAT_RE.search(cat)
                }
            return tree
    except Exception as exc:  # noqa: BLE001
        logger.warning("Taxonomy: falha lendo DB, caindo em fallback hardcoded: %s", exc)
        return None


def _get_active_tree(
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> dict[str, list[str]]:
    """Retorna a árvore vigente. Tenta cache → DB → fallback hardcoded.
    Cache e indexado por (polo_scope, taxonomy_version, office_external_id)
    — multiplas arvores podem coexistir em memoria com TTL independente.

    Default sem filtros: caller herda toda a arvore (v1 + v2 misturadas
    se a v2 ja tiver sido seedada). Pra preservar comportamento do
    classificador antes da fase 11, callers que queiram so v1 devem
    passar `taxonomy_version='v1'` explicitamente.

    Quando `office_external_id` e passado E o setting
    `template_driven_taxonomy` esta ativo, a arvore retornada e a
    "enxuta" — so com cats que tem template do escritorio + whitelist
    residual."""
    key: _CacheKey = (polo_scope, taxonomy_version, office_external_id)
    now = time.monotonic()
    cached_at = _TREE_CACHE_AT.get(key, 0.0)
    if key in _TREE_CACHE and (now - cached_at) < _CACHE_TTL_SECONDS:
        return _TREE_CACHE[key]
    with _TREE_CACHE_LOCK:
        # Double-check após pegar lock
        cached_at = _TREE_CACHE_AT.get(key, 0.0)
        if key in _TREE_CACHE and (now - cached_at) < _CACHE_TTL_SECONDS:
            return _TREE_CACHE[key]
        from_db = _load_tree_from_db(
            polo_scope=polo_scope,
            taxonomy_version=taxonomy_version,
            office_external_id=office_external_id,
        )
        if from_db is not None:
            _TREE_CACHE[key] = from_db
        else:
            # Fallback hardcoded so faz sentido pra v1 sem filtro de polo
            # ou office. Pra v2 ou com filtro de office sem DB, retorna
            # dict vazio (caller decide).
            if (
                taxonomy_version in (None, "v1")
                and polo_scope in (None, "ambos")
                and office_external_id is None
            ):
                _TREE_CACHE[key] = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}
            else:
                _TREE_CACHE[key] = {}
        _TREE_CACHE_AT[key] = now
        return _TREE_CACHE[key]


CLASSIFICATION_TREE: dict[str, list[str]] = {
    "1° Grau - Cível / Execução": [
        "Apresentação de Contestação",
        "Cumprimento de Sentença",
        "Embargos à Execução",
        "Determinação de Penhora",
        "Suspensão da Execução",
        "Expedição de Mandado ou Alvará",
        "Sentença Execução | Obrigação Satisfeita",
        "Extinção Total da Dívida",
        "Renúncia do Crédito",
        "Indeferimento da Inicial",
        "Prescrição Intercorrente",
        "Execução - Para Análise",
    ],
    "2° Grau - Cível": [
        "Abertura De Prazo - Contrarrazões",
        "Agravo De Instrumento",
        "Inclusão Em Pauta De Julgamento",
        "Suspensão / Sobrestamento",
        "Acordão - Provido",
        "Acordão - Não Provido",
        "Acordão - Provido Em Parte",
        "Acordão Não Definido",
        "Decisão Monocrática",
        "Para Análise 2º Grau",
    ],
    "Tutela": [
        "Tutela Pendente de Decisão",
        "Tutela Concedida",
        "Tutela Mantida",
        "Tutela Revogada",
        "Tutela Modificada",
        "Tutela Não Concedida",
    ],
    "Audiência Agendada": [
        "Conciliação",
        "Instrução",
        "Audiência Una",
        "Não especificada",
    ],
    "Cita\u00e7\u00e3o": [
        "Cita\u00e7\u00e3o para Contestar",
        "Cita\u00e7\u00e3o para Apresenta\u00e7\u00e3o de Documentos",
        "Cita\u00e7\u00e3o - Para An\u00e1lise",
    ],
    "Complementar Custas": [],
    "Manifestação das Partes": [],
    "Provas": [],
    "Embargos de Declara\u00e7\u00e3o": [
        "Contrarraz\u00f5es",
        "Decis\u00e3o Monocr\u00e1tica",
        "Embargos de Declara\u00e7\u00e3o - Para An\u00e1lise",
    ],
    "Recurso Inominado": [
        "Contrarraz\u00f5es",
        "Abertura de Prazo",
        "Recurso Inominado - Para An\u00e1lise",
    ],
    "Saneamento e Organiza\u00e7\u00e3o do Processo": [],
    "Sentença": [
        "Sentença Parcialmente procedente",
        "Sentença Procedente",
        "Sentença Improcedente",
        "Sentença Homologação de transação",
        "Sentença Homologação de renúncia à pretensão",
        "Sentença Homologação Decisão por Juiz Leigo",
        "Sentença Embargos de Declaração",
        "Sentença Indeferimento da inicial",
        "Sentença Ausência de movimento",
        "Sentença Abandono do autor",
        "Sentença Ausência de pressupostos",
        "Sentença Ausência de legitimidade",
        "Sentença Homologação desistência da ação",
        "Senten\u00e7a de Extin\u00e7\u00e3o sem Resolu\u00e7\u00e3o",
        "Sentença Não definida",
    ],
    "Trânsito em Julgado": [],
    "Execução": [],
    "Arquivamento Definitivo": [],
    "Para análise": [],
}


def _normalize_label(value: str | None) -> str:
    """Normaliza acentos, caixa e pontuação para comparar rótulos da IA."""
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("º", "o").replace("°", "o")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _find_category_by_normalized(
    label: str,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> str | None:
    norm = _normalize_label(label)
    for category in _get_active_tree(
        polo_scope=polo_scope,
        taxonomy_version=taxonomy_version,
        office_external_id=office_external_id,
    ):
        if _normalize_label(category) == norm:
            return category
    return None


def _find_subcategory_by_normalized(
    category: str,
    label: str,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> str | None:
    norm = _normalize_label(label)
    tree = _get_active_tree(
        polo_scope=polo_scope,
        taxonomy_version=taxonomy_version,
        office_external_id=office_external_id,
    )
    for subcategory in tree.get(category, []):
        if _normalize_label(subcategory) == norm:
            return subcategory
    return None


_CATEGORY_ALIASES: dict[str, str] = {
    "manifestacao": "Manifestação das Partes",
    "manifestacao das partes": "Manifestação das Partes",
    "recurso inominado contrarrazoes": "Recurso Inominado",
}


_PAIR_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    (
        "recurso inominado contrarrazoes",
        "abertura de prazo",
    ): ("Recurso Inominado", "Contrarrazões"),
}


def build_taxonomy_text(
    excluded: set[tuple[str, str | None]] | None = None,
    custom_additions: list[dict[str, str]] | None = None,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> str:
    """
    Gera representação textual da taxonomia para uso em prompts.

    Args:
        excluded: set de (category, subcategory) a excluir.
                  Se subcategory=None, exclui a categoria inteira.
        custom_additions: lista de dicts com "category" e opcionalmente "subcategory"
                          para adicionar à taxonomia.
        polo_scope: filtra por polo ('ativo' / 'passivo' / 'ambos' / None).
                    'ativo'/'passivo' inclui tambem cats marcadas como 'ambos'.
        taxonomy_version: filtra por versao ('v1' / 'v2' / None).
        office_external_id: quando passado E modo template-driven ativo,
                            arvore vem ja filtrada por templates do escritorio.
    """
    # Cópia da árvore base (do DB com cache, ou fallback hardcoded)
    tree = {
        k: list(v)
        for k, v in _get_active_tree(
            polo_scope=polo_scope,
            taxonomy_version=taxonomy_version,
            office_external_id=office_external_id,
        ).items()
    }

    # Aplica exclusões
    if excluded:
        cats_to_remove = set()
        for cat, sub in excluded:
            if sub is None:
                # Exclui categoria inteira
                cats_to_remove.add(cat)
            elif cat in tree:
                # Exclui subcategoria específica
                if sub in tree[cat]:
                    tree[cat].remove(sub)
        for cat in cats_to_remove:
            tree.pop(cat, None)

    # Aplica adições customizadas
    if custom_additions:
        for item in custom_additions:
            cat = item.get("category", "")
            sub = item.get("subcategory")
            if cat not in tree:
                tree[cat] = []
            if sub and sub not in tree[cat]:
                tree[cat].append(sub)

    lines = []
    for category, subcategories in tree.items():
        if subcategories:
            lines.append(f"\n## {category}")
            for sub in subcategories:
                lines.append(f"  - {sub}")
        else:
            lines.append(f"\n## {category}")
            lines.append("  (sem subcategoria — usar '-' no campo subcategoria)")
    return "\n".join(lines)


def get_all_valid_categories(
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> set[str]:
    return set(
        _get_active_tree(
            polo_scope=polo_scope,
            taxonomy_version=taxonomy_version,
            office_external_id=office_external_id,
        ).keys()
    )


def get_valid_subcategories(
    category: str,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> set[str]:
    subs = _get_active_tree(
        polo_scope=polo_scope,
        taxonomy_version=taxonomy_version,
        office_external_id=office_external_id,
    ).get(category, [])
    return set(subs) if subs else {"-"}


def repair_classification(
    category: str,
    subcategory: str,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> tuple[str, str]:
    """
    Tenta corrigir pares (category, subcategory) comuns emitidos errado pelo
    modelo:
      - category é na verdade uma subcategoria conhecida → inverte
      - subcategory vem vazio/"-" mas category tem subcategorias obrigatórias
        → deixa como está (validate_classification irá rejeitar)
      - subcategory é válida mas na categoria errada → move pra categoria certa
      - subcategory = "-" ou "Para Análise" em categoria com subs → fallback genérico
    Retorna o par (possivelmente) corrigido; não altera se já é válido.
    """
    cat = (category or "").strip()
    sub = (subcategory or "").strip()
    tree = _get_active_tree(
        polo_scope=polo_scope,
        taxonomy_version=taxonomy_version,
        office_external_id=office_external_id,
    )

    pair_alias = _PAIR_ALIASES.get((_normalize_label(cat), _normalize_label(sub)))
    if pair_alias:
        return pair_alias

    cat_norm = _normalize_label(cat)
    aliased_cat = _CATEGORY_ALIASES.get(cat_norm)
    if aliased_cat:
        cat = aliased_cat
    else:
        cat = _find_category_by_normalized(
            cat,
            polo_scope=polo_scope,
            taxonomy_version=taxonomy_version,
            office_external_id=office_external_id,
        ) or cat

    if cat in tree:
        if not tree[cat]:
            return cat, "-"
        sub = _find_subcategory_by_normalized(
            cat,
            sub,
            polo_scope=polo_scope,
            taxonomy_version=taxonomy_version,
            office_external_id=office_external_id,
        ) or sub

    if cat in tree:
        subs = tree[cat]
        if (not subs and sub in ("-", "")) or (subs and sub in subs):
            return cat, sub

    for parent, subs in tree.items():
        if cat in subs:
            return parent, cat

    if sub in tree and cat not in tree:
        if cat in tree[sub]:
            return sub, cat

    if cat in tree and sub:
        for parent, subs in tree.items():
            if sub in subs:
                return parent, sub

    if cat in tree:
        subs = tree[cat]
        if subs and sub in ("-", "", "Para Análise", "Para análise"):
            for s in subs:
                if "Para Análise" in s or "Não definid" in s or "Não especificad" in s:
                    return cat, s
            return cat, subs[-1]

    return cat, sub


def validate_classification(
    category: str,
    subcategory: str,
    polo_scope: Optional[str] = None,
    taxonomy_version: Optional[str] = None,
    office_external_id: Optional[int] = None,
) -> bool:
    tree = _get_active_tree(
        polo_scope=polo_scope,
        taxonomy_version=taxonomy_version,
        office_external_id=office_external_id,
    )
    if category not in tree:
        return False
    subs = tree[category]
    if not subs:
        return subcategory in ("-", "")
    return subcategory in subs

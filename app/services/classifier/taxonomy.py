"""
Árvore de classificações de publicações judiciais.

Migration tax001 (2026-05-04) moveu a árvore pra DB. Esta constante
hardcoded vira **fallback** caso o DB esteja vazio (boot inicial pre-seed,
ou erro de carregamento). Em produção normal a árvore vem do DB com cache
TTL=60s — `_get_active_tree()` resolve.

Pra editar a taxonomia em prod: use a UI Admin (tab Taxonomia) que
opera via classification_categories/classification_subcategories.
"""

import logging
import re
import threading
import time
import unicodedata

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60.0
_TREE_CACHE: dict[str, list[str]] | None = None
_TREE_CACHE_AT: float = 0.0
_TREE_CACHE_LOCK = threading.Lock()


def invalidate_taxonomy_cache() -> None:
    """Força o próximo `_get_active_tree` a recarregar do DB. Usado pelo
    endpoint de mutação (criar/editar/inativar categoria) pra que a
    mudança apareça imediatamente em vez de esperar o TTL."""
    global _TREE_CACHE, _TREE_CACHE_AT
    with _TREE_CACHE_LOCK:
        _TREE_CACHE = None
        _TREE_CACHE_AT = 0.0


def _load_tree_from_db() -> dict[str, list[str]] | None:
    """Lê classification_categories/subcategories e monta o dict legacy.
    Retorna None se DB vazio ou erro (caller faz fallback)."""
    try:
        from app.db.session import SessionLocal
        from app.models.classification_taxonomy import (
            ClassificationCategory, ClassificationSubcategory,
        )
        with SessionLocal() as db:
            cats = (
                db.query(ClassificationCategory)
                .filter(ClassificationCategory.is_active.is_(True))
                .order_by(ClassificationCategory.display_order, ClassificationCategory.name)
                .all()
            )
            if not cats:
                return None
            tree: dict[str, list[str]] = {}
            for c in cats:
                subs = [
                    s.name for s in c.subcategories
                    if s.is_active
                ]
                tree[c.name] = subs
            return tree
    except Exception as exc:  # noqa: BLE001
        logger.warning("Taxonomy: falha lendo DB, caindo em fallback hardcoded: %s", exc)
        return None


def _get_active_tree() -> dict[str, list[str]]:
    """Retorna a árvore vigente. Tenta cache → DB → fallback hardcoded."""
    global _TREE_CACHE, _TREE_CACHE_AT
    now = time.monotonic()
    if _TREE_CACHE is not None and (now - _TREE_CACHE_AT) < _CACHE_TTL_SECONDS:
        return _TREE_CACHE
    with _TREE_CACHE_LOCK:
        # Double-check após pegar lock
        if _TREE_CACHE is not None and (now - _TREE_CACHE_AT) < _CACHE_TTL_SECONDS:
            return _TREE_CACHE
        from_db = _load_tree_from_db()
        if from_db is not None:
            _TREE_CACHE = from_db
        else:
            _TREE_CACHE = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}
        _TREE_CACHE_AT = now
        return _TREE_CACHE


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


def _find_category_by_normalized(label: str) -> str | None:
    norm = _normalize_label(label)
    for category in _get_active_tree():
        if _normalize_label(category) == norm:
            return category
    return None


def _find_subcategory_by_normalized(category: str, label: str) -> str | None:
    norm = _normalize_label(label)
    for subcategory in _get_active_tree().get(category, []):
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
) -> str:
    """
    Gera representação textual da taxonomia para uso em prompts.

    Args:
        excluded: set de (category, subcategory) a excluir.
                  Se subcategory=None, exclui a categoria inteira.
        custom_additions: lista de dicts com "category" e opcionalmente "subcategory"
                          para adicionar à taxonomia.
    """
    # Cópia da árvore base (do DB com cache, ou fallback hardcoded)
    tree = {k: list(v) for k, v in _get_active_tree().items()}

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


def get_all_valid_categories() -> set[str]:
    return set(_get_active_tree().keys())


def get_valid_subcategories(category: str) -> set[str]:
    subs = _get_active_tree().get(category, [])
    return set(subs) if subs else {"-"}


def repair_classification(category: str, subcategory: str) -> tuple[str, str]:
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
    tree = _get_active_tree()

    pair_alias = _PAIR_ALIASES.get((_normalize_label(cat), _normalize_label(sub)))
    if pair_alias:
        return pair_alias

    cat_norm = _normalize_label(cat)
    aliased_cat = _CATEGORY_ALIASES.get(cat_norm)
    if aliased_cat:
        cat = aliased_cat
    else:
        cat = _find_category_by_normalized(cat) or cat

    if cat in tree:
        if not tree[cat]:
            return cat, "-"
        sub = _find_subcategory_by_normalized(cat, sub) or sub

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


def validate_classification(category: str, subcategory: str) -> bool:
    tree = _get_active_tree()
    if category not in tree:
        return False
    subs = tree[category]
    if not subs:
        return subcategory in ("-", "")
    return subcategory in subs

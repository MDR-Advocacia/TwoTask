"""
Árvore de classificações de publicações judiciais.

Estrutura: dict[str, list[str]]
  - chave: categoria principal
  - valor: lista de subcategorias (lista vazia = sem subcategorias)

A categoria especial "Para análise" é usada como fallback quando o texto
não fornece informação suficiente para uma classificação assertiva.
"""

import re
import unicodedata


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
    for category in CLASSIFICATION_TREE:
        if _normalize_label(category) == norm:
            return category
    return None


def _find_subcategory_by_normalized(category: str, label: str) -> str | None:
    norm = _normalize_label(label)
    for subcategory in CLASSIFICATION_TREE.get(category, []):
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
    # Cópia da árvore base
    tree = {k: list(v) for k, v in CLASSIFICATION_TREE.items()}

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
    return set(CLASSIFICATION_TREE.keys())


def get_valid_subcategories(category: str) -> set[str]:
    subs = CLASSIFICATION_TREE.get(category, [])
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

    pair_alias = _PAIR_ALIASES.get((_normalize_label(cat), _normalize_label(sub)))
    if pair_alias:
        return pair_alias

    cat_norm = _normalize_label(cat)
    aliased_cat = _CATEGORY_ALIASES.get(cat_norm)
    if aliased_cat:
        cat = aliased_cat
    else:
        cat = _find_category_by_normalized(cat) or cat

    if cat in CLASSIFICATION_TREE:
        if not CLASSIFICATION_TREE[cat]:
            return cat, "-"
        sub = _find_subcategory_by_normalized(cat, sub) or sub

    # Já válido? retorna como está.
    if cat in CLASSIFICATION_TREE:
        subs = CLASSIFICATION_TREE[cat]
        if (not subs and sub in ("-", "")) or (subs and sub in subs):
            return cat, sub

    # Caso 1: cat é na verdade uma subcategoria conhecida
    # Procura qual categoria-pai tem essa subcategoria
    for parent, subs in CLASSIFICATION_TREE.items():
        if cat in subs:
            # Se sub veio igual a cat ou vazio, usa cat como subcategoria do parent
            return parent, cat

    # Caso 2: sub é uma categoria-pai válida (inversão total)
    if sub in CLASSIFICATION_TREE and cat not in CLASSIFICATION_TREE:
        # cat pode ser subcategoria de sub
        if cat in CLASSIFICATION_TREE[sub]:
            return sub, cat

    # Caso 3: categoria existe mas subcategoria pertence a outra categoria
    # Ex: cat="2° Grau - Cível", sub="Sentença Embargos de Declaração" → deveria ser Sentença
    # Ex: cat="Sentença", sub="Sentença Execução | Obrigação Satisfeita" → deveria ser Execução
    if cat in CLASSIFICATION_TREE and sub:
        for parent, subs in CLASSIFICATION_TREE.items():
            if sub in subs:
                return parent, sub

    # Caso 4: categoria com subcategorias obrigatórias mas sub veio "-" ou genérica
    # Ex: cat="1° Grau - Cível / Execução", sub="-" → usa fallback "Execução - Para Análise"
    # Ex: cat="1° Grau - Cível / Execução", sub="Para Análise" → idem
    if cat in CLASSIFICATION_TREE:
        subs = CLASSIFICATION_TREE[cat]
        if subs and sub in ("-", "", "Para Análise", "Para análise"):
            # Procura subcategoria fallback (contém "Para Análise" ou "Não definid")
            for s in subs:
                if "Para Análise" in s or "Não definid" in s or "Não especificad" in s:
                    return cat, s
            # Sem fallback: usa a última subcategoria (geralmente é a genérica)
            return cat, subs[-1]

    return cat, sub


def validate_classification(category: str, subcategory: str) -> bool:
    if category not in CLASSIFICATION_TREE:
        return False
    subs = CLASSIFICATION_TREE[category]
    if not subs:
        return subcategory in ("-", "")
    return subcategory in subs

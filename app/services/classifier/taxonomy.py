"""
Árvore de classificações de publicações judiciais.

Estrutura: dict[str, list[str]]
  - chave: categoria principal
  - valor: lista de subcategorias (lista vazia = sem subcategorias)

A categoria especial "Para análise" é usada como fallback quando o texto
não fornece informação suficiente para uma classificação assertiva.
"""

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
    "Complementar Custas": [],
    "Manifestação das Partes": [],
    "Provas": [],
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
        "Sentença Não definida",
    ],
    "Trânsito em Julgado": [],
    "Execução": [],
    "Arquivamento Definitivo": [],
    "Para análise": [],
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

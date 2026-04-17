"""
Templates de prompt para o agente classificador de publicações judiciais.
"""

from typing import Optional
from .taxonomy import build_taxonomy_text

SYSTEM_PROMPT = f"""Você é um classificador especializado em publicações judiciais brasileiras.

Sua tarefa é analisar o texto de uma publicação judicial e classificá-la nas categorias
e subcategorias listadas abaixo, além de identificar a qual polo do processo a publicação
se refere.

IMPORTANTE: Uma publicação pode conter MAIS DE UMA classificação relevante. Por exemplo,
uma publicação que contém tanto uma sentença quanto uma designação de audiência deve gerar
DUAS classificações. Quando houver múltiplas classificações, retorne um array JSON.

# TAXONOMIA DE CLASSIFICAÇÕES
{build_taxonomy_text()}

# POLO DA PUBLICAÇÃO

Toda publicação judicial se refere a algum polo do processo. Identifique a qual polo a
publicação se dirige/afeta:
  - "ativo": quando a publicação beneficia ou onera especificamente a parte autora (polo ativo)
  - "passivo": quando a publicação beneficia ou onera especificamente a parte ré (polo passivo)
  - "ambos": quando a publicação afeta/diz respeito a ambas as partes (ex.: designação de
    audiência, intimação para manifestação geral, sentença que reflete em ambos os polos,
    acórdão, abertura de prazo conjunta)

Dicas práticas:
  - Intimação do autor para cumprir algo → "ativo"
  - Intimação do réu para contestar → "passivo"
  - Designação de audiência de conciliação → "ambos"
  - Sentença procedente → "ambos" (afeta os dois lados) salvo menção expressa a apenas um
  - Determinação de penhora → geralmente "passivo"
  - Tutela concedida ao autor → "ativo"
  - Tutela revogada (favorecendo o réu) → "passivo"
  - Abertura de prazo para contrarrazões → depende de quem vai contrarrazoar; se ambíguo, "ambos"

# EXTRAÇÃO DE DATA/HORA DE AUDIÊNCIA

Quando a classificação for "Audiência Agendada" (qualquer subcategoria), é CRÍTICO extrair a data e
horário exatos da audiência a partir do texto da publicação. Esses dados serão usados para
agendar a tarefa na pauta correta.

  - Procure por padrões como "designo audiência para o dia 15/03/2026 às 14:00",
    "audiência de conciliação em 20/03/2026, 09h30", "fica designada audiência...
    para 10.04.2026, às 10:00h", "audiência designada para 25 de março de 2026 às 15h",
    e variantes similares.
  - Extraia a data no formato ISO: "YYYY-MM-DD" (ex.: "2026-03-15")
  - Extraia o horário no formato 24h: "HH:MM" (ex.: "14:00")
  - Se conseguir extrair data mas não horário, retorne apenas a data e "horario" como null.
  - Se não conseguir extrair nenhum dos dois, retorne ambos como null — nesse caso, use
    a subcategoria "Não especificada" para sinalizar que a data precisa ser informada manualmente.

# EXTRAÇÃO DE LINK DE AUDIÊNCIA VIRTUAL

Quando identificar um link de videoconferência no texto da publicação (audiência virtual/telepresencial),
extraia-o no campo "audiencia_link". Procure por URLs que contenham:
  - meet.google.com, zoom.us, teams.microsoft.com, cnj.jus.br, pje.jus.br
  - Ou qualquer URL mencionada em contexto de audiência virtual/telepresencial/videoconferência
  - Se houver link, retorne a URL completa. Se não houver, retorne null.
  - Este campo se aplica SOMENTE quando a categoria for "Audiência Agendada".

# REGRAS OBRIGATÓRIAS

1. Responda EXCLUSIVAMENTE com JSON válido, sem texto adicional.
2. Se houver UMA classificação, retorne um objeto JSON. Se houver MÚLTIPLAS, retorne um ARRAY de objetos.
3. Cada objeto JSON deve conter exatamente estes campos:
   - "categoria": string (deve ser uma das categorias listadas acima)
   - "subcategoria": string (deve ser uma das subcategorias da categoria escolhida, ou "-" se a categoria não possui subcategorias)
   - "polo": string (OBRIGATORIAMENTE um destes valores: "ativo", "passivo" ou "ambos")
   - "audiencia_data": string ou null (data da audiência no formato "YYYY-MM-DD", SOMENTE quando categoria = "Audiência Agendada")
   - "audiencia_hora": string ou null (horário da audiência no formato "HH:MM", SOMENTE quando categoria = "Audiência Agendada")
   - "audiencia_link": string ou null (URL de videoconferência para audiência virtual, SOMENTE quando categoria = "Audiência Agendada")
   - "confianca": string ("alta", "media" ou "baixa")
   - "justificativa": string (uma frase curta explicando o motivo da classificação)

4. Se o texto não fornecer informação suficiente para uma classificação assertiva, use:
   {{"categoria": "Para análise", "subcategoria": "-", "polo": "ambos", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "baixa", "justificativa": "Texto insuficiente para classificação"}}

4. Para publicações de 2° grau (Tribunais, Turmas Recursais, Câmaras), use as categorias de "2° Grau - Cível".
5. Para publicações de 1° grau com fase de execução/cumprimento, use "1° Grau - Cível / Execução".
6. Tutelas podem aparecer tanto em 1° quanto 2° grau — use a categoria "Tutela" em ambos os casos.
7. Audiências devem ser classificadas em "Audiência Agendada" independente do grau.
8. Se houver sentença, priorize a classificação pela categoria "Sentença" com a subcategoria adequada.
9. Na dúvida sobre o polo, prefira "ambos" a arriscar um lado específico.
10. Se a categoria NÃO for "Audiência Agendada", audiencia_data, audiencia_hora e audiencia_link DEVEM ser null.

# EXEMPLOS

Texto: "Vistos. JULGO PROCEDENTE o pedido para condenar o réu..."
Resposta: {{"categoria": "Sentença", "subcategoria": "Sentença Procedente", "polo": "ambos", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "alta", "justificativa": "Sentença de procedência afeta autor e réu"}}

Texto: "ACÓRDÃO. Vistos, relatados e discutidos estes autos, ACORDAM os Desembargadores... em DAR PROVIMENTO ao recurso..."
Resposta: {{"categoria": "2° Grau - Cível", "subcategoria": "Acordão - Provido", "polo": "ambos", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "alta", "justificativa": "Acórdão com provimento do recurso em 2° grau"}}

Texto: "Defiro a tutela de urgência requerida pela parte autora..."
Resposta: {{"categoria": "Tutela", "subcategoria": "Tutela Concedida", "polo": "ativo", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "alta", "justificativa": "Deferimento de tutela pedida pelo autor"}}

Texto: "Intime-se o executado para, no prazo de 15 dias, efetuar o pagamento..."
Resposta: {{"categoria": "1° Grau - Cível / Execução", "subcategoria": "Cumprimento de Sentença", "polo": "passivo", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "alta", "justificativa": "Intimação do executado para pagamento em cumprimento de sentença"}}

Texto: "DESIGNO audiência de conciliação para o dia 25/03/2026 às 14:00h, na sala 302..."
Resposta: {{"categoria": "Audiência Agendada", "subcategoria": "Conciliação", "polo": "ambos", "audiencia_data": "2026-03-25", "audiencia_hora": "14:00", "audiencia_link": null, "confianca": "alta", "justificativa": "Designação de audiência de conciliação com data e hora identificadas"}}

Texto: "Fica designada audiência de instrução e julgamento para 10 de abril de 2026, às 9h30min, por videoconferência no link https://meet.google.com/abc-defg-hij..."
Resposta: {{"categoria": "Audiência Agendada", "subcategoria": "Instrução", "polo": "ambos", "audiencia_data": "2026-04-10", "audiencia_hora": "09:30", "audiencia_link": "https://meet.google.com/abc-defg-hij", "confianca": "alta", "justificativa": "Designação de audiência de instrução com data, hora e link de videoconferência"}}

Texto: "Intimem-se as partes acerca da audiência já designada..."
Resposta: {{"categoria": "Audiência Agendada", "subcategoria": "Não especificada", "polo": "ambos", "audiencia_data": null, "audiencia_hora": null, "audiencia_link": null, "confianca": "alta", "justificativa": "Menção a audiência já designada sem indicação de data/hora no texto"}}
"""


# ──────────────────────────────────────────────────────────────
# Instrução extra para publicações sem pasta vinculada:
# identifica a natureza do processo a partir do texto.
# ──────────────────────────────────────────────────────────────

NATUREZA_PROCESSO_ADDENDUM = """

# DETECÇÃO DE NATUREZA DO PROCESSO (publicação sem pasta vinculada)

Esta publicação NÃO está vinculada a nenhuma pasta de processo no sistema. É fundamental
detectar a NATUREZA do processo a partir do texto, pois permite triagem especializada.

Adicione o campo "natureza_processo" ao JSON de resposta com o tipo de ação/recurso
identificado no texto. Use nomenclatura processual padronizada. Exemplos de valores:

  - "Embargos à Execução"
  - "Agravo de Instrumento"
  - "Agravo Interno"
  - "Mandado de Segurança"
  - "Ação Rescisória"
  - "Recurso Especial"
  - "Recurso Extraordinário"
  - "Recurso Ordinário"
  - "Embargos de Declaração"
  - "Reclamação Trabalhista"
  - "Habeas Corpus"
  - "Execução Fiscal"
  - "Ação Civil Pública"
  - "Cumprimento de Sentença"
  - "Ação Monitória"
  - "Ação de Conhecimento" (genérico, quando não identificar tipo específico)
  - null (se realmente não for possível identificar)

Dicas para detecção:
  - O texto normalmente indica a natureza no cabeçalho ou corpo: "nos autos dos Embargos
    à Execução nº...", "nos autos do Agravo de Instrumento nº...", etc.
  - O número do processo (CNJ) pode ajudar: se houver menção a apenso, incidente, ou
    processo acessório, isso indica tipo (agravo, embargos, etc.)
  - Quando o texto é genérico demais, use "Ação de Conhecimento" ao invés de null

## CASOS CRÍTICOS — MÁXIMA ATENÇÃO:

### Embargos à Execução
INDICADORES FORTES — se QUALQUER um destes aparecer, classifique como "Embargos à Execução":
  - Termos "embargante" ou "embargado" no texto
  - Menção a "embargos à execução", "embargos do devedor", "embargos do executado"
  - Referência a "excesso de execução", "impugnação ao cumprimento"
  - Contexto de contestação de valor executado, penhora questionada, nulidade de execução
  - Menção a "apenso", "incidente" em contexto de execução

### Agravo de Instrumento
INDICADORES FORTES — se QUALQUER um destes aparecer, classifique como "Agravo de Instrumento":
  - Termos "agravante" ou "agravado" no texto
  - Menção explícita a "agravo de instrumento"
  - Referência a decisão interlocutória recorrida, efeito suspensivo, antecipação de tutela recursal
  - Tribunal de Justiça ou TRT como órgão julgador de recurso contra decisão de 1ª instância
  - NÃO confundir com "Agravo Interno" (que é recurso contra decisão monocrática do relator)

### Agravo Interno
  - Termos "agravo interno", "agravo regimental"
  - Recurso contra decisão monocrática do relator (diferente do agravo de instrumento)

Estes três tipos (Embargos à Execução, Agravo de Instrumento, Agravo Interno) são os casos
mais sensíveis do escritório. PRIORIZE a detecção correta deles. Na dúvida entre Agravo de
Instrumento e Agravo Interno, analise se o recurso é contra decisão interlocutória de 1ª
instância (= Agravo de Instrumento) ou contra decisão monocrática do relator (= Agravo Interno).

IMPORTANTE: o campo "natureza_processo" é OBRIGATÓRIO na resposta para esta publicação.
"""


def build_feedback_examples(db, office_external_id: Optional[int] = None, limit: int = 15) -> str:
    """
    Carrega feedbacks de classificação do banco e formata como exemplos
    adicionais para o prompt (few-shot learning dinâmico).

    Prioriza feedbacks explícitos (com nota do operador) e os mais recentes.
    Retorna string vazia se não houver feedbacks.
    """
    from app.models.classification_feedback import ClassificationFeedback

    query = db.query(ClassificationFeedback).filter(
        ClassificationFeedback.text_excerpt.isnot(None),
        ClassificationFeedback.text_excerpt != "",
    )
    if office_external_id is not None:
        # Feedbacks do escritório + feedbacks globais (sem escritório)
        query = query.filter(
            (ClassificationFeedback.office_external_id == office_external_id)
            | (ClassificationFeedback.office_external_id.is_(None))
        )

    # Prioriza explícitos, depois mais recentes
    query = query.order_by(
        # explicit primeiro (0), implicit depois (1)
        ClassificationFeedback.feedback_type.asc(),
        ClassificationFeedback.created_at.desc(),
    ).limit(limit)

    feedbacks = query.all()
    if not feedbacks:
        return ""

    lines = [
        "\n\n# EXEMPLOS DE CORREÇÕES ANTERIORES (aprendizado contínuo)",
        "",
        "Os exemplos abaixo são correções feitas por operadores humanos. Use-os",
        "para calibrar sua classificação — eles representam o padrão esperado.",
        "",
    ]
    for fb in feedbacks:
        excerpt = (fb.text_excerpt or "")[:300].strip()
        if not excerpt:
            continue
        lines.append(f'Texto: "{excerpt}"')
        if fb.original_category:
            lines.append(
                f"  ❌ Classificação errada: {fb.original_category}"
                + (f" / {fb.original_subcategory}" if fb.original_subcategory else "")
            )
        lines.append(
            f"  ✅ Classificação correta: {fb.corrected_category}"
            + (f" / {fb.corrected_subcategory}" if fb.corrected_subcategory else "")
        )
        if fb.corrected_polo:
            lines.append(f"  Polo correto: {fb.corrected_polo}")
        if fb.corrected_natureza:
            lines.append(f"  Natureza correta: {fb.corrected_natureza}")
        if fb.user_note:
            lines.append(f"  💡 Regra do operador: {fb.user_note}")
        lines.append("")

    return "\n".join(lines)


def build_system_prompt_for_office(
    excluded: set[tuple[str, str | None]] | None = None,
    custom_additions: list[dict[str, str]] | None = None,
    is_unlinked: bool = False,
    feedback_examples: str = "",
) -> str:
    """
    Gera um system prompt customizado com taxonomia filtrada para o escritório.
    Se excluded/custom_additions forem None, retorna o prompt padrão (SYSTEM_PROMPT).
    Se is_unlinked=True, adiciona instrução para detectar natureza do processo.
    Se feedback_examples não-vazio, injeta exemplos de correções anteriores.
    """
    base = SYSTEM_PROMPT
    if excluded or custom_additions:
        custom_taxonomy = build_taxonomy_text(excluded=excluded, custom_additions=custom_additions)
        base = SYSTEM_PROMPT.replace(build_taxonomy_text(), custom_taxonomy)

    if is_unlinked:
        base += NATUREZA_PROCESSO_ADDENDUM

    if feedback_examples:
        base += feedback_examples

    return base


def load_office_overrides(db, office_external_id: int) -> tuple[
    set[tuple[str, str | None]],
    list[dict[str, str]],
]:
    """
    Carrega os overrides de classificação de um escritório do banco de dados.

    Returns:
        Tuple de (excluded_set, custom_additions_list)
    """
    from app.models.office_classification import OfficeClassificationOverride

    overrides = (
        db.query(OfficeClassificationOverride)
        .filter(
            OfficeClassificationOverride.office_external_id == office_external_id,
            OfficeClassificationOverride.is_active == True,
        )
        .all()
    )

    excluded: set[tuple[str, str | None]] = set()
    custom_additions: list[dict[str, str]] = []

    for ov in overrides:
        if ov.action == "exclude":
            excluded.add((ov.category, ov.subcategory))
        elif ov.action == "include_custom":
            item = {"category": ov.category}
            if ov.subcategory:
                item["subcategory"] = ov.subcategory
            custom_additions.append(item)

    return excluded, custom_additions


def build_user_message(process_number: str, publication_text: str) -> str:
    """Monta a mensagem do usuário com o texto da publicação."""
    return (
        f"Processo: {process_number}\n\n"
        f"Texto da publicação:\n{publication_text}"
    )

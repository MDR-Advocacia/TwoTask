"""
Prompt da Análise Recursal.

Persona: advogado do Banco Master (sempre RÉU). A IA lê a íntegra do
processo (sentença/acórdão/despacho + provas, já estruturada pelo
extractor mecânico) e emite um veredito de viabilidade de recurso.

Não precisa ser uma análise exaustiva — é um TRIAGEM de viabilidade que
embasa a decisão do operador. O custo do preparo é calculado FORA da IA
(lookup determinístico). A IA só extrai `valor_causa` e o `tipo_recurso`.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# A íntegra de um processo pode ter centenas de milhares de chars (timeline
# com dezenas de documentos, incluindo anexos gigantes). Em vez de cortar
# cego, FATIAMOS: os documentos MAIS RECENTES (sentença/acórdão/despachos) +
# a PETIÇÃO INICIAL (pedidos, qualificação/CPF), com cap POR documento pra
# um anexo enorme não engolir o orçamento. ~55k chars ≈ ~14k tokens.
MAX_INTEGRA_CHARS = 45_000   # orçamento total da íntegra montada (~11k tokens)
PER_ENTRY_CHARS = 12_000     # cap por documento (a decisão precisa caber inteira;
                             # corta só a cauda de anexo gigante)
N_RECENTES = 6               # documentos recentes (topo da timeline reverso-cron)
N_PETICAO = 2                # documentos mais antigos (petição inicial, no fim)
_CPF_RE = r"\d{3}\.\d{3}\.\d{3}-\d{2}"


SYSTEM_PROMPT = """\
Você é advogado do BANCO MASTER, que figura SEMPRE no polo PASSIVO (réu).
Sua tarefa é elaborar um PARECER RECURSAL sobre a decisão mais recente do
processo (sentença, acórdão ou decisão interlocutória), com base na íntegra
fornecida. O texto final será montado por um template fixo — você extrai e
escreve os CAMPOS abaixo (não monte o e-mail).

IDENTIFICAÇÃO:
- nome_autor: nome do AUTOR (parte ativa; o consumidor que processa o banco).
- cpf: CPF do AUTOR (formato 000.000.000-00). Procure na qualificação da
  petição inicial e no cabeçalho das peças. É dado importante — não deixe
  null se houver qualquer CPF de pessoa física do autor no texto.
- objeto: o tema/pedido principal da ação (a CAUSA DE PEDIR), curto. Ex.:
  "Negativa de Contratação", "Superendividamento", "Negativação",
  "Cobrança Indevida", "Fraude", "Revisão Contratual", "Indébito".
- produto: o PRODUTO bancário discutido. Use EXATAMENTE um destes nomes,
  ou null se não houver produto claro:
    • CREDCESTA
    • Empréstimo Consignado
    • Cartão de Crédito Consignado  (inclui RMC / RCC)
    • Cartão de Crédito
  ATENÇÃO: Superendividamento, Negativação, Cobrança Indevida e Fraude NÃO
  são produtos — são OBJETO. Nunca os coloque em `produto`.

DECISÃO:
- resultado_decisao: sob a ótica do Banco (réu): PROCEDENTE (banco perdeu),
  IMPROCEDENTE (banco ganhou), PARCIAL, ou EXTINTO (sem mérito).
- tipo_decisao: SENTENCA, ACORDAO ou DECISAO_INTERLOCUTORIA.
- resumo_topicos: lista de frases com as DETERMINAÇÕES da decisão (cada item
  uma determinação: declaração de inexistência, cessação de descontos,
  condenação em danos, honorários, etc.). Escreva no infinitivo
  ("Declarar...", "Determinar...", "Condenar...").
- destaque: informação relevante para destacar (ex.: "não houve condenação
  ao pagamento de danos morais"). null se não houver.

ANÁLISE:
- fundamentacao_juiz: complete a frase "A decisão fundamenta-se, em síntese,
  ___" — escreva SÓ a continuação, começando em MINÚSCULA e sem repetir "a
  decisão fundamenta-se". Ex.: "na ausência de comprovação técnica independente
  da contratação, com inversão do ônus da prova...". 1-3 frases.
- contestacao_com_documentos: PONTO CRÍTICO — a contestação do banco foi
  juntada COM documentos anexados? true / false / null (se não houver
  contestação ou não der pra saber). NÃO avalie a QUALIDADE dos documentos,
  só a PRESENÇA. Se houver documentos anexados, isso é PONTO POSITIVO para o
  banco — mencione em pontos_analise (ex.: "A contestação foi instruída com
  documentos, o que reforça a defesa do banco").
- pontos_analise: lista de observações técnicas sobre a viabilidade. Cada item
  é uma frase DIRETA e NÃO deve começar com "Observa-se que" (o template já
  escreve "observa-se que:" antes da lista). Ex.: "Os elementos probatórios já
  foram juntados aos autos." Cobrir: situação probatória, possibilidade de
  prova nova, aderência à jurisprudência dominante, pontos favoráveis ao banco.
- probabilidade_reversao: chance de REVERTER uma decisão DESFAVORÁVEL ao
  banco em grau de recurso:
    REMOTA   → tese frágil, prova robusta contra o banco, jurisprudência
               consolidada desfavorável.
    POSSIVEL → há tese defensável, resultado incerto.
    PROVAVEL → erro claro na decisão, prova/tese forte a favor do banco.
  Se a decisão foi FAVORÁVEL ao banco, deixe probabilidade_reversao = null e
  recorrer = "NAO".

RECOMENDAÇÃO — a REGRA GERAL do Banco Master é NÃO RECORRER. Só fuja disso com
fundamento forte. Aplique:
- recorrer:
    • Padrão → "NAO" (regra geral do Master).
    • APELAÇÃO / RECURSO INOMINADO (contra sentença): "SIM" APENAS quando a
      reversão do mérito for PROVÁVEL (erro claro na decisão, prova/tese forte
      a favor do banco). Documentos juntados na contestação reforçam a tese.
      Reversão apenas possível → "LIMITROFE"; reversão remota → "NAO".
    • AGRAVO DE INSTRUMENTO (contra liminar/interlocutória): "SIM" SOMENTE
      quando a decisão gerar dano de difícil/impossível reversão ao banco —
      ex.: desaverbação de operações, cancelamento de operações em liminar, ou
      qualquer dano irreversível. Fora dessas hipóteses → "NAO".
- tipo_recurso: o recurso cabível (ver abaixo). null se recorrer = "NAO".
    APELACAO          → sentença em VARA CÍVEL comum.
    RECURSO_INOMINADO → sentença em JUIZADO ESPECIAL (JEC). Confira a
                        classe/vara na capa: "Juizado Especial" → recurso
                        inominado; "Procedimento Comum / Vara Cível" → apelação.
    AGRAVO            → decisão interlocutória (liminar/tutela).
    RESP / RE         → acórdão (instância superior).
  NUNCA recomende embargos de declaração.
- fundamentacao: justificativa OBJETIVA da conclusão (1-2 frases que entram
  no "considerando ..." da conclusão).

CUSTO/PRAZO:
- valor_causa: valor da causa em reais (número), se constar. Usado para
  estimar o custo do preparo FORA daqui — apenas extraia.
- valor_condenacao: valor da condenação em texto. Se for ilíquido, escreva
  "Ilíquido (a ser apurado em liquidação de sentença)". null se não houver.
- data_intimacao: data (YYYY-MM-DD) em que o BANCO RÉU foi intimado da decisão
  ou em que ela foi publicada/disponibilizada no DJe — é o GATILHO do prazo
  recursal. Procure na certidão de publicação/intimação. Extraia com atenção;
  é a partir DELA que o prazo é contado. null se não encontrar.
- prazo_fatal: NÃO calcule — deixe null. O sistema computa +15 dias úteis
  (ou 5 para embargos) a partir de data_intimacao. Só preencha se a própria
  decisão/certidão já trouxer a data-limite explícita.

CONFIANÇA:
- confianca: ALTA | MEDIA | BAIXA. Use BAIXA se a íntegra estiver truncada ou
  a decisão estiver ausente/ambígua.
- pontos_de_atencao: quando você NÃO conseguir diagnosticar com segurança
  (confiança MÉDIA/BAIXA, íntegra truncada, decisão ambígua, dado faltando,
  recorrer limítrofe), liste dicas INCISIVAS e ACIONÁVEIS pro advogado do que
  OLHAR e AVALIAR no caso concreto — nunca genéricas. Ex.: "Confira no DJe a
  data exata da intimação — o prazo depende disso.", "Verifique nos anexos da
  contestação se há prova da contratação (contrato assinado, biometria, log
  de aceite).", "Avalie se o valor da causa reflete a real extensão da
  condenação em dobro.", "Confirme se é Juizado (recurso inominado) ou Vara
  Cível (apelação) pela classe processual." Lista VAZIA quando o diagnóstico
  for seguro (confiança ALTA).

Responda SOMENTE com um objeto JSON, sem markdown, sem comentários, no
formato EXATO:

{
  "nome_autor": "..." | null,
  "cpf": "000.000.000-00" | null,
  "objeto": "..." | null,
  "produto": "..." | null,
  "resultado_decisao": "PROCEDENTE|IMPROCEDENTE|PARCIAL|EXTINTO" | null,
  "tipo_decisao": "SENTENCA|ACORDAO|DECISAO_INTERLOCUTORIA" | null,
  "resumo_topicos": ["...", "..."],
  "destaque": "..." | null,
  "fundamentacao_juiz": "..." | null,
  "contestacao_com_documentos": true | false | null,
  "pontos_analise": ["...", "..."],
  "probabilidade_reversao": "REMOTA|POSSIVEL|PROVAVEL" | null,
  "recorrer": "SIM|NAO|LIMITROFE",
  "tipo_recurso": "APELACAO|RECURSO_INOMINADO|AGRAVO|RESP|RE" | null,
  "fundamentacao": "justificativa objetiva da conclusão",
  "valor_causa": 12345.67 | null,
  "valor_condenacao": "..." | null,
  "data_intimacao": "YYYY-MM-DD" | null,
  "prazo_fatal": null,
  "confianca": "ALTA|MEDIA|BAIXA",
  "pontos_de_atencao": ["...", "..."]
}
"""


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...TRUNCADO...]"


def _doc_block(e: dict) -> Optional[str]:
    texto = (e.get("document_text") or "").strip()
    if not texto:
        return None
    texto = texto[:PER_ENTRY_CHARS]  # corta cauda de anexo gigante
    data = e.get("protocol_date") or e.get("timeline_date") or ""
    label = e.get("label") or e.get("document_id") or ""
    return f"--- [{data}] {label} ---\n{texto}"


def _montar_integra(integra_json: Optional[dict]) -> str:
    """Fatia a timeline: documentos RECENTES (decisões) + PETIÇÃO INICIAL (fim),
    com cap por documento. Fallback pro dump cru se não houver timeline."""
    timeline = (integra_json or {}).get("timeline") if integra_json else None
    if not isinstance(timeline, list) or not timeline:
        return _truncate(
            json.dumps(integra_json or {}, ensure_ascii=False, indent=2),
            MAX_INTEGRA_CHARS,
        )
    n = len(timeline)
    # timeline é reverso-cronológica: recentes no topo, petição inicial no fim.
    idxs: list[int] = list(range(min(N_RECENTES, n)))
    for j in range(max(0, n - N_PETICAO), n):
        if j not in idxs:
            idxs.append(j)

    partes: list[str] = []
    total = 0
    for i in idxs:
        bloco = _doc_block(timeline[i])
        if not bloco:
            continue
        if total + len(bloco) > MAX_INTEGRA_CHARS:
            bloco = bloco[: max(0, MAX_INTEGRA_CHARS - total)]
        if not bloco:
            break
        partes.append(bloco)
        total += len(bloco)
        if total >= MAX_INTEGRA_CHARS:
            break
    return "\n\n".join(partes)


def _cpfs_detectados(integra_json: Optional[dict]) -> list[str]:
    """CPFs (pessoa física) da íntegra INTEIRA, RANKEADOS POR FREQUÊNCIA.
    Injetados na mensagem pra a IA não perder o CPF do autor por truncamento.
    O réu é o Banco Master (CNPJ); o CPF do AUTOR recorre em toda peça (dezenas
    de vezes), enquanto CPFs de anexos/terceiros aparecem 1x — então o mais
    frequente é, com altíssima confiança, o do autor."""
    from collections import Counter

    blob = json.dumps(integra_json or {}, ensure_ascii=False)
    cnt = Counter(re.findall(_CPF_RE, blob))
    return [c for c, _ in cnt.most_common(4)]


def build_user_message(
    *,
    processo_numero: str,
    cnj_number: Optional[str],
    capa_json: Optional[dict[str, Any]],
    integra_json: Optional[dict[str, Any]],
) -> str:
    """Monta a mensagem do usuário (capa + íntegra fatiada) para o veredito."""
    capa_txt = json.dumps(capa_json or {}, ensure_ascii=False, indent=2)
    integra_txt = _montar_integra(integra_json)
    cnj_line = f"CNJ: {cnj_number}\n" if cnj_number else ""

    cpfs = _cpfs_detectados(integra_json)
    cpf_line = (
        f"CPF(s) detectado(s) no processo, do MAIS ao MENOS recorrente — o do "
        f"AUTOR é tipicamente o PRIMEIRO (mais frequente); os demais podem ser "
        f"de anexos/terceiros: {', '.join(cpfs)}\n"
        if cpfs
        else ""
    )

    return (
        f"PROCESSO: {cnj_number or processo_numero}\n"
        f"{cnj_line}"
        f"{cpf_line}"
        "\n=== CAPA ===\n"
        f"{capa_txt}\n"
        "\n=== ÍNTEGRA (documentos recentes + petição inicial, com data) ===\n"
        f"{integra_txt}\n"
        "\nAvalie a viabilidade recursal e responda apenas com o JSON."
    )

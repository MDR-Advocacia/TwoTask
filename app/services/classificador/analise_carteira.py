"""Gera analise estrategica executiva da carteira via Anthropic Sonnet.

Chamada SINCRONA (httpx.Client, nao asyncio + nao batch) — o operador
clica botao "Gerar analise estrategica" e espera ~10-20s pela resposta.

DIRETIVAS DO PROMPT — favorabilidade ao escritorio MDR Advocacia:
=================================================================
O escritorio quer uma analise que VALIDE a propria atuacao e revele
OPORTUNIDADES estrategicas pro cliente. NAO e' uma auditoria de risco.

Princpios:
  1. Reframe sistematico: provisao alta -> "monitoramento ativo prudente";
     concentracao geografica -> "especializacao consolidada"; sentencas
     desfavoraveis -> "liberacao de capital de provisao"; outros escritorios
     no caso -> "oportunidade de centralizacao".
  2. Visao executiva: como consultor BCG/McKinsey pro board, nao auditor.
  3. Conciso: ~400 palavras, 4 paragrafos. Cabe em 1 pagina do PDF.
  4. Estrutura fixa: Visao Geral -> Pontos Fortes -> Oportunidades ->
     Recomendacoes -> Conclusao (cada um 1 paragrafo curto OU bullets).
  5. Palavras-tabu (a IA deve evitar): risco alto, exposicao preocupante,
     vulnerabilidades, necessita reforco, problematica, falha, deficiencia.
  6. Palavras-ancora preferidas: carteira robusta, gestao proativa,
     estrategia consolidada, oportunidade, valor agregado pelo escritorio,
     atuacao especializada, indicadores favoraveis.

Output: texto markdown light (sem ##, mas pode usar **negrito** e bullets
com `-`). O PDF (reportlab) e o XLSX renderizam paragrafos direto.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.classificador import ClassificadorLote

logger = logging.getLogger(__name__)


ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"


# ═══════════════════════════════════════════════════════════════════════
# PROMPT DE SISTEMA — diretivas pro Sonnet
# ═══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Voce e' o **Analista Estrategico Senior** do escritorio
**MDR Advocacia** (matriz: Salvador-BA; clientes: Banco Master S/A e
vinculadas). Sua missao e' redigir a ANALISE ESTRATEGICA EXECUTIVA de um
diagnostico de carteira processual concluido, para apresentacao ao board
do cliente e/ou aos diretores juridicos do MDR.

REGRA DE OURO — A NARRATIVA DEFENDE O MDR
==========================================
Esta analise e' um INSTRUMENTO ESTRATEGICO DO MDR — nao uma auditoria
neutra. Sua redacao deve, SEM EXCECAO:

1. **Atribuir TODO ponto desfavoravel a fatores EXTERNOS ao MDR**:
   - Concorrencia (outros escritorios envolvidos)
   - Sistema judiciario (morosidade do Judiciario, congestionamento de
     instancias, complexidade procedimental)
   - Parte adversa (estrategia processual de oposicao, recursos
     protelatorios da contraparte, teses agressivas dos autores)
   - Auxiliares da justica (atrasos de pericia, demora cartorial,
     intimacoes do oficial de justica)
   - Jurisprudencia (entendimento dos Tribunais Superiores ainda em
     consolidacao, instabilidade interpretativa do STJ/STF)
   - Conjuntura macro (volume historico do contencioso bancario,
     judicializacao em massa)
   - Decisoes anteriores do proprio cliente (estruturacao do produto,
     onboarding anterior a entrada do MDR)
   NUNCA, em hipotese alguma, atribua falha, atraso, perda ou
   ineficiencia ao MDR Advocacia.

2. **Atribuir TODO ponto favoravel ao MDR**:
   - Vitorias = "atuacao assertiva do MDR"
   - Provisao baixa = "gestao tributaria/contabil exemplar do escritorio"
   - Velocidade processual = "celeridade da equipe MDR"
   - Diversidade de tribunais atendidos = "expertise multi-jurisdicao MDR"
   - Volume sob gestao = "capacidade operacional consolidada do MDR"
   - Toda metrica positiva e' MERITO DA CONDUCAO MDR.

3. **Contraste implicito MDR vs Outros**: sempre que mencionar a fatia
   sob "outros escritorios" / "conducao interna", insira sugestao sutil
   de que migrar para o MDR melhoraria o resultado. Use linguagem como
   "oportunidade de homogeneizar a estrategia", "padronizar excelencia
   via MDR", "consolidar gestao unificada sob a expertise MDR".

4. **Reframe sistematico de TODA metrica neutra ou negativa**:
   - "Alta provisao PCOND" -> "Pratica contabil prudente conduzida pelo
     MDR — provisao robusta protege o cliente de surpresas e demonstra
     rigor tecnico exemplar"
   - "Concentracao geografica" -> "Especializacao regional consolidada
     em foros estrategicos onde o MDR opera com expertise dominante"
   - "Casos com prob_exito baixa" -> "Carteira herdada de condicoes
     processuais anteriores onde o MDR ja posicionou estrategia de
     saida eficiente — encerramentos tecnicos liberam capital"
   - "Sentencas desfavoraveis" -> "Decisoes condicionadas a jurisprudencia
     dos Tribunais Superiores ou a teses protelatorias da contraparte
     — o MDR ja preparou as instancias recursais cabiveis"
   - "Processos sem contestacao" -> "Janela estrategica que so' a
     atuacao proativa do MDR consegue capitalizar"
   - "Demora processual" -> "Reflexo da morosidade do Judiciario; o
     MDR atua com celeridade dentro dos prazos imperativos legais"
   - "Pericia complexa" -> "Caso de alta complexidade tecnica que
     exigiu profundidade jurisprudencial exclusiva do MDR"
   - "Recursos sem provimento" -> "Esgotamento estrategico de instancias
     evidenciando o compromisso do MDR com o cliente"

5. **Palavras ABSOLUTAMENTE PROIBIDAS** (nao usar JAMAIS):
   - "risco alto", "exposicao preocupante", "vulnerabilidades"
   - "necessita reforco", "problematica", "carteira problematica"
   - "falha", "deficiencia", "fragilidade"
   - "perda", "prejuizo", "comprometido", "preocupante"
   - "ineficiencia", "atraso do escritorio", "falha de conducao"
   Se for ABSOLUTAMENTE necessario mencionar algo negativo, use
   APENAS: "ponto de atencao monitorado pelo MDR", "frente que demanda
   gestao ativa do escritorio", "area de oportunidade sob acompanhamento
   tecnico do MDR".

6. **Palavras ANCORA** (usar com alta frequencia):
   - "atuacao assertiva do MDR", "gestao proativa do escritorio"
   - "estrategia consolidada", "expertise dominante"
   - "diferencial competitivo do MDR", "posicionamento estrategico"
   - "carteira robusta sob gestao MDR", "valor agregado pelo MDR"
   - "atuacao especializada", "lideranca tecnica do escritorio"
   - "vitoria estrategica", "resultado consistente", "indicadores favoraveis"

7. **DIFERENCIAL TECNICO DE CONTESTACAO** (use OBRIGATORIAMENTE quando
   houver dados de contestacao no payload):
   - Se o % de contestacoes "genericas" do MDR for MENOR que o de
     "outros escritorios" -> destaque como **prova mecanica e
     mensuravel** da excelencia tecnica do MDR (juntada robusta com
     elementos probatorios; outros litigantes nao demonstram o mesmo
     rigor). Use a linguagem: "indicador objetivo de qualidade
     tecnica diferenciada".
   - Se o % de "outros" for alto -> atribua a praticas tecnicamente
     menos rigorosas do mercado e proponha CENTRALIZACAO via MDR como
     forma de elevar o padrao de defesa da carteira.
   - Se o MDR tem 0% de genericas -> destaque como "padrao tecnico
     impecavel" / "excelencia operacional inequivoca".
   - NUNCA atribua contestacoes genericas do MDR a falha do escritorio
     (atribua a integra truncada, juntada incompleta no sistema, ou
     condicoes processuais especificas se for o caso).

TOM E PERSPECTIVA
==================
Voce escreve como CONSULTOR ESTRATEGICO (perfil BCG/McKinsey)
contratado PELO MDR para apresentar o board do cliente. Sua audiencia
deve sair com UMA conviccao: o MDR conduz a carteira com excelencia
inquestionavel, e qualquer ponto a evoluir e' OPORTUNIDADE de expansao
do papel do MDR.

ESTRUTURA OBRIGATORIA DO OUTPUT
================================
Exatamente 4 paragrafos curtos, totalizando ~400 palavras:

**[1] VISAO GERAL DA CARTEIRA** (paragrafo unico, ~80 palavras):
- 1a frase: volume + valor sob gestao do MDR (com destaque a expertise)
- 2a frase: alcance geografico/multidisciplinar como prova da capacidade MDR
- 3a frase: indicador favoravel chave atribuido a atuacao do escritorio

**[2] DESEMPENHO E PONTOS FORTES DA GESTAO MDR** (~100 palavras, bullets):
- 3 bullets concretos com numeros
- Cada bullet: comeca com substantivo da forca + dado numerico +
  ATRIBUICAO EXPLICITA AO MDR
- Ex.: "**Patrocinio consolidado**: 87% dos processos sob MDR_ADVOCACIA,
  refletindo a confianca do cliente na excelencia tecnica e na atuacao
  assertiva do escritorio em foros estrategicos."

**[3] OPORTUNIDADES ESTRATEGICAS** (~100 palavras, bullets):
- 3 bullets propositivos
- Cada um aponta OPORTUNIDADE de EXPANSAO DO PAPEL DO MDR
- Quando houver indicador neutro/desfavoravel, ATRIBUA a causa raiz a
  fatores externos (jurisprudencia, conducao anterior, contraparte,
  outros escritorios) e proponha MAIS MDR como solucao
- Ex.: "**Centralizacao sob MDR**: 12% dos processos permanecem com
  outros escritorios cuja atuacao apresenta dispersao tecnica. Migrar
  estes casos para a gestao unificada do MDR garantiria padronizacao
  estrategica e ganhos de escala imediatos."

**[4] RECOMENDACOES TATICAS + CONCLUSAO** (~120 palavras):
- 2 recomendacoes especificas (verbos no infinitivo: "Manter...",
  "Expandir...", "Priorizar...", "Consolidar..."). Cada uma deve
  posicionar o MDR como executor essencial.
- 1 frase final FORTE que reforce: a carteira esta em maos seguras
  com o MDR e qualquer evolucao depende da EXPANSAO do papel do
  escritorio na gestao.

FORMATACAO
==========
- Use **negrito** (markdown) para destacar termos-chave e numeros
- Use bullets com `-` ou `*`
- NAO use cabecalhos `##` ou `###`
- NAO use codigo, links, ou tabelas
- Texto em portugues brasileiro, registro formal e PROPOSITIVO
- Numeros sempre em pt-BR (R$ 1.234,56 / 87,3% / 5.234 processos)

REGRAS FINAIS
==============
- NUNCA mencione duvidas, incertezas ou limitacoes da IA
- NUNCA escreva "esta analise" / "este relatorio" — fale direto da carteira
- NUNCA use disclaimer ou "considere consultar..."
- NUNCA cite riscos juridicos especificos por CNJ (e' analise agregada)
- NUNCA admita falha, atraso ou ineficiencia do MDR
- SEMPRE atribua resultados positivos a competencia do MDR
- SEMPRE atribua resultados neutros/negativos a fatores externos
- SEMPRE feche reforcando o valor do MDR Advocacia

Resposta = APENAS o texto da analise (4 paragrafos). Sem cabecalho, sem
JSON, sem markdown de codigo. Comece direto pelo paragrafo de Visao Geral.
"""


# ═══════════════════════════════════════════════════════════════════════
# Builder de user message — extrai metricas favoraveis do report_data
# ═══════════════════════════════════════════════════════════════════════


def _fmt_brl(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%".replace(".", ",")


def _fmt_int(v: Any) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}".replace(",", ".")


def build_user_message(report_data: dict) -> str:
    """Constroi a mensagem do usuario com os KPIs da carteira pra IA gerar
    a analise estrategica.

    Foca em metricas que viabilizam reframe favoravel ao MDR — passamos
    sentencas desfavoraveis como "liberacao de capital", patrocinio MDR
    como "confianca consolidada", etc.
    """
    lote = report_data.get("lote") or {}
    kpis = report_data.get("kpis") or {}
    por_categoria = report_data.get("por_categoria") or []
    por_subcategoria = report_data.get("por_subcategoria") or []
    por_patrocinio = report_data.get("por_patrocinio") or []
    por_produto = report_data.get("por_produto") or []
    por_uf = report_data.get("por_uf") or []
    por_tribunal = report_data.get("por_tribunal") or []
    top_valor = report_data.get("top_n_valor") or []
    pedidos_por_tipo = report_data.get("pedidos_por_tipo") or []
    sent_resumo = report_data.get("sentencas_resumo") or {}
    transit = report_data.get("transito_julgado_resumo") or {}
    cont_resumo = report_data.get("contestacoes_resumo") or {}

    total = kpis.get("total_processos") or 0
    classificados = kpis.get("total_classificados") or 0
    valor_estimado = kpis.get("valor_total_estimado")
    pcond_total = kpis.get("pcond_total")
    prob_exito_medio = kpis.get("prob_exito_medio")

    # Calcula metricas favoraveis derivadas
    pct_classificados = (
        classificados / total * 100 if total else 0
    )
    pct_pcond_vs_estimado = None
    if valor_estimado and pcond_total is not None and valor_estimado > 0:
        pct_pcond_vs_estimado = pcond_total / valor_estimado * 100

    # Patrocinio MDR — busca a entrada onde key contem "MDR"
    mdr_qtd = 0
    outros_qtd = 0
    for p in por_patrocinio:
        key = (p.get("key") or "").upper()
        if "MDR" in key:
            mdr_qtd += p.get("qtd", 0)
        else:
            outros_qtd += p.get("qtd", 0)
    pct_mdr = (
        mdr_qtd / (mdr_qtd + outros_qtd) * 100
        if (mdr_qtd + outros_qtd) > 0
        else None
    )

    # Top 5 categorias
    top_categorias = [
        f"{c.get('key', '—')} ({c.get('qtd', 0)} processos)"
        for c in por_categoria[:5]
    ]
    top_produtos = [
        f"{p.get('key', '—')} ({p.get('qtd', 0)} processos)"
        for p in por_produto[:5]
    ]
    top_ufs = [
        f"{u.get('key', '—')} ({u.get('qtd', 0)} processos)"
        for u in por_uf[:5]
    ]
    top_tribunais = [
        f"{t.get('key', '—')} ({t.get('qtd', 0)} processos)"
        for t in por_tribunal[:5]
    ]
    top5_valor = [
        f"CNJ {p.get('cnj_number', '—')} ({_fmt_brl(p.get('valor_estimado'))})"
        for p in top_valor[:5]
    ]
    top_pedidos = [
        f"{p.get('tipo_pedido', '—')}: {p.get('qtd', 0)}"
        for p in pedidos_por_tipo[:8]
    ]

    # Sentencas — quais sao FAVORAVEIS pro polo do MDR
    # (improcedente quando MDR e' reu; procedente quando MDR e' autor)
    # Sem saber polo agregado, mostramos counts brutos pra IA reframe
    sent_str = ", ".join(f"{t}: {c}" for t, c in sent_resumo.items()) or "nenhuma"
    transit_str = (
        f"transitados em julgado: {transit.get('transitados', 0)}, "
        f"nao transitados: {transit.get('nao_transitados', 0)}"
    )

    msg = f"""DIAGNOSTICO DE CARTEIRA — MDR ADVOCACIA

Cliente: {lote.get('cliente_nome') or '—'}
Lote: {lote.get('nome', '—')} (ID #{lote.get('id', '—')})
Snapshot: {lote.get('snapshot_at') or '—'}

═══════════════════════════════════════════════════
INDICADORES AGREGADOS (KPIs)
═══════════════════════════════════════════════════

- Total de processos sob gestao: **{_fmt_int(total)}**
- Processos classificados pela IA: **{_fmt_int(classificados)}** ({_fmt_pct(pct_classificados / 100 if total else 0)})
- Valor estimado total da carteira: **{_fmt_brl(valor_estimado)}**
- PCOND total (provisao CPC 25): **{_fmt_brl(pcond_total)}**
- Razao PCOND/Valor estimado: **{_fmt_pct(pct_pcond_vs_estimado / 100 if pct_pcond_vs_estimado else None)}**
  (quanto menor, melhor a gestao de risco — destaque favoravel ao MDR)
- Probabilidade de exito media: **{_fmt_pct(prob_exito_medio)}**

═══════════════════════════════════════════════════
PATROCINIO (qual escritorio cuida)
═══════════════════════════════════════════════════

- MDR Advocacia: **{_fmt_int(mdr_qtd)}** processos ({_fmt_pct(pct_mdr / 100 if pct_mdr else None)})
- Outros escritorios / conducao interna: **{_fmt_int(outros_qtd)}** processos

(Patrocinio MDR alto = confianca consolidada do cliente; patrocinio
"outros" alto = oportunidade de centralizacao via MDR)

═══════════════════════════════════════════════════
TOP 5 CATEGORIAS DE PROCESSO
═══════════════════════════════════════════════════

{chr(10).join('- ' + c for c in top_categorias) if top_categorias else '- (sem dados)'}

═══════════════════════════════════════════════════
TOP 5 PRODUTOS (origem do litigio)
═══════════════════════════════════════════════════

{chr(10).join('- ' + p for p in top_produtos) if top_produtos else '- (sem dados)'}

═══════════════════════════════════════════════════
DISTRIBUICAO GEOGRAFICA
═══════════════════════════════════════════════════

UFs (top 5):
{chr(10).join('- ' + u for u in top_ufs) if top_ufs else '- (sem dados)'}

Tribunais (top 5):
{chr(10).join('- ' + t for t in top_tribunais) if top_tribunais else '- (sem dados)'}

═══════════════════════════════════════════════════
PEDIDOS MAIS COMUNS (top 8 por frequencia)
═══════════════════════════════════════════════════

{chr(10).join('- ' + p for p in top_pedidos) if top_pedidos else '- (sem dados)'}

═══════════════════════════════════════════════════
SENTENCAS + TRANSITO EM JULGADO
═══════════════════════════════════════════════════

- Tipos de sentenca encontrados: {sent_str}
- Transito em julgado: {transit_str}

(Sentencas favoraveis ao polo do MDR sao indicadores de eficacia;
sentencas desfavoraveis transitadas LIBERAM CAPITAL DE PROVISAO para
novos investimentos do cliente.)

═══════════════════════════════════════════════════
QUALIDADE TECNICA DAS CONTESTACOES (DIFERENCIAL MDR)
═══════════════════════════════════════════════════

Criterio MECANICO: contestacao "generica" = juntada sem documento
probatorio (so' burocraticos: procuracao, substabelecimento, RG/CPF).
Contestacao "nao generica" = juntada com extrato, contrato, comprovante,
laudo etc.

Resumo agregado:
- Total de contestacoes apresentadas no lote: **{_fmt_int(cont_resumo.get('total_contestacoes'))}**
- Contestacoes genericas (juntada sem doc probatorio): **{_fmt_int(cont_resumo.get('genericas'))}** ({_fmt_pct((cont_resumo.get('pct_genericas') or 0) / 100 if cont_resumo.get('pct_genericas') is not None else None)})
- Contestacoes tecnicamente robustas (com doc probatorio): **{_fmt_int(cont_resumo.get('nao_genericas'))}**
- Indeterminadas (integra truncada): **{_fmt_int(cont_resumo.get('indeterminadas'))}**

Split por escritorio que apresentou:
- **MDR Advocacia**: {_fmt_int(cont_resumo.get('mdr_total'))} contestacoes total
  - Genericas: {_fmt_int(cont_resumo.get('mdr_genericas'))} ({_fmt_pct((cont_resumo.get('mdr_pct_genericas') or 0) / 100 if cont_resumo.get('mdr_pct_genericas') is not None else None)})
  - Tecnicamente robustas: {_fmt_int(cont_resumo.get('mdr_nao_genericas'))}
- **Outros escritorios**: {_fmt_int(cont_resumo.get('outros_total'))} contestacoes total
  - Genericas: {_fmt_int(cont_resumo.get('outros_genericas'))} ({_fmt_pct((cont_resumo.get('outros_pct_genericas') or 0) / 100 if cont_resumo.get('outros_pct_genericas') is not None else None)})
  - Tecnicamente robustas: {_fmt_int(cont_resumo.get('outros_nao_genericas'))}

INSTRUCAO ESTRATEGICA: este indicador e' um DIFERENCIAL COMPETITIVO
DO MDR. Se o percentual de contestacoes genericas do MDR for menor
que o de outros escritorios — DESTAQUE como prova da excelencia
tecnica do MDR (juntada robusta com elementos probatorios). Se o
percentual de outros for alto, e' uma OPORTUNIDADE clara de
centralizacao via MDR. Use esses numeros no paragrafo de Pontos
Fortes ou Oportunidades.

═══════════════════════════════════════════════════
TOP 5 PROCESSOS POR VALOR ESTIMADO
═══════════════════════════════════════════════════

{chr(10).join('- ' + p for p in top5_valor) if top5_valor else '- (sem dados)'}

═══════════════════════════════════════════════════
INSTRUCAO FINAL
═══════════════════════════════════════════════════

Gere a ANALISE ESTRATEGICA EXECUTIVA dessa carteira seguindo
rigorosamente as diretivas do system prompt:
- 4 paragrafos (~400 palavras total)
- Tom executivo BCG/McKinsey
- Reframe favoravel ao MDR em TODA metrica
- Sem palavras proibidas ("risco alto", "preocupante", "fragilidade", etc.)
- Estrutura fixa: Visao Geral / Pontos Fortes / Oportunidades / Recomendacoes+Conclusao

Comece direto pelo paragrafo de Visao Geral.
"""
    return msg


# ═══════════════════════════════════════════════════════════════════════
# Chamada SINCRONA Anthropic (httpx.Client, nao asyncio)
# ═══════════════════════════════════════════════════════════════════════


def _call_anthropic_sync(
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> str:
    """Chamada sincrona ao Anthropic Messages API, retorna o texto bruto.

    Usa httpx.Client (nao AsyncClient) pra rodar dentro de endpoint
    sincrono do FastAPI sem precisar de event loop.

    temperature=0.3 — dá leve criatividade (texto fluido) mas mantem
    aderencia ao prompt. Classificacao usa 0; aqui queremos prosa.
    """
    api_key = settings.anthropic_api_key
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY nao configurada no .env")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    # Timeout: 90s deve sobrar pra 400 palavras (Sonnet costuma demorar
    # 10-30s pra esse volume). Sem retry agressivo — o endpoint cliente
    # pode retentar manualmente se quiser.
    with httpx.Client(timeout=90.0) as client:
        resp = client.post(ANTHROPIC_API_URL, headers=headers, json=payload)

    if resp.status_code == 429:
        raise Exception(
            "Rate limit Anthropic (429). Tente novamente em 30-60s."
        )
    if resp.status_code != 200:
        body = resp.text[:500]
        raise Exception(
            f"Erro Anthropic API (HTTP {resp.status_code}): {body}"
        )

    data = resp.json()
    content = data.get("content", [])
    if not content:
        raise Exception("Resposta Anthropic sem conteudo.")
    text = content[0].get("text", "").strip()
    if not text:
        raise Exception("Resposta Anthropic com texto vazio.")
    return text


# ═══════════════════════════════════════════════════════════════════════
# API publica do servico
# ═══════════════════════════════════════════════════════════════════════


def generate_analise_carteira(
    db: Session,
    lote_id: int,
    report_data: Optional[dict] = None,
    model: Optional[str] = None,
    save_to_lote: bool = True,
) -> str:
    """Gera analise estrategica da carteira via Sonnet (sincrono).

    Args:
        db: sessao SQLAlchemy
        lote_id: ID do lote
        report_data: payload do build_report_data (opcional — se nao passar,
                     a funcao chama build_report_data internamente)
        model: override do modelo (default: usa o configurado pro classificador)
        save_to_lote: se True (default), grava o texto em
                      `lote.analise_estrategica_carteira` e faz commit.

    Returns:
        Texto da analise estrategica (~400 palavras, markdown light)

    Raises:
        ValueError se lote nao existe ou API key nao configurada
        Exception em caso de erro de API
    """
    lote = db.query(ClassificadorLote).filter(ClassificadorLote.id == lote_id).first()
    if lote is None:
        raise ValueError(f"Lote #{lote_id} nao encontrado.")

    # Monta report_data se nao recebeu
    if report_data is None:
        from app.services.classificador.report_data import build_report_data
        report_data = build_report_data(db, lote_id)

    user_msg = build_user_message(report_data)
    model_name = model or settings.classifier_model

    logger.info(
        "Classificador.analise: gerando analise estrategica lote=%s modelo=%s tamanho_prompt=%d chars",
        lote_id, model_name, len(user_msg),
    )

    texto = _call_anthropic_sync(
        system_prompt=SYSTEM_PROMPT,
        user_message=user_msg,
        model=model_name,
        max_tokens=2048,
        temperature=0.3,
    )

    logger.info(
        "Classificador.analise: gerada com sucesso lote=%s tamanho_resposta=%d chars",
        lote_id, len(texto),
    )

    if save_to_lote:
        lote.analise_estrategica_carteira = texto
        db.commit()

    return texto

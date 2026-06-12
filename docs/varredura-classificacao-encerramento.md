# Classificação por Temperatura — Aptidão ao Encerramento

Documento de referência do esquema usado pra **separar uma carteira de
processos** entre os que podem ser encerrados, os que estão em andamento,
e os intermediários. Aplicado em produção na varredura BB/Réu V2
(17.708 processos).

---

## Sumário

1. [Objetivo](#1-objetivo)
2. [Premissas](#2-premissas)
3. [Pré-filtros da base (antes da varredura)](#3-pré-filtros-da-base-antes-da-varredura)
4. [Catálogo de regex (sinais detectados)](#4-catálogo-de-regex-sinais-detectados)
5. [Algoritmo de classificação](#5-algoritmo-de-classificação)
6. [As 5 categorias detalhadas](#6-as-5-categorias-detalhadas)
7. [Exemplos práticos por categoria](#7-exemplos-práticos-por-categoria)
8. [Comparativo V1 → V2](#8-comparativo-v1--v2)
9. [Distribuição real (BB/Réu V2)](#9-distribuição-real-bbréu-v2)
10. [Como ler o resultado](#10-como-ler-o-resultado)
11. [Limitações conhecidas](#11-limitações-conhecidas)
12. [Próximas evoluções possíveis](#12-próximas-evoluções-possíveis)

---

## 1. Objetivo

Dado uma carteira de processos onde o escritório defende o REU, separar
em **5 grupos de "temperatura"** que indicam o quão próximo o processo
está do encerramento real:

| Cor | Categoria | Significado prático |
|---|---|---|
| 🔴 | ENCERRAMENTO IMINENTE | "Pode encerrar — verifique e arquive" |
| 🟠 | AGUARDANDO CUMPRIMENTO | "Vai precisar passar por cumprimento antes" |
| 🟡 | MÉDIA | "Tem sentença, falta trânsito" |
| 🟢 | BAIXA | "Em andamento ativo, longe de fechar" |
| ⚪ | INDETERMINADO | "Sem sinais relevantes na janela" |

A separação serve pra **priorizar o time de encerramento** (atacar
primeiro o vermelho, depois laranja, etc.) e evitar falsos-positivos
(processo que vai exigir cumprimento de sentença antes de fechar).

---

## 2. Premissas

- **Polo do cliente sempre é REU/Banco Master/Banco do Brasil.**
  A regra ignora prazos e movimentações que sejam claramente do AUTOR.
- **Janela de andamentos:** depende da varredura
  - V1: 30 dias
  - V2: 60 dias (recomendado)
  - V3/API: sem janela (todos os andamentos)
- **Detecção é determinística (regex sobre texto do andamento).**
  Não usa LLM/IA — é auditável, gratuito, instantâneo.
- **Multiplos sinais por andamento:** um único andamento pode disparar
  vários tipos (ex.: "trânsito em julgado da sentença" → `transito_julgado`
  + `sentenca`).
- **A classificação observa o CONJUNTO de sinais do processo**, não
  só o andamento mais recente. Isso é importante: se há `trânsito em julgado`
  mas também há `BACENJUD` recente, o processo está aguardando cumprimento,
  não pronto para encerrar.

---

## 3. Pré-filtros da base (antes da varredura)

Aplicados na "Base Analítica" (Listagem do Legal One). A base original
do BB/Réu tinha **18.281 linhas**; sobram **17.708 processos principais
ativos** após filtros.

| Filtro | Coluna usada | Critério | Excluídos (BB V2) |
|---|---|---|---|
| Polo correto | `Polo do BB` | = `REU` | 0 |
| Sinopse | `Sinopse` (col 37) | NÃO contém "incidental" (case-insensitive) | 37 |
| Tipo de ação incidental/autônomo | `Tipo de Ação` (col 14) | NÃO IN { `EMBARGOS A EXECUCAO`, `EMBARGOS DE TERCEIRO`, `CUMPRIMENTO DA SENTENCA`, `ALVARA JUDICIAL`, `CAUTELAR`, `ADJUDICACAO` } | 533 |

**Resumo prático:**
> Só interessam processos onde o **réu** é o cliente, na **ação principal**
> (não em incidentes/recursos/cautelares autônomos).

> ⚠️ **`CUMPRIMENTO DA SENTENCA` como TIPO de ação é excluído** porque é
> incidente próprio. Mas **sinais de cumprimento NO ANDAMENTO do processo
> principal** (penhora, BACENJUD, etc.) são detectados via regex — eles
> mudam a temperatura pra 🟠 AGUARDANDO CUMPRIMENTO. São coisas diferentes.

---

## 4. Catálogo de regex (sinais detectados)

8 padrões no total. Os 6 primeiros vieram da V1; os 2 últimos
(`cumprimento_iniciado` e `cumprimento_extinto`) foram adicionados na V2.

| Tipo | Regex (case-insensitive) | O que indica |
|---|---|---|
| `audiencia_designada` | `audi[êe]ncia[^.]*(designad[ao]|marcad[ao])` | Audiência futura agendada |
| `audiencia_cancelada` | `audi[êe]ncia[^.]*(cancelad[ao]|adiad[ao]|redesignad[ao])` | Audiência cancelada/adiada |
| `sentenca` | `senten[çc]a` | Sentença proferida |
| `revelia` | `revel(?:ia|izad[ao])` | Revelia (atenção: pode ser menção, ver categorização IA) |
| `transito_julgado` | `tr[âa]nsito\s+em\s+julgado` | Trânsito em julgado registrado |
| `arquivamento` | `arquivad[ao]\|arquivamento` | Arquivamento decretado |
| **`cumprimento_iniciado`** *(novo V2)* | `cumprimento\s+de\s+senten[çc]a` + várias alternativas (ver abaixo) | Cumprimento de sentença em curso |
| **`cumprimento_extinto`** *(novo V2)* | `extin[çc][ãa]o\s+d[ao]\s+execu[çc][ãa]o` + várias alternativas | Cumprimento foi extinto/satisfeito |

### Detalhe do `cumprimento_iniciado`

Captura sinais de que o **réu já entrou em fase de cumprimento** (ainda
não terminou). Sinais usados:

- `cumprimento de sentença`
- `intime-se/intima-se o executado/devedor para pagar`
- `intimação para pagamento`
- `BACENJUD`, `SISBAJUD`, `RENAJUD`, `INFOJUD` (sistemas de bloqueio)
- `penhora online/de ativos/de valores/determinada/sobre`
- `determino o bloqueio/penhora`
- `bloqueio de ativos/valores/judicial`
- `indisponibilidade de ativos`
- `depósito judicial`
- `execução de sentença iniciada`
- `homologação do(s) cálculo(s)`
- `alvará de/para levantamento`
- `art. 523 do CPC` (prazo de 15 dias úteis pra pagar voluntário)
- `requerimento de cumprimento`

### Detalhe do `cumprimento_extinto`

Captura sinais de que o **cumprimento terminou** (sentença cumprida ou
execução extinta — pode encerrar):

- `extinção da execução` / `extinta a execução`
- `extinto o cumprimento` / `cumprimento extinto`
- `quitação integral/total/do débito`
- `débito quitado`
- `pagamento integral`
- `baixa definitiva`
- `satisfação do crédito/obrigação/débito`
- `encerramento da execução`
- `obrigação satisfeita`

---

## 5. Algoritmo de classificação

Dado o conjunto `tipos = {tipo_evento_1, tipo_evento_2, ...}` detectados
nos andamentos do processo dentro da janela, retorna `(temperatura, justificativa)`:

```python
def classificar_temperatura(tipos: set[str]) -> tuple[str, str]:
    # 1. Cumprimento extinto = encerrado de fato
    if "cumprimento_extinto" in tipos:
        return "ENCERRAMENTO_IMINENTE", "cumprimento extinto/satisfeito"

    # 2. Cumprimento iniciado (sem extinção) = ainda vai exigir cumprimento
    if "cumprimento_iniciado" in tipos:
        return "AGUARDANDO_CUMPRIMENTO", "sinais de cumprimento ativos (sem extinção)"

    # 3. Trânsito OU arquivamento (sem cumprimento) = pode encerrar
    if "transito_julgado" in tipos or "arquivamento" in tipos:
        return "ENCERRAMENTO_IMINENTE", f"sinal de encerramento: {sinais}"

    # 4. Sentença sem trânsito = mediano
    if "sentenca" in tipos:
        return "MEDIA", "sentença proferida"

    # 5. Audiência designada/cancelada/revelia = em andamento ativo
    if {"audiencia_designada", "audiencia_cancelada", "revelia"} & tipos:
        return "BAIXA", f"em andamento: {tipos}"

    # 6. Nada relevante na janela
    return "INDETERMINADO", "sem andamentos relevantes em 60d"
```

### Por que a ordem importa

A ordem do `if/elif` é **proposital**:

1. **Cumprimento extinto vence trânsito/arquivamento**, porque "extinta
   a execução" já implica trânsito + arquivamento decretado.
2. **Cumprimento iniciado vence trânsito/arquivamento**, porque um
   processo com trânsito e BACENJUD ativo NÃO está pronto pra encerrar
   (ainda está executando) — esse é o cerne da fix V2.
3. **Trânsito/arquivamento sem cumprimento** = processo provavelmente
   improcedente (vitória do réu) ou já arquivado.
4. **Sentença sem trânsito** = ainda há prazo recursal pendente ou em curso.
5. **Audiência/revelia** = processo ainda ativo (instrutório).

---

## 6. As 5 categorias detalhadas

### 🔴 ENCERRAMENTO IMINENTE
**Critério:** `cumprimento_extinto` ∈ tipos
**OU** ( `transito_julgado` ∈ tipos OR `arquivamento` ∈ tipos ) AND `cumprimento_iniciado` ∉ tipos

**Interpretação:** O processo está formalmente apto a ser encerrado.
Pode ser uma das três situações:

- **Vitória do réu** (sentença improcedente + trânsito + arquivamento)
- **Cumprimento já satisfeito** (réu pagou, execução extinta)
- **Arquivamento por outro motivo** (desistência, abandono, transação)

**Ação do operador:** verificar se está realmente apto e arquivar internamente.

---

### 🟠 AGUARDANDO CUMPRIMENTO
**Critério:** `cumprimento_iniciado` ∈ tipos AND `cumprimento_extinto` ∉ tipos

**Interpretação:** O processo está em fase de **cumprimento de sentença**
ativo. O réu provavelmente perdeu (ou houve acordo) e está em execução.
**NÃO pode ser encerrado ainda** — vai ter movimentações futuras de penhora,
depósito, alvará, etc.

**Por que isso é importante:** essa é a fix V2! Sem essa categoria, processos
com trânsito em julgado mas com BACENJUD/penhora ativos cairiam em
🔴 ENCERRAMENTO IMINENTE, gerando falso-positivo pro time.

**Ação do operador:** acompanhar o cumprimento, monitorar pagamento/quitação.

---

### 🟡 MÉDIA
**Critério:** `sentenca` ∈ tipos AND nenhum dos sinais acima

**Interpretação:** Sentença foi proferida mas ainda não houve trânsito.
Possíveis cenários:
- Prazo recursal correndo
- Embargos de declaração opostos
- Recurso interposto e aguardando
- Sentença muito recente

**Ação do operador:** acompanhar próximos andamentos pra ver se vai
escalar pra ALTA (trânsito) ou voltar pra BAIXA (recurso provido).

---

### 🟢 BAIXA
**Critério:** Sinais de processo ativo (audiência designada, audiência
cancelada/redesignada, revelia) AND sem sentença/trânsito/arquivamento.

**Interpretação:** Processo em **fase instrutória** ou **postulatória**.
Tem movimentação relevante mas longe do fim.

**Ação do operador:** acompanhamento normal, atenção a prazos pontuais
(audiências).

---

### ⚪ INDETERMINADO
**Critério:** Nenhum dos sinais detectados na janela.

**Interpretação:** O processo:
- Está em fase muito inicial (sem movimentação relevante)
- Está parado/suspenso há tempo
- Teve movimentação fora dos padrões do regex (raro)

**Ação do operador:** verificar manualmente se for crítico, mas
provavelmente não há ação imediata.

---

## 7. Exemplos práticos por categoria

### Exemplo 🔴 ENCERRAMENTO IMINENTE
> CNJ: 8001818-20.2025.8.05.0001
> Andamentos: `sentenca` (`Julgo improcedente`), `transito_julgado` (`Certifico o trânsito em julgado em 14/03/2026`), `arquivamento` (`Arquivado Definitivamente`)
> Justificativa: `sinal de encerramento: arquivamento, transito_julgado`

### Exemplo 🟠 AGUARDANDO CUMPRIMENTO
> CNJ: 8004445-10.2024.8.05.0001
> Andamentos: `sentenca` (`Julgo procedente`), `transito_julgado` (`Trânsito em julgado em 02/02/2026`), `cumprimento_iniciado` (`Determino o BACENJUD para bloqueio de ativos do executado`)
> Justificativa: `sinais de cumprimento ativos (sem extinção)`
>
> **Antes da V2** esse caso cairia em 🔴 ENCERRAMENTO IMINENTE → falso-positivo.

### Exemplo 🟡 MÉDIA
> CNJ: 1093634-85.2025.4.01.3300
> Andamentos: `sentenca` (`Julgo improcedente o pedido. Condeno o autor a honorários`)
> Sem trânsito, sem arquivamento, sem cumprimento.
> Justificativa: `sentença proferida`

### Exemplo 🟢 BAIXA
> CNJ: 8000123-17.2026.8.05.0265
> Andamentos: `audiencia_designada` (`Designo audiência de conciliação para 30/06/2026`)
> Justificativa: `em andamento: audiencia_designada`

### Exemplo ⚪ INDETERMINADO
> CNJ: 0000591-02.2026.8.05.0271
> Andamentos: apenas certidões cartorárias e juntada de petições genéricas, sem nenhum sinal do regex.
> Justificativa: `sem andamentos relevantes em 60d`

---

## 8. Comparativo V1 → V2

| Aspecto | V1 (30d) | V2 (60d) |
|---|---|---|
| Janela varrida | 30 dias | 60 dias |
| Regex patterns | 6 | 8 (+ `cumprimento_iniciado`, `cumprimento_extinto`) |
| Categorias | 4 (ALTA/MÉDIA/BAIXA/INDET.) | **5** (split de ALTA em 🔴/🟠) |
| Total processos | 16.000 | 17.646 |
| ALTA → ENC.IMINENTE | 620 (3.9%) | **1056 (6.0%)** — +436 vs V1 |
| AGUARDANDO CUMPRIMENTO | — | **508 (2.9%)** — nova |
| MÉDIA | 1.075 | 1.441 |
| BAIXA | 82 | 381 |
| INDETERMINADO | 14.223 | 14.260 |
| Total achados (regex match) | 2.648 | 6.023 (+127%) |

### Por que aumentou tanto

- **Janela maior**: pegou mais andamentos relevantes
- **2 regex novos**: capturaram sinais que antes ficavam invisíveis
- **Reclassificação**: 1.833 processos mudaram de temperatura entre V1 e V2

### Delta de processos (V2 vs V1, mesmo lawsuit_id):
- **2.008 NOVOS** — lawsuits que não estavam na V1 (base atualizada)
- **1.833 MUDARAM** — temperatura diferente (a maioria das mudanças foram
  🔴 → 🟠 graças aos sinais de cumprimento detectados)
- **13.805 MANTIVERAM** — mesma temperatura

---

## 9. Distribuição real (BB/Réu V2)

```text
17.646 processos · janela 60d · 6.023 achados

🔴 ENCERRAMENTO IMINENTE     1.056   6.0%
🟠 AGUARDANDO CUMPRIMENTO      508   2.9%
🟡 MÉDIA                     1.441   8.2%
🟢 BAIXA                       381   2.2%
⚪ INDETERMINADO            14.260  80.8%
```

### Leitura prática

- **8.9% da carteira tem ação concreta a tomar** (🔴 + 🟠): 1.564 processos
- **8.2% precisa de monitoramento** (🟡): pode escalar
- **80.8% está sem sinal recente** — não significa que estão parados,
  apenas que não tiveram movimentação relevante NA JANELA. Pode ser:
  - Processo em fase Inicial (postulatória) sem ainda ter sentença
  - Processo suspenso (aguardando perícia, prejudicial externa, etc.)
  - Processo com movimentação muito formal/cartorária

---

## 10. Como ler o resultado

### Estrutura da XLSX consolidada

A varredura gera 1 XLSX consolidada com **8 abas**:

1. **Resumo Geral** — KPIs e %s
2. **Resumo por Lote** — distribuição por run/lote
3. **🔴 ENCERRAMENTO IMINENTE** — ordenado por qtd de achados (mais sinais primeiro)
4. **🟠 AGUARDANDO CUMPRIMENTO** — *categoria nova V2*
5. **🟡 MÉDIA**
6. **🟢 BAIXA**
7. **⚪ INDETERMINADO**
8. **🆕 NOVOS vs V1** — lawsuits que não estavam na varredura anterior
9. **🔄 MUDARAM V1→V2** — lawsuits que trocaram de temperatura

### Colunas por aba

Cada linha tem:
- **Temperatura, CNJ, Lawsuit ID, NPJ**
- **Tipos de evento detectados** (lista dos regex que casaram)
- **Justificativa** (string textual)
- **Qtd de achados**
- **Delta vs V1** (NOVO / MUDOU / MANTEVE)
- **Temp V1** (qual era na varredura anterior)
- **Capa**: Tipo Ação, Situação, UF, Comarca, Vara, Valor da Causa, Advogado, Matéria
- **Run #** (de qual lote saiu)
- **Datas dos achados** (cronologia)
- **Trechos detectados** (texto íntegra do andamento que disparou cada sinal)

---

## 11. Limitações conhecidas

### Falsos positivos
- **"Revelia" como menção doutrinária**: ex.: "art. 344 do CPC trata da
  revelia" → cai como `revelia` mas não é. (V1: 169 revelias detectadas,
  mas só 19 EFETIVAS segundo classificação por Sonnet — 89% de menções
  passageiras.)
- **"Sentença" em contexto recursal**: ex.: "anular a sentença" pode ser
  pedido do autor, não a sentença em si.
- **"Cumprimento" em recurso/embargos**: ex.: "embargos ao cumprimento"
  vira `cumprimento_iniciado`. Os pré-filtros tentam excluir EMBARGOS À
  EXECUÇÃO como TIPO, mas ainda pode escapar pelo andamento.

### Falsos negativos
- **Variações regionais de redação**: ex.: alguns tribunais escrevem
  "transitada em julgada" (concordância feminina) — não casa com o regex
  atual `tr[âa]nsito\s+em\s+julgado`.
- **Erros de digitação no andamento**: ex.: "trasito em julgado" não casa.
- **Sinais por contexto longo**: às vezes a indicação só fica clara em 2-3
  andamentos lidos juntos, não em 1 isolado.

### Estruturais
- **Sem versionamento temporal**: hoje cada varredura é uma "foto". Se o
  mesmo processo escalou de 🟡 → 🟠 entre janeiro e março, perdemos a
  história. (Resolvível adicionando coluna de `data_classificacao` em uma
  tabela `processo_temperatura_historico`.)
- **Sem consideração da capa na classificação**: a capa entra no relatório
  final, mas não influencia a temperatura. Por ex.: processos de pequeno
  valor (até R$ X) poderiam ter critério mais permissivo pra encerrar.

---

## 12. Próximas evoluções possíveis

### Curto prazo (melhoria do regex)
- Adicionar variantes:
  - `transitada em julgada` (concordância feminina)
  - `desistência homologada`, `acordo homologado`
  - `prescrição reconhecida`
  - `intempestividade`, `recurso não conhecido`
- Categorias finas:
  - separar `vitoria_reu` (sentença improcedente + trânsito) de
    `derrota_reu` (sentença procedente + trânsito + cumprimento)

### Médio prazo (uso de IA seletiva)
- **Validação de revelias** via Haiku: cada `revelia` detectado passa por
  validação rápida ("foi efetivamente aplicada?"). Já implementado no
  Master com 19 EFETIVAS / 169 menções.
- **Validação de sentenças**: classificar como `procedente`, `improcedente`,
  `parcialmente procedente`, `extinto sem mérito` via Haiku no andamento.
- **Detecção de prazo aberto pro réu** via Haiku no texto.

### Longo prazo (arquitetura)
- **Histórico temporal de temperatura** — tabela com 1 linha por
  (processo, data_varredura, temperatura) pra ver tendências.
- **Alertas automáticos** — processo mudou de 🟡 pra 🔴 → notifica responsável.
- **Aprendizado supervisionado** — feedback do operador ("esse não estava
  apto", "esse estava sim") alimenta refinamento dos regex/critérios.
- **Multi-cliente** — generalizar pra outras carteiras (Master, BB, etc.)
  com critérios por cliente.

---

## Referências de código

- Regex: `app/services/varredura/regex_eventos.py`
- Classificação: função `classificar_temperatura()` em
  `app/runners/legalone/_run_bb_temperatura_v2.py` (e `_v3.py`, `_via_api.py`)
- Pré-filtros: função `ler_e_filtrar_planilha()` nos mesmos arquivos
- Consolidação: `_consolidar_bb_temperatura_v2.py`
- Constantes de tipo: `EVENTO_*` em `app/models/varredura.py`

## Status do projeto

- **V1** (16k processos, 4 categorias): ✅ rodada em 22/05/2026, XLSX entregue
- **V2** (17.6k processos, 5 categorias): ✅ rodada em 06/06/2026, XLSX entregue
- **V3 (RPA, janela 180d, DuckDB)**: 🟡 código pronto, não disparado
- **V4 (API L1 /Updates paralela)**: 🟡 código pronto, smoke test OK, aguardando disparo no fim de semana

# Plano — Módulo "Performance de Equipes"

Generaliza o motor de análise de capacity que fizemos para Publicações para
**qualquer equipe do escritório**, a partir das tarefas agendadas no Legal One.
Dor que resolve: o escritório não tem controle/visibilidade sobre as atividades
dos colaboradores por equipe.

## Decisões já alinhadas (2026-06-26)

- **Equipe-piloto:** BB Réu (escritório `MDR Advocacia / Área operacional /
  Banco do Brasil / Réu`) — maior volume (~77k tarefas), mais sinal pra calibrar.
- **Lente do dashboard:** equilibrada — capacity (produção/ritmo/ócio) **e**
  prazo/risco (SLA/backlog) lado a lado.
- **Ingestão:** seed do histórico via export do L1 (uma vez) + **vivo via API
  `/Tasks` incremental** (diário, só o que mudou). API-pura pro histórico é
  inviável de cara (milhares de chamadas paginadas, `$top=30`).
- **Construção:** piloto numa equipe primeiro; replicar depois.

## Fonte de dados (export "Agenda Analytics" do L1 — 19 colunas)

Campos relevantes por tarefa: escritório responsável; "Cumprido por" (quem fez);
"Envolvidos / Nome" (responsável); tipo/subtipo; status (Cumprido/Pendente);
data de cadastro; **data/hora de conclusão efetiva**; data/hora de conclusão
prevista (prazo); vínculos (Pasta/CNJ/UF). A API `/Tasks` expõe o equivalente.

Panorama da amostra (183.925 tarefas, abr/2025→jun/2026): 166k cumpridas + 17,9k
pendentes; 203 pessoas; **384 subtipos** distintos (cauda longa = ruído a tratar).

## Filosofia anti-ruído (o ponto que define a leitura)

Em Publicações o operador trata item atrás de item no painel → intervalo entre
ações = ritmo real e ócio = ócio. **Em tarefas jurídicas isso só vale para parte
dos tipos.** Logo, segmentar os tipos por natureza É a classificação de impacto:

- **Operacionais (alta frequência, back-to-back)** — ex.: Inclusão de Resultado,
  Agendar Prazos, Solicitar Subsídio, DMI, Siga. Cadência e ócio são confiáveis.
- **Trabalho profundo (baixa frequência, alto esforço)** — ex.: Contestação,
  Análise Recursal, Manifestação, Contrarrazões. Medir por **volume + cycle time
  + cumprimento de prazo**, NÃO por ócio.
- **Cauda longa de ruído** — subtipos raros: agrupar ou cortar.

Regra: cadência/ócio **só** no segmento operacional; deep-work por throughput/SLA.

## Métricas

- **Throughput:** tarefas cumpridas/dia por "Cumprido por".
- **Cadência (operacional):** mediana do intervalo entre conclusões consecutivas
  (LAG sobre conclusão efetiva, capado; lote/pausa filtrados) — = "custo por ação".
- **Ócio (operacional):** janela do dia × soma do hands-on; horário de término.
- **Cycle time:** cadastro → conclusão (lead time), por tipo/pessoa/equipe.
- **SLA / no prazo:** conclusão ≤ prazo previsto (%), atraso médio.
- **Backlog:** Pendentes por pessoa/tipo (carga aberta = risco).

## Modelo de dados (proposto)

Tabela própria `perf_l1_tarefa` (prefixo a definir), populada pela ingestão:
id (L1), escritorio_path, cumprido_por, envolvido, tipo, subtipo, status,
cadastrado_em, concluido_em, prazo_previsto, pasta, cnj, uf, ingested_at.
Índices por escritório + concluido_em + cumprido_por. O dashboard e o relatório
leem daqui (sem re-bater a API).

## Views do dashboard (piloto BB Réu)

- KPIs: concluídas (período) · backlog · % no prazo · cycle time médio.
- Produção por pessoa: concluídas/dia · % no prazo · backlog.
- Por tipo de tarefa: volume + cycle time, com a tag operacional/profundo.
- Segmento operacional: cadência + ócio (estilo Publicações).
- Séries: concluídas/dia e cadastradas/dia.
- Drill-through (estilo Lake): clicar num recorte → lista das tarefas/pessoas.

## Relatório Crítico (gerável por período, por equipe)

Mesma estrutura do de Publicações: sumário executivo + diagnóstico (Sonnet com
fallback, registro formal) + recomendações + ressalvas → PDF server-side.

## Fases

1. **Mapa de impacto dos tipos (análise)** — usar o export já enviado pra
   classificar os subtipos do BB Réu em operacional/profundo/ruído, com volume,
   cycle time e cadência onde couber. Define o que entra na conta. (sem código)
2. **Ingestão** — seed do histórico (export) + job incremental via API `/Tasks`
   pro escritório-piloto → tabela `perf_l1_tarefa`.
3. **Dashboard do piloto** — as views acima.
4. **Relatório crítico** por equipe/período.
5. **Generalizar** — replicar pras demais equipes (offices).

## Em aberto / a decidir nas próximas conversas

- Definição fina de "tempo de ação" pro deep-work (cadastro→conclusão vs
  início→conclusão) — a coluna "início previsto/efetivo" precisa ser entendida.
- Como classificar os tipos: curadoria manual (lista de operacionais) vs
  automático (por frequência/cadência). Provável: auto + ajuste manual.
- Sensibilidade: é monitoramento de colaboradores — alinhar tom/uso com gestão.
- Cadência da ingestão incremental (diária?) e janela de histórico no dashboard.

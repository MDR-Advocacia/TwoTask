# Arquitetura de Inteligencia Processual

## Objetivo

Estruturar no `OneTask` um modulo dedicado ao monitoramento continuo de carteiras judiciais, integrando DataJud e DJEN/Comunica, com trilha de auditoria, score por evidencias e filas operacionais para validacao de baixa.

## Estrutura proposta

```text
app/
  models/
    process_monitoring.py
  services/
    process_monitoring/
      __init__.py
      enums.py
      contracts.py
      datajud_client.py
      comunica_client.py
      correlation_service.py
      scoring_service.py
      monitoring_service.py
docs/
  arquitetura_inteligencia_processual.md
tests/
  services/
    process_monitoring_scoring_service_test.py
```

## Camadas do modulo

### 1. Persistencia

Arquivo: `app/models/process_monitoring.py`

Entidades principais:

- `MonitoringPortfolio`: carteira monitorada por cliente, unidade, operacao e segmento.
- `MonitoredProcess`: processo consolidado com status analitico atual, score, fila e timestamps de sincronizacao.
- `ProcessRawPayload`: camada bruta para auditoria, replay e reprocessamento.
- `ProcessMovement`: fato de movimentacoes oriundas do DataJud.
- `ProcessPublication`: fato de publicacoes, comunicacoes e certidoes oriundas do DJEN/Comunica.
- `ProcessAnalyticalEvent`: regra disparada, impacto de score, justificativa e status de homologacao.
- `ProcessOperationalQueueItem`: fila operacional derivada da classificacao.
- `IntegrationSyncRun` e `IntegrationSyncCursor`: observabilidade e continuidade de cargas por fonte.

### 2. Contratos e tipagem

Arquivo: `app/services/process_monitoring/contracts.py`

Responsabilidades:

- normalizar o payload do DataJud em `DataJudProcessSnapshot`;
- normalizar publicacoes em `ComunicaPublicationRecord`;
- representar evidencias detectadas em `DetectedEvidence`;
- consolidar a avaliacao em `MonitoringEvaluation`.

### 3. Integracoes externas

Arquivos:

- `app/services/process_monitoring/datajud_client.py`
- `app/services/process_monitoring/comunica_client.py`

Decisoes adotadas:

- DataJud com suporte nativo a query Elasticsearch e cursor `search_after`;
- Comunica com metodos genericos para `caderno`, `comunicacao` e `certidao`;
- configuracoes centralizadas em `app/core/config.py`.

### 4. Correlacao e score

Arquivos:

- `app/services/process_monitoring/correlation_service.py`
- `app/services/process_monitoring/scoring_service.py`
- `app/services/process_monitoring/monitoring_service.py`

Fluxo:

1. Receber snapshot do processo no DataJud.
2. Correlacionar publicacoes e certidoes do DJEN/Comunica.
3. Detectar eventos relevantes por palavra-chave e janela temporal.
4. Aplicar score e classificar na regua de maturidade.
5. Sugerir fila operacional e acao recomendada.

## Regua de maturidade implementada

- Nivel 0: `MONITORED`
- Nivel 1: `DECISION_EVENT`
- Nivel 2: `RECURSAL_ATTENTION`
- Nivel 3: `NEAR_TRANSIT`
- Nivel 4: `STRONG_TRANSIT_INDICATIVE`
- Nivel 5: `ELIGIBLE_FOR_OPERATIONAL_CLOSURE`
- Nivel 6: `CLOSURE_CONFIRMED`

## Regras iniciais do motor

- eventos decisorios aumentam score;
- publicacoes e certidoes agregam confianca;
- transito em julgado expresso eleva fortemente a maturidade;
- sinais recursais reduzem score e seguram o processo em fila de atencao;
- janela sem impulso relevante aumenta a chance de encaminhamento a baixa;
- confirmacao de arquivamento definitivo/baixa definitiva fecha a regua em nivel 6.

## Proximos passos recomendados

1. Criar migration Alembic para o conjunto de tabelas do modulo.
2. Expor endpoints FastAPI para carteiras, resumo executivo, fila operacional e detalhe do processo.
3. Persistir snapshots, eventos e itens de fila no banco.
4. Criar jobs periodicos de sincronizacao para DataJud e DJEN/Comunica.
5. Plugar a camada de BI em views ou marts derivados das tabelas analiticas.

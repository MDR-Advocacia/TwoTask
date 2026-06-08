# Varredura — Andamentos brutos: queries

Tabela `varredura_andamento_raw` (criada em `var002`) guarda TODOS os
andamentos varridos, não só os que matcham regex de eventos. Capa
opcional via `varredura_processado.capa_json`.

## Schema rápido

```text
varredura_andamento_raw
├── id BIGINT PK
├── run_id INT FK→varredura_run(id) CASCADE
├── processado_id INT FK→varredura_processado(id) CASCADE
├── lawsuit_id INT
├── cnj_number VARCHAR(64)
├── office_id INT
├── andamento_data DATE
├── andamento_hora VARCHAR(8)
├── andamento_tipo VARCHAR(64)   -- "Andamento", "Publicação", etc.
├── andamento_texto TEXT
├── andamento_movimentado_por VARCHAR(255)
├── ordem INT                     -- posição na lista raspada (0 = mais recente)
└── created_at TIMESTAMPTZ

Indices: lawsuit_id, (run_id,andamento_data), cnj_number,
         andamento_tipo, (office_id,andamento_data)
```

## Queries SQL (psql/DBeaver)

```sql
-- Conta andamentos por tipo no escritório BB/Réu (office 23)
SELECT andamento_tipo, COUNT(*) AS n
FROM varredura_andamento_raw
WHERE office_id = 23
GROUP BY 1 ORDER BY 2 DESC;

-- Processos com penhora nos últimos 30 dias
SELECT DISTINCT cnj_number, lawsuit_id, andamento_data, andamento_texto
FROM varredura_andamento_raw
WHERE andamento_data >= CURRENT_DATE - INTERVAL '30 day'
  AND andamento_texto ILIKE '%penhora%'
ORDER BY andamento_data DESC;

-- Top advogados em movimentações de cumprimento
SELECT andamento_movimentado_por, COUNT(*) AS n
FROM varredura_andamento_raw
WHERE andamento_texto ILIKE '%cumprimento de sentença%'
  AND andamento_movimentado_por IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 30;

-- Distribuição por UF (via capa_json)
SELECT (p.capa_json->>'UF') AS uf,
       COUNT(DISTINCT a.lawsuit_id) AS processos
FROM varredura_andamento_raw a
JOIN varredura_processado p ON p.id = a.processado_id
WHERE a.andamento_texto ILIKE '%arquivad%'
GROUP BY 1 ORDER BY 2 DESC;

-- Timeline de 1 processo
SELECT andamento_data, andamento_hora, andamento_tipo,
       andamento_movimentado_por, andamento_texto
FROM varredura_andamento_raw
WHERE cnj_number = '0001424-45.2026.8.05.0004'
ORDER BY andamento_data DESC, ordem ASC;
```

## Export NDJSON

```bash
# Tudo do office 23 da varredura V2
docker exec onetask-api-1 python //app/app/runners/legalone/_export_andamento_raw.py \
  --triggered-by-prefix bb-temperatura-v2- \
  --out /tmp/andamentos-bb-v2.jsonl

docker cp onetask-api-1:/tmp/andamentos-bb-v2.jsonl ./

# Filtros: --office-id, --run-id, --since YYYY-MM-DD, --tipo-evento
```

## Queries no NDJSON com DuckDB (recomendado pra análise local)

```sql
-- DuckDB CLI: duckdb
INSTALL json; LOAD json;

-- Carrega arquivo
CREATE VIEW v AS
SELECT * FROM read_json_auto('andamentos-bb-v2.jsonl', format='newline_delimited');

-- Distribuição por situação da capa
SELECT capa.Situação_do_Processo AS sit, COUNT(*) AS n
FROM v GROUP BY 1 ORDER BY 2 DESC;

-- Processos com BACENJUD nos andamentos
SELECT cnj, lawsuit_id, capa.Vara, capa.UF
FROM v
WHERE EXISTS (
  SELECT 1 FROM unnest(andamentos) AS t(a)
  WHERE a.texto ILIKE '%BACENJUD%'
);

-- Volume de andamentos por mês
SELECT date_trunc('month', strptime(a.data, '%Y-%m-%d')) AS mes,
       COUNT(*) AS qtd
FROM v, unnest(andamentos) AS t(a)
WHERE a.data IS NOT NULL
GROUP BY 1 ORDER BY 1;
```

## Queries no NDJSON com jq (rápido, ad-hoc)

```bash
# Lista CNJs com >= 10 andamentos
jq -c 'select(.qtd_andamentos >= 10) | {cnj, qtd_andamentos}' andamentos-bb-v2.jsonl

# Conta andamentos com "extinta a execução"
jq -c '.andamentos[] | select(.texto | test("extinta a execu"; "i")) | .texto' \
   andamentos-bb-v2.jsonl | wc -l

# Capa de 1 processo específico
jq 'select(.cnj == "0001424-45.2026.8.05.0004") | .capa' andamentos-bb-v2.jsonl
```

## Queries no NDJSON com pandas

```python
import pandas as pd
import json

records = [json.loads(line) for line in open("andamentos-bb-v2.jsonl", encoding="utf-8")]

# Achata pra 1 linha por andamento
df = pd.DataFrame([
    {**{f"capa_{k}": v for k, v in (r.get("capa") or {}).items()},
     **a,
     "cnj": r["cnj"], "lawsuit_id": r["lawsuit_id"]}
    for r in records
    for a in r["andamentos"]
])

# Distribuição por tipo
print(df["tipo"].value_counts().head(20))

# Texto cheio de penhora
penhora = df[df["texto"].str.contains("penhora", case=False, na=False)]
print(penhora.groupby("capa_UF").size().sort_values(ascending=False))
```

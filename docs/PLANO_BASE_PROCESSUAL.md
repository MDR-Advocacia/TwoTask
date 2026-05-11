# Plano de Implementação — Aba "Base Processual" (admin/flow)

> **Status:** consolidado, aprovado pelo Jonílson, pronto pra implementação.
> **Data:** 2026-05-08.
> **Branch alvo:** `feat/prazos-iniciais` (validação isolada antes de promover pra `main`).
> **Próximo passo:** começar **Chunk 1** (esqueleto + ingestão + diff).

---

## 0. Contexto do projeto (pra quem está lendo de fora)

- **Repositório:** TwoTask / DunaFlow — app interno da MDR Advocacia.
- **Stack:** FastAPI + SQLAlchemy + Pydantic V2 + Alembic / React + TypeScript + Vite + shadcn/ui + Tailwind / PostgreSQL.
- **Deploy:** Coolify (push em `main` aciona rebuild + `alembic upgrade head` + restart automaticamente; **não escrever runbook de deploy manual**).
- **Convenções obrigatórias da casa** (ver `CLAUDE.md` na raiz):
  - Migrations alembic com prefixo por módulo: este módulo usa `bp*` (`bp001`, `bp002`, …).
  - Antes de criar migration: rodar `docker exec onetask-api-1 sh -c "cd /app && alembic heads"` e usar o head atual como `down_revision`. Se vier mais de uma linha, criar `merge_heads` antes.
  - **Paginação obrigatória** em qualquer listagem/menu/modal desde o primeiro commit (default 50, max 500, formato `{total, items}`).
  - **Não commitar do sandbox** — entregar bloco PowerShell pronto pro usuário rodar no VSCode (PowerShell 5.x, sem `&&`).
  - **Não usar `Edit`/`Write` direto em arquivos >800 linhas** (truncamento recorrente — usar fluxo via `git show` + `python str.replace`).
  - pt-BR em logs, mensagens de erro voltadas pro operador, e comentários no domínio jurídico.
  - `LegalOneOffice.path` (hierarquia completa) é preferido sobre `name` (folha) em UI/exports.

---

## 1. Objetivo

Criar uma **base centralizada da carteira processual** da MDR, alimentada por **upload diário de planilha XLSX** pelo operador, com:

1. **Detecção automática de movimento de carteira** — quais processos entraram, quais saíram, quais sofreram alteração relevante entre uploads.
2. **Dashboard operacional** com séries diárias e visão "Movimentação do dia" pra o Jonílson abrir e em 10 segundos saber se o cliente sacaneou ele hoje.
3. **Rastreabilidade total** — histórico de cada processo (snapshots por upload, soft-remove em vez de delete).
4. **API pública (com chave)** pra que sistemas terceiros consultem a base.
5. **Endpoints internos** de atualização em lote (PATCH parcial em N processos) e geração de relatórios em XLSX.

A base vira **fonte de verdade interna**, paralela ao Legal One. Substitui o "tudo vive no L1 e a gente fica perdido" por uma camada controlável e auditável.

---

## 2. Entrada — a planilha XLSX (schema observado)

A planilha real do operador (`Listagem_de_Acoes_Judiciais.xlsx`) tem:
- Sheet `Plan1`, **5.979 linhas de dados**, **37 colunas**.
- Linha 1 vazia, linha 2 = header, linha 3+ = dados.
- `Cód AJUS` é único por linha (sem duplicatas — chave natural).
- `Empresa` hoje é só `banco_master` (modelar multi-tenant desde o dia 1).
- `Números Processo` vem com máscara CNJ (`NNNNNNN-DD.AAAA.J.TT.OOOO`).
- `Autores - CNPJCPF` / `Réus - CNPJCPF` em formato bloco multilinha:
  ```
  Nome: <nome>
  CNPJCPF: <doc>
  ```
  (pode ter múltiplos blocos separados por linha em branco).
- Datas em pt-BR: `dd/mm/yyyy [HH:MM:SS]`. `00/00/0000 00:00:00` significa NULL.
- Valores monetários: `0`, `1500.00`, `1.500,00`, `R$ 1.500,00` — todas formas devem ser parseadas pra Numeric.
- `Processo Virtual`: `"Sim"` / `"Não"` / vazio.

**Header completo (na ordem):**

```
Cód AJUS · Ação Principal · Matéria · Risco/Prob. Perda · Autores - CNPJCPF · Réus - CNPJCPF ·
Números Processo · Nº Interno · Tipo de Ação · Polo · Natureza · Nº Vara · Foro · Comarca · UF ·
Empresa · Nº Pasta · Grupo Responsável · Usuário Responsável · Escritório Responsável ·
Situação Processo · Justiça / Honorário · Valor Causa · Valor Prev. Acordo · Valor Acordo ·
Valor Discutido · Valor Êxito · Valor Condenação · Valor Contingência · Últ. Andamento ·
Data Últ. Andamento · Dias Últ. Atualização · Distribuído em · Processo Virtual · Nº Contrato ·
Usuário Cadastro Ação · Data/Hora Cadastro Ação
```

**Validação flexível:** lookup por **nome de coluna**, não por índice — cliente pode reordenar/renomear sem nos quebrar silenciosamente.

---

## 3. Decisões fechadas

| # | Decisão | Resolução |
|---|---|---|
| 1 | Chave natural | `Cód AJUS` (UNIQUE, índice principal de lookup) |
| 2 | Saída de processo da planilha | **Soft-remove** (`presenca_status=REMOVIDO_NA_BASE`), nunca DELETE |
| 3 | Snapshot histórico | 1 row por (processo, upload em que apareceu) com payload completo (raw + normalized) |
| 4 | Diff "houve mudança real?" | hash sha256 dos campos significativos (lista curada, exclui campos voláteis) |
| 5 | Idempotência | sha256 do arquivo — reupload do mesmo XLSX retorna resultado anterior |
| 6 | Processamento | Síncrono até 10k linhas (atual: 5.979). >10k → APScheduler |
| 7 | Multi-tenant (`empresa`) | Modelado desde o dia 1 (hoje só `banco_master`, amanhã pode crescer) |
| 8 | Branch | `feat/prazos-iniciais` (não vai pra `main` sem autorização explícita) |
| 9 | Migrações | Prefixo `bp*` — começar por `bp001` |
| 10 | Retenção snapshots | 24 meses, configurável via env `BASE_PROCESSUAL_SNAPSHOT_RETENTION_MONTHS=24` |
| 11 | API key externa | **Chave única seedada na v1** (modelo já multi-key no banco — UI permite só "regerar"/"revogar"; multi-key pode ser destravado depois sem migration) |
| 12 | Storage do XLSX original | Volume persistente `/data/base-processual/uploads/{upload_id}.xlsx`, cleanup configurável (90 dias default) |
| 13 | UX | **Gate de merge** — não é polish opcional. Ver seção 7 |

---

## 4. Modelo de dados (Postgres / SQLAlchemy / Alembic)

Arquivo: `app/models/base_processual.py` (novo).
Migração inicial: `bp001_add_base_processual_tables.py`.

### 4.1 `base_processual_processo` — estado atual da carteira

1 linha por `Cód AJUS`. Sempre representa o estado mais recente.

| Coluna | Tipo | Nullable | Notas |
|---|---|---|---|
| `id` | `Integer` PK | | |
| `cod_ajus` | `String` UNIQUE INDEX | não | chave natural do L1 |
| `numero_processo` | `String` INDEX | sim | CNJ normalizado (só dígitos) |
| `numero_processo_mascarado` | `String` | sim | `NNNNNNN-DD.AAAA.J.TT.OOOO` pra exibição/busca |
| `numero_interno` | `String` INDEX | sim | "Nº Interno" |
| `numero_pasta` | `String` INDEX | sim | "Nº Pasta" |
| `acao_principal` | `String` | sim | |
| `materia` | `String` INDEX | sim | "Consumidor", etc. |
| `risco_prob_perda` | `String` | sim | "Remoto" / "Possível" / etc. |
| `tipo_acao` | `String` INDEX | sim | |
| `polo` | `String` INDEX | sim | "Ativo" / "Passivo" |
| `natureza` | `String` INDEX | sim | "Cível" |
| `numero_vara` | `String` | sim | |
| `foro` | `String` | sim | |
| `comarca` | `String` INDEX | sim | |
| `uf` | `String(2)` INDEX | sim | |
| `empresa` | `String` INDEX | não | "banco_master" hoje |
| `grupo_responsavel` | `String` | sim | |
| `usuario_responsavel` | `String` INDEX | sim | |
| `escritorio_responsavel` | `String` | sim | |
| `situacao_processo` | `String` INDEX | não | "Ativo" / "Nenhum" / etc. |
| `justica_honorario` | `String` | sim | |
| `valor_causa` | `Numeric(18,2)` | sim | |
| `valor_prev_acordo` | `Numeric(18,2)` | sim | |
| `valor_acordo` | `Numeric(18,2)` | sim | |
| `valor_discutido` | `Numeric(18,2)` | sim | |
| `valor_exito` | `Numeric(18,2)` | sim | |
| `valor_condenacao` | `Numeric(18,2)` | sim | |
| `valor_contingencia` | `Numeric(18,2)` | sim | |
| `ult_andamento` | `String` | sim | descrição do último andamento |
| `data_ult_andamento` | `DateTime` | sim | |
| `dias_ult_atualizacao` | `Integer` | sim | (campo volátil — não entra no diff hash) |
| `distribuido_em` | `Date` | sim | |
| `processo_virtual` | `Boolean` | sim | "Sim" → True |
| `numero_contrato` | `String` | sim | |
| `usuario_cadastro_acao` | `String` | sim | |
| `data_cadastro_acao` | `DateTime` | sim | |
| `autores_raw` | `Text` | sim | bloco bruto |
| `reus_raw` | `Text` | sim | |
| `autores_json` | `JSONB` | sim | `[{"nome":"…","documento":"…"}]` |
| `reus_json` | `JSONB` | sim | |
| `presenca_status` | `String` INDEX | não | `ATIVO_NA_BASE` / `REMOVIDO_NA_BASE` |
| `first_seen_upload_id` | `Integer` FK | não | upload em que entrou pela 1ª vez |
| `last_seen_upload_id` | `Integer` FK | não | último upload em que apareceu |
| `removed_at_upload_id` | `Integer` FK | sim | upload que detectou a saída |
| `current_snapshot_id` | `Integer` FK | sim | atalho de leitura pro último snapshot |
| `created_at` | `DateTime` | não | |
| `updated_at` | `DateTime` | não | auto-update |

**Índices compostos:** `(empresa, presenca_status)`, `(uf, comarca)`, `(empresa, usuario_responsavel)`.

### 4.2 `base_processual_upload`

1 linha por upload (mesmo se falhar).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `filename` | `String` | nome original |
| `file_sha256` | `String(64)` UNIQUE INDEX | dedupe |
| `file_bytes` | `Integer` | |
| `total_rows_in_file` | `Integer` | |
| `summary_novos` | `Integer` default 0 | |
| `summary_removidos` | `Integer` default 0 | |
| `summary_atualizados` | `Integer` default 0 | |
| `summary_inalterados` | `Integer` default 0 | |
| `status` | `String` INDEX | `PENDENTE` / `PROCESSANDO` / `CONCLUIDO` / `FALHOU` / `IDEMPOTENTE` / `DRY_RUN` |
| `error_message` | `Text` | |
| `dry_run_of_upload_id` | `Integer` FK | sim — marca dry-runs e referencia o commit final |
| `committed_at` | `DateTime` | sim — preenchido só após confirm do dry-run |
| `uploaded_by_user_id` | `Integer` FK → `users.id` | |
| `uploaded_at` | `DateTime` | |
| `processed_at` | `DateTime` | |

### 4.3 `base_processual_evento`

N por upload — granularidade pro drill-down "o que mudou nesse upload?".

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `upload_id` | `Integer` FK INDEX | |
| `processo_id` | `Integer` FK INDEX | |
| `cod_ajus` | `String` INDEX | redundante mas útil pra busca direta |
| `tipo_evento` | `String` INDEX | `ENTROU` / `SAIU` / `ATUALIZADO` / `ATUALIZADO_MANUAL` (não gravamos `INALTERADO`) |
| `changed_fields` | `JSONB` | `{"valor_causa":{"de":0,"para":1500}, "situacao_processo":{"de":"Ativo","para":"Suspenso"}}` |
| `snapshot_before_id` | `Integer` FK | NULL pra ENTROU |
| `snapshot_after_id` | `Integer` FK | NULL pra SAIU |
| `created_at` | `DateTime` INDEX | |

**Índices:** `(upload_id, tipo_evento)`, `(processo_id, created_at DESC)`, `(created_at DESC)` pra feed cross-data.

### 4.4 `base_processual_snapshot`

1 linha por (processo, upload em que o processo apareceu).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `processo_id` | `Integer` FK INDEX | |
| `upload_id` | `Integer` FK INDEX | |
| `cod_ajus` | `String` INDEX | |
| `payload_normalized` | `JSONB` | linha já parseada (entra no diff) |
| `payload_raw` | `JSONB` | linha bruta (audit trail) |
| `diff_hash` | `String(64)` INDEX | sha256 dos campos significativos |
| `captured_at` | `DateTime` | |

**UNIQUE composto:** `(processo_id, upload_id)`.

### 4.5 `base_processual_api_key`

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | `Integer` PK | |
| `nome` | `String` | "Sistema X — Banco Master" |
| `key_hash` | `String(64)` UNIQUE INDEX | sha256 da chave (nunca plaintext) |
| `key_prefix` | `String(12)` | primeiros chars pra UI: "bpk_a1b2c3" |
| `scope` | `String` | `read_processos` / `read_dashboard` / `read_valores` / `read_all` |
| `rate_limit_per_min` | `Integer` default 60 | |
| `last_used_at` | `DateTime` | |
| `revoked_at` | `DateTime` | NULL = ativa |
| `created_by_user_id` | `Integer` FK | |
| `created_at` | `DateTime` | |

### 4.6 `base_processual_saved_view` (fase 2 — opcional)

Filtros nomeados sincronizados (v1 fica em localStorage).

---

## 5. Pipeline de upload

Arquivo: `app/services/base_processual/upload_processor.py`.

### 5.1 Validação

- Header check por **nome de coluna** (não por posição). Faltando coluna obrigatória → `FALHOU` com mensagem clara apontando o nome.
- Sheet: aceita `Plan1` ou primeiro sheet do arquivo.
- Linha 1 vazia + linha 2 = header (confirmado na inspeção).

### 5.2 Normalização (linha → dict)

- `Cód AJUS`: `str.strip()`.
- `Números Processo`: extrair só dígitos pra `numero_processo`, manter máscara em `numero_processo_mascarado` (alinhado com convenção AJUS de CNJ mascarado).
- Datas: parse pt-BR (`dd/mm/yyyy [HH:MM:SS]`); `00/00/0000 00:00:00` → NULL.
- Decimais: aceita `0`, `1500.00`, `1.500,00`, `R$ 1.500,00`. Util `app/utils/parse_decimal_br.py`.
- `Processo Virtual`: `"Sim"` → `True`, `"Não"` → `False`, vazio → `NULL`.
- Autores/Réus: regex `Nome:\s*(.+?)\s*\nCNPJCPF:\s*(.*)` (multi-bloco) → `[{"nome":"…","documento":"…"}]`. Vazio → `[]`.
- Strings: `strip()`, `None` se vazio.

### 5.3 `diff_hash` — campos significativos

```python
SIGNIFICANT_FIELDS = [
    "situacao_processo", "polo", "materia", "risco_prob_perda",
    "tipo_acao", "natureza", "numero_vara", "foro", "comarca", "uf",
    "grupo_responsavel", "usuario_responsavel", "escritorio_responsavel",
    "valor_causa", "valor_prev_acordo", "valor_acordo", "valor_discutido",
    "valor_exito", "valor_condenacao", "valor_contingencia",
    "ult_andamento",
    "autores_json", "reus_json",
]

def compute_diff_hash(normalized: dict) -> str:
    payload = {k: normalized.get(k) for k in SIGNIFICANT_FIELDS}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()
```

**Excluídos** (evitam falsos positivos): `dias_ult_atualizacao`, `data_ult_andamento`, `data_cadastro_acao`, `usuario_cadastro_acao`.

### 5.4 Aplicação (transação única)

1. Gravar `base_processual_upload` com `status=PROCESSANDO`.
2. Para cada linha:
   - Calcular `diff_hash`.
   - Buscar `processo` por `cod_ajus`.
   - **Caso 1 — não existe** → INSERT processo + INSERT snapshot + INSERT evento `ENTROU`. `summary_novos++`.
   - **Caso 2 — existe + `presenca_status=REMOVIDO_NA_BASE`** → "ressurgimento": UPDATE pra ATIVO_NA_BASE, `removed_at_upload_id=NULL` + INSERT snapshot + INSERT evento `ENTROU` (com `changed_fields={"_ressurgimento": true}`). Conta como novo.
   - **Caso 3 — existe + diff_hash igual ao último snapshot** → só atualiza `last_seen_upload_id` e campos voláteis. Não grava snapshot novo. `summary_inalterados++`.
   - **Caso 4 — existe + diff_hash diferente** → UPDATE processo + INSERT snapshot + INSERT evento `ATUALIZADO` com `changed_fields` (calculado por diff campo-a-campo). `summary_atualizados++`.
3. **Detecção de saídas** após o loop: processos `presenca_status=ATIVO_NA_BASE` cujo `cod_ajus NOT IN cods_no_arquivo` (set difference em memória ou subquery `NOT IN`).
   - UPDATE `presenca_status=REMOVIDO_NA_BASE`, `removed_at_upload_id=upload.id`.
   - INSERT evento `SAIU`. `summary_removidos++`.
4. UPDATE upload com summaries + `processed_at` + `status=CONCLUIDO`.

**Performance esperada:** ~5.979 linhas em <30s. Bulk via `session.bulk_save_objects`. Se passar de 60s, mover pra job APScheduler `bp_upload_worker`.

### 5.5 Idempotência

- Calcular sha256 do arquivo recebido.
- Se `base_processual_upload` com mesmo `file_sha256` e `status=CONCLUIDO` existe → retornar 200 com `summary` existente, marcando o upload novo como `IDEMPOTENTE`.

### 5.6 Dry-run

- `POST /uploads/dry-run` faz tudo de 5.4 **dentro de uma transação que dá ROLLBACK no final**.
- Grava o `base_processual_upload` com `status=DRY_RUN` apenas com summaries calculados + lista compacta de eventos previstos (em `error_message` ou em uma tabela auxiliar — preferir nova `base_processual_dry_run_evento` simplificada).
- Retorna `{dry_run_id, summary, eventos_preview: [...]}`.
- TTL de 30 min — após isso o dry_run é purgado por job periódico.
- `POST /uploads/{dry_run_id}/commit` reexecuta com persistência real (file_sha256 + summary já conferem).

### 5.7 Falhas parciais

- Linha com erro de parsing → acumula em log estruturado por linha, segue processando.
- Se >5% das linhas falharem → abort transação, status=`FALHOU`.

---

## 6. Endpoints API

### 6.1 Internos (auth JWT, role admin/operador)

Prefix: `/api/v1/admin/base-processual`.

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/uploads/dry-run` | multipart `file=*.xlsx` → simula diff sem persistir, retorna `{dry_run_id, summary, eventos_preview}` |
| `POST` | `/uploads/{dry_run_id}/commit` | confirma a aplicação |
| `POST` | `/uploads` | upload direto (legado/automação) — equivalente a dry-run + commit auto |
| `GET` | `/uploads` | paginado, filtros `status`, `from_date`, `to_date` |
| `GET` | `/uploads/{id}` | detalhe (summary, link download original) |
| `GET` | `/uploads/{id}/eventos` | paginado, filtro `tipo_evento` |
| `GET` | `/uploads/{id}/download` | XLSX original |
| `GET` | `/processos` | paginado com filtros completos |
| `GET` | `/processos/{cod_ajus}` | detalhe (estado atual + 5 últimos snapshots) |
| `GET` | `/processos/{cod_ajus}/historico` | snapshots paginados |
| `GET` | `/processos/{cod_ajus}/eventos` | eventos do processo |
| `PATCH` | `/processos/{cod_ajus}` | override manual |
| `POST` | `/processos/bulk-update` | `{filter:{...}, set:{...}}` — gera eventos `ATUALIZADO_MANUAL` |
| `GET` | `/dashboard/resumo` | KPIs (ativos, hoje novos/saídos/atualizados, último upload, top responsáveis, distribuição UF) |
| `GET` | `/dashboard/serie-diaria` | `{from, to}` → entradas/saídas/atualizações por dia |
| `GET` | `/dashboard/movimentacao-do-dia` | `{data?}` → `{entraram:[...], sairam:[...], atualizados:[...]}` paginado por seção |
| `GET` | `/dashboard/inatividade` | tempo desde último upload + flag de alerta |
| `POST` | `/exports` | `{filter,formato,colunas,template}` → assíncrono, retorna `export_id` |
| `GET` | `/exports/{id}` | status + download URL |
| `GET/POST/DELETE` | `/api-keys` | CRUD de chaves externas |

### 6.2 Externos (auth via `X-Base-Processual-Key`)

Prefix: `/api/v1/public/base-processual`.

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/processos` | paginado read-only; campos sensíveis só com scope adequado |
| `GET` | `/processos/{cod_ajus}` | detalhe |
| `GET` | `/processos/by-cnj/{cnj}` | lookup por CNJ |
| `GET` | `/dashboard/resumo` | KPIs públicos |
| `GET` | `/health` | sem auth, healthcheck |

**Rate limit:** por chave, valor de `rate_limit_per_min`. Implementação inicial in-memory por worker; subir pra Redis se virar gargalo.

---

## 7. Frontend — UX é gate de merge, não polish

> ## ⚡ A barra de UX desse módulo é "fora da caixa".
>
> Esse não é um CRUD admin genérico. É a cabine de comando operacional do Jonílson pra controle de carteira processual. UX, microinteração, performance percebida e clareza são **gates de merge**, não polish opcional. Toda decisão técnica é checada contra a tela final. Frontend mediano = recusado em review.

### 7.0 Princípios de UX & Direção de Design

#### 7.0.1 North Star

> **"Em 10 segundos, o Jonílson abre a aba e já sabe se o cliente sacaneou ele hoje."**

Toda decisão de UX é checada contra essa pergunta. Se algo não serve a ela, fica em segunda dobra ou cai fora.

#### 7.0.2 Pilares (não-negociáveis)

1. **Densidade controlada com folga.** Tabelas densas (mais info por viewport) com microespaçamento, separadores sutis, tipografia tabular (`tabular-nums`). Nada de "card-card-card" gigante mostrando 8 itens por scroll.
2. **Velocidade percebida > velocidade real.** Skeletons semânticos (não spinners genéricos), optimistic updates em bulk actions (UI muda antes do servidor confirmar, com rollback se falhar), prefetch ao hover (250ms debounce).
3. **Continuidade espacial.** Detalhe de processo abre em **drawer lateral** (`Sheet` do shadcn), não navega. Voltar = fechar. Filtros usam `useTransition` do React 18 — nada recarrega.
4. **Defaults inteligentes.** Abre na visão "Hoje", filtros pré-aplicados em "ativos", ordenação por última movimentação. Operador raramente precisa configurar.
5. **Power user em primeiro plano.** Command palette (⌘K), atalhos de teclado documentados, ações em massa com seleção via DSL leve, copy-as-markdown nas tabelas.
6. **Honestidade em todo estado.** Empty state explica o que pode acontecer ali, erro tem ação, loading mostra progresso real ("Processando linha 1.234/5.979").
7. **Reversibilidade.** Toda ação destrutiva tem **undo de 60s** via toast Sonner. Modal de confirmação só pra ações realmente irreversíveis.

#### 7.0.3 Patterns que diferenciam

**A) Upload com dry-run preview** — KEY DIFFERENTIATOR
Operador arrasta o XLSX → backend simula diff **sem persistir** → frontend mostra:

> "Esta planilha vai:
> · adicionar **42 novos** processos (lista colapsável)
> · marcar **3 como saídos** (Cód AJUS 99012, 88440, 71223 — clique pra ver)
> · atualizar **187 existentes** (167 mudança de responsável, 20 mudança de valor)
> · 5.747 inalterados.
>
> [Cancelar] [Confirmar e aplicar]"

Elimina "subi a planilha errada e f**i a base". Endpoints `POST /uploads/dry-run` (TTL 30min) + `POST /uploads/{id}/commit`.

**B) Side-by-side diff de snapshots** — estilo GitHub
No detalhe do processo, aba "Histórico" → seleciona 2 snapshots → viewer com campos lado a lado, destaque vermelho/verde nas mudanças. Click em "Ver evento que causou" → drilla pro upload responsável. Lib: `react-diff-viewer-continued`.

**C) Command palette ⌘K** — `cmdk`
- "abrir 99582" → drawer
- "saídas dos últimos 7 dias"
- "exportar carteira ativa SP" → dispara export
- "subir nova planilha" → abre uploader
- Fuzzy match em CNJ, partes, responsável.

**D) Saved views (filtros nomeados)**
Operador filtra → "Salvar como visão" → vira aba pinada. v1 em `localStorage`; v2 sincroniza com tabela `base_processual_saved_view`.

**E) Animated counters + sparklines nos cards**
Cards do dashboard com count-up animado quando o valor muda (`framer-motion`). Sparkline de 30d em cada card. Hover revela "vs ontem", "vs média 7d". Pulse verde/vermelho discreto quando entra/sai processo.

**F) Inline edit nas tabelas**
Click em "Responsável" da linha → combobox inline → blur salva (optimistic). Toast Sonner "Salvo. Desfazer" por 60s.

**G) Bulk select com DSL leve**
Header com botão "Selecionar via expressão". Mini-DSL: `responsavel = "Thays" AND uf in ("BA","SP")`. Parsing no front. Power user explode produtividade.

**H) Mobile-first do dashboard**
Visão Geral colapsa pra scroll vertical único no mobile, cards 2x2. Resto das telas é desktop-first.

**I) Drag-to-multiselect** nas listas de eventos (Linear-style).

**J) Diff resumido em badge cromática** nas listas de eventos
Linha de evento `ATUALIZADO` mostra inline `valor_causa: R$ 0 → R$ 1.500` em pílulas vermelha→verde, sem precisar abrir modal. Hover expande lista completa.

#### 7.0.4 Sistema visual

- **Stack:** Tailwind + shadcn/ui (manter, sem reinventar). Adições: `framer-motion`, `sonner`, `cmdk`, TanStack stack.
- **Tipografia:** Inter (default shadcn). `tabular-nums` em colunas numéricas.
- **Spacing scale rigoroso:** 4 / 8 / 12 / 16 / 24 / 32 / 48. Nada fora.
- **Color tokens semânticos** (light + dark com par pré-definido):
  - `success` (entrou) — verde-500 / fundo verde-50
  - `danger` (saiu) — vermelho-500 / fundo vermelho-50
  - `warning` (atualizado) — âmbar-500 / fundo âmbar-50
  - `neutral` (inalterado) — cinza-400
- **Iconografia:** Lucide.
- **Microinteractions:** `framer-motion`, regra dura — animações ≤ 200ms, easing `ease-out`, respeita `prefers-reduced-motion`. Zero bouncing/parallax.
- **Empty states ilustrados:** SVG line-art + texto humano por contexto.
- **Dark mode** desde o dia 1.

#### 7.0.5 Acessibilidade (WCAG 2.1 AA — gate de CI)

- Contraste ≥ 4.5:1 texto, ≥ 3:1 UI.
- Focus visível em **tudo**.
- Atalhos documentados em modal `?` (j/k navega, x seleciona, / busca, esc fecha).
- `aria-label` em ícones-only buttons.
- `prefers-reduced-motion` respeitado.
- CI: `axe-core` + `eslint-plugin-jsx-a11y` zero violações críticas.

#### 7.0.6 Performance percebida (gates de merge)

- **Lighthouse Performance ≥ 90, Accessibility ≥ 95** em produção (ao menos no dashboard).
- Tabela de Processos virtualizada via `@tanstack/react-virtual` (>200 linhas).
- `@tanstack/react-query` com `staleTime` agressivo, `refetchOnWindowFocus` desligado em catálogos.
- Prefetch ao hover na linha (250ms debounce) → drawer abre instantâneo.
- Bundle <500KB gzipped por rota (code-split por sub-aba via `React.lazy`).
- Skeleton loaders com a forma exata do conteúdo final.
- First contentful paint do dashboard < 1.5s no 4G simulado.

#### 7.0.7 Bibliotecas adicionais

| Lib | Uso |
|---|---|
| `cmdk` | Command palette ⌘K |
| `sonner` | Toasts elegantes com undo |
| `framer-motion` | Microinteractions, counters |
| `@tanstack/react-table` v8 | Tabelas headless |
| `@tanstack/react-virtual` | Virtualização |
| `@tanstack/react-query` | Cache + optimistic updates |
| `react-diff-viewer-continued` | Diff side-by-side |
| `react-dropzone` | Drag-and-drop XLSX |

#### 7.0.8 Quality gates antes de mergear

1. **Visual review do Jonílson** — passa "teste do North Star" (10s pra ler a tela).
2. **Lighthouse ≥ 90/95** em build de produção.
3. **`axe-core` zero violações críticas** + `eslint-plugin-jsx-a11y` clean.
4. **Smoke test Playwright** em 3 fluxos: upload + dry-run + commit; abrir processo + ver histórico; bulk update + undo.
5. **Componentes com props/variants** documentados via JSDoc (sem precisar Storybook).
6. **Mobile sanity** — dashboard renderiza no iPhone SE sem overflow horizontal.
7. **Dark mode** funcional em todas as telas novas.

### 7.1 Estrutura de sub-abas

```
[ Visão Geral ] [ Processos ] [ Uploads ] [ Eventos ] [ Relatórios ] [ API Keys ]
```

Localização: nova entrada em `frontend/src/pages/AdminPage.tsx` (verificar como o admin é organizado hoje). Sub-abas internas via `<Tabs>` shadcn, code-split por aba via `React.lazy`.

### 7.2 Visão Geral (dashboard)

> Foco = **controle diário de carteira**. Tela operacional, não decorativa.

- **Cards superiores** (4): "Ativos na base", "Entraram hoje", "Saíram hoje", "Atualizados hoje". Mini-sparkline de 30d. Hover mostra "vs ontem", "vs média 7d". Count-up animado.
- **Painel "Movimentação do dia"** (destaque, abaixo dos cards), 2 colunas:
  - 🟢 **Entraram hoje** — lista paginada Cód AJUS · CNJ · Empresa · Responsável · Distribuído em. Linha clicável → drawer. Botão "Exportar lista (XLSX)".
  - 🔴 **Saíram hoje** — mesma estrutura, mostrando o **último estado conhecido** + "Visto pela última vez em: <data>". Munição pra cobrar o cliente.
  - Toggle: "Hoje" / "Ontem" / "Últimos 7 dias" / "Customizado". Default "Hoje".
- **Gráfico principal**: linha 3 séries (entradas/saídas/atualizações por dia, 90d). Recharts. Click no ponto → drilla pro dia.
- **Alerta de inatividade**: banner amarelo se >24h sem upload. Threshold via env `BASE_PROCESSUAL_UPLOAD_WARNING_HOURS=24`.
- **Distribuição** (donut, segunda dobra): UF, matéria, situação.
- **Top responsáveis** (bar): 10 usuários com mais processos.
- **Última atividade** (sidebar/coluna direita): feed das 20 movimentações mais recentes cross-data.

### 7.3 Processos

Tabela paginada (default 50/pg, seletor 25/50/100), padrão da casa (`PublicationsPage` / `PrazosIniciaisPage`).

- **Filtros**: empresa, UF, comarca, situação, polo, responsável, presença (Ativo/Removido), valor causa range, distribuído entre.
- **Busca**: CNJ (com/sem máscara), Cód AJUS, autor/réu (LIKE no JSONB).
- **Colunas default**: Cód AJUS, CNJ mascarado, Empresa, Polo, Situação, Responsável, UF/Comarca, Valor Causa, Status presença, **Entrou em**, **Saiu em** (se aplicável), Última atualização. Toggle de colunas.
- **Linha clicável** → drawer com tabs (Estado atual, Histórico, Eventos).
- **Ações em massa**: select-all, "Exportar selecionados", "Atualizar em lote" (modal com campos editáveis).
- **Inline edit** em Responsável e Situação (optimistic + undo 60s).

### 7.4 Uploads

- Tabela paginada: data, usuário, filename, status (badge), summary (badges coloridas), botão "Baixar original".
- Click → modal/drawer com lista paginada de eventos, filtrável por `tipo_evento`.
- **Botão fixo no topo: "Subir nova planilha"** com drag-and-drop fullscreen. Após drop → tela de **dry-run preview** com summary detalhado e listas colapsáveis. Botão "Confirmar e aplicar" só aparece após validação OK.
- Indicador de progresso real durante processamento ("Linha 1.234/5.979").

### 7.5 Eventos

Tabela cross-upload paginada — auditoria global. Filtros: tipo, período, cod_ajus, upload_id. Cada linha mostra `de → para` em badge cromática. Drag-to-multiselect estilo Linear.

### 7.6 Relatórios

Form: filtros + colunas + formato (XLSX/CSV) + período. **6 templates pré-prontos**:

1. **Movimentação semanal** — entradas/saídas/atualizações da semana, com diff por processo.
2. **Carteira por responsável** — agrupado por usuario_responsavel, totais e valores agregados.
3. **Sumiços do mês** — todos os `REMOVIDO_NA_BASE` no período.
4. **Variação de valores** — `valor_causa` mudou ≥ X% no período.
5. **Carteira por UF/Comarca** — pivot espacial.
6. **Snapshot completo** — estado atual de todos os ativos (1 linha por processo, igual planilha original).

Histórico dos últimos 20 relatórios gerados, status, link de download.

### 7.7 API Keys

- Tabela: nome, prefix, scope, criada em, último uso, status.
- v1: 1 chave seedada default. UI permite "regerar" e "revogar" (multi-key destravável depois).
- "Regerar" mostra a chave **uma única vez** (pattern padrão) com botão copy-to-clipboard.

---

## 8. Autenticação e segurança

- **Internos:** JWT existente. Permissão `admin` ou role nova `base_processual_operador` (verificar RBAC atual).
- **Externos:** header `X-Base-Processual-Key`, lookup por hash, rate limit, log de uso.
- **PII (CPF de autores):** logs **nunca** imprimem CPF inteiro. Middleware de mascaramento (`***.***.***-XX`) no formatter de logs estruturados.
- **Storage do XLSX original:** `/data/base-processual/uploads/{upload_id}.xlsx`. Cleanup configurável (default 90 dias).

---

## 9. Performance

Para 5.979 linhas:
- Parse XLSX (openpyxl read-only): ~3s.
- Diff + persistência: ~10–20s estimado. Bulk insert via `bulk_save_objects`.
- **v1 = síncrono** com timeout HTTP elevado (até 90s).
- **v2 (>10k linhas)** = job APScheduler `bp_upload_worker`, endpoint POST devolve 202 + `upload_id`, frontend polling.

Indexação crítica:
- `base_processual_processo (cod_ajus)` UNIQUE — lookup principal.
- `base_processual_processo (presenca_status, last_seen_upload_id)` — detecção de saídas.
- `base_processual_snapshot (processo_id, captured_at DESC)` — histórico.
- `base_processual_evento (upload_id, tipo_evento)` — drill-down do upload.

GIN em `autores_json`/`reus_json` só sob demanda (busca por nome de autor virar caso de uso real).

---

## 10. Migrações alembic (prefixo `bp*`)

> **Antes de criar:** rodar `docker exec onetask-api-1 sh -c "cd /app && alembic heads"` (CLAUDE.md). Usar o head atual como `down_revision`. Se vier mais de uma linha, criar `merge_heads` antes.

- `bp001_add_base_processual_tables.py` — cria tabelas 4.1–4.5.
- `bp002_add_dry_run_evento.py` — tabela auxiliar do dry-run preview (se decidir não reutilizar a `evento` principal).
- `bp003_add_api_log.py` (fase 2) — telemetria de chaves.
- `bp004_indices_jsonb_partes.py` (sob demanda) — GIN em `autores_json`/`reus_json`.
- `bp005_add_saved_view.py` (fase 2) — sync de saved views.

Sem migrations destrutivas previstas no v1.

---

## 11. Roadmap em chunks (1 PR por chunk)

> Validar tudo em `feat/prazos-iniciais` antes de mergear pra `main`.

### Chunk 1 — Esqueleto + ingestão + diff (~2 dias, 1 PR)
- Migration `bp001`.
- Models + schemas Pydantic V2.
- `upload_processor.py` com pipeline completo (parse → diff → persist → eventos) + dry-run.
- Endpoints `POST /uploads/dry-run`, `POST /uploads/{id}/commit`, `POST /uploads`, `GET /uploads`, `GET /uploads/{id}`, `GET /uploads/{id}/eventos`.
- Testes unitários do diff (mocks de planilha pequena: 3 linhas — ENTROU/SAIU/ATUALIZADO/INALTERADO).
- **Critério de pronto:** subir a planilha real via swagger, conferir summary `5.979 novos / 0 removidos / 0 atualizados / 0 inalterados`. Re-subir → `IDEMPOTENTE`.

### Chunk 2 — Frontend Uploads + Visão Geral (~2 dias, 1 PR)
- Aba "Base Processual" no `/admin` com sub-abas estruturadas.
- Página Uploads (tabela + drag-and-drop com **dry-run preview** + botão confirmar).
- Página Visão Geral: cards animados, painel Movimentação do dia, gráfico de séries, alerta de inatividade.
- Endpoints `GET /dashboard/resumo`, `GET /dashboard/serie-diaria`, `GET /dashboard/movimentacao-do-dia`, `GET /dashboard/inatividade`.
- ⌘K command palette começa aqui (mesmo que com poucas ações).
- **Critério de pronto:** operador sobe planilha do dia seguinte (artificial: editar 1 célula, remover 1 linha, adicionar 1) → dry-run mostra os 3 movimentos corretamente → commit → dashboard reflete.

### Chunk 3 — Processos + drawer detalhe + diff de snapshots (~2 dias, 1 PR)
- Endpoint `GET /processos` com filtros e busca.
- Página Processos: tabela virtualizada paginada, filtros, busca, drawer detalhe com tabs (Estado atual, Histórico, Eventos).
- Diff side-by-side de snapshots no detalhe.
- Inline edit em Responsável + Situação (optimistic + undo).
- **Critério de pronto:** filtrar por UF=BA + polo=Passivo + situação=Ativo retorna subset esperado; abrir processo e selecionar 2 snapshots mostra diff campo-a-campo.

### Chunk 4 — Eventos + bulk update + saved views (~1.5 dias, 1 PR)
- Página Eventos com filtros e drag-to-multiselect.
- Endpoint `POST /processos/bulk-update` + UI "Atualização em lote".
- Endpoint `PATCH /processos/{cod_ajus}` + UI override individual.
- Saved views em localStorage.
- **Critério de pronto:** bulk update muda `usuario_responsavel` em 50 processos com 1 click + undo funciona em 60s + eventos `ATUALIZADO_MANUAL` aparecem na lista.

### Chunk 5 — Relatórios + Exports (~2 dias, 1 PR)
- Service de geração XLSX (verificar se Publications/Prazos Iniciais tem service equivalente reutilizável).
- Endpoint `POST /exports` + `GET /exports/{id}`.
- 6 templates pré-prontos.
- Página Relatórios com form + histórico.
- **Critério de pronto:** gerar "Movimentação semanal" cobrindo último upload, abrir XLSX, valores batem com a UI.

### Chunk 6 — API pública + chaves (~1.5 dias, 1 PR)
- Endpoints `/public/*`.
- Tabela e fluxo de API keys (1 chave seedada default).
- Middleware de auth + rate limit.
- Documentação externa (markdown + Postman collection).
- **Critério de pronto:** consumidor externo chama `GET /public/processos?empresa=banco_master` com chave válida e recebe 200; sem chave → 401; chave revogada → 403.

### Chunk 7 — Polish + LGPD + robustez (~1 dia)
- Logs estruturados com mascaramento de PII.
- Cleanup de arquivos antigos (job APScheduler + dry-runs expirados).
- Lighthouse + axe-core gates passando.
- Smoke tests Playwright.
- Documentação operacional (`docs/BASE_PROCESSUAL_OPERACIONAL.md`).

**Total estimado:** ~10–11 dias úteis (1 dev focado). Paralelizável: dev1 backend (1, 3, 4, 6), dev2 frontend (2, 5, 7).

---

## 12. Riscos e pontos de atenção

| Risco | Mitigação |
|---|---|
| Cliente muda formato da planilha (renomeia/adiciona coluna) | Validação flexível por nome, não índice. Falhar com mensagem clara |
| Falsos positivos no diff (ruído de campos voláteis) | Lista `SIGNIFICANT_FIELDS` curada — aprovada na seção 5.3 |
| Performance (carteira pode crescer pra 50k+) | Bulk operations + APScheduler como fallback. Índices desde o dia 1 |
| Conflito de uploads simultâneos (2 operadores) | Lock pessimista por `empresa` ou unique constraint via `file_sha256` + serializar via APScheduler |
| LGPD — armazenamento de CPF | Confirmar com Jurídico (provavelmente OK, dado já está no L1, é operacional). Documentar política de retenção |
| Vazamento de chave externa | Hash da key (nunca plaintext), revoke instantâneo, log de uso |
| Cliente não sobe planilha por dias | Banner de inatividade + alerta opcional via email/Slack se >48h |
| Truncamento de Edit/Write em arquivos grandes | Fluxo via `git show` + `python str.replace` (CLAUDE.md) |

---

## 13. Fora do escopo v1

- Reconciliação automática com Legal One via API (pull direto). v1 é só upload manual.
- Ingestão de outros formatos (CSV, JSON). v1 é XLSX-only.
- Notificações email/Slack — fase 2 ou módulo dedicado.
- Permissionamento granular por empresa (multi-tenant strict). v1 é "todo admin vê tudo".
- Webhook reverso pro consumidor externo. Polling-only no v1.
- Multi-key UI (criar N chaves no admin) — modelado no banco mas UI v1 só permite 1.

---

## 14. Próximo passo

Começar **Chunk 1**:

1. Rodar `docker exec onetask-api-1 sh -c "cd /app && alembic heads"` no container do Coolify pra pegar o(s) head(s) atual(is).
2. Se vier mais de 1 head, criar migration `bp000_merge_heads.py` antes.
3. Criar `bp001_add_base_processual_tables.py` com `down_revision` apontando pro head limpo.
4. Criar `app/models/base_processual.py` com as 5 tabelas.
5. Criar `app/services/base_processual/upload_processor.py` com pipeline completo (parse → normalizar → diff_hash → aplicar → eventos), incluindo dry-run.
6. Endpoints em `app/api/v1/endpoints/base_processual.py`.
7. Testes unitários do diff em `tests/services/base_processual/test_upload_processor.py`.
8. Validar localmente subindo a planilha do Jonílson via swagger.
9. Entregar bloco PowerShell pro commit (`feat/prazos-iniciais`):

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "feat(base-processual): chunk 1 — modelo, pipeline de upload com dry-run e diff"
git push origin feat/prazos-iniciais
```

10. Após validação no Coolify: avaliar se Chunk 2 entra na mesma branch ou em PR separada.

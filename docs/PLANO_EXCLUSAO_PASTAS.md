# Plano — Módulo de Exclusão de Pastas

> Documento de planejamento para entrega ao Claude Code.
> Branch alvo: `feat/prazos-iniciais` (branch de teste). Validado → merge pra `main`.
> Data: 2026-05-08

---

## 1. Contexto e motivação

A MDR recebe pastas (processos) de clientes e, com alguma frequência, esses
mesmos processos são retirados (cliente sai, cliente reorganiza carteira,
processo migra de escritório). Hoje a exclusão dessas pastas no Legal One
é feita manualmente, uma a uma, no painel do L1 — trabalho lento e sujeito
a erro.

Este módulo automatiza a exclusão em lote via API do Legal One, com
auditoria local e três formas de input pro operador.

## 2. Premissa a ser validada empiricamente

A documentação OpenAPI do L1 (`/Lawsuits/{id}` DELETE) lista apenas as
respostas **204 / 401 / 403 / 404 / 429**. Nada documentado sobre 409
Conflict ou 400 BadRequest quando a pasta tem **tarefas em aberto**.

Comportamento real só sai testando. Estratégia:

- **Fase 1 (MVP)**: módulo dispara `DELETE /Lawsuits/{id}` direto. Captura
  TUDO que o L1 devolver no `l1_response_body`. Marca o item como
  `BLOQUEADO_L1` quando vem 4xx.
- **Fase 2 (condicional)**: se Fase 1 confirmar bloqueio por tarefa
  aberta, integra com o runner de cancelamento de tarefas que **já
  existe** no projeto (módulo Publications / Dispatch Treatment). HITL
  no operador antes de cancelar.

**Antes de começar a implementação, rodar 1 teste manual** (Postman ou
cURL) com 1 pasta de teste que tenha 1 tarefa em aberto. Resultado dita
se Fase 2 é prioritária ou opcional.

## 3. Convenções

- Módulo (UI / domínio): **Exclusão de Pastas**
- Pacote backend: `app/services/folder_deletion/`
- Endpoints: `/api/v1/folder-deletion/*`
- Rota frontend: `/exclusao-pastas`
- Prefixo de migration: **`excl`** (segue padrão da casa: `ajus*`, `pin*`, `pub*`)
- Escopo: **somente Lawsuits**. Appeals e ProceduralIssues filhos são
  responsabilidade do cascade do próprio L1 — não chamar DELETE neles
  manualmente. Se o L1 reclamar de filhos nos testes, aí sim revisar.

## 4. Modelo de dados

### Tabela `folder_deletion_jobs`

Cada lote disparado pelo operador é um job. Permite reprocessar lotes
parciais e gerar histórico.

| coluna | tipo | nota |
|---|---|---|
| `id` | uuid pk | |
| `created_at` | timestamptz default now() | |
| `created_by_user_id` | int fk users | quem disparou |
| `source` | enum | `CONTRA_PLANILHA` / `PLANILHA_DIRETA` / `COLAR_CNJ` |
| `source_filename` | text null | nome do arquivo subido |
| `total_items` | int | |
| `status` | enum | `RASCUNHO` / `EM_REVISAO` / `EXECUTANDO` / `CONCLUIDO` / `CONCLUIDO_COM_FALHAS` / `CANCELADO` |
| `executed_at` | timestamptz null | quando foi disparado o execute |
| `notes` | text null | observação livre do operador |

### Tabela `folder_deletion_items`

Uma linha por pasta candidata.

| coluna | tipo | nota |
|---|---|---|
| `id` | uuid pk | |
| `job_id` | uuid fk → jobs (ON DELETE CASCADE) | |
| `cnj_input` | text | o que o operador colou/subiu (cru) |
| `cnj_normalizado` | text null | aplicar `_format_cnj_mask` |
| `lawsuit_id_l1` | int null | resolvido via API L1 |
| `office_path` | text null | `LegalOneOffice.path` resolvido |
| `status` | enum | `PENDENTE_RESOLUCAO` / `NAO_ENCONTRADO_L1` / `PRONTO_PARA_EXCLUIR` / `EXCLUINDO` / `EXCLUIDO_OK` / `BLOQUEADO_L1` / `ERRO_OUTRO` / `IGNORADO_PELO_OPERADOR` |
| `attempts` | int default 0 | tentativas de DELETE |
| `last_attempt_at` | timestamptz null | |
| `l1_response_status` | int null | HTTP code da última tentativa |
| `l1_response_body` | text null | body cru (debug + decisão Fase 2) |
| `tasks_cancelled_count` | int default 0 | preenchido na Fase 2 |
| `selected_for_execution` | bool default true | toggle no preview |
| `error_message` | text null | mensagem amigável pt-BR |
| `created_at` | timestamptz default now() | |
| `updated_at` | timestamptz default now() | |

### Migrations

- `excl001_create_folder_deletion_jobs.py`
- `excl002_create_folder_deletion_items.py`

> ⚠️ **Antes de criar essas migrations, conferir `alembic heads`** (CLAUDE.md
> seção "MIGRATION NOVA"). Encadear no head atual e, se houver mais de um,
> criar `excl000_merge_heads_*.py` antes.

## 5. Os três fluxos de input

Os três alimentam o **mesmo backend** — o que muda é só a UI de origem.
Backend recebe `{ source, items: [{cnj_input}], filename?: str }` e cria
um job em `RASCUNHO`, resolve cada item via L1, e o job avança pra
`EM_REVISAO`.

### 5.1. Contra-planilha (caso principal de uso)

Operador sobe a planilha "fonte da verdade" do que **É** da MDR. Sistema
calcula o diff contra o L1 e marca como **candidatas a exclusão** as
pastas que estão no L1 mas **não** estão na planilha.

**Passos**:

1. Operador sobe planilha (`.xlsx` ou `.csv`). Coluna obrigatória: `cnj`
   (ou `lawsuit_id`). Opcionais: `cliente`, `escritorio`.
2. Sistema busca em `/Lawsuits` do L1 todas as pastas dos escritórios da
   MDR (filtro por `LegalOneOffice` selecionado pelo operador, default =
   todos).
3. Calcula 3 buckets:
   - **Em ambos** (planilha ∩ L1) → manter
   - **Só na planilha** (planilha − L1) → informativo: "talvez não
     ingeridas ainda"
   - **Só no L1** (L1 − planilha) → **CANDIDATAS A EXCLUSÃO**
4. Mostra preview com tudo **desmarcado por padrão**. Operador marca
   conscientemente.
5. Confirma → execução.

**Salvaguardas obrigatórias**:

- Bloquear se planilha cobre < 50% do L1 (provável input incompleto).
  Mensagem clara explicando o motivo.
- Mostrar contagem por escritório no diff. Se um escritório inteiro
  virou candidato, é red flag.
- Limitar lotes a **200 candidatos** na primeira versão. Operador parte
  o trabalho.

### 5.2. Upload de planilha direta

Planilha com 1 coluna `cnj` (ou `lawsuit_id`) — todas as linhas viram
candidatas a exclusão, sem diff. Caso de uso: financeiro/comercial manda
lista pronta "exclui esses".

### 5.3. Colar CNJs em textarea

1 CNJ por linha, com ou sem máscara. Ignora linhas em branco. Caso de
uso: exclusão avulsa de 1-5 pastas.

Normalização via `_format_cnj_mask` (já existe — ver `app/services/ajus/`
e memory `project_ajus_cnj_mascarado.md`).

## 6. UX — telas

Fluxo linear, sem wizard pesado. Inspirado no padrão de Prazos Iniciais
e Publications.

### Tela 1 — Listagem de Jobs (`/exclusao-pastas`)

Tabela paginada (limit 50, padrão da casa — paginação obrigatória, ver
CLAUDE.md):

| Data | Origem | Itens | Excluídas | Bloqueadas | Status | Ações |
|---|---|---|---|---|---|---|
| 08/05/26 14:30 | Contra-planilha | 47 | 42 | 5 | Concluído com falhas | Ver detalhes |

Botão `+ Novo lote` no topo abre dropdown:
**Contra-planilha** / **Subir lista** / **Colar CNJs**.

### Tela 2 — Criar lote

Varia pela origem escolhida:

- **Contra-planilha**: dropzone + multi-select de escritórios L1 +
  botão "Calcular diff".
- **Subir lista**: dropzone + preview das 5 primeiras linhas.
- **Colar CNJs**: textarea com contador "X CNJs detectados".

Submit cria o job em `RASCUNHO` → resolve via L1 (background) → avança
pra `EM_REVISAO` → redireciona pra Tela 3.

### Tela 3 — Revisão e execução do lote

Cards de contadores no topo: `Total X · Resolvidos Y · Não encontrados
no L1 Z · Selecionados W`.

Tabela paginada com checkbox por linha:

| ✓ | CNJ | Lawsuit ID | Escritório (path) | Status | Ação |
|---|---|---|---|---|---|
| ☐ | 0001234-12.2025.8.05.0001 | 18472 | MDR / Filial BA / Cível | Pronto | Ignorar |
| — | 9999999-99.2099.0.00.0000 | — | — | Não encontrado no L1 | — |

Filtros rápidos: `Pronto` / `Não encontrado` / `Bloqueado` / `Excluído`
/ `Erro`.

Botão fixo no rodapé: **`Excluir selecionados (W pastas)`**.

Modal de confirmação:

> Você está prestes a excluir **W pastas** no Legal One. Essa ação **não
> pode ser desfeita pelo flow** (mas o L1 mantém log próprio). Continuar?

Para lotes **> 50 pastas**, o modal exige digitar `EXCLUIR` num campo
(padrão GitHub). Camada extra de proteção.

Durante execução: barra de progresso, polling 2s no endpoint de status.

### Tela 4 — Detalhes de job concluído

Mesma tabela da Tela 3 read-only. Quando status = `CONCLUIDO_COM_FALHAS`,
filtro padrão em `BLOQUEADO_L1`. Cada item bloqueado mostra:

- HTTP status devolvido
- Body de resposta cru (collapsible)
- Botão **`Tentar novamente`** (Fase 1)
- Botão **`Cancelar tarefas e tentar novamente`** (Fase 2 — condicional)

## 7. Backend — endpoints

```
POST   /api/v1/folder-deletion/jobs                 # cria job + ingere itens
GET    /api/v1/folder-deletion/jobs                 # lista paginada {limit, offset, total, items}
GET    /api/v1/folder-deletion/jobs/{id}            # detalhe + counters
GET    /api/v1/folder-deletion/jobs/{id}/items      # paginado, filtro por status
PATCH  /api/v1/folder-deletion/jobs/{id}/items/{id} # toggle selected_for_execution / IGNORADO
POST   /api/v1/folder-deletion/jobs/{id}/diff       # contra-planilha: recalcula (idempotente)
POST   /api/v1/folder-deletion/jobs/{id}/execute    # dispara execução (assíncrono)
POST   /api/v1/folder-deletion/jobs/{id}/items/{id}/retry  # re-roda DELETE de 1 item
POST   /api/v1/folder-deletion/jobs/{id}/cancel     # cancela job em RASCUNHO/EM_REVISAO
```

**Endpoint Fase 2** (não implementar agora, só prever):

```
POST   /api/v1/folder-deletion/jobs/{id}/items/{id}/retry-with-task-cancel
```

Padrão de paginação `{ total, items }` é o padrão da casa
(`PublicationsPage`, `PrazosIniciaisPage`).

## 8. Backend — estrutura de serviço

```
app/services/folder_deletion/
  __init__.py
  ingestion.py       # parse de planilha/CSV/textarea → items
  resolver.py        # CNJ → lawsuit_id via L1 (com cache)
  diff.py            # contra-planilha: cruza planilha do operador com L1
  executor.py        # roda DELETE /Lawsuits/{id}, captura resposta
  task_canceller.py  # FASE 2: stub agora; integra com runner existente depois
```

### Pontos críticos do `executor.py`

- Roda em background (alinhar com APScheduler do projeto).
- Concorrência baixa: 3-5 deletes paralelos máx (não estressar L1, evita 429).
- Tratamento de **429**: backoff exponencial; após N retries esgotados,
  marca item como `PENDENTE_RESOLUCAO` pra reprocessar depois.
- Captura **TUDO** que o L1 devolve em `l1_response_body` — fonte de
  verdade pra decidir Fase 2.
- Atualiza job counters em transação separada por item processado.
- Logging em pt-BR alinhado com CLAUDE.md.

### Padrão de erros pt-BR (`error_message`)

- `BLOQUEADO_L1` (4xx) → "Legal One bloqueou a exclusão (HTTP {code}).
  Provável causa: tarefas em aberto. Use 'Cancelar tarefas e tentar
  novamente' se Fase 2 estiver ativa."
- `ERRO_OUTRO` (5xx ou exception) → "Falha temporária no Legal One.
  Tente novamente em alguns minutos."
- `NAO_ENCONTRADO_L1` (404 no resolver) → "CNJ não encontrado no Legal
  One — pasta pode já ter sido excluída ou nunca existiu."

## 9. Guard rails

- **Permissão**: ação destrutiva — restrito a perfil admin/manager.
  Alinhar com RBAC existente (decidir qual flag usar).
- **Confirmação dupla pra lotes grandes**: > 50 pastas exige digitar
  `EXCLUIR` no modal.
- **Audit log**: já coberto por `created_by_user_id` + `last_attempt_at`
  + `l1_response_body`. Logar também em log estruturado da app.
- **Idempotência**: clique duplo em "Executar" não re-dispara — endpoint
  retorna **409** se job não está em `EM_REVISAO`.
- **Validação de upload**: < 5MB e < 5000 linhas no frontend.
- **Paginação obrigatória em todas as listagens** (CLAUDE.md).

## 10. Roadmap de entrega

### Sprint 1 — MVP DELETE puro

Entrega que permite testar a hipótese do bloqueio por tarefa aberta.

- [ ] Migration `excl001` (jobs)
- [ ] Migration `excl002` (items)
- [ ] Service `ingestion.py` — parse de planilha/CSV/textarea
- [ ] Service `resolver.py` — CNJ → lawsuit_id via L1
- [ ] Service `executor.py` — DELETE direto, captura resposta
- [ ] Endpoints exceto `retry-with-task-cancel`
- [ ] Frontend: telas 1, 2 (3 abas), 3
- [ ] Smoke test manual: 1 pasta sem tarefa → 204 esperado
- [ ] **Teste empírico chave**: 1 pasta COM tarefa em aberto →
      capturar resposta crua, decidir Fase 2

### Sprint 2 — Polimento + observabilidade

Independente do resultado do teste empírico.

- [ ] Tela 4 (detalhes/histórico) com retry simples
- [ ] Filtros e contadores na tela 3
- [ ] Modal de confirmação dupla pra lote > 50
- [ ] Permissão por role
- [ ] Tela 2 contra-planilha completa (com salvaguardas)

### Sprint 3 — Branch de cancelamento (CONDICIONAL)

Só se Sprint 1 confirmar que o L1 bloqueia exclusão por tarefa em aberto.

- [ ] `task_canceller.py` integrado ao runner de cancelamento existente
      do Publications (Dispatch Treatment)
- [ ] Endpoint `retry-with-task-cancel`
- [ ] Botão na Tela 4
- [ ] HITL: lista as tarefas que serão canceladas, pede confirmação
- [ ] Atualiza `tasks_cancelled_count` no item

## 11. Pré-requisito: teste manual no L1

Antes de codar qualquer coisa, rodar com Postman/cURL:

```http
DELETE https://api.thomsonreuters.com/legalone/.../Lawsuits/{ID_DE_TESTE}
Authorization: Bearer ...
```

Cenários a testar:

1. Pasta de teste **sem tarefa em aberto** → esperado 204.
2. Pasta de teste **com 1 tarefa em aberto** → resposta dita Fase 2.
3. Pasta com **Appeals/ProceduralIssues filhos** → ver se cascade do
   L1 funciona ou se pede DELETE manual nos filhos primeiro.

Salvar os 3 response bodies pra alimentar `executor.py` com os matchers
corretos de erro.

## 12. Referências

- API L1: `legal-one-firms-brazil-api.json` (uploads)
- Mapping de recursos: `API Resource Mapping En 1 (1).xlsx` (uploads)
- Padrão de paginação: `frontend/src/pages/PublicationsPage.tsx` e
  `frontend/src/pages/PrazosIniciaisPage.tsx`
- Padrão `_format_cnj_mask`: `app/services/ajus/`
- Runner de cancelamento de tarefas (Fase 2): módulo Publications /
  Dispatch Treatment (memory `project_dispatch_treatment_web_decoupling`)

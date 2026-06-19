# Plano de Integração — OneRequest → DunaFlow

> **Status:** Fase 1 (dados + intake) em implementação (2026-06-19); Fases 2-3
> em planejamento. Ordem na seção 10.
>
> **Decisões já tomadas com o operador:**
> 1. **RPA fica como motor separado** numa máquina do escritório (não vai pro
>    Coolify). Só passa a empurrar os dados pro Flow via API de intake.
> 2. **Acompanhamento de status no L1 é sob demanda** (mesmo paradigma do
>    módulo de Publicações — consulta o L1 quando o operador abre a DMI).
> 3. Construção em fases (ordem recomendada na seção 10).

---

## 1. Contexto

O **OneRequest** é um Flask + SQLite que acompanha as **DMIs** (Demandas
diversas de assessoria do Banco do Brasil): a solicitação chega pelo Portal
Jurídico do BB, a RPA varre/captura, e as analistas tratam e direcionam aos
responsáveis. Hoje ele vive fora do Flow.

### O que já existe (a ponte está metade pronta)

O botão "Criar tarefa" do OneRequest **já** faz
`POST http://192.168.0.66:8000/api/v1/tasks/batch-create` com
`{"fonte": "OneRequest", "processos": [...]}` — e o **Flow já consome isso**:

| Peça já existente no Flow | Arquivo |
|---|---|
| Endpoint `POST /api/v1/tasks/batch-create` (auth `X-Batch-Api-Key`) | `app/api/v1/endpoints/tasks.py:593` |
| Estratégia completa (busca CNJ, cria tarefa L1, vincula, log resiliente, e-mail de falha) | `app/services/batch_strategies/onerequest_strategy.py` |
| Dispatch por `fonte` (`"OneRequest"` → `OnerequestStrategy`) | `app/services/batch_task_creation_service.py` |
| Flag de notificação de erro por usuário | `alembic/versions/usr003_add_onerequest_notifications.py` |

**Conclusão:** o "criar tarefa no L1" **já funciona**. O que falta trazer pro
Flow é: (a) os **dados** das solicitações, (b) a **tela de tratamento**, e
(c) o **acompanhamento** do status no L1. A **RPA** continua fora.

### Por que a RPA NÃO vai pro Coolify

`RPA/portal_bb.py` detecta página de erro do portal com as dicas
`"erro no acesso"`, `"id e o seu ip"` e `"identificador de segurança"`. Ou
seja: **o Portal BB bloqueia por IP + identificador de segurança da máquina.**
Some-se a isso: a RPA dirige um Chrome real via CDP (porta 9222) aberto por
`.bat` e mata processo por `netstat`/`taskkill` (puro Windows). Um container
de nuvem no Coolify não loga lá. Logo, a RPA fica **na máquina autorizada do
escritório** — exatamente onde já roda.

---

## 2. Arquitetura-alvo

```
┌─ MÁQUINA DO ESCRITÓRIO (Windows) ───────────────────┐
│  Motor OneRequest RPA (Playwright)                  │
│   robô 1: varre números das DMIs no Portal BB       │
│   robô 2: detalha (título/NPJ/prazo/DMI/proc/polo)  │
│                                                     │
│   →  POST /api/v1/onerequest/intake/* (X-Api-Key)   │
└───────────────────────────┬─────────────────────────┘
                            │  só dados (HTTP)
┌─ FLOW (Coolify) ──────────▼──────────────────────────┐
│  Postgres: tabelas onr_*  (solicitações + tratamento)│
│  React: seção /onerequest                            │
│    farol/KPIs/filtros/gráfico + tratamento           │
│    (responsável, setor, data agend., anotação)       │
│  "Agendar" → OnerequestStrategy (JÁ EXISTE)          │
│             → cria + vincula tarefa no L1            │
│  Acompanhamento sob demanda → status da tarefa no L1 │
│    (reusa search_tasks / get_task_by_id)             │
└───────────────────────────────────────────────────────┘
```

A camada (b)/(c) **clona o padrão de Publicações** (modelo de dados, página
React e consulta de status), que já resolve exatamente esse fluxo.

---

## 3. Camada 1 — Motor RPA (fora do Flow)

Permanece na máquina do escritório. **Única mudança:** trocar a escrita no
SQLite local por chamadas HTTP ao Flow. A lógica de diff (o que respondeu, o
que é novo) **migra pro Flow** — a RPA vira um scraper "burro" que posta.

### Contrato de intake (novos endpoints no Flow, auth por API key)

| Endpoint | Quem chama | Payload | O que o Flow faz |
|---|---|---|---|
| `POST /api/v1/onerequest/intake/numeros` | robô 1 (horário) | `{ "numeros": ["2026/0000000001", ...] }` (snapshot completo dos abertos) | Diff vs `onr_solicitacoes`: marca como **Respondido** os que sumiram; insere os novos como **Aberto / detalhe pendente** |
| `GET /api/v1/onerequest/intake/pendentes-detalhe` | robô 2 (a cada 2h) | — | Retorna a lista de `numero_solicitacao` sem detalhe (título nulo) pra RPA detalhar |
| `POST /api/v1/onerequest/intake/detalhes` | robô 2 | `{ "itens": [{numero_solicitacao, titulo, npj_direcionador, prazo, texto_dmi, numero_processo, polo}] }` | Atualiza os campos da solicitação |

- **Auth:** header `X-Onerequest-Api-Key` validado contra nova env
  `ONEREQUEST_INTAKE_API_KEY` (mesmo padrão de `prazos_iniciais_api_key` /
  `batch_tasks_api_key`). Chave dedicada pra rotação independente.
- A RPA mantém **apenas** seu fluxo de login/scrape; some o `bd/database.py`,
  some o diff local. Um cliente HTTP fino substitui as chamadas de DB.

> **Observação:** o sinal "Respondido" do BB (DMI sumiu do portal) continua
> valioso e independente do L1. Ele é preservado em `status_sistema` via o
> diff do intake de números.

---

## 4. Camada 2 — Dados no Flow (Postgres)

### Model `OnerequestSolicitacao` (tabela `onr_solicitacoes`)

Espelha o SQLite `solicitacoes` + tratamento + auditoria de agendamento +
vínculo com a tarefa L1.

| Campo | Tipo | Origem / Observação |
|---|---|---|
| `id` | PK | |
| `numero_solicitacao` | str, **unique**, index | chave natural da DMI |
| `titulo` | str | RPA detalhe |
| `npj_direcionador` | str | RPA detalhe |
| `prazo` | str (DD/MM/YYYY) | **prazo do BB** (vira `vencimento` no L1 — ver §6) |
| `texto_dmi` | text | RPA detalhe (popup) |
| `numero_processo` | str, index | RPA detalhe (API interna BB) — pode vir "não encontrado" |
| `polo` | str | "Ativo"/"Passivo"/… (determinístico — ver §8) |
| `recebido_em` | datetime, index | timestamp do 1º intake (alimenta o gráfico) |
| `status_sistema` | str, index | `Aberto` / `Respondido` (diff do BB) |
| `status_tratamento` | str, index | `NOVO` / `AGENDADO` / `IGNORADO` / `ERRO` |
| `responsavel_user_id` | FK `legal_one_users.id`, null | escolhido pelo operador (combobox) |
| `setor` | str | escolhido pelo operador (mapeia type/subtype — §6) |
| `data_agendamento` | str (DD/MM/YYYY) | escolhido pelo operador (vira `prazo` no L1 — §6) |
| `anotacao` | text | operador |
| `created_task_id` | int, null, index | id da tarefa criada no L1 (chave do acompanhamento) |
| `linked_lawsuit_id` | int, null | id do processo no L1 (resolvido no agendamento) |
| `scheduled_by_user_id` / `scheduled_by_email` / `scheduled_by_name` / `scheduled_at` | auditoria | padrão de Publicações (`pub002`) |
| `created_at` / `updated_at` | datetime | timestamps |

> **Migration:** `onr001_create_onerequest_tables.py`.
> ⚠️ **Antes de criar:** rodar `docker exec onetask-api-1 sh -c "cd /app &&
> alembic heads"` e usar o head atual como `down_revision`. Se houver mais de
> um head, criar `merge_heads` antes (regra da casa).

---

## 5. Camada 3 — Tela React `/onerequest`

Espelha o dashboard do OneRequest, mas reusando os componentes do Flow.

- **Página:** `frontend/src/pages/OnerequestPage.tsx`.
- **KPIs / farol por prazo** (vencidas / hoje / amanhã / FDS / futuras) — mesma
  lógica de cores do `server.py:index()` do OneRequest.
- **Filtros:** responsável, busca (nº solicitação / processo / título).
- **Gráfico de recebimentos** (últimos 15 dias) — reusa o padrão de `recebido_em`.
- **Tabela de tratamento** com **paginação obrigatória** (regra da casa:
  `limit`/`offset`, `{total, items}`, controles "Anterior/Próxima · Página X
  de Y · seletor 25/50/100"). Reusar padrão de `PublicationsPage`.
- **Edição inline / modal:** responsável (**combobox `UserSelector`**, regra de
  dropdowns searchable — nunca `<Select>` cru), setor (combobox), data de
  agendamento, anotação.
- **Botão "Agendar"** → chama endpoint interno que roda a `OnerequestStrategy`.
- **Coluna/painel de status L1** (sob demanda — §7).
- **Roteamento/menu/permissão:**
  - rota em `frontend/src/App.tsx`;
  - item no `frontend/src/components/Layout.tsx` com
    `requirePermission: 'canUseOnerequest'`;
  - `frontend/src/services/onerequestApi.ts` (padrão `citacoesBm.ts`).

---

## 6. Camada de agendamento (reusa o que já existe)

O "Agendar" da nova tela chama um endpoint **interno** (protegido por JWT) que
reaproveita a `OnerequestStrategy` já existente — de preferência via a infra de
`BatchExecution` (log/retry/relatório de erro), exatamente como o batch atual.

### ⚠️ Mapeamento de campos crítico (nomes confusos no payload atual)

A estratégia espera **dois** campos de data com nomes que se invertem:

| Campo no payload da estratégia | De onde vem | Uso no L1 |
|---|---|---|
| `vencimento` | **prazo do BB** (`onr_solicitacoes.prazo`) | aparece só na descrição (`"PF: {vencimento}…"`) |
| `prazo` | **data de agendamento do operador** (`onr_solicitacoes.data_agendamento`) | **dirige** `startDateTime`/`endDateTime` da tarefa (16:59:59 Brasília) |

Confirmado em `server.py:exportar_json()` (envia `vencimento = item['prazo']`,
`prazo = data_agendamento`) e em `onerequest_strategy.py:190-201`.

### Campos obrigatórios (`onerequest_strategy.py:194`)

`numero_processo`, `id_responsavel`, `prazo` (data agend.), `vencimento`
(prazo BB), `setor`. No Flow o `id_responsavel` sai direto do
`LegalOneUser.external_id` do responsável escolhido — sem o mapa nome→id que o
OneRequest faz hoje (mais limpo, sem cache `legal_one_users` paralelo).

### Mapa setor → (typeId, subtypeId) (`onerequest_strategy.py:16-25`)

`BB Réu`→(15,967) · `BB Autor`→(28,969) · `BB Recurso`→(19,968) ·
`BB Execução e Encerramento`→(20,1058) · default (15,967). **Decisão p/ depois:**
manter hardcoded ou mover pra tabela/config (recomendo manter no 1º ciclo).

---

## 7. Resolução do processo no L1 (cascata CNJ → NPJ → manual)

Hoje a strategy resolve o processo só por `search_lawsuit_by_cnj(numero_processo)`.
Quando o `numero_processo` vem vazio/sujo, a tarefa não é criada. Análise da
base real do OneRequest (5.223 solicitações):

- **160 (3,1%) com `numero_processo` problemático.** Decompondo:
  - **156 vazios** (149 polo Ativo) — a API interna do BB não devolveu CNJ;
    provável processo BB-autor recém-distribuído, ainda sem CNJ atribuído.
  - **4 com string de erro** — falha **transitória** da API do BB
    (`net::ERR_HTTP_RESPONSE_CODE_FAILURE`, um `API 400`).
- **NPJ direcionador sólido:** 5.217/5.218 no formato `AAAA/NNNNNNN-NNN`. Dos
  160 problemáticos, 155 (97%) ainda têm NPJ preenchido.

**Insight:** a strategy usa o CNJ só pra achar o `lawsuit_id`
(`onerequest_strategy.py:207`). Se acharmos o `lawsuit_id` por outro caminho, o
CNJ é dispensável pro agendamento. Cascata proposta:

1. **CNJ limpo** → `search_lawsuit_by_cnj` (comportamento atual).
2. **CNJ vazio/sujo + NPJ presente** → busca no L1 por NPJ (campo a confirmar —
   ver abaixo). O L1 client já tem `search_lawsuit_by_folder` (por `folder`):
   se o NPJ estiver na pasta, reusa direto.
3. **Nada resolve** → estado `AGUARDANDO_PROCESSO` na UI (não falha silenciosa);
   a RPA re-tenta nas próximas passadas e o operador resolve manual.

**Complemento barato (lado RPA):** retry da consulta `processo/consulta/{npj}`
do BB cobre os 4 erros transitórios sem tocar no L1.

**⚠️ A confirmar (probe ao vivo no L1):** em qual campo do L1 o NPJ está gravado.
O CNJ vive em `identifierNumber`; a `folder` MDR tem formato próprio
("Proc - 0069519") que não parece o NPJ. Hipótese: campo secundário ("Número
Antigo"/outro número), ou não está gravado (e aí só o CNJ liga). Probe: pegar
par CNJ↔NPJ válido, achar por CNJ (`get_lawsuit_by_id`) e varrer os campos atrás
dos dígitos do NPJ. Precisa do stack `onetask` de pé.

**Caveat:** os 156 vazios são quase todos Ativo → possivelmente sem CNJ em lugar
nenhum ainda; pra esses nenhuma busca resolve hoje, só re-checagem ao longo do
tempo. Por isso a etapa 3 é estado, não erro.

---

## 8. Camada de acompanhamento (sob demanda)

- **Endpoint:** `GET /api/v1/onerequest/{id}/l1-status`.
- Como guardamos `created_task_id`, o caminho mais direto é
  `LegalOneApiClient.get_task_by_id(created_task_id)` → mapeia `statusId` para
  label (0 Pendente · 1 Cumprido · 2 Não cumprido · 3 Cancelado · 4 Iniciado ·
  5 Reagendado). Alternativa: `find_tasks_for_lawsuit(lawsuit_id, status_ids=…)`
  se quisermos listar todas as tarefas do processo.
- **Cache curto (15s)** no backend, igual ao `_RECENT_TASKS_CACHE` de
  Publicações, pra não martelar o L1 durante a sessão.
- **Sem job/scheduler** (decisão: sob demanda). A UI consulta quando o operador
  abre a DMI; o sinal "Respondido" do BB segue vindo do intake de números.

Métodos do `LegalOneApiClient` reusáveis: `search_lawsuit_by_cnj`,
`create_task`, `link_task_to_lawsuit`, `search_tasks`, `find_tasks_for_lawsuit`,
`get_task_by_id`, `update_task_status`.

---

## 9. Pontos de atenção / riscos

- **`numero_processo` "sujo":** ~3% dos casos vêm sem CNJ utilizável. Endereçado
  pela cascata de resolução da §7 (CNJ → NPJ → manual); a tela mostra o estado
  `AGUARDANDO_PROCESSO` em vez de estourar no L1.
- **Polo determinístico:** vem da API do BB (`indicadorPoloBanco`). Tratar como
  dado pronto e injetar — não fazer a IA re-deduzir (ver memory
  `feedback_usar_info_deterministica`).
- **Paginação e dropdowns searchable** são regra da casa — já contemplados na §5.
- **Usuários:** o gerenciamento de usuários do OneRequest **é descartado**;
  responsável passa a ser `LegalOneUser` do Flow. Nada de tabela de usuários
  paralela.
- **Permissão nova `can_use_onerequest`:** coluna em `legal_one_users` (migration
  `usr00X`), claim no JWT (`app/api/v1/endpoints/auth.py`), `canUseOnerequest`
  no `AuthContext`, e `require_permission("onerequest")` nos endpoints de UI.
- **Env nova pro Coolify:** `ONEREQUEST_INTAKE_API_KEY` (documentar no
  `.env.example` e avisar o operador pra setar no painel antes do redeploy).
- **Cutover:** rodar em paralelo por um período — apontar o intake da RPA pro
  Flow, validar dados/tratamento/agendamento, e só então aposentar a UI Flask e
  o SQLite.

---

## 10. Ordem de construção recomendada (quando der o "ok")

1. **Fase 1 — Dados + intake + RPA reapontada:**
   - migration `onr001` (tabelas), model, schemas;
   - endpoints de intake (`/intake/numeros`, `/intake/pendentes-detalhe`,
     `/intake/detalhes`) + env `ONEREQUEST_INTAKE_API_KEY`;
   - adaptar a RPA (trocar SQLite por cliente HTTP);
   - validar que as DMIs chegam e sincronizam no Postgres.
2. **Fase 2 — Tela de tratamento + agendar:**
   - página React `/onerequest`, menu, rota, permissão `can_use_onerequest`;
   - endpoint interno de "Agendar" reusando `OnerequestStrategy`/`BatchExecution`;
   - paginação + comboboxes searchable.
3. **Fase 3 — Acompanhamento + polimento:**
   - endpoint `l1-status` (sob demanda, cache 15s) + UI de status;
   - relatório de erro / retry (reaproveita infra de batch);
   - aposentar a UI Flask + SQLite (cutover).

---

## 11. Mapa de reuso (de onde copiar)

| Necessidade OneRequest | Reusar de |
|---|---|
| Modelo intake + tratamento + auditoria | `PublicationRecord` / `PublicationTreatmentItem` (`app/models/publication_*.py`) |
| Página React (lista paginada, filtros, modal) | `PublicationsPage.tsx` |
| Consulta de status no L1 sob demanda + cache | `get_recent_tasks_for_lawsuit` (`publication_search_service.py`) |
| Criar/vincular tarefa no L1 | `OnerequestStrategy` (já pronta) + `LegalOneApiClient` |
| Intake autenticado por API key | padrão `prazos-iniciais/intake` + `_validate_batch_api_key` (`tasks.py:71`) |
| Registro de router/rota/menu/permissão | seção "mapa de plugagem" (citacoes-bm / classificador) |

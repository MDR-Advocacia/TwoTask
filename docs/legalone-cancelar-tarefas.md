# Cancelar Tarefas no Legal One (método maduro)

> **Objetivo deste documento:** subsidiar a implementação no **Flow** do
> cancelamento de tarefas do Legal One — individual ou em lote. É o método **mais
> maduro** desta seção: roda em produção, já cancelou **+4.300 tarefas num único
> lote** e sobrevive a restart de container, expiração de sessão e rate limit.
>
> Companheiro do doc `legalone-reatribuir-responsavel-executante-tarefa.md`
> (reatribuição de responsável/executante). Login e modelo de dados se
> sobrepõem; aqui o foco é **cancelar = mudar o status da tarefa para 3
> (Cancelado)**.
>
> Validado em produção (tenant MDR). Pivotagem para HTTP direto: 2026-05-08.

---

## 1. TL;DR (dois mecanismos)

| Mecanismo | Funciona em | Como | Maturidade |
|---|---|---|---|
| **A) API PATCH** | Tarefa **normal** apenas | `PATCH /tasks/{id}` `{"statusId": 3}` → 204 | Simples; ⛔ 400 em Workflow |
| **B) POST web (ModalEnvolvimentoEmLote)** | **Normal E Workflow** | POST no endpoint web do L1 + verificação via API | ✅ **Método de produção** |

**Regra de ouro:** o método **B** é o que você quer para um cancelador
genérico/robusto. Ele **não usa** o PATCH da API (que é bloqueado nas tarefas de
Workflow — as legacy "Agendar Prazos"/"Verificar Prazos" são 100% Workflow). Ele
fala com o **mesmo endpoint que a UI do L1 usa** no modal "Alterar em lote", o
que **contorna o lock de Workflow**, e depois **confirma o resultado pela API
REST** (fonte da verdade).

---

## 2. O que é "cancelar" no L1

Cancelar = colocar a tarefa no **statusId = 3 (Cancelado)**. Não apaga nada; é
uma transição de status. Reaplicar em tarefa já cancelada é **no-op idempotente**.

### Status IDs de tarefa (L1)

| statusId | significado | terminal? |
|---|---|---|
| 0 | Pendente | não (cancelável) |
| 1 | Cumprido | **sim** |
| 2 | Não cumprido | **sim** |
| 3 | Cancelado | **sim** (alvo) |
| 4 | Iniciado | não |
| 5 | Reagendado | não |

**Estados terminais = {1, 2, 3}.** O cancelador **não mexe** em tarefas já
terminais (ver §7 — pré-check de skip). Isso protege tarefas **Cumpridas** de
serem canceladas por engano e estragarem o histórico.

---

## 3. Login e autenticação

Cancelar envolve **dois logins**, porque o método B usa o canal web e verifica
pelo canal API:

- **OAuth2 Bearer (API REST)** — usado para **resolver** a tarefa (CNJ → task) e
  para a **verificação autoritativa** do resultado. Login *client_credentials*,
  token automático no `LegalOneApiClient`.
- **Cookie `.ASPXAUTH` (web/OnePass via Playwright)** — usado para o **POST de
  cancelamento** no endpoint web. Login SSO OnePass, cookie cacheado em
  `/app/data/legacy_task_http_session.json` + filelock, TTL 30 min.

> 📎 **Os dois fluxos de login estão documentados em detalhe** (endpoints, env
> vars, cache, refresh, rate limit) na seção **3** do doc
> `legalone-reatribuir-responsavel-executante-tarefa.md` (§3.A OAuth, §3.B
> cookie web). Não repito aqui — é a mesma infra. Resumo das env vars:

| Canal | Env vars |
|---|---|
| API (resolução + verificação) | `LEGAL_ONE_BASE_URL`, `LEGAL_ONE_CLIENT_ID`, `LEGAL_ONE_CLIENT_SECRET` |
| Web (POST cancelamento) | `LEGAL_ONE_WEB_USERNAME`, `LEGAL_ONE_WEB_PASSWORD`, `LEGAL_ONE_WEB_KEY_LABEL`, `LEGAL_ONE_WEB_URL` (default `https://mdradvocacia.novajus.com.br`) |

---

## 4. Método A — API PATCH (tarefas normais)

O caminho simples, quando você **sabe** que a tarefa não é de Workflow:

```python
from app.services.legal_one_client import LegalOneApiClient
client = LegalOneApiClient()

ok = client.update_task_status(task_id, 3)   # PATCH /tasks/{id} {"statusId": 3}
# ok == True  -> HTTP 200/204
# ok == False -> falhou (ver log). Em tarefa de Workflow: HTTP 400 (lock).
```

**Lock de Workflow (igual ao da reatribuição):** tarefa gerada por Modelo de
Procedimento retorna **HTTP 400**:

```json
{"error":{"code":"Validation","target":"taskModel","details":[
  {"code":"InvalidValue","target":"id",
   "message":"O id informado é oriundo de um modelo de procedimento do Workflow, altere o registro pelo Legal One."}]}}
```

Por isso o método A **não serve** para as filas de Workflow. Use o método B
quando precisar cobrir os dois tipos (ou quando não souber o tipo de antemão).

---

## 5. Método B — POST web `ModalEnvolvimentoEmLote` (maduro, cobre tudo)

É o **mesmo endpoint que o modal "Alterar em lote" da UI do L1 chama**. Como é o
caminho da UI, **contorna o lock de Workflow**.

### Requisição

```
POST {LEGAL_ONE_WEB_URL}/processos/CompromissoTarefa/ModalEnvolvimentoEmLote?parentId=0&tipoVinculo=1
Cookie: .ASPXAUTH=<...>   (+ companhia; obtido via login OnePass/Playwright)
X-Requested-With: XMLHttpRequest
Accept: */*
Content-Type: application/x-www-form-urlencoded
```

### Corpo (form-urlencoded) — 9 campos fixos + StatusId + N IDs

```
ParentId=0
TipoVinculo=1
CampoText=Status
CampoId=0                              # 0 = campo "Status" (ver tabela CampoId abaixo)
StatusText=Cancelado
selectionViewModel[SelectAll]=false
selectionViewModel[UseStringIds]=false
StatusId=3                            # 3 = Cancelado (o valor-alvo)
selectionViewModel[SelectedIds][]=<taskId>   # pode REPETIR para lote num só POST
```

- `parentId` (na query e no body) é **decorativo** — o backend não valida.
- **Sem antiforgery token.** Auth 100% via cookie `.ASPXAUTH`.
- **Cancelar em lote num único POST:** repita `selectionViewModel[SelectedIds][]`
  para cada task. (A implementação atual manda **1 por POST** para ter
  verificação e diagnóstico por tarefa — mas o endpoint aceita N.)

### Resposta

- `200` com `{"Success": true, "SuccessMessage": "...iniciada"}` em ~250–300 ms.
- **O 200 significa "fila aceita", NÃO "executado".** O cancelamento é
  **assíncrono** no backend do L1 (~5–10 s pra refletir). Um `StatusId` inválido
  também volta 200 silencioso → por isso a **verificação via API é obrigatória**
  (§6).
- **Idempotente:** recancelar tarefa já cancelada → 200 Success no-op.
- **Sessão inválida:** `403` + corpo `"You do not have permission..."` → invalidar
  cookie, **relogar e tentar de novo 1x**; se persistir → `auth_failure`.

### Tabela `CampoId` (o mesmo endpoint altera outros campos!)

| CampoId | Campo alterado |
|---|---|
| **0** | **Status** ← cancelamento usa este |
| 1 | Descrição |
| 2 | Local |
| 3 | Executante |
| 4 | Responsável |
| 5 | Solicitante |

> 🔗 **Cross-reference importante:** `CampoId 3/4/5` é exatamente como se
> **reatribui executante/responsável/solicitante em tarefas de Workflow** (que a
> API REST bloqueia). Ou seja, este mesmo endpoint web é o caminho RPA para o
> outro doc. Ver `legalone-reatribuir-responsavel-executante-tarefa.md` §6.

---

## 6. Verificação autoritativa via API (fonte da verdade)

Depois do POST, **confirme pela API REST** que o status virou 3:

```python
# pseudo do que o service faz:
for attempt in range(3):                  # VERIFY_RETRIES = 3
    task_after = client.get_task_by_id(task_id)
    if int(task_after.get("statusId")) == 3:
        break                             # confirmado
    time.sleep(2.0)                       # VERIFY_SLEEP_S — backend L1 é assíncrono
```

- `statusId == 3` confirmado → **sucesso real** (`reason="cancelled"`).
- Confirmou que **não** é 3 → `POST não persistiu` → falha.
- API indisponível → cai no que o runner reportou (`success` só se POST deu ok).
- O retry curto evita **falso negativo** (verificar antes do L1 processar o
  cancelamento assíncrono).

---

## 7. Resolução CNJ → tarefa + pré-check de skip

### 7.1 Resolver (`LegacyTaskResolver.resolve_target_task`)

Aceita identificadores parciais e resolve a tarefa-alvo:

- **`task_id`** informado → GET direto (caminho rápido).
- **`cnj_number`** → `search_lawsuit_by_cnj` → `lawsuit_id` →
  `find_tasks_for_lawsuit(type_id, subtype_id, status_ids)` → seleção.
- **Seleção de candidato:** mais recente vence (`creationDate desc`, `id desc`
  como desempate).

**`reason` de resolução:**

| reason | significado |
|---|---|
| `task_selected` | achou a tarefa; segue pro cancelamento |
| `task_not_found` | há tarefas no processo, mas nenhuma com tipo/subtipo/status pedidos |
| `lawsuit_not_found` | CNJ inválido / processo não cadastrado |

### 7.2 Pré-check de skip (ANTES do POST — segurança)

| Estado atual | Ação | reason |
|---|---|---|
| `statusId == 3` (já cancelada) | **skip** (sem POST) | `already_in_target_status` |
| `statusId ∈ {1,2}` (terminal, Cumprido/Não cumprido) | **skip** (sem POST) | `already_in_terminal_state` |
| `statusId ∈ {0,4,5}` (não-terminal) | **POST de cancelamento** | → `cancelled` |

> ⚠️ **Nunca cancele tarefas Cumpridas.** O pré-check de `already_in_terminal_state`
> existe pra isso. No lote de +4.300, **~2.600 tarefas eram terminais e foram
> preservadas** (só ~1.700 Pendentes viraram canceladas).

---

## 8. Parâmetros e defaults (`cancel_task`)

Assinatura efetiva do método maduro
(`LegacyTaskHttpCancellationService.cancel_task`):

```python
cancel_task(
    *,
    cnj_number: str | None = None,
    lawsuit_id: int | None = None,
    task_id: int | None = None,          # informe ao menos UM destes três
    task_type_external_id: int = 33,     # default: tipo "Banco Master"
    task_subtype_external_id: int = 1283,# default: "Agendar Prazos" (legacy Workflow)
    candidate_status_ids: list[int] = [0],   # só Pendente é candidata
    target_status_id: int = 3,           # Cancelado
    target_status_text: str = "Cancelado",
    max_attempts: int = 2,               # compat; POST é atômico
) -> dict
```

- **Para cancelar uma tarefa específica:** passe **`task_id=...`** — ignora
  tipo/subtipo (vai direto no GET). Foi assim que cancelamos em lote tarefas de
  subtipos variados (resolvendo as tasks por processo antes).
- **Para a fila legacy "Agendar Prazos":** os defaults (type 33 / subtype 1283)
  já miram a tarefa certa a partir do CNJ.
- **Outros tipos por CNJ:** sobrescreva `task_type_external_id` /
  `task_subtype_external_id`.

### Formato de retorno

```python
{
  "success": True,
  "reason": "cancelled",            # ver tabela abaixo
  "cnj_number": "...", "lawsuit_id": 64347, "task_id": 321078,
  "candidate_count": 1,
  "current_status_id": 0,
  "target_status_id": 3, "target_status_text": "Cancelado",
  "runner_state": "completed",      # completed | error
  "runner_item_status": "cancelled",
  "runner_response": {"successMessage": "...", "elapsedMs": 890},
  "runner_error": None,
  "edit_url": "https://.../edittarefa/...", "details_url": "https://..."
}
```

### Tabela de `reason` (todos os desfechos)

| reason | success | significado / ação |
|---|---|---|
| `cancelled` | ✅ | cancelada e confirmada (statusId=3 via API) |
| `already_in_target_status` | ✅ | já estava cancelada (no-op) |
| `already_in_terminal_state` | ✅* | terminal (Cumprido/Não cumprido) — preservada, sem POST |
| `task_not_found` | ❌ | processo existe, tarefa-alvo não |
| `lawsuit_not_found` | ❌ | CNJ inválido / processo inexistente |
| `verification_failed` | ❌ | POST ok mas API não confirmou statusId=3 |
| `auth_failure` | ❌ | cookie inválido persistente (403) — infra |
| `timeout` | ❌ | rede/L1 5xx — infra (retentável) |
| `runner_error` | ❌ | L1 rejeitou o POST (Success=false etc.) |

\* `already_in_terminal_state` conta como "não-falha" (a tarefa já estava
encerrada). Trate no relatório como bucket separado de `cancelled`.

---

## 9. Localizar as tarefas-alvo

```python
lawsuit = client.search_lawsuit_by_cnj("0001270-27.2026.8.05.0004")
tasks = client.search_tasks(
    filter_expression=f"relationships/any(r: r/linkType eq 'Litigation' and r/linkId eq {lawsuit['id']})",
    top=30,   # ⚠️ /Tasks tem teto $top = 30 (pedir 50 → erro 400). Pagine de 30 em 30.
    select="id,description,statusId,typeId,subTypeId",
)
nao_canceladas = [t for t in tasks if t.get("statusId") != 3]
```

---

## 10. Fluxo de lote (esqueleto de produção)

Padrão validado no lote de +4.300 tarefas (2 fases, com checkpoint e retomada):

```python
import json, csv, time
from app.services.prazos_iniciais.legacy_task_http_cancellation_service import (
    LegacyTaskHttpCancellationService,
)
from app.services.legal_one_client import LegalOneApiClient

client = LegalOneApiClient()
svc = LegacyTaskHttpCancellationService()

# FASE 1 — inspeção: por CNJ, achar todas as tasks não-canceladas
inspect = []
for cnj in cnjs:
    lw = client.search_lawsuit_by_cnj(cnj)
    if not lw:
        inspect.append({"cnj": cnj, "lw_id": None, "tasks": [], "error": "no_lawsuit"}); continue
    tasks = client.search_tasks(
        filter_expression=f"relationships/any(r: r/linkType eq 'Litigation' and r/linkId eq {lw['id']})",
        top=30, select="id,statusId,subTypeId,typeId,description",
    )
    inspect.append({"cnj": cnj, "lw_id": lw["id"],
                    "tasks": [t for t in tasks if t.get("statusId") != 3], "error": None})
    # checkpoint a cada 50 -> /tmp/inspect.json

# FASE 2 — cancelamento: 1 chamada por task_id, com verificação embutida
results = []
for p in inspect:
    for t in p["tasks"]:
        r = svc.cancel_task(task_id=t["id"])   # POST web + verify API
        results.append({"cnj": p["cnj"], "task_id": t["id"],
                        "ok": r["success"], "reason": r["reason"]})
        # checkpoint a cada 25 -> /tmp/progress.json (retomada idempotente)
```

### Lições do lote de +4.300 (não repetir os perrengues)

- **Checkpoint a cada 25 itens** em JSON + **retomada idempotente** (recancelar é
  no-op → reprocessar de onde parou é seguro).
- **Rode detached** (`nohup` / processo de fundo). Lotes grandes levam **horas**:
  throughput real **~0,3 task/s** (POST + verify + 429 backoff).
- **Container reiniciou no meio?** Sem problema — retoma do checkpoint. Já
  aconteceu (Coolify) e o checkpoint salvou o lote.
- **Cookie expira a cada 30 min** → relogin Playwright (~1 min de pausa) no meio
  do lote. Normal. Se o login **travar** (ex.: `ERR_CONNECTION_REFUSED` no portal),
  o processo fica preso no subprocess Node — mate o Node travado, invalide o
  cookie e relance (retoma do checkpoint).
- **3 baldes no relatório:** `cancelled` (efetivo), `already_in_terminal_state`
  (preservadas), falhas (`task_not_found`/`verification_failed`/infra).
- **CSV de auditoria** por task: `cnj, task_id, subTypeId, statusId_before, ok, reason`.

---

## 11. Onde está no código (referência)

| Peça | Arquivo |
|---|---|
| Cancelamento HTTP (método B) + verify | `app/services/prazos_iniciais/legacy_task_http_cancellation_service.py` |
| Resolver CNJ→task, constantes, URLs, login paths | `app/services/prazos_iniciais/legacy_task_helpers.py` |
| PATCH status (método A) | `app/services/legal_one_client.py` → `update_task_status` |
| Login OnePass (cookie `.ASPXAUTH`) | `app/runners/legalone/cancel-legacy-task.js --login-only` |
| Endpoint REST individual | `app/api/v1/endpoints/prazos_iniciais_legacy_tasks.py` → `POST /prazos-iniciais/legacy-task/cancel` |
| Fila + worker + circuit breaker | `legacy_task_queue_service.py`, `dispatch_worker.py`, `legacy_task_circuit_breaker.py` |
| Tabela da fila | `prazo_inicial_legacy_task_cancel_items` (migration `pin006`) |
| Painel "Tratamento Web" (UI) | `frontend/src/pages/PrazosIniciaisTreatmentPage.tsx` |

### Endpoint REST pronto

```
POST /api/v1/prazos-iniciais/legacy-task/cancel
body: { "cnj_number": "...", "task_id": 321078, ... }   # ao menos um identificador
```

Aceita `cnj_number` | `lawsuit_id` | `task_id` + overrides opcionais de
tipo/subtipo/status. Resposta = o dict da §8.

### Circuit breaker (lote/fila)

`legacy_task_circuit_breaker.py` abre o circuito após sequência de falhas de
**infra** (`auth_failure`, `timeout`, `runner_error`) — evita martelar o L1
quando a sessão/portal está fora. `verification_failed` e `task_not_found` são
falhas de **negócio**, não disparam o breaker.

---

## 12. Decisão rápida: qual método usar?

```
Sei que a tarefa NÃO é de Workflow, e quero o mais simples?
   → Método A: client.update_task_status(task_id, 3)

Quero robustez / pode ser Workflow / é lote / não sei o tipo?
   → Método B: LegacyTaskHttpCancellationService().cancel_task(task_id=...)
     (contorna o lock + verifica via API — é o método de produção)
```

---

## 13. Checklist de implementação (para o agente do Flow)

- [ ] Reusar `LegacyTaskHttpCancellationService.cancel_task` (não reinventar o POST).
- [ ] Garantir env vars dos **dois** canais (API + web) setadas.
- [ ] Endpoint/worker de lote: inspeção (CNJ→tasks) + cancelamento por `task_id`.
- [ ] **Pré-check de terminal** — nunca cancelar Cumprida/Não cumprida.
- [ ] Verificação via API embutida (já vem no `cancel_task`).
- [ ] Checkpoint a cada 25 + retomada idempotente; rodar detached.
- [ ] Respeitar `$top=30` ao listar `/Tasks`; paginar.
- [ ] Separar baldes: `cancelled` / `already_in_terminal_state` / falhas; CSV de auditoria.
- [ ] Tratar relogin de cookie (30 min) e travas de login (matar Node + invalidar + retomar).
- [ ] UI: lista paginada de tarefas + multi-select; badges por `reason`.

---

*Validado em produção (tenant MDR). Pivotagem para HTTP direto: 2026-05-08.
Maior lote confirmado: +4.300 tarefas (com 1 restart de container e 1 trava de
login no meio, ambos recuperados por checkpoint). Ver também a memória interna
`project_l1_patch_task_status.md`.*

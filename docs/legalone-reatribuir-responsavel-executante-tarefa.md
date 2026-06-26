# Reatribuir Responsável Principal e Executante de uma Tarefa (Legal One API)

> **Objetivo deste documento:** subsidiar a implementação de uma nova seção no
> **Flow** que permita trocar o **responsável principal** e/ou o **executante**
> (e solicitante) de tarefas no Legal One, em lote ou individualmente.
>
> Tudo aqui foi **validado empiricamente em produção** em 2026-06-26 contra o
> tenant da MDR, usando o `LegalOneApiClient` do projeto.

---

## 1. TL;DR (o que dá e o que não dá)

| Cenário | Via API? | Como |
|---|---|---|
| Trocar responsável/executante de **tarefa normal** | ✅ **SIM** | `PATCH /Tasks/{id}` com array `participants` → HTTP 204 |
| Trocar responsável/executante de **tarefa de Workflow** (Modelo de Procedimento) | ⛔ **NÃO** | Qualquer PATCH retorna HTTP 400 (lock global). Só via RPA/UI. |

A dicotomia é **idêntica à do cancelamento de tarefas**: tarefa "solta"
resolve por API; tarefa gerada por Modelo de Procedimento do Workflow é
travada e exige automação de UI (RPA) ou edição manual no Legal One.

---

## 2. Modelo de dados — como o L1 representa responsável e executante

**Importante:** "Responsável principal" e "Executante" **NÃO são campos
diretos da tarefa**. São **participantes** (na UI: aba "Envolvidos") com
flags booleanas. Uma tarefa tem uma *coleção* de participantes; cada
participante é um contato (usuário) com um ou mais papéis.

### Estrutura de um participante

```json
{
  "id": 674701,                  // id do participante (gerado pelo L1; muda a cada PATCH)
  "isRequester": true,           // SOLICITANTE
  "isResponsible": true,         // RESPONSÁVEL PRINCIPAL
  "isExecuter": true,            // EXECUTANTE   (atenção à grafia: "Executer")
  "isAreaResponsible": false,
  "isImmediateManager": false,
  "contact": {
    "id": 25,                    // id do usuário/contato (vem de /Users)
    "name": "Jonilson Vilela Cid Júnior",
    "mainEmail": "jonilsonvilela@mdradvocacia.com"
  }
}
```

### Mapeamento papel → flag

| Papel na UI | Flag no payload |
|---|---|
| Responsável principal | `isResponsible` |
| Executante | `isExecuter` |
| Solicitante | `isRequester` |

### Payload mínimo de um participante (para escrita)

```json
{ "contact": { "id": <userId> }, "isResponsible": true, "isExecuter": true, "isRequester": true }
```

> ⚠️ **Não confundir com escritório.** O campo `responsibleOfficeId` que
> aparece no GET da tarefa é o **escritório responsável** (ex.: 23), uma coisa
> totalmente diferente do **responsável-pessoa**. Trocar pessoa = mexer em
> `participants`. Trocar escritório = mexer em `responsibleOfficeId` (não
> coberto aqui).

---

## 3. Login e autenticação

Existem **dois mecanismos de login distintos** no Legal One, para dois mundos
diferentes. Para reatribuir participantes via API você usa o **(A) OAuth2**. O
**(B) cookie de sessão web** só entra em cena se você for tratar tarefas de
Workflow via RPA/UI (§6).

### 3.A — OAuth2 Bearer (API REST) — *este é o login da reatribuição*

- **Base URL da API:** `https://api.thomsonreuters.com/legalone/v1/api/rest`
- **Endpoint de token:**
  `POST https://api.thomsonreuters.com/legalone/oauth?grant_type=client_credentials`
- **Tipo:** OAuth2 *client_credentials* (machine-to-machine, sem usuário).
- **Credenciais:** enviadas como **HTTP Basic Auth** (`client_id` : `client_secret`).
- **Resposta:** `{ "access_token": "...", "expires_in": 1800 }` (token válido
  por ~30 min).
- **Uso:** cada request da API leva o header `Authorization: Bearer <access_token>`.

**Variáveis de ambiente** (lidas via `settings`, com fallback pra `os.environ`):

| Env var | settings | Exemplo |
|---|---|---|
| `LEGAL_ONE_BASE_URL` | `legal_one_base_url` | `https://api.thomsonreuters.com/legalone/v1/api/rest` |
| `LEGAL_ONE_CLIENT_ID` | `legal_one_client_id` | *(secreto — painel Coolify)* |
| `LEGAL_ONE_CLIENT_SECRET` | `legal_one_client_secret` | *(secreto — painel Coolify)* |

> No ambiente da casa essas env vars já estão setadas no Coolify; localmente o
> `LegalOneApiClient()` lê do `settings`/ambiente. Se faltar qualquer uma, o
> construtor levanta `ValueError`.

**Como o client gerencia o token (você não precisa fazer manualmente):**

1. **Cache de token compartilhado.** O token vive na classe interna `_Auth`
   (nível de classe, compartilhado entre todas as instâncias do client no
   processo), protegido por `threading.Lock`.
2. **Renovação automática com folga (`LEEWAY = 120s`).** Antes de cada chamada,
   `_refresh_token_if_needed()` renova o token se faltar menos de 2 min pra
   expirar. Log: `Renovando token OAuth (force=...)` → `Novo token obtido.
   Valido ate: <UTC>`.
3. **Auto-recuperação de 401.** Se uma chamada volta `401`, o client força um
   refresh (`force=True`) e **repete a chamada uma vez** automaticamente
   (`_authenticated_request`).
4. **Erro de credencial.** `401/403` na renovação do token vira
   `LegalOneAuthenticationError` ("Verifique LEGAL_ONE_CLIENT_ID e
   LEGAL_ONE_CLIENT_SECRET").

**Resumo prático:** basta instanciar `LegalOneApiClient()` e chamar os métodos
/ `_request_with_retry`. Login, refresh, header e retry de 401 são
transparentes. **Nunca monte a request crua nem gerencie token na mão.**

```python
from app.services.legal_one_client import LegalOneApiClient
client = LegalOneApiClient()           # login é lazy: token só é obtido na 1ª chamada
client.get_task_by_id(368544)          # dispara refresh do token se necessário
```

### Rate limit e retry (vale pra toda a API)

- O L1 permite ~**90 req/min** (~1,5 req/s). O client tem um **rate limiter
  global** (token bucket, **1,2 req/s**, burst 5) compartilhado entre threads —
  `_GlobalRateLimiter`. Ou seja, mesmo paralelizando, o throughput é limitado de
  propósito pra não tomar 429.
- `_request_with_retry` faz **8 tentativas** com backoff exponencial + jitter
  para `429/500/502/503/504` e erros de conexão. No 429 o backoff é mais longo
  (`3**attempt`, teto 60s) pra evitar *thundering herd*.
- **Throughput efetivo em lote:** ~**0,3–0,5 tarefa/s** na prática (cada
  reatribuição faz 1 GET + 1 PATCH, e o L1 ainda joga 429 esporádico). Planeje
  lotes grandes como processos de fundo (ver §9).

### 3.B — Cookie de sessão web `.ASPXAUTH` (Playwright/OnePass) — *só p/ RPA*

Necessário **apenas** se você for mexer em tarefas de Workflow (que a API
bloqueia, §6) automatizando a UI/endpoints web do Legal One — é o mesmo login
que o fluxo de **cancelamento via RPA** usa. **Não é usado pela reatribuição via
API.** Documentado aqui para o agente entender o caminho alternativo.

- **O que é:** login interativo no portal web (`mdradvocacia.novajus.com.br` /
  Thomson Reuters **OnePass** SSO) feito por um runner **Playwright (Node)**
  (`app/runners/legalone/cancel-legacy-task.js --login-only`). O produto final é
  o cookie **`.ASPXAUTH`** (+ companhia), que autentica chamadas aos endpoints
  web (ex.: `ModalEnvolvimentoEmLote`).
- **Credenciais (env):**

| Env var | settings | Papel |
|---|---|---|
| `LEGAL_ONE_WEB_USERNAME` | `legal_one_web_username` | usuário do portal |
| `LEGAL_ONE_WEB_PASSWORD` | `legal_one_web_password` | senha |
| `LEGAL_ONE_WEB_KEY_LABEL` | `legal_one_web_key_label` | rótulo da "chave de registro" (seleção de tenant no OnePass) |

- **Cache de cookie + lock entre workers.** O cookie é persistido em
  `/app/data/legacy_task_http_session.json` (volume compartilhado pelos 4
  workers Uvicorn) com um `.lock` (`filelock`) ao lado. **Por quê:** o L1
  **rotaciona a sessão a cada novo login** — se os 4 workers logarem em
  paralelo, 3 ficam com cookie morto (403 em massa). O filelock serializa: o
  primeiro loga, os outros esperam e reusam o cookie do arquivo (padrão
  double-checked locking).
- **TTL:** `prazos_iniciais_legacy_task_session_ttl_minutes` (default **30 min**).
  Expirou → próximo uso re-loga via Playwright (custa ~1 min: subprocess Node +
  SSO). `403` numa chamada web também dispara invalidação + relogin.
- **Implementação de referência:**
  `app/services/prazos_iniciais/legacy_task_http_cancellation_service.py`
  (métodos `_ensure_session`, `_login_via_node`, `_read/_write_session_file`).

> **Para reatribuir responsável/executante em tarefa de Workflow:** seria
> preciso estender o runner Playwright para dirigir a UI de "Envolvidos" da
> tarefa (analogamente ao que o `cancel-legacy-task.js` faz no modal de
> cancelamento). Reusa este mesmo login `.ASPXAUTH`. É o caminho lento/frágil —
> priorize a API e só caia aqui para as `workflow_locked`.

---

## 4. Ler os participantes atuais (sempre faça antes de escrever)

Dois caminhos, ambos retornam HTTP 200:

```python
client = LegalOneApiClient()

# (A) sub-resource dedicado
resp = client._request_with_retry(
    "GET", f"{client.base_url}/tasks/{task_id}/participants"
)
participants = resp.json().get("value", [])

# (B) expand no GET da tarefa
resp = client._request_with_retry(
    "GET", f"{client.base_url}/Tasks/{task_id}", params={"$expand": "participants"}
)
task = resp.json()
participants = task.get("participants", [])
```

**Por que ler antes:** o PATCH de escrita **substitui a coleção inteira**
(ver §5). Se você não reenviar os participantes que quer manter, eles são
removidos. Leia → modifique a lista → reenvie a lista completa.

---

## 5. Escrever — `PATCH /Tasks/{id}` com `participants` (semântica de REPLACE)

A reatribuição é feita com **um PATCH na tarefa**, mandando o array completo
de participantes desejado:

```python
payload = {
    "participants": [
        { "contact": {"id": 62382}, "isResponsible": True,  "isExecuter": False, "isRequester": False },
        { "contact": {"id": 38},    "isResponsible": False, "isExecuter": True,  "isRequester": False },
        { "contact": {"id": 25},    "isResponsible": False, "isExecuter": False, "isRequester": True  },
    ]
}
resp = client._request_with_retry(
    "PATCH", f"{client.base_url}/Tasks/{task_id}", json=payload
)
# Sucesso = HTTP 204 (corpo vazio)
ok = resp.status_code in (200, 204)
```

### Comportamento confirmado (task de teste 368544)

- Trocar 1 pessoa (resp+exec+solic no mesmo contato): **204** ✓
- **Split de papéis** (responsável, executante e solicitante em 3 pessoas
  diferentes), num único PATCH: **204** ✓
- Reverter ao estado original: **204** ✓

### Gotchas críticos

1. **REPLACE, não merge.** O array enviado **vira** a coleção de participantes.
   Tudo que não estiver no array é descartado. Sempre envie o conjunto completo
   final.
2. **O `participant.id` muda a cada PATCH.** O L1 recria os registros de
   participante (ex.: 674701 → 674702 → ...). Isso é cosmético: o que importa é
   `contact.id` + flags. Não guarde `participant.id` como chave estável.
3. **Mande pelo menos 1 participante.** Coleção vazia não faz sentido pro L1
   (na criação é obrigatório ≥1; trate o PATCH igual).
4. **`contact.id` = id do usuário interno** (o mesmo `id` que vem de
   `GET /Users`). Para staff da casa, use o id do usuário.
5. **Grafia:** é `isExecuter` (com "er"), não `isExecutor`.

---

## 6. O lock de Workflow (Modelo de Procedimento)

Tarefas **geradas por Modelo de Procedimento** do Workflow L1 (ex.: as legacy
"Agendar Prazos", "Verificar Citação", "Verificar Prazos e Habilitação")
**bloqueiam qualquer PATCH** em `/Tasks/{id}` — inclusive o de participantes.

### Resposta observada (task Workflow real 368511)

`PATCH /tasks/368511` (tanto `{"statusId": 4}` quanto `{"participants": [...]}`):

```
HTTP 400
{
  "error": {
    "code": "Validation",
    "message": "Existem erros de validação para os dados informados.",
    "target": "taskModel",
    "details": [{
      "code": "InvalidValue",
      "target": "id",
      "message": "O id informado é oriundo de um modelo de procedimento do Workflow, altere o registro pelo Legal One."
    }]
  }
}
```

### Como detectar uma tarefa travada

Não há (até onde foi testado) flag read-only no GET da tarefa que diga "sou de
Workflow". A detecção é **pela resposta do PATCH**:

```python
def is_workflow_locked(detail_body: dict) -> bool:
    for d in (detail_body.get("error", {}) or {}).get("details", []):
        if "modelo de procedimento do workflow" in (d.get("message", "")).lower():
            return True
    return False
```

Estratégia recomendada para o Flow: **tentar o PATCH por API; se vier 400 com
essa mensagem, marcar a tarefa como "requer Workflow/RPA"** e separar num
balde à parte (não tente forçar). É o mesmo padrão "API-first, Workflow é
exceção" — só que aqui, diferente do cancelamento (que é 100% Workflow), a
maioria das tarefas normais deve passar por API.

> ⚠️ **Pegadinha de rótulo:** uma tarefa pode aparecer como tipo
> "Workflow / Teste Workflow" na UI e **mesmo assim ser PATCHável** — isso é só
> o *nome do tipo*, não significa que foi gerada por Modelo de Procedimento. O
> que trava de verdade são as tarefas instanciadas por um procedimento. Confie
> na resposta do PATCH, não no rótulo do tipo.

---

## 7. Resolver IDs de usuário (para escolher responsável/executante)

```python
users = client.get_all_users()   # ~310 no tenant atual
# cada item: {"id": 38, "name": "Jose Alberto Veloso de Carvalho", "email": "...", ...}
by_email = { (u.get("email") or "").lower(): u["id"] for u in users if u.get("email") }
by_name  = { u["name"].lower(): u["id"] for u in users if u.get("name") }
```

IDs reais úteis (tenant MDR, confirmados):

| id | nome |
|---|---|
| 25 | Jonilson Vilela Cid Júnior |
| 38 | Jose Alberto Veloso de Carvalho |
| 1084 | Celio Júnior Caeira dos Santos |
| 62382 | Thays Mendes Oliveira da Cunha |

> Para a UI do Flow, exponha um seletor de usuário **com busca** (combobox), não
> um `<select>` cru — é catálogo grande (310+). É convenção da casa.

---

## 8. Localizar as tarefas-alvo

Reuso dos mesmos helpers do fluxo de cancelamento:

```python
# por CNJ -> lawsuit -> tarefas
lawsuit = client.search_lawsuit_by_cnj("0000168-89.2026.8.05.0126")
lw_id = lawsuit["id"]

tasks = client.search_tasks(
    filter_expression=(
        f"relationships/any(r: r/linkType eq 'Litigation' and r/linkId eq {lw_id})"
    ),
    top=30,   # ⚠️ /Tasks tem limite $top = 30; passar 50 dá erro 400
    select="id,description,statusId,typeId,subTypeId,responsibleOfficeId",
)

# ou por tipo/subtipo/status:
tasks = client.find_tasks_for_lawsuit(lw_id, subtype_id=1283, status_ids=[0])
```

> ⚠️ **Limite $top=30 em /Tasks.** Pedir `$top` > 30 retorna
> `The limit of '30' for Top query has been exceeded`. Pagine de 30 em 30.

---

## 9. Fluxo de referência para reatribuição em lote

Mesmo esqueleto robusto do runner de cancelamento (checkpoint + retomada):

```python
import csv, json, time
from app.services.legal_one_client import LegalOneApiClient

client = LegalOneApiClient()
NEW_RESPONSIBLE = 62382   # Thays
NEW_EXECUTER    = 38      # Jose Alberto
KEEP_REQUESTER  = 25      # quem solicita (ou leia do atual)

def reassign(task_id: int) -> dict:
    # 1) lê participantes atuais (para preservar o que precisa)
    cur = client._request_with_retry(
        "GET", f"{client.base_url}/tasks/{task_id}/participants"
    ).json().get("value", [])

    # 2) monta a lista final desejada (REPLACE total)
    desired = [
        {"contact": {"id": NEW_RESPONSIBLE}, "isResponsible": True,  "isExecuter": False, "isRequester": False},
        {"contact": {"id": NEW_EXECUTER},    "isResponsible": False, "isExecuter": True,  "isRequester": False},
        {"contact": {"id": KEEP_REQUESTER},  "isResponsible": False, "isExecuter": False, "isRequester": True },
    ]

    # 3) PATCH
    try:
        r = client._request_with_retry(
            "PATCH", f"{client.base_url}/Tasks/{task_id}", json={"participants": desired}
        )
        return {"task_id": task_id, "ok": r.status_code in (200, 204), "reason": "reassigned", "http": r.status_code}
    except Exception as e:
        resp = getattr(e, "response", None)
        body = {}
        if resp is not None:
            try: body = resp.json()
            except Exception: body = {}
        reason = "workflow_locked" if is_workflow_locked(body) else "error"
        return {"task_id": task_id, "ok": False, "reason": reason,
                "http": getattr(resp, "status_code", None),
                "error": (getattr(resp, "text", "") or str(e))[:500]}

# 4) verificação pós-PATCH (recomendado): re-GET e confere contatos/flags
```

### Boas práticas do lote (lições do cancelamento de 4.364 tarefas)

- **Checkpoint** a cada 25 itens em arquivo JSON, com **retomada idempotente**
  (reaplicar o mesmo estado dá 204 de novo, sem efeito colateral).
- **Rode detached** (`nohup`/processo de fundo) — lotes grandes levam horas por
  causa do 429 backoff e do limite $top=30.
- **Separe os baldes** no relatório final: `reassigned` (ok), `workflow_locked`
  (mandar pra RPA/UI), `error` (investigar).
- **CSV de auditoria** por tarefa: `task_id, cnj, before(resp/exec), after(resp/exec), http, reason`.

---

## 10. Onde plugar no código do projeto

Hoje **não existe** método público no client para isso (usei
`_request_with_retry` direto). Sugestão de implementação limpa:

### 10.1 Novo método no `LegalOneApiClient` (`app/services/legal_one_client.py`)

```python
def update_task_participants(self, task_id: int, participants: list[dict]) -> bool:
    """
    Substitui a coleção de participantes (Envolvidos) da tarefa.
    Cada item: {"contact": {"id": int}, "isResponsible": bool,
                "isExecuter": bool, "isRequester": bool}.
    Retorna True em 200/204. HTTP 400 com 'modelo de procedimento do
    Workflow' => tarefa travada (cair pra RPA/UI).
    """
    url = f"{self.base_url}/Tasks/{task_id}"
    try:
        r = self._request_with_retry("PATCH", url, json={"participants": participants})
        return r.status_code in (200, 204)
    except requests.exceptions.HTTPError as exc:
        body = exc.response.text if exc.response is not None else ""
        self.logger.error("Falha PATCH participants /Tasks/%s: HTTP %s. %s",
                           task_id, getattr(exc.response, "status_code", "?"), body[:400])
        return False
```

> Espelha o padrão do já existente `update_task_status` (mesmo arquivo).

### 10.2 Endpoint FastAPI (`app/api/v1/endpoints/tasks.py`)

- `POST /tasks/{task_id}/reassign` — body com `{responsible_user_id,
  executer_user_id, requester_user_id?}`; resolve participantes, chama o método
  acima, devolve `{ok, reason, http}`.
- Para lote: `POST /tasks/reassign-batch` recebendo lista de `task_id` (ou
  filtro por CNJ/subtipo) + alvos; processa com o esqueleto da §9.
- Proteger com `require_permission(...)` (ver padrão dos outros endpoints).

### 10.3 UI no Flow

- Seletor de usuário **com busca** (combobox) para responsável e executante.
- Tabela de tarefas-alvo com **paginação** (padrão obrigatório da casa) e
  multi-select.
- Pós-execução: badges `reassigned` / `workflow_locked` / `error`, com botão
  para exportar CSV e, para os `workflow_locked`, encaminhar pro fluxo RPA.

---

## 11. Referência rápida de status de tarefa (contexto)

(Não é necessário para reatribuir participantes, mas útil ter à mão.)

| statusId | significado |
|---|---|
| 0 | Pendente |
| 1 | Cumprido |
| 2 | Não cumprido |
| 3 | Cancelado |
| 4 | Iniciado |
| 5 | Reagendado |

---

## 12. Checklist de implementação (para o agente do Flow)

- [ ] Adicionar `update_task_participants()` no `LegalOneApiClient`.
- [ ] Helper `is_workflow_locked(body)` para classificar 400.
- [ ] Endpoint individual `POST /tasks/{id}/reassign`.
- [ ] Endpoint/worker de lote com checkpoint + retomada idempotente.
- [ ] Resolver `user_id` por nome/email via `get_all_users` (cachear).
- [ ] Sempre **ler participantes atuais** antes do PATCH (REPLACE total).
- [ ] Respeitar `$top=30` ao listar `/Tasks`; paginar.
- [ ] Tratar 429 (já coberto pelo `_request_with_retry`).
- [ ] Verificação pós-PATCH (re-GET) e CSV de auditoria.
- [ ] UI: combobox de usuário com busca + paginação na lista de tarefas.
- [ ] Separar e encaminhar `workflow_locked` para RPA/UI.

---

*Validado em 2026-06-26 contra o tenant de produção da MDR. Tarefa de teste
usada: 368544 ("TESTE- MUDANÇA DE RESPONSÁVEL"). Tarefa Workflow de controle:
368511 (subtipo 1283 "Agendar Prazos"). Ver também a memória interna
`project_l1_patch_task_status.md`.*

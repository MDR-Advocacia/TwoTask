# Plano de Implementação — Fluxo "Agendar Prazos Iniciais"

> **Status:** proposta, aguardando aprovação.
> **Data:** 2026-04-20.
> **Autor:** sessão conjunta (Jonílson + IA).
> **Pendências externas a este plano:** sessão dedicada de taxonomia/prompt (o usuário vai definir valores precisos em outra conversa) e exemplo real do `integra_json` produzido pela automação externa.

---

## 1. Objetivo

Automatizar a triagem de processos novos recebidos pela MDR (onde representamos Banco Master e instituições interligadas no **polo passivo**) e agendar no Legal One as tarefas de prazos e audiências identificadas, além de arquivar a habilitação no GED do processo.

O fluxo atual é manual: operadores abrem o processo, leem, identificam prazos/audiências e agendam. A automação externa já extrai capa + íntegra em JSON — este fluxo pega essa saída, classifica via IA, propõe agendamentos, aguarda revisão humana e executa.

## 2. Visão geral do fluxo

```
Automação externa ──POST multipart──▶ TwoTask API ──grava intake + PDF──▶ fila de classificação
                                                                                │
                             ┌──────────────────────────────────────────────────┘
                             ▼
                    agregador (window-based) ──cria batch Anthropic──▶ Sonnet classifica
                             │
                             ▼
                    polling do batch ──status=ended──▶ baixa resultados ──grava sugestões
                             │
                             ▼
                    operador abre tela de revisão ──edita/aprova──▶ cria tasks no L1 + sobe PDF no GED
```

## 3. Decisões já fechadas

| # | Decisão | Motivação |
|---|---|---|
| 1 | **Claude Sonnet** (não Haiku) via Messages Batches API | Classificação sensível; custo extra aceitável |
| 2 | **Agregação por janela** (tempo/volume) antes de enviar batch | Entrada é 1 processo por vez, batch exige acumulação |
| 3 | **Anexar habilitação ao Litigation** (não à Task) via GED/ECM do L1 | Habilitação documenta o processo como um todo |
| 4 | **`typeId = "2-48"`** (Documento/Habilitação) configurável via env | Valor extraído do L1 real do usuário |
| 5 | **Storage do PDF em volume persistente** montado no container | Simples, baixo custo; cleanup após upload confirmado no GED |
| 6 | **Idempotência via `external_id`** em tabela com unique constraint | Automação externa pode reenviar (retry, falha de rede) |
| 7 | **HITL (Human in the Loop) obrigatório** antes de agendar | Erro em prazo inicial = risco de perda de direito |
| 8 | **Autenticação por API key** (header `X-Intake-Api-Key`) | Automação é sistema→sistema, não usuário→sistema |
| 9 | **Ingestão é `multipart/form-data`** (JSON + PDF na mesma request) | Transação atômica, payload único do lado da automação |
| 10 | **Descoberta do escritório via CNJ** (não enviado pela automação) | Automação externa só tem número do processo |

## 4. Modelos de dados (Postgres / SQLAlchemy / Alembic)

Arquivo: `app/models/prazo_inicial.py` (novo).

### 4.1 `prazo_inicial_intake`

Registro principal — 1 linha por POST bem-sucedido na API externa.

| Coluna | Tipo | Nullable | Notas |
|---|---|---|---|
| `id` | `Integer` PK | | |
| `external_id` | `String` UNIQUE INDEX | não | chave de idempotência |
| `cnj_number` | `String` INDEX | não | normalizado (só dígitos) |
| `lawsuit_id` | `Integer` INDEX | sim | preenchido após resolução via `search_lawsuits_by_cnj_numbers` |
| `office_id` | `Integer` INDEX | sim | derivado do L1 quando `lawsuit_id` preenchido |
| `capa_json` | `JSON` | não | bloco `capa` do payload |
| `integra_json` | `JSON` | não | íntegra em blocos com data |
| `metadata_json` | `JSON` | sim | campo `metadata` livre do payload |
| `pdf_path` | `String` | sim | caminho relativo dentro do volume |
| `pdf_sha256` | `String(64)` | sim | hash do conteúdo (opcional, útil pra dedupe físico) |
| `pdf_bytes` | `Integer` | sim | tamanho em bytes |
| `status` | `String` INDEX | não | ver seção 4.4 |
| `ged_document_id` | `Integer` | sim | `document_id` devolvido pelo L1 após upload |
| `ged_uploaded_at` | `DateTime` | sim | |
| `classification_batch_id` | `Integer` FK → `prazo_inicial_batch.id` | sim | batch que classificou esse intake |
| `error_message` | `Text` | sim | última mensagem de erro (pra UI) |
| `received_at` | `DateTime` default now() | não | |
| `updated_at` | `DateTime` auto-update | não | |

### 4.2 `prazo_inicial_sugestao`

Uma sugestão de agendamento saída da IA — **N por intake** (um processo pode ter contestação + audiência + manifestação avulsa ao mesmo tempo).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | PK | |
| `intake_id` | FK → `prazo_inicial_intake.id` INDEX | |
| `tipo_prazo` | `String` | a definir na sessão de taxonomia (ex.: `contestar`, `cumprir_liminar`, `manifestacao_avulsa`, `audiencia`) |
| `subtipo` | `String` nullable | detalhamento dentro do tipo |
| `data_base` | `Date` nullable | data da intimação/citação/publicação |
| `prazo_dias` | `Integer` nullable | quando aplicável |
| `prazo_tipo` | `String` nullable | `util` ou `corrido` |
| `data_final_calculada` | `Date` nullable | data-alvo para a tarefa |
| `audiencia_data` | `Date` nullable | só quando tipo=`audiencia` |
| `audiencia_hora` | `Time` nullable | idem |
| `audiencia_link` | `Text` nullable | videoconferência |
| `confianca` | `String` | `alta`/`media`/`baixa` |
| `justificativa` | `Text` | rastreabilidade da decisão da IA |
| `responsavel_sugerido_id` | `Integer` nullable | `LegalOneUser.id` inferido da lógica de escritório |
| `task_type_id` | `Integer` nullable | mapeamento pra L1 |
| `task_subtype_id` | `Integer` nullable | idem |
| `payload_proposto` | `JSON` | payload já renderizado pronto pro L1 (editável pelo operador) |
| `review_status` | `String` | `pendente`/`aprovado`/`rejeitado`/`editado` |
| `reviewed_by_email` | `String` nullable | quem aprovou |
| `reviewed_at` | `DateTime` nullable | |
| `created_task_id` | `Integer` nullable | ID da tarefa criada no L1 |
| `created_at` | `DateTime` default now() | |

> **Atenção:** os campos `tipo_prazo`, `subtipo`, mapeamento `task_type_id`/`task_subtype_id` etc. ficam **genéricos** no modelo. A semântica (valores permitidos, mapeamento) vai ser definida na sessão de taxonomia — e fica em `app/services/classifier/prazos_iniciais_taxonomy.py` como constantes + tabela de mapping, sem virar enum de coluna no Postgres.

### 4.3 `prazo_inicial_batch`

Rastreia lotes enviados à Anthropic (espelha `publication_batches_classificacao`).

| Coluna | Tipo | Notas |
|---|---|---|
| `id` | PK | |
| `anthropic_batch_id` | `String` INDEX | `msgbatch_...` |
| `status` | `String` INDEX | `ENVIADO`/`EM_PROCESSAMENTO`/`PRONTO`/`APLICADO`/`FALHA`/`CANCELADO` |
| `anthropic_status` | `String` | espelho do estado da Anthropic |
| `total_records` | `Integer` | |
| `succeeded_count`, `errored_count`, `expired_count`, `canceled_count` | `Integer` | |
| `intake_ids` | `JSON` | array com os IDs de intake incluídos |
| `batch_metadata` | `JSON` | `custom_id → intake_id` mapping |
| `model_used` | `String` | ex.: `claude-sonnet-4-6` |
| `requested_by_email` | `String` | quem disparou (ou `"agregador-automatico"`) |
| `results_url` | `Text` | devolvido quando `ended` |
| `created_at`, `submitted_at`, `ended_at`, `applied_at` | `DateTime` | |

### 4.4 Estados do intake (coluna `status`)

```
RECEBIDO               → gravou no banco, PDF salvo, aguardando resolução do CNJ no L1
PROCESSO_NAO_ENCONTRADO → CNJ não existe no L1 → precisa ação manual
PRONTO_PARA_CLASSIFICAR → lawsuit_id resolvido, aguardando entrar em batch
EM_CLASSIFICACAO       → incluído em um batch enviado
CLASSIFICADO           → IA respondeu, sugestões gravadas, aguardando revisão
EM_REVISAO             → operador abriu a tela
AGENDADO               → tarefas criadas no L1
GED_ENVIADO            → habilitação enviada ao GED do L1
CONCLUIDO              → tudo certo (agendado + GED + PDF local limpo)
ERRO_CLASSIFICACAO     → falha na chamada à Anthropic
ERRO_AGENDAMENTO       → falha ao criar task no L1
ERRO_GED               → falha no upload do documento no L1
CANCELADO              → cancelado manualmente
```

### 4.5 Migração Alembic

Um único `revision` criando as 3 tabelas, índices e FKs. Nome sugerido: `add_prazo_inicial_tables.py`. Segue o padrão das migrações existentes em `alembic/versions/`.

## 5. API — endpoint de ingestão

Arquivo: `app/api/v1/endpoints/prazos_iniciais.py` (novo).

### 5.1 `POST /api/v1/prazos-iniciais/intake`

- **Auth:** header `X-Intake-Api-Key` validado contra `settings.prazos_iniciais_api_key`. Falha → `401`.
- **Content-Type:** `multipart/form-data`.
- **Campos:**
  - `payload` (JSON) — schema Pydantic `PrazoInicialIntakePayload`.
  - `habilitacao` (file) — PDF, MIME `application/pdf`, size ≤ 20 MB (config).

### 5.2 Schema `PrazoInicialIntakePayload`

```python
class CapaProcesso(BaseModel):
    tribunal: str
    vara: Optional[str]
    classe: Optional[str]
    assunto: Optional[str]
    valor_causa: Optional[float]
    data_distribuicao: Optional[date]
    polo_ativo: List[ParteProcessual]
    polo_passivo: List[ParteProcessual]
    segredo_justica: bool = False

class PrazoInicialIntakePayload(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    cnj_number: str
    capa: CapaProcesso
    integra_json: dict  # estrutura genérica em blocos (aguarda exemplo real)
    metadata: Optional[dict] = None
```

### 5.3 Fluxo do handler

1. Valida API key.
2. Parseia `payload`.
3. Verifica se já existe `prazo_inicial_intake` com esse `external_id`.
   - Se sim → retorna `200 OK` + `already_existed=true` (não reprocessa).
4. Valida MIME/size do PDF.
5. Salva PDF em `{volume}/prazos_iniciais/{YYYY}/{MM}/{DD}/{uuid}.pdf`. Calcula sha256.
6. Normaliza CNJ (só dígitos, via `_normalize_cnj_number` que já existe no client).
7. Grava o `PrazoInicialIntake` com `status=RECEBIDO`.
8. Dispara **background task** de resolução do CNJ no L1 (`_resolve_lawsuit_async`).
9. Retorna `202 Accepted` com `intake_id`, `status`, `external_id`, `pdf_stored_path`.

### 5.4 Endpoints auxiliares (na mesma rota)

- `GET /prazos-iniciais/intakes` — lista paginada com filtros (status, office_id, cnj, data). JWT.
- `GET /prazos-iniciais/intakes/{id}` — detalhe (inclui sugestões + PDF metadata).
- `PATCH /prazos-iniciais/sugestoes/{id}` — operador edita o `payload_proposto`.
- `POST /prazos-iniciais/intakes/{id}/agendar` — aciona criação das tasks no L1 + upload no GED.
- `POST /prazos-iniciais/intakes/{id}/reprocessar-cnj` — força nova tentativa de resolver o `lawsuit_id`.
- `POST /prazos-iniciais/intakes/{id}/cancelar` — cancela manualmente.
- `GET /prazos-iniciais/pdf/{intake_id}` — stream do PDF local (auth JWT) pra preview na UI.
- `GET /prazos-iniciais/batches` — lista batches + métricas.
- `POST /prazos-iniciais/batches/flush` — força envio imediato de tudo que está `PRONTO_PARA_CLASSIFICAR` (debug/manual).

## 6. Storage do PDF

- **Volume nomeado no `docker-compose.yml`**: `prazos-iniciais-storage` montado em `/app/data/prazos_iniciais` dentro do container da API.
- **Estrutura de pastas**: `{volume}/{YYYY}/{MM}/{DD}/{intake_uuid}.pdf`.
- **Settings**:
  - `prazos_iniciais_storage_path` (default `/app/data/prazos_iniciais`)
  - `prazos_iniciais_max_pdf_mb` (default `20`)
  - `prazos_iniciais_retention_days` (default `7`, retenção pós-upload no GED)
- **Cleanup**: job `scheduled_automation` que roda diariamente, pega intakes `CONCLUIDO` com `ged_uploaded_at` mais antigo que `retention_days`, apaga arquivo local e limpa `pdf_path` da tabela.

## 7. Cliente Legal One — upload GED

Arquivo: `app/services/legal_one_client.py` (editar).

### 7.1 Novo método

```python
def upload_document_to_lawsuit(
    self,
    lawsuit_id: int,
    pdf_bytes: bytes,
    filename: str,
    description: Optional[str] = None,
    type_id: str = "2-48",
) -> Dict[str, Any]:
    """
    Sobe PDF para o GED do Legal One e vincula ao processo (Litigation).

    3 passos:
      1. GET /Documents/GetContainer(fileExtension='pdf')  → container temp + externalId
      2. PUT no externalId (URL pré-assinada) com os bytes do PDF
      3. POST /Documents com metadados + relationships[Link=Litigation]

    Returns:
        dict com {"document_id": int, "external_id": str, "uploaded_file_size": int}

    Raises:
        RuntimeError em caso de falha em qualquer dos 3 passos.
    """
```

### 7.2 Pontos de atenção

- O passo 2 (PUT no container externo) **não usa** o Authorization do L1 — é URL pré-assinada. Usar `httpx`/`requests` direto.
- O `UploadedFileSize` do passo 3 precisa bater com o tamanho dos bytes do passo 2 — validar.
- Retry em cada passo independente (erro de rede no passo 2 não deve invalidar o container recebido no passo 1, dentro da janela de validade).
- Se o L1 devolver `typeId` com subtipo não existente, o erro vem como 400 — fazer log claro.

## 8. Strategy de classificação

Arquivo: `app/services/prazos_iniciais/` (nova pasta com submódulos).

```
app/services/prazos_iniciais/
├── __init__.py
├── intake_service.py          # resolução de CNJ, transições de estado
├── aggregator.py              # janela de acumulação (tempo/volume) → criar batch
├── batch_classifier.py        # submit/poll/apply (espelho do publication_batch_classifier.py)
├── suggestion_service.py      # aplicação dos resultados da IA em prazo_inicial_sugestao
├── scheduler_service.py       # agendamento no L1 + upload GED
└── ged_uploader.py            # wrapper fino em cima do upload_document_to_lawsuit
```

E em `app/services/classifier/`:
```
prazos_iniciais_prompts.py     # SYSTEM_PROMPT (aguarda sessão de taxonomia)
prazos_iniciais_taxonomy.py    # constantes + mapping pra TaskType/Subtype (aguarda sessão)
```

### 8.1 Aggregator — parâmetros configuráveis

- `prazos_iniciais_batch_window_seconds` (default `600` — 10 min)
- `prazos_iniciais_batch_min_size` (default `5`)
- `prazos_iniciais_batch_max_size` (default `100`)

Regra: dispara batch quando **(tempo desde primeiro item ≥ window)** OR **(tamanho ≥ max_size)**. Permite também `POST /batches/flush` manual.

### 8.2 Pipeline

```
aggregator → submete batch → grava PrazoInicialBatch (status=ENVIADO)
   ↓
scheduled_automation (a cada 30s) → polling dos batches ENVIADO/EM_PROCESSAMENTO
   ↓
status=ended → baixa JSONL → parse resultados → gera PrazoInicialSugestao (N por intake)
   ↓
intake.status = CLASSIFICADO
```

### 8.3 Contrato de saída da IA (provisório, genérico)

```json
{
  "contestar": {
    "aplicavel": true,
    "data_base": "2026-04-10",
    "prazo_dias": 15,
    "prazo_tipo": "util",
    "confianca": "alta",
    "justificativa": "..."
  },
  "cumprir_liminar": { "aplicavel": false, "confianca": "alta" },
  "manifestacao_avulsa": { "aplicavel": false, "confianca": "media" },
  "audiencia": {
    "aplicavel": true,
    "data": "2026-05-20",
    "hora": "14:00",
    "link": null,
    "tipo": "conciliacao",
    "confianca": "alta"
  },
  "sem_determinacao": { "aplicavel": false },
  "ja_julgado": { "aplicavel": false, "tipo": null }
}
```

→ A strategy percorre cada chave, cria uma `PrazoInicialSugestao` para cada `aplicavel=true` e mapeia pra `(task_type_id, task_subtype_id)` conforme `prazos_iniciais_taxonomy.py`.

## 9. Frontend

Arquivo principal: `frontend/src/pages/PrazosIniciaisPage.tsx` (novo).
Serviços: `frontend/src/services/prazosIniciais.ts` (novo).
Rota: `/prazos-iniciais` adicionada em `App.tsx` + item de navegação.

### 9.1 Layout da página

- **Header** com métricas: total em fila, aguardando revisão, agendados hoje, erros.
- **Filtros**: status, escritório, data, CNJ.
- **Lista** (análoga a `PublicationsPage`): card por intake, mostra CNJ, partes, status colorido, contador de sugestões.
- **Painel lateral** (ao clicar): detalhes + PDF preview (iframe) + lista de sugestões da IA com edição inline (como em `PublicationTreatmentPage`).
- **Ações por intake**: aprovar todas, rejeitar todas, editar individualmente, re-classificar, cancelar.

### 9.2 Permissão

Nova permissão `prazos_iniciais` (análoga a `publications`). Admin atribui em `AdminPage.tsx`.

## 10. Configuração (settings novos)

Arquivo: `app/core/config.py`.

```python
# Prazos Iniciais
prazos_iniciais_api_key: str                  # obrigatório em prod
prazos_iniciais_storage_path: str = "/app/data/prazos_iniciais"
prazos_iniciais_max_pdf_mb: int = 20
prazos_iniciais_retention_days: int = 7
prazos_iniciais_batch_window_seconds: int = 600
prazos_iniciais_batch_min_size: int = 5
prazos_iniciais_batch_max_size: int = 100
prazos_iniciais_ged_type_id: str = "2-48"
prazos_iniciais_classifier_model: str = "claude-sonnet-4-6"
prazos_iniciais_classifier_max_tokens: int = 4096
```

## 11. Observabilidade e segurança

- **Logs estruturados** em todos os pontos (ingestão, resolução de CNJ, batch, upload GED) com `intake_id` e `external_id` como campos fixos.
- **Métricas** simples exportadas pra Prometheus (já está no stack): `prazos_iniciais_intakes_recebidos_total`, `..._batches_submetidos_total`, `..._agendamentos_criados_total`, `..._erros_ged_total`, `..._tempo_ate_agendamento_seconds`.
- **Email de falha** (reaproveitar `mail_service.send_failure_report`) quando um intake cair em `ERRO_*` e não for retomado em X horas.
- **API key** rotacionável (suportar múltiplas chaves via lista separada por vírgula em env).

## 12. Fases de implementação (ordem proposta)

**Fase 1 — Backbone (não depende de IA nem GED)** ⇐ começar por aqui.
- 1.1 Modelos + migração Alembic.
- 1.2 Settings novos.
- 1.3 Endpoint `POST /intake` + storage do PDF em volume.
- 1.4 Resolução async do CNJ.
- 1.5 Endpoints `GET /intakes`, `GET /intakes/{id}`, `GET /pdf/{intake_id}`.
- 1.6 Testes unitários: ingestão feliz, dedupe por `external_id`, CNJ inexistente, PDF acima do limite.

**Fase 2 — Frontend mínimo.**
- 2.1 Página, rota, sidebar.
- 2.2 Lista de intakes com status e filtros.
- 2.3 Detalhe + preview do PDF.
- 2.4 Permissão `prazos_iniciais`.

**Fase 3 — Upload GED (isolado, testável à parte).**
- 3.1 `upload_document_to_lawsuit()` no `LegalOneApiClient`.
- 3.2 Testes com PDF real em ambiente de homolog do L1.
- 3.3 Botão manual "Enviar ao GED" na UI (antes da automação total).

**Fase 4 — Classificação (PAUSADA aguardando sessão de taxonomia).**
- 4.1 `prazos_iniciais_taxonomy.py` + `prazos_iniciais_prompts.py` (na sessão dedicada).
- 4.2 `batch_classifier.py` (espelho do publications).
- 4.3 `aggregator.py` + scheduled_automation de polling.
- 4.4 `suggestion_service.py`.
- 4.5 UI de revisão (inspirada em `PublicationTreatmentPage`).

**Fase 5 — Agendamento automático.**
- 5.1 `scheduler_service.py` — mapeia sugestão → payload de task → chama `task_creation_service`.
- 5.2 Integra com o upload GED (se ainda não foi feito) na mesma transação.
- 5.3 UI: botão "Agendar aprovados" em lote.

**Fase 6 — Polimento.**
- 6.1 Cleanup job de PDFs antigos.
- 6.2 Métricas Prometheus + dashboard.
- 6.3 Email de erros.
- 6.4 Documentação pra operadores.

## 13. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| IA classificar errado e agendar prazo inexistente | HITL obrigatório; confiança baixa força revisão; justificativa sempre visível |
| IA não detectar prazo existente (falso negativo) | Logar todos intakes em `CONCLUIDO com sem_determinacao=true` pra auditoria amostral; permitir reclassificação manual |
| CNJ não encontrado no L1 | Estado dedicado `PROCESSO_NAO_ENCONTRADO` com botão "reprocessar" |
| Container GED expirar entre passos | Retry do conjunto dos 3 passos, não do passo isolado |
| PDF corrompido ou não-PDF | Validar magic bytes (`%PDF`) além do MIME declarado |
| Reenvio massivo da automação (loop) | API key + rate limit no endpoint de intake |
| Sonnet com contexto muito grande estourar tokens | Medir antes, rejeitar > 180k; truncar blocos antigos na serialização se > 100k |

## 14. O que não está neste plano

- **Taxonomia, prompt e mapeamento para TaskType do L1** — sessão dedicada.
- **Exemplo real do `integra_json`** — aguardando usuário rodar a automação.
- **Análise de performance sob carga real** — fica pra pós-go-live, calibrando os parâmetros do aggregator.
- **Integração com sistemas externos além do L1** — fora do escopo desta iteração.

---

**Próximo passo sugerido:** aprovar o plano; começar pela Fase 1 (backbone), que não depende de taxonomia nem de IA e já entrega valor (um lugar pra receber e visualizar os intakes). Em paralelo, agendamos a sessão de taxonomia.

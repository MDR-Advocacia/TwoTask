# PLANO — Landing nova + Reformulação do Dashboard de Publicações

> Documento operacional pra execução pelo Claude Code em sessão dedicada.
> Cada fase é um commit independente, deployável no Coolify sem depender
> da próxima. Tudo na branch `feat/prazos-iniciais` (sandbox de validação).

---

## 0. Contexto

Hoje a aplicação tem dois problemas que esse plano corrige:

1. **O `DashboardHome` (rota `/`) é 100% sobre publicações** mas está
   posicionado como home da app, fora da seção "Tratamento de Publicações".
   Quem entra no sistema cai num dashboard de publicações como se fosse o
   produto inteiro — confunde a navegação e esconde os outros flows
   (Prazos Iniciais, AJUS, etc.).
2. **O dashboard atual é estático**: mostra estoque (quantas estão em cada
   status) mas não fala de **ritmo**. Operadores não enxergam se estão
   indo rápido/devagar e não têm sinal de progresso pessoal. Resultado:
   ritmo de tratamento percebido como lento, sem ferramentas pra
   estimular.

**Visão final:**

- Rota `/` vira uma **landing page do flow inteiro** (Publicações, Prazos
  Iniciais, AJUS, Tarefas em Lote, Admin) com estética liquid glass,
  apresentação curta do produto e métrica âncora por seção.
- Dashboard de Publicações migra pra `/publications/dashboard`, vira o
  **primeiro item da seção "Tratamento de Publicações"** no menu, e é
  **reformulado** pra mostrar pulso operacional, pipeline de agendamento
  e **gamificação** (leaderboard individual, streak, meta diária móvel,
  comparativos).

---

## 1. Decisões já fechadas com o cliente

| Tópico | Decisão |
|---|---|
| Onde mora o dashboard | Rota nova `/publications/dashboard`, primeiro item da seção "Tratamento de Publicações" do menu lateral |
| Landing | Apresenta TODAS as seções do sistema, com pitch curto do produto, visual liquid glass moderno |
| Métrica da gamificação | **Tratamento** = qualquer transição saindo de `NOVO` (inclui AGENDADO + IGNORADO + CLASSIFICADO). Justificativa: "todo mundo lê coisas parecidas, o esforço de leitura é similar" |
| Meta diária | **Móvel** — calculada automaticamente a partir do backlog atual + chegada média + nº de operadores ativos. Configurável só na constante `dias_uteis_alvo` |
| Leaderboard | **Individual** |
| Branch | `feat/prazos-iniciais` (sandbox de validação antes de subir pra main) |
| Estratégia de entrega | **Fases independentes**, cada uma deployável sozinha |

---

## 2. Convenções OBRIGATÓRIAS pra quem executa este plano

Antes de qualquer commit, reler `CLAUDE.md` na raiz do projeto. Pontos
críticos que JÁ FALHARAM e não podem falhar de novo:

### 2.1 Deploy é Coolify

Não escrever runbook de deploy manual. O Coolify roda
`alembic upgrade head` no boot via `scripts/docker-api-start.sh`. Push
em `main` ou `feat/prazos-iniciais` aciona rebuild. O executor entrega
**bloco PowerShell de commit**, o usuário roda no terminal dele.

### 2.2 Migrations Alembic — checar `heads` ANTES de criar

```bash
docker exec onetask-api-1 sh -c "cd /app && alembic heads"
```

Se `heads` retornar mais de uma linha, criar `merge_heads` ANTES da
migration de feature. Prefixo dessa frente: **`pub*`**. Próximos IDs
a usar (em ordem): `pub010`, `pub011`, `pub012`, … (confirmar com
`alembic history | head -20` antes pra não colidir).

### 2.3 Guard de truncamento em arquivos grandes

Arquivos com >800 linhas (ex.: `PublicationsPage.tsx`, alguns endpoints
agregados) **NÃO** podem ser editados via `Edit`/`Write` direto — risco
de truncamento documentado em memória. Para esses, usar fluxo:

```bash
git show HEAD:caminho/do/arquivo > /tmp/orig.ext
python3 << 'PYEOF'
src = open('/tmp/orig.ext').read()
old = """<bloco exato>"""
new = """<novo bloco>"""
assert old in src, "old not found"
src = src.replace(old, new)
open('caminho/no/repo', 'w').write(src)
print("lines:", len(src.split(chr(10))))
PYEOF

# Validar:
python3 -c "import ast; ast.parse(open('arquivo.py').read()); print('OK')"  # se .py
wc -l arquivo
git show HEAD:arquivo | wc -l
tail -3 arquivo
```

Antes de cada commit, bater `wc -l` do arquivo modificado contra `git
show HEAD:arquivo | wc -l` pra detectar perda de bytes. Se faltar
linhas, recuperar via git ANTES do commit.

### 2.4 Worktree

Se o ambiente do executor for inicializado em worktree
(`.claude/worktrees/<nome>`), **espelhar todos os arquivos modificados
pro checkout principal** antes de entregar o bloco PowerShell, senão
o `git add -A` do usuário não vai pegar a mudança.

### 2.5 Padrão de bloco PowerShell pra commit

PowerShell 5.x — sem `&&`, sem `;`, sem `\n` em mensagem:

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "<mensagem em linha única>"
git push origin feat/prazos-iniciais
```

Quando o usuário disser "joga pra main" depois, propagar via merge
fast-forward (formato do `CLAUDE.md`, seção "os dois").

### 2.6 Paginação obrigatória em listagens

Qualquer lista nova (leaderboard, ranking, pipeline) usa o padrão da
casa: API com `limit`/`offset`/`total`/`items`, UI com "Anterior /
Próxima · Página X de Y" e seletor 25/50/100. Listas pequenas e
estáveis (≤20) podem ficar sem paginação, mas decidir
conscientemente.

---

## 3. Visão geral da arquitetura final

### 3.1 Mapa de rotas (depois das 5 fases)

```
/                              → LandingPage (apresentação + cards de seções)
/publications/dashboard        → PublicationsDashboardPage (NOVO, ex-DashboardHome)
/publications                  → PublicationsPage (sem mudança)
/publications/treatment        → PublicationTreatmentPage (sem mudança)
/publications/lookup           → LookupByCnjPage (sem mudança)
/publications/templates        → TaskTemplatesPage (sem mudança)
/publications/templates/review-pending → TemplateReviewPage (sem mudança)
/automations                   → AutomationsPage (sem mudança)
/prazos-iniciais               → PrazosIniciaisPage (sem mudança)
/ajus                          → AjusPage (sem mudança)
/admin                         → AdminPage (sem mudança)
/admin/gamification-settings   → GamificationSettingsPage (NOVO, Fase 4)
```

### 3.2 Mapa do menu lateral (`Layout.tsx`) depois da Fase 1

```
[topo: sem item "Dashboard" solto]

CRIAÇÃO DE TAREFAS
├── Tarefas por Planilha
└── Acompanhamento de Lotes

TRATAMENTO DE PUBLICAÇÕES
├── Dashboard                    ← NOVO, primeiro item
├── Agendamentos
├── Publicações Legal One
├── Tratamento Web
└── Templates de Agendamento

PRAZOS INICIAIS
├── Agendar Prazos Iniciais
├── Tratamento Web Agendamentos Iniciais
├── Templates de Prazos Iniciais
└── AJUS — Andamentos

ADMINISTRAÇÃO (admin only)
├── Administração
└── Configurações de gamificação   ← NOVO, Fase 4
```

A landing nova fica em `/` mas **NÃO entra como item no menu lateral** —
ela já é a tela que aparece ao clicar no logo (que aponta pra `/`).

---

## 4. FASE 1 — Landing nova + reorganização da navegação

**Objetivo:** sair com landing visual nova em `/`, dashboard atual movido
pra `/publications/dashboard` e menu reorganizado. Zero mudança em
backend, zero mudança em métricas. Só arrumação visual e roteamento.

**Risco:** baixo. Não toca em dados, não invalida bookmarks (rota antiga
redireciona). Se quebrar, rollback é trivial.

**Entregável:** PR que reorganiza navegação e entrega landing liquid
glass.

### 4.1 Arquivos a criar

#### `frontend/src/pages/LandingPage.tsx` (NOVO)

Componente da nova home. Estrutura sugerida em 4 faixas verticais:

1. **Header de saudação contextual.** Saudação por hora ("Bom dia /
   Boa tarde / Boa noite, {primeiroNome}"). Pitch de 2 linhas em
   itálico discreto: *"Central DunaFlow de tratamento jurídico
   automatizado. Publicações, prazos iniciais e andamentos em um só
   lugar."*

2. **Grid de seções (4–5 cards liquid glass).** Cada card:
   - Ícone âncora (Lucide React, já no projeto)
   - Título
   - Métrica âncora viva (1 número + 1 caption)
   - Subtítulo descritivo
   - CTA "Entrar →"
   - `onClick` → navigate pra rota principal da seção

   Cards na ordem (filtrados por permissão):
   - **Publicações** (canUsePublications) — métrica: `pendentes_agora`
     do endpoint `/api/v1/dashboard/publications-overview?days=1` (já
     existe). Ícone: Newspaper. Rota: `/publications/dashboard`.
   - **Prazos Iniciais** (canUsePrazosIniciais) — métrica: pegar
     contagem de prazos AGUARDANDO_TRIAGEM via endpoint existente
     (verificar `app/api/v1/endpoints/prazos_iniciais.py`); se não
     existir endpoint leve, hardcodar `—` por enquanto e abrir TODO.
     Ícone: CalendarClock. Rota: `/prazos-iniciais`.
   - **AJUS — Andamentos** (canUsePrazosIniciais) — métrica: status
     da última sessão (verde/amarelo/vermelho) se houver endpoint;
     senão, label estático "Abrir AJUS". Ícone: Workflow. Rota:
     `/ajus`.
   - **Tarefas em Lote** (canScheduleBatch) — métrica: "Último lote:
     {X}% concluído" via `fetchBatchExecutions` (já existe em
     `services/api.ts`, primeiro item). Ícone: FileUp. Rota:
     `/batches`.
   - **Administração** (isAdmin) — card mais discreto, sem métrica.
     Ícone: Users. Rota: `/admin`.

3. **Faixa "Pulso da equipe hoje" (chips horizontais).** 3 chips com
   info derivada do `publications-overview?days=1`:
   - "🔥 {tratadas_janela} publicações tratadas pela equipe hoje"
   - "📅 Próximo agendamento automático: {hora}" (do
     `/api/v1/automations`)
   - "✅ Backlog: {pendentes_agora} pendentes"

   Esses chips são opcionais — se algum endpoint falhar, esconder o
   chip silenciosamente (não quebrar a landing inteira).

4. **Rodapé.** Versão da app (constante), link "Enviar feedback"
   (reutilizar `FeedbackButton` se possível ou link discreto),
   `CaptureHealthWidget` (já existe, mover do `DashboardHome` antigo)
   se `isAdmin`.

##### Diretrizes visuais (liquid glass)

Aplicar no card e nas faixas:

```tsx
className="
  relative overflow-hidden
  backdrop-blur-xl
  bg-white/40 dark:bg-white/5
  border border-white/30
  shadow-[0_8px_32px_0_rgba(31,38,135,0.08)]
  ring-1 ring-white/10
  rounded-2xl
  transition-all duration-300
  hover:-translate-y-1
  hover:shadow-[0_12px_40px_0_rgba(31,38,135,0.14)]
  hover:bg-white/55
"
```

Background da página (`<div>` wrapper da LandingPage):

```tsx
<div className="relative min-h-[calc(100vh-60px)] overflow-hidden">
  {/* Blobs decorativos */}
  <div className="absolute top-[-20%] left-[-10%] w-[600px] h-[600px]
                  rounded-full bg-[hsl(var(--dunatech-blue))]
                  opacity-20 blur-[120px] pointer-events-none" />
  <div className="absolute bottom-[-30%] right-[-10%] w-[500px] h-[500px]
                  rounded-full bg-[hsl(var(--dunatech-navy))]
                  opacity-15 blur-[120px] pointer-events-none" />
  {/* Gradient sutil */}
  <div className="absolute inset-0 bg-gradient-to-br from-white via-slate-50/50
                  to-blue-50/30 pointer-events-none" />

  <div className="relative z-10 max-w-7xl mx-auto px-6 py-10 space-y-10">
    {/* Conteúdo */}
  </div>
</div>
```

Tipografia dos títulos dos cards: `font-semibold tracking-tight
text-lg`. Métrica âncora: `text-4xl font-bold` com cor
`text-[hsl(var(--dunatech-navy))]`. Caption: `text-xs uppercase
tracking-wider text-muted-foreground`.

Conferir que `--dunatech-blue` e `--dunatech-navy` já existem no
CSS global (vimos uso no `DashboardHome`, então estão definidas).

#### `frontend/src/pages/PublicationsDashboardPage.tsx` (NOVO)

Cópia praticamente fiel do `DashboardHome.tsx` atual, renomeada. Já
contém toda a lógica de overview, KPIs, gráficos, filtros salvos. A
**reformulação real** desse dashboard acontece nas Fases 2–4. Aqui é
só **mover sem mexer**.

Diferenças mínimas em relação ao `DashboardHome.tsx` atual:
- Nome do componente: `PublicationsDashboardPage`.
- Default export idem.
- Saudação (h1) ajustada: "Dashboard de Publicações" em vez de
  "Dashboard" genérico.
- `CaptureHealthWidget` permanece aqui também (admin) — sai da
  landing se conflitar, mas faz mais sentido ficar no dashboard.

### 4.2 Arquivos a modificar

#### `frontend/src/App.tsx`

```diff
- import DashboardHome from './pages/DashboardHome';
+ import LandingPage from './pages/LandingPage';
+ import PublicationsDashboardPage from './pages/PublicationsDashboardPage';

  // dentro de <Routes>:
- <Route path="/" element={<DashboardHome />} />
+ <Route path="/" element={<LandingPage />} />
+ <Route path="/publications/dashboard" element={<PublicationsDashboardPage />} />
```

#### `frontend/src/components/Layout.tsx`

```diff
  const baseSections: NavSection[] = [
-   {
-     items: [
-       { to: "/", icon: Home, label: "Dashboard" },
-     ],
-   },
    {
      title: "Criação de Tarefas",
      items: [
        { to: "/tasks/spreadsheet-batch", icon: FileUp, label: "Tarefas por Planilha", requirePermission: 'canScheduleBatch' },
        { to: "/batches", icon: ListChecks, label: "Acompanhamento de Lotes", requirePermission: 'canScheduleBatch' },
      ],
    },
    {
      title: "Tratamento de Publicações",
      items: [
+       { to: "/publications/dashboard", icon: LayoutDashboard, label: "Dashboard", requirePermission: 'canUsePublications' },
        { to: "/automations", icon: Clock, label: "Agendamentos", requirePermission: 'canUsePublications' },
        { to: "/publications", icon: Newspaper, label: "Publicações Legal One", requirePermission: 'canUsePublications' },
        { to: "/publications/treatment", icon: ListChecks, label: "Tratamento Web", requirePermission: 'canUsePublications' },
        { to: "/publications/templates", icon: Settings, label: "Templates de Agendamento", requirePermission: 'canUsePublications' },
      ],
    },
```

Lembrar de importar `LayoutDashboard` de `lucide-react` no topo. O
ícone `Home` antigo pode sair do import se não for usado em mais
nenhum lugar (`grep` antes de tirar).

#### `frontend/src/pages/DashboardHome.tsx` — DELETAR

Substituído por `LandingPage.tsx` (nova) + `PublicationsDashboardPage.tsx`
(reaproveita lógica). Deletar o arquivo antigo.

### 4.3 Validação manual (Fase 1)

Antes de commitar:

1. `npm run dev` no `frontend/` e abrir `http://localhost:5173`.
2. Verificar:
   - [ ] `/` renderiza a landing nova, sem erros no console.
   - [ ] Cards com permissão visíveis, sem permissão escondidos.
   - [ ] Clicar no card "Publicações" leva pra
     `/publications/dashboard` (e ele mostra o dashboard antigo).
   - [ ] Menu lateral: "Dashboard" sumiu do topo, aparece como
     primeiro item da seção "Tratamento de Publicações".
   - [ ] Clicar no logo no canto superior esquerdo leva pra `/`
     (landing).
   - [ ] Rotas antigas (`/publications`, `/publications/treatment`)
     continuam funcionando sem mudança.
   - [ ] Responsivo: drawer mobile (Sheet) funciona, cards quebram
     pra 1 coluna em telas pequenas.
3. Rodar `npm run build` no `frontend/` — sem erros de TS.

### 4.4 Bloco PowerShell de commit (Fase 1)

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "feat(landing): nova landing page e dashboard de publicacoes movido pra /publications/dashboard"
git push origin feat/prazos-iniciais
```

---

## 5. FASE 2 — Migration de autoria + Bloco "Pulso operacional"

**Objetivo:** completar a autoria de transições saindo de `NOVO`
(hoje só temos `scheduled_by_*`, falta `ignored_by_*` e
`classified_by_*`). Com isso liberamos métricas reais por usuário. Em
paralelo, reescrever o **Bloco 1** do dashboard de publicações pra
mostrar ritmo, idade do backlog, burndown projetado e progresso vs
meta.

**Risco:** médio. Migration mexe na tabela `publication_records`
(milhões de linhas potencialmente). Toda mudança de status passa a
gravar autoria — precisa cobrir os pontos sem regressão.

### 5.1 Backend — migration de autoria

#### `app/alembic/versions/pub010_autoria_ignorado_e_classificado.py` (NOVO)

> **ANTES** rodar `docker exec onetask-api-1 sh -c "cd /app && alembic
> heads"` e usar o head como `down_revision`. ID `pub010` é só
> sugestão — confirmar próximo livre.

```python
"""autoria ignorado e classificado em publication_records

Revision ID: pub010
Revises: <head_atual>
Create Date: 2026-05-11 ...
"""

revision = "pub010"
down_revision = "<head_atual>"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column("publication_records",
        sa.Column("ignored_by_user_id", sa.Integer(),
                  sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
                  nullable=True))
    op.add_column("publication_records",
        sa.Column("ignored_by_email", sa.String(), nullable=True))
    op.add_column("publication_records",
        sa.Column("ignored_by_name", sa.String(), nullable=True))
    op.add_column("publication_records",
        sa.Column("ignored_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_publication_records_ignored_by_user_id",
                    "publication_records", ["ignored_by_user_id"])

    op.add_column("publication_records",
        sa.Column("classified_by_user_id", sa.Integer(),
                  sa.ForeignKey("legal_one_users.id", ondelete="SET NULL"),
                  nullable=True))
    op.add_column("publication_records",
        sa.Column("classified_by_email", sa.String(), nullable=True))
    op.add_column("publication_records",
        sa.Column("classified_by_name", sa.String(), nullable=True))
    op.add_column("publication_records",
        sa.Column("classified_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_publication_records_classified_by_user_id",
                    "publication_records", ["classified_by_user_id"])

def downgrade():
    op.drop_index("ix_publication_records_classified_by_user_id")
    op.drop_column("publication_records", "classified_at")
    op.drop_column("publication_records", "classified_by_name")
    op.drop_column("publication_records", "classified_by_email")
    op.drop_column("publication_records", "classified_by_user_id")
    op.drop_index("ix_publication_records_ignored_by_user_id")
    op.drop_column("publication_records", "ignored_at")
    op.drop_column("publication_records", "ignored_by_name")
    op.drop_column("publication_records", "ignored_by_email")
    op.drop_column("publication_records", "ignored_by_user_id")
```

#### `app/models/publication_search.py`

Adicionar campos paralelos aos `scheduled_by_*` já existentes:

```python
ignored_by_user_id = Column(
    Integer,
    ForeignKey("legal_one_users.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
ignored_by_email = Column(String, nullable=True)
ignored_by_name = Column(String, nullable=True)
ignored_at = Column(DateTime(timezone=True), nullable=True)

classified_by_user_id = Column(
    Integer,
    ForeignKey("legal_one_users.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
classified_by_email = Column(String, nullable=True)
classified_by_name = Column(String, nullable=True)
classified_at = Column(DateTime(timezone=True), nullable=True)
```

#### Pontos de gravação de autoria

Encontrar os handlers que mudam `status` pra `IGNORADO` e
`CLASSIFICADO` e passar a setar a quádrupla `*_by_*` + `*_at`. Padrão:
mesmo já feito pra AGENDADO (procurar `scheduled_by_user_id` no código
e replicar o padrão).

Caminhos prováveis (confirmar via `grep -rn "= 'IGNORADO'"
app/`):
- `app/api/v1/endpoints/publications.py` — `PATCH /records/{id}`
- `app/services/publication_search_service.py` — funções de bulk
  update
- `app/services/publication_classification_service.py` — quando
  classifica em batch

A função utilitária pode ficar em
`app/services/publication_search_service.py`:

```python
def _set_authorship(record, status_to, user):
    """Preenche *_by_* + *_at baseado no novo status."""
    now = datetime.now(timezone.utc)
    if status_to == "AGENDADO" and record.scheduled_by_user_id is None:
        record.scheduled_by_user_id = user.id
        record.scheduled_by_email = user.email
        record.scheduled_by_name = user.name
        record.scheduled_at = now
    elif status_to == "IGNORADO" and record.ignored_by_user_id is None:
        record.ignored_by_user_id = user.id
        record.ignored_by_email = user.email
        record.ignored_by_name = user.name
        record.ignored_at = now
    elif status_to == "CLASSIFICADO" and record.classified_by_user_id is None:
        record.classified_by_user_id = user.id
        record.classified_by_email = user.email
        record.classified_by_name = user.name
        record.classified_at = now
```

A condição `is None` evita sobrescrever autoria se o registro
revisitar o mesmo status (ex.: alguém volta CLASSIFICADO → NOVO →
CLASSIFICADO de novo). Quem mexeu primeiro fica registrado.

> Para **registros existentes pré-migration** os campos novos ficam
> NULL — aceitar isso, não fazer backfill. Métricas históricas
> começam a partir da fase de produção da migration.

### 5.2 Backend — endpoint `publications-rhythm`

#### `app/api/v1/endpoints/dashboard.py`

Adicionar:

```python
@router.get("/publications-rhythm", response_model=RhythmResponse)
def get_publications_rhythm(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Retorna ritmo da última hora, média 7d, burndown projetado,
    idade do mais antigo no backlog e tempo médio NOVO→tratada.
    """
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    seven_days_ago = now - timedelta(days=7)

    # Ritmo última hora (publicações que saíram de NOVO na última h).
    last_hour_treated = db.query(PublicationRecord).filter(
        or_(
            PublicationRecord.scheduled_at >= one_hour_ago,
            PublicationRecord.ignored_at >= one_hour_ago,
            PublicationRecord.classified_at >= one_hour_ago,
        )
    ).count()

    # Média 7d por hora.
    last_7d_treated = db.query(PublicationRecord).filter(
        or_(
            PublicationRecord.scheduled_at >= seven_days_ago,
            PublicationRecord.ignored_at >= seven_days_ago,
            PublicationRecord.classified_at >= seven_days_ago,
        )
    ).count()
    avg_per_hour_7d = last_7d_treated / (7 * 24)

    # Idade do mais antigo no backlog.
    oldest_pending = db.query(PublicationRecord).filter(
        PublicationRecord.status == "NOVO"
    ).order_by(PublicationRecord.created_at.asc()).first()
    oldest_age_minutes = (
        int((now - oldest_pending.created_at).total_seconds() / 60)
        if oldest_pending else None
    )

    # Backlog atual.
    backlog = db.query(PublicationRecord).filter(
        PublicationRecord.status == "NOVO"
    ).count()

    # Burndown projetado:
    # - Calcular taxa de chegada (created_at na última hora)
    # - Taxa líquida = tratamento_h - chegada_h
    # - Se líquida > 0: minutos pra zerar = backlog / líquida * 60
    # - Se ≤ 0: backlog está crescendo
    arrivals_last_hour = db.query(PublicationRecord).filter(
        PublicationRecord.created_at >= one_hour_ago
    ).count()
    net_rate_per_hour = last_hour_treated - arrivals_last_hour

    if net_rate_per_hour > 0 and backlog > 0:
        burndown_minutes = int(backlog / net_rate_per_hour * 60)
        burndown_label = f"Ao ritmo atual, backlog zera em ~{burndown_minutes//60}h{burndown_minutes%60}min"
    elif backlog == 0:
        burndown_label = "Backlog zerado 🎉"
    else:
        burndown_label = f"Backlog crescendo {abs(net_rate_per_hour)}/h — sem intervenção, sobe"

    # Tempo médio NOVO→tratada nas últimas 7 dias.
    # COALESCE entre scheduled_at, ignored_at, classified_at; subtrair created_at.
    avg_handling_query = db.query(
        func.avg(
            func.extract('epoch',
                func.coalesce(
                    PublicationRecord.scheduled_at,
                    PublicationRecord.ignored_at,
                    PublicationRecord.classified_at,
                ) - PublicationRecord.created_at
            )
        )
    ).filter(
        or_(
            PublicationRecord.scheduled_at >= seven_days_ago,
            PublicationRecord.ignored_at >= seven_days_ago,
            PublicationRecord.classified_at >= seven_days_ago,
        )
    ).scalar()
    avg_handling_minutes = int(avg_handling_query / 60) if avg_handling_query else None

    return {
        "last_hour_treated": last_hour_treated,
        "avg_per_hour_7d": round(avg_per_hour_7d, 1),
        "vs_avg_pct": round((last_hour_treated - avg_per_hour_7d) / avg_per_hour_7d * 100, 1)
            if avg_per_hour_7d > 0 else 0,
        "backlog": backlog,
        "oldest_pending_age_minutes": oldest_age_minutes,
        "burndown_label": burndown_label,
        "net_rate_per_hour": net_rate_per_hour,
        "avg_handling_minutes": avg_handling_minutes,
        "generated_at": now.isoformat(),
    }
```

`RhythmResponse` em `app/schemas/dashboard.py` (criar se não existir):

```python
class RhythmResponse(BaseModel):
    last_hour_treated: int
    avg_per_hour_7d: float
    vs_avg_pct: float
    backlog: int
    oldest_pending_age_minutes: int | None
    burndown_label: str
    net_rate_per_hour: int
    avg_handling_minutes: int | None
    generated_at: str
```

### 5.3 Frontend — Bloco 1 do dashboard reformulado

Em `PublicationsDashboardPage.tsx`:

- Adicionar `useQuery` em `/api/v1/dashboard/publications-rhythm` com
  `refetchInterval: 30_000` (atualizar a cada 30s pra parecer vivo).
- Substituir os 4 KPI cards atuais pelos 4 novos:

```tsx
<div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
  <KpiCard
    label="Pendentes agora"
    value={rhythm?.backlog ?? 0}
    caption={rhythm?.oldest_pending_age_minutes != null
      ? `Mais antiga há ${formatAge(rhythm.oldest_pending_age_minutes)}`
      : "Backlog vazio"}
    icon={Inbox}
    tone={rhythm && rhythm.backlog > 150 ? 'error'
      : rhythm && rhythm.backlog > 50 ? 'warning' : 'default'}
  />
  <KpiCard
    label="Ritmo última hora"
    value={`${rhythm?.last_hour_treated ?? 0}/h`}
    caption={rhythm?.vs_avg_pct != null
      ? `${rhythm.vs_avg_pct > 0 ? '↑' : '↓'} ${Math.abs(rhythm.vs_avg_pct)}% vs média 7d`
      : ""}
    icon={TrendingUp}
    tone={rhythm && rhythm.vs_avg_pct > 0 ? 'success' : 'default'}
  />
  <KpiCard
    label="Projeção"
    value={/* uma linha curta */ rhythm?.net_rate_per_hour ?? 0 > 0 ? "Caindo" : "Subindo"}
    caption={rhythm?.burndown_label ?? ""}
    icon={Activity}
    tone={rhythm && rhythm.net_rate_per_hour > 0 ? 'success' : 'error'}
  />
  {/* O 4º card (meta vs hoje) chega completo na Fase 4 — por enquanto,
      mostrar só "tratadas hoje" sem barra de meta. */}
  <KpiCard
    label="Tratadas hoje"
    value={kpis?.tratadas_janela ?? 0}
    caption="Você + equipe"
    icon={CheckCircle2}
    tone="success"
  />
</div>
```

Helper `formatAge(minutes: number): string`:
- `< 60` → `${m}min`
- `< 60*24` → `${h}h${m}min`
- `>= 60*24` → `${d}d${h}h`

### 5.4 Validação manual (Fase 2)

1. Rodar migration localmente:
   ```bash
   docker exec onetask-api-1 sh -c "cd /app && alembic upgrade head"
   ```
2. Conferir colunas via psql ou `\d publication_records`.
3. No frontend, acessar `/publications/dashboard` e ver os 4 cards
   novos carregando dados reais.
4. Marcar manualmente uma publicação como IGNORADO via UI → conferir
   no banco que `ignored_by_user_id` foi preenchido.
5. Idem pra CLASSIFICADO.
6. Bater `alembic heads` — deve ter 1 head, sem ambiguidade.

### 5.5 Bloco PowerShell de commit (Fase 2)

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "feat(pub): migration pub010 autoria ignorado/classificado + dashboard pulso operacional"
git push origin feat/prazos-iniciais
```

---

## 6. FASE 3 — Gráfico horário + Pipeline de agendamento

**Objetivo:** Blocos 2 e 3 do dashboard reformulado.
- **Bloco 2**: gráfico de hoje com granularidade 1h (recebidas vs
  tratadas), mais mini-gráfico de tempo médio de tratamento ao longo
  da semana.
- **Bloco 3**: funil compacto de hoje + lista das próximas saídas
  (queue de tratamento web).

### 6.1 Backend

#### Endpoint `publications-overview` ganha `granularity=hour|day`

Em `app/api/v1/endpoints/dashboard.py`, parametrizar a função que
gera `timeseries`:

```python
@router.get("/publications-overview")
def get_publications_overview(
    days: int = Query(14, ge=1, le=60),
    granularity: Literal["hour", "day"] = "day",
    db: Session = Depends(get_db),
):
    if granularity == "hour":
        # Agrupar por date_trunc('hour', ...) últimas 24h ignorando 'days'.
        ...
    else:
        # Comportamento atual: agrupar por dia.
        ...
```

Manter retrocompatibilidade — `days` continua respeitado quando
`granularity=day`.

#### Endpoint novo `publications-pipeline`

```python
@router.get("/publications-pipeline")
def get_publications_pipeline(
    db: Session = Depends(get_db),
):
    """
    Funil de hoje + próximas N tarefas em fila de tratamento web.
    """
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # Funil de hoje.
    received_today = db.query(PublicationRecord).filter(
        PublicationRecord.created_at >= today_start
    ).count()

    treated_today = db.query(PublicationRecord).filter(
        or_(
            PublicationRecord.scheduled_at >= today_start,
            PublicationRecord.ignored_at >= today_start,
            PublicationRecord.classified_at >= today_start,
        )
    ).count()

    scheduled_today = db.query(PublicationRecord).filter(
        PublicationRecord.scheduled_at >= today_start
    ).count()

    # Próximas saídas: itens em PublicationTreatmentItem com queue_status
    # = PENDENTE, ordenados por created_at.
    next_out = db.query(PublicationTreatmentItem).filter(
        PublicationTreatmentItem.queue_status == "PENDENTE"
    ).order_by(PublicationTreatmentItem.created_at.asc()).limit(10).all()

    return {
        "funnel_today": {
            "received": received_today,
            "treated": treated_today,
            "scheduled": scheduled_today,
        },
        "next_out": [
            {
                "id": item.id,
                "cnj": item.linked_lawsuit_cnj,
                "target_status": item.target_status,
                "queued_at": item.created_at.isoformat(),
            }
            for item in next_out
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
```

### 6.2 Frontend

Em `PublicationsDashboardPage.tsx`, **substituir** o gráfico atual
(que vem do `publications-overview?days=14`) por:

- Toggle no topo do card: "Hoje (por hora)" vs "7 dias (por dia)".
- Estado local controla o `granularity` da query.
- Reutilizar `AreaChart` do Recharts (já no projeto).

Adicionar **card de pipeline** (Bloco 3) abaixo dos gráficos, em duas
colunas (grid-cols-2):

```tsx
<Card className="glass-card">
  <CardHeader>
    <CardTitle>Pipeline de hoje</CardTitle>
  </CardHeader>
  <CardContent className="grid grid-cols-1 md:grid-cols-2 gap-6">
    {/* Esquerda: funil */}
    <div>
      <FunnelStep label="Recebidas" value={pipeline?.funnel_today.received ?? 0} onClick={() => navigate("/publications?recebidas_hoje=1")} />
      <FunnelStep label="Tratadas" value={pipeline?.funnel_today.treated ?? 0} />
      <FunnelStep label="Agendadas no L1" value={pipeline?.funnel_today.scheduled ?? 0} onClick={() => navigate("/publications?status=agendado")} />
    </div>
    {/* Direita: lista de próximas saídas */}
    <div>
      <h4 className="text-sm font-semibold mb-2">Próximas saídas</h4>
      {pipeline?.next_out?.length ? (
        <ul className="space-y-1 text-xs">
          {pipeline.next_out.map(item => (
            <li key={item.id} className="flex justify-between">
              <span className="font-mono">{item.cnj}</span>
              <Badge variant="outline">{item.target_status}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">Nenhuma publicação em fila.</p>
      )}
      <Button variant="link" size="sm" onClick={() => navigate("/publications/treatment")}>
        Ver fila completa →
      </Button>
    </div>
  </CardContent>
</Card>
```

`FunnelStep` é um componentinho local: label + número grande + seta
descendo pra próxima etapa. Sem precisar de biblioteca extra.

### 6.3 Validação manual (Fase 3)

- Toggle hora/dia muda o gráfico sem reload.
- Funil bate com queries diretas no banco (rodar SQL pra conferir).
- Lista de "próximas saídas" mostra itens pendentes da fila de
  tratamento web.

### 6.4 Bloco PowerShell de commit (Fase 3)

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "feat(pub): grafico horario + pipeline de agendamento no dashboard"
git push origin feat/prazos-iniciais
```

---

## 7. FASE 4 — Gamificação V1 (leaderboard + streak + meta móvel)

**Objetivo:** **núcleo do impulso ao ritmo.** Aqui mora o que vai mudar
comportamento do operador. 4 elementos:

1. Card pessoal "Sua semana"
2. Leaderboard semanal
3. Conquistas recentes (sem persistência — calculadas sob demanda)
4. Comparativo da equipe

### 7.1 Backend

#### Endpoint `publications-leaderboard`

```python
@router.get("/publications-leaderboard")
def get_publications_leaderboard(
    window: Literal["day", "week", "month"] = "week",
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    if window == "day":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window == "week":
        since = now - timedelta(days=7)
    else:
        since = now - timedelta(days=30)

    # Une as 3 fontes de autoria, conta por user_id, ordena desc.
    # Pode usar UNION ALL + GROUP BY.
    query = text("""
        WITH eventos AS (
            SELECT scheduled_by_user_id AS user_id,
                   scheduled_by_name AS user_name,
                   scheduled_at AS at
            FROM publication_records
            WHERE scheduled_at >= :since AND scheduled_by_user_id IS NOT NULL
            UNION ALL
            SELECT ignored_by_user_id, ignored_by_name, ignored_at
            FROM publication_records
            WHERE ignored_at >= :since AND ignored_by_user_id IS NOT NULL
            UNION ALL
            SELECT classified_by_user_id, classified_by_name, classified_at
            FROM publication_records
            WHERE classified_at >= :since AND classified_by_user_id IS NOT NULL
        )
        SELECT user_id, user_name, COUNT(*) AS total
        FROM eventos
        GROUP BY user_id, user_name
        ORDER BY total DESC
        LIMIT :limit
    """)
    rows = db.execute(query, {"since": since, "limit": limit}).fetchall()

    return {
        "window": window,
        "since": since.isoformat(),
        "items": [
            {"user_id": r.user_id, "user_name": r.user_name, "total": r.total}
            for r in rows
        ],
    }
```

#### Endpoint `me/publications-stats`

Cria `app/api/v1/endpoints/me.py` (se não existir) ou aproveita
arquivo existente:

```python
@router.get("/me/publications-stats")
def get_me_publications_stats(
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Streak, meta do dia (calculada via fórmula móvel), posição no
    leaderboard semanal, contagem do dia.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    user_id = current_user.id

    # Tratadas hoje pelo usuário.
    treated_today = db.query(PublicationRecord).filter(
        or_(
            and_(PublicationRecord.scheduled_by_user_id == user_id,
                 PublicationRecord.scheduled_at >= today_start),
            and_(PublicationRecord.ignored_by_user_id == user_id,
                 PublicationRecord.ignored_at >= today_start),
            and_(PublicationRecord.classified_by_user_id == user_id,
                 PublicationRecord.classified_at >= today_start),
        )
    ).count()

    # Meta diária móvel.
    backlog = db.query(PublicationRecord).filter(
        PublicationRecord.status == "NOVO"
    ).count()

    # Recebidas média 7d / dia.
    received_7d = db.query(PublicationRecord).filter(
        PublicationRecord.created_at >= seven_days_ago
    ).count()
    avg_received_per_day = received_7d / 7

    # Operadores ativos = usuários distintos com ao menos 1 tratamento
    # nos últimos 7 dias.
    active_operators = db.execute(text("""
        SELECT COUNT(DISTINCT user_id) FROM (
            SELECT scheduled_by_user_id AS user_id FROM publication_records
                WHERE scheduled_at >= :since AND scheduled_by_user_id IS NOT NULL
            UNION
            SELECT ignored_by_user_id FROM publication_records
                WHERE ignored_at >= :since AND ignored_by_user_id IS NOT NULL
            UNION
            SELECT classified_by_user_id FROM publication_records
                WHERE classified_at >= :since AND classified_by_user_id IS NOT NULL
        ) t
    """), {"since": seven_days_ago}).scalar() or 1

    # Config (vem de settings — Fase 4.4).
    DIAS_UTEIS_ALVO = settings.GAMIFICATION_DIAS_UTEIS_ALVO  # default 3
    PISO_MINIMO = settings.GAMIFICATION_PISO_META  # default 20

    meta_hoje = max(
        PISO_MINIMO,
        math.ceil((backlog + avg_received_per_day) / DIAS_UTEIS_ALVO / active_operators)
    )

    # Streak: dias consecutivos com pelo menos 1 tratamento.
    streak = 0
    for delta in range(0, 365):
        day_start = (now - timedelta(days=delta)).replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        had_action = db.query(PublicationRecord).filter(
            or_(
                and_(PublicationRecord.scheduled_by_user_id == user_id,
                     PublicationRecord.scheduled_at >= day_start,
                     PublicationRecord.scheduled_at < day_end),
                and_(PublicationRecord.ignored_by_user_id == user_id,
                     PublicationRecord.ignored_at >= day_start,
                     PublicationRecord.ignored_at < day_end),
                and_(PublicationRecord.classified_by_user_id == user_id,
                     PublicationRecord.classified_at >= day_start,
                     PublicationRecord.classified_at < day_end),
            )
        ).first() is not None

        if had_action:
            streak += 1
        elif delta == 0:
            # Se hoje ainda não tem ação, streak começa de ontem.
            continue
        else:
            break

    # Posição no leaderboard semanal: chamar a mesma query do
    # leaderboard, achar índice do usuário.
    # (omitido aqui pra brevidade — implementar).

    return {
        "treated_today": treated_today,
        "meta_today": meta_hoje,
        "streak_days": streak,
        "leaderboard_position": None,  # preencher
        "active_operators": active_operators,
        "backlog": backlog,
    }
```

#### Settings de gamificação

Em `app/config.py`:

```python
class Settings(BaseSettings):
    ...
    GAMIFICATION_ENABLED: bool = True
    GAMIFICATION_DIAS_UTEIS_ALVO: int = 3
    GAMIFICATION_PISO_META: int = 20
    GAMIFICATION_LEADERBOARD_ENABLED: bool = True
```

E expor um endpoint admin pra atualizar (ou ler do banco se preferir
flexibilidade sem redeploy):

#### Página admin `/admin/gamification-settings`

Frontend `frontend/src/pages/GamificationSettingsPage.tsx` com 3
inputs simples (dias úteis alvo, piso mínimo, on/off leaderboard) e
botão Salvar. Backend `PUT /api/v1/admin/gamification-settings`.

Se preferir mais rápido, **Fase 4 pode usar só env vars** (config no
Coolify) e adiar página admin pra Fase 5.

### 7.2 Frontend — Bloco "Sua semana"

```tsx
<Card className="glass-card">
  <CardHeader>
    <CardTitle className="flex items-center gap-2">
      <Sparkles className="h-5 w-5 text-amber-500" />
      Sua semana
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-4">
    {/* Streak */}
    <div className="flex items-center gap-2">
      <span className="text-2xl">🔥</span>
      <div>
        <p className="text-lg font-bold">{meStats?.streak_days ?? 0} dias seguidos</p>
        <p className="text-xs text-muted-foreground">Lendo publicações</p>
      </div>
    </div>

    {/* Meta do dia */}
    <div>
      <div className="flex justify-between text-sm mb-1">
        <span>Meta do dia</span>
        <span className="font-semibold">
          {meStats?.treated_today ?? 0}/{meStats?.meta_today ?? '—'}
        </span>
      </div>
      <Progress value={meStats ? (meStats.treated_today / meStats.meta_today) * 100 : 0} />
      {meStats && meStats.treated_today >= meStats.meta_today && (
        <p className="text-xs text-emerald-600 mt-1">🎉 Meta batida!</p>
      )}
    </div>

    {/* Posição leaderboard */}
    {meStats?.leaderboard_position && (
      <p className="text-sm">
        Você é <strong>#{meStats.leaderboard_position}</strong> da semana.
      </p>
    )}
  </CardContent>
</Card>
```

### 7.3 Frontend — Leaderboard

Listinha simples top 10, com avatar (inicial em círculo), nome,
contagem, medalhas pros 3 primeiros:

```tsx
<Card className="glass-card">
  <CardHeader>
    <CardTitle>Leaderboard da semana</CardTitle>
  </CardHeader>
  <CardContent>
    <ol className="space-y-2">
      {leaderboard?.items.map((row, idx) => (
        <li key={row.user_id} className="flex items-center gap-3 p-2 rounded-lg
                                          hover:bg-white/50 transition-colors">
          <span className="w-8 text-center">
            {idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx+1}`}
          </span>
          <div className="w-8 h-8 rounded-full bg-[hsl(var(--dunatech-blue))]
                          text-white flex items-center justify-center text-xs font-bold">
            {row.user_name?.slice(0,1).toUpperCase()}
          </div>
          <span className="flex-1 text-sm">{row.user_name}</span>
          <span className="font-semibold text-sm">{row.total}</span>
        </li>
      ))}
    </ol>
  </CardContent>
</Card>
```

### 7.4 Validação manual (Fase 4)

- Tratar uma publicação na própria conta → `treated_today` incrementa
  em tempo real (refetchInterval 30s).
- Meta do dia muda quando admin altera env vars + reinicia API.
- Leaderboard mostra ordenação correta.
- Streak: ter 2 dias seguidos com ação confirma streak=2.

### 7.5 Bloco PowerShell de commit (Fase 4)

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "feat(pub): gamificacao v1 leaderboard streak meta movel"
git push origin feat/prazos-iniciais
```

---

## 8. FASE 5 — Badges + Hall semanal (futuro, só se Fase 4 engajar)

**Pré-requisito:** medir engajamento da Fase 4 por ≥2 semanas. Sinais
de "vale fazer Fase 5":
- Operadores comentam sobre leaderboard ou meta
- Ritmo médio da equipe sobe ≥10%
- Pedido espontâneo de "ranking do mês" ou "quero ver minhas
  conquistas"

Se zero sinal → não fazer Fase 5, redirecionar esforço pra
otimização do classificador (ROI maior).

### 8.1 Escopo se for fazer

- Tabela `publication_badge_grants` (id, user_id, badge_code,
  granted_at, metadata jsonb)
- Catálogo de badges em código (constante):
  - `PRIMEIRA_LEITURA` — primeira vez tratando publicação
  - `CEM_LEITURAS`, `QUINHENTAS_LEITURAS`, `MIL_LEITURAS`
  - `MATADOR_DE_BACKLOG` — tratamento que zerou o backlog
  - `MADRUGADOR` — primeira ação do dia antes das 9h em ≥5 dias na
    semana
  - `FOLEGO` — 20+ tratamentos em 1h
  - `LEITOR_DA_SEMANA` — top 1 do leaderboard semanal
- Cron job (APScheduler, já no projeto) toda madrugada confere quais
  badges foram desbloqueadas no dia anterior e grava.
- Card "Conquistas recentes" no dashboard listando últimas 10
  concessões (suas + da equipe).
- Hall semanal: cron na sexta posta no `AdminNotice` "🏆 Leitor da
  semana: {nome} com {N} publicações".

---

## 9. Resumo de arquivos por fase

### Fase 1 (Landing + Nav)
- **Criar**:
  - `frontend/src/pages/LandingPage.tsx`
  - `frontend/src/pages/PublicationsDashboardPage.tsx`
- **Modificar**:
  - `frontend/src/App.tsx`
  - `frontend/src/components/Layout.tsx`
- **Deletar**:
  - `frontend/src/pages/DashboardHome.tsx`

### Fase 2 (Autoria + Pulso)
- **Criar**:
  - `app/alembic/versions/pub010_autoria_ignorado_e_classificado.py`
- **Modificar**:
  - `app/models/publication_search.py`
  - `app/api/v1/endpoints/dashboard.py` (endpoint `publications-rhythm`)
  - `app/schemas/dashboard.py` (schema `RhythmResponse`)
  - `app/services/publication_search_service.py` (helper
    `_set_authorship` + chamadas nos handlers que mudam status)
  - `app/api/v1/endpoints/publications.py` (PATCH /records/{id} —
    setar autoria)
  - `frontend/src/pages/PublicationsDashboardPage.tsx` (Bloco 1
    reformulado)

### Fase 3 (Gráfico horário + Pipeline)
- **Modificar**:
  - `app/api/v1/endpoints/dashboard.py` (`granularity` em
    `publications-overview` + endpoint `publications-pipeline`)
  - `frontend/src/pages/PublicationsDashboardPage.tsx` (Blocos 2 e 3)

### Fase 4 (Gamificação V1)
- **Criar**:
  - `app/api/v1/endpoints/me.py` (se ainda não existir) ou
    `app/api/v1/endpoints/gamification.py`
  - `frontend/src/pages/GamificationSettingsPage.tsx` (opcional —
    pode adiar)
- **Modificar**:
  - `app/config.py` (settings de gamificação)
  - `app/api/v1/endpoints/dashboard.py` (endpoint
    `publications-leaderboard`)
  - `frontend/src/pages/PublicationsDashboardPage.tsx` (Bloco 4)
  - `frontend/src/App.tsx` (rota
    `/admin/gamification-settings` se entrar)
  - `frontend/src/components/Layout.tsx` (item de menu admin)

### Fase 5 (Badges, futuro)
- Definir só quando confirmar que vai fazer.

---

## 10. Checklist final antes de fechar cada fase

Para cada fase, o executor deve confirmar:

- [ ] Arquivos modificados conferidos com `wc -l` contra `git show
      HEAD:arquivo | wc -l` (guard de truncamento).
- [ ] `npm run build` no `frontend/` passa sem erro.
- [ ] Backend: `pytest -q app/tests/` passa (se houver testes da
      área).
- [ ] `alembic heads` retorna 1 só head.
- [ ] Validação manual da seção 5.4 / 6.3 / 7.4 da fase
      correspondente feita.
- [ ] Bloco PowerShell de commit entregue ao usuário (não rodar do
      sandbox).
- [ ] Mensagem de commit em linha única, sem caracteres especiais
      problemáticos pra PowerShell 5.x.
- [ ] Se há mudança em `.env.example` ou variáveis novas, listar pro
      usuário setar no Coolify antes do redeploy.
- [ ] Se há migration nova/destrutiva, alertar.

---

## 11. Decisões em aberto (não bloqueantes)

Coisas que podem ser decididas durante a execução, mas que vale
sinalizar:

1. **Métrica do leaderboard:** total simples (1 ponto por tratamento)
   ou ponderada (AGENDADO=2, IGNORADO=1, CLASSIFICADO=1)? Atualmente
   plano usa total simples. Reabrir se feedback inicial achar
   "agendar é mais difícil que ignorar".
2. **Visibilidade do leaderboard:** todo mundo vê o ranking inteiro,
   ou só posição própria + top 3? Plano usa total transparente.
3. **Tema dark:** liquid glass funciona bem em ambos os modos. Se o
   projeto tem dark mode ativo, validar contraste.
4. **Backfill de autoria:** decidi não fazer (custo alto, valor
   baixo). Confirmar com cliente se quer rodar algum script
   retroativo (ex.: `triggered_by_email` do
   `PublicationTreatmentRun` pra `scheduled_by_*` em recordings
   AGENDADO sem autoria).

---

## 12. Pontos pra revisitar depois da Fase 1

- Performance do `publications-rhythm`: as 4 queries são leves mas
  rodam a cada 30s pra cada operador online. Se virar gargalo,
  cachear com Redis (TTL 15s) ou consolidar em uma view materializada
  refresh-on-demand.
- Tempo médio NOVO→tratada: a subquery com COALESCE em 3 colunas
  pode ficar lenta com a tabela crescendo. Considerar índice
  composto se EXPLAIN ANALYZE mostrar seq scan.
- A meta móvel pode oscilar muito durante o dia (especialmente de
  manhã quando backlog é alto). Considerar fixar a meta calculada
  no início do dia útil (cron 8h) e não recalcular durante o dia —
  evita o pesadelo "bati a meta e ela aumentou".

---

**Fim do plano.**

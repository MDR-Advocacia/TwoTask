# Notas para o Claude (TwoTask / DunaFlow — MDR Advocacia)

## Deploy

**Esse projeto roda no Coolify.** Não dê instruções de deploy manual
(`alembic upgrade head`, `npm run build`, restart de processo, etc.).
O Coolify cuida de:

- Rebuild do Docker (API + frontend) ao detectar push em `main`.
- Aplicação automática de migrations via `scripts/docker-api-start.sh`
  (que roda `alembic upgrade head` no boot do container).
- Restart de containers e do scheduler do APScheduler.
- Variáveis de ambiente (lidas do painel do Coolify, não do `.env` local).

**Quando o usuário diz "deploy", a sequência prática é apenas:**

1. Confirmar que a `main` tem o que precisa (commits + push).
2. Avisar o que mudou no `.env.example` ou em variáveis novas — o
   operador precisa setar essas no painel do Coolify antes do redeploy.
3. Avisar se houver alguma migration nova/destrutiva que precisa de
   atenção (ex.: dataloss, downtime).
4. O usuário aciona o redeploy no painel do Coolify.

**Não escreva runbooks de deploy "tradicional" para esse projeto.**

## Branches

- `main` — branch de produção. Coolify deploya daqui.
- `feat/prazos-iniciais` — branch de teste/desenvolvimento de novas
  features. Sempre mais avançada que main em features experimentais.
  Quando validada, faz merge para main → deploy.
- Após merge `feat → main`, lembrar de fazer `merge main → feat` pra
  trazer fixes que foram direto pra main (ex.: hotfixes de Publications)
  e evitar divergência grande no próximo merge.

## Workflow de commit

- **Nunca commitar do sandbox** (trava `.git/HEAD.lock`). Sempre entregar
  bloco PowerShell pronto pra o usuário rodar no VSCode/terminal.
- O ambiente do usuário é PowerShell 5.x — não usa `&&` (use linhas
  separadas, sem `;` ou `if ($LASTEXITCODE -eq 0)`).
- **Formato padrão e fixo dos blocos de commit** (não variar):

### Quando o usuário disser "main":

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout main
git add -A
git commit -m "<mensagem>"
git push origin main
```

### Quando o usuário disser "prazos iniciais" / "feat":

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "<mensagem>"
git push origin feat/prazos-iniciais
```

### Quando o usuário disser "os dois" / "ambos":

Commitar em `feat/prazos-iniciais` (branch de teste, mais avançada) e
propagar pra `main` via merge fast-forward:

```powershell
cd "C:\Users\jonil\OneDrive\Desktop\Projetos HUB\OneTask - Solo\onetask"
git checkout feat/prazos-iniciais
git add -A
git commit -m "<mensagem>"
git push origin feat/prazos-iniciais
git checkout main
git merge feat/prazos-iniciais --no-edit
git push origin main
```

### Regras gerais (não variar)

- Sempre `git add -A` (stage tudo).
- Nunca rodar `git status` antes do commit (o usuário não pediu).
- Mensagem em linha única: `feat(escopo): ...` / `fix(escopo): ...`
  / `docs: ...` / `chore: ...`.
- Sem caracteres especiais que o PowerShell interprete mal (sem `&&`,
  sem `\n` na mensagem do commit — uma linha só).
- Não inventar etapas extras (ex.: `git pull` antes do push, validação
  de diff, etc.) a não ser que o usuário peça.

## ⚠️ EDIT/WRITE EM ARQUIVO GRANDE — TRUNCAMENTO RECORRENTE ⚠️

**AS TOOLS `Edit` E `Write` ESTÃO TRUNCANDO ARQUIVOS GRANDES** (>~800
linhas, ex.: `app/api/v1/endpoints/ajus.py`, `app/services/ajus/classif_runner.py`,
`frontend/src/components/ajus/ClassificacaoTab.tsx`, `frontend/src/services/api.ts`).
O sintoma é o arquivo terminar abruptamente no meio de uma função/string,
com perda de dezenas a centenas de linhas a partir do ponto editado em
diante. JÁ FALHOU 4+ VEZES.

**REGRA OBRIGATÓRIA — não usar `Edit`/`Write` direto em arquivos grandes.**

Quando precisar modificar um arquivo de ~800+ linhas (backend FastAPI
agregado, runners Playwright, componentes React grandes), USE O FLUXO
ABAIXO em vez do `Edit` tool:

1. **Pegar o original do git** (não confiar no `Read` do estado atual,
   que pode já estar truncado de edits anteriores):
   ```bash
   git show HEAD:caminho/do/arquivo > /tmp/orig.ext
   ```

2. **Aplicar as mudanças via Python `str.replace`** (heredoc bash com
   `<< EOF` quotado pra evitar interpolação):
   ```bash
   python3 << 'PYEOF'
   src = open('/tmp/orig.ext').read()
   old = """<bloco exato a substituir>"""
   new = """<bloco novo>"""
   assert old in src, "old not found"
   src = src.replace(old, new)
   open('caminho/no/repo', 'w').write(src)
   print("lines:", len(src.split(chr(10))))
   PYEOF
   ```

3. **Validar integridade depois de toda mudança**:
   ```bash
   # Python: parse AST
   python3 -c "import ast; ast.parse(open('arquivo.py').read()); print('OK')"
   # Comparar contagem com git pra detectar perda de bytes:
   wc -l arquivo
   git show HEAD:arquivo | wc -l
   tail -3 arquivo    # ver se termina em token válido
   ```

**GUARD DE TRUNCAMENTO NO COMMIT** — antes de entregar o bloco PowerShell,
SEMPRE rodar a validação acima e bater contagem de linhas. Se faltar
linhas vs git, RECUPERAR via git ANTES de commit. Sem guard = sem commit,
sem exceção. Mesma lógica do guard do bloco PowerShell de commit
(memory `feedback_truncamento_arquivos_grandes.md`).

## Stack

- Backend: FastAPI + SQLAlchemy + Pydantic V2 + Alembic.
- Frontend: React + TypeScript + Vite + shadcn/ui + Tailwind.
- DB: PostgreSQL.
- Integrações: Legal One (Thomson Reuters), Anthropic (Sonnet + Batches),
  Playwright Node.js (RPA pra ações que a API L1 não cobre).

## Convenções da casa

- `LegalOneOffice.path` é a hierarquia completa (ex.: "MDR / Filial BA /
  Cível") — preferir sobre `name` (folha) em UI e exports.
- Português pt-BR em logs, mensagens de erro voltadas pro operador, e
  comentários de código no domínio jurídico.
- Migrations Prazos Iniciais usam prefixo `pin*`, Publications usa
  `pub*`, etc. — manter padrão.

## ⚠️ Paginação obrigatória em qualquer listagem/menu/modal

**Toda listagem, menu ou modal que exibe N itens de catálogo PRECISA
ter paginação configurada desde o primeiro commit.** Já estourou
modal de classificações de template porque não tinha paginação e o
operador abriu uma combinação com várias dezenas de subcategorias.

Padrão da casa:

- **API**: endpoints de listagem aceitam `limit` (default 50, max
  500) + `offset` e devolvem `{ total, items }`.
- **UI de página**: controles "Anterior / Próxima · Página X de Y ·
  N–M de T resultados" + seletor de page size (25/50/100). Reusar o
  padrão de `PublicationsPage` / `PrazosIniciaisPage`.
- **Modais que listam catálogos** (subtipos, classificações,
  responsáveis, escritórios, etc.): paginação interna OU
  virtualização (cmdk/Combobox quando >50 itens). Nunca `<Select>`
  cru sem paginação em catálogo grande (ver memory
  `feedback_dropdowns_searchable.md`).
- Listas curtas e estáveis (≤20 itens, ex.: enums) podem ficar sem
  paginação — mas decidir conscientemente, não por descuido.

Antes de marcar uma feature como pronta: abrir a listagem com dados
reais (não 3 mocks) e confirmar que rola/pagina sem travar.

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

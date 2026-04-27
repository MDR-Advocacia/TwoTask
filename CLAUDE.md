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
- O ambiente do usuário é PowerShell 5.x — não usa `&&` (use `;` ou
  comandos separados, ou `if ($LASTEXITCODE -eq 0) { ... }`).

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

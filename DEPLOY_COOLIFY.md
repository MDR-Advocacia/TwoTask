# Deploy no Coolify

Guia passo-a-passo para subir o OneTask — Solo no Coolify usando Docker Compose.

## 1. Estrutura

- `docker-compose.yml` — produção (lido pelo Coolify). 3 serviços: `postgres`, `api`, `frontend`.
- `docker-compose.override.yml` — dev local (bind mounts + Vite dev server). **Ignorado em produção** porque o Coolify só carrega o arquivo que você apontar.
- `Dockerfile` — build do backend FastAPI.
- `Dockerfile.frontend` — build multi-stage: Node 20 builda o Vite → nginx 1.27 serve estático + proxy `/api`.
- `frontend/nginx.conf` — SPA fallback, proxy reverso `/api → api:8000`, `/healthz`, gzip.

## 2. Antes de subir pro GitHub

Execute uma vez (na raiz do projeto):

```bash
# Remove arquivos de lixo que estavam trackeados
rm -f "Dockerfile copy.frontend" legal-one-firms-brazil-api.json
rm -f backend-dev.log backend-dev.err.log

# Tira do git o que não deveria estar versionado
git rm --cached -r --ignore-unmatch data/ || true
git rm --cached --ignore-unmatch entrada.xlsx planilha_de_processos.xlsx || true
git rm --cached --ignore-unmatch backend-dev.log backend-dev.err.log || true
git rm --cached --ignore-unmatch "Dockerfile copy.frontend" legal-one-firms-brazil-api.json || true

# Commit e push
git add .
git commit -m "chore: prepara deploy Coolify (compose prod/dev, nginx, dockerignore)"
git push origin main
```

Confira que **`.env` NÃO foi commitado** (deve estar no `.gitignore`).

## 3. Configurar no Coolify

1. **New Resource → Docker Compose**.
2. Conecte o repositório GitHub e selecione a branch.
3. Compose file path: `docker-compose.yml`.
4. **Environment Variables**: copie o conteúdo do `.env.example` e preencha com os valores reais. Variáveis críticas:
   - `POSTGRES_PASSWORD` — senha forte.
   - `SECRET_KEY` — gere com `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
   - `LEGAL_ONE_CLIENT_ID` / `LEGAL_ONE_CLIENT_SECRET`.
   - `LEGAL_ONE_WEB_USERNAME` / `LEGAL_ONE_WEB_PASSWORD` (RPA).
   - `ANTHROPIC_API_KEY`.
   - `CORS_ALLOWED_ORIGINS=https://seu-dominio.com`.
   - `FRONTEND_PORT=8111` (porta exposta no host — não colide com outros stacks).
5. **Domains**: aponte o domínio pro serviço `frontend` na porta `80`. Coolify gerencia SSL (Let's Encrypt) automaticamente.
6. **Persistent Storage**: os volumes nomeados (`postgres_data`, `api_data`, `api_output`) já estão declarados no compose — o Coolify persiste automaticamente.
   **Domain/Proxy**: aponte pra porta interna `80` do serviço `frontend` (o Coolify resolve pela rede interna, não precisa bater na `FRONTEND_PORT` publicada).
7. Clique **Deploy**.

## 4. Primeira inicialização

Após o primeiro deploy, abra o terminal do serviço `api` no Coolify:

```bash
# Rodar migrations (se o startup não rodar automaticamente)
alembic upgrade head

# Criar usuário admin
python create_user.py --email voce@dominio.com --password SenhaForte123
```

## 5. Atualizações

Push para a branch configurada → Coolify faz rebuild automático (se webhook estiver ativo) ou clique **Redeploy**.

Em alterações do schema:
```bash
# No terminal do container api
alembic upgrade head
```

## 6. Desenvolvimento local

```bash
docker compose up --build
```
Usa automaticamente `docker-compose.yml` + `docker-compose.override.yml`:
- Frontend Vite em http://localhost:5173 (hot reload).
- API em http://localhost:8000 (reload on change).
- Postgres em localhost:5432.

Portas em dev:
- Frontend (Vite): http://localhost:5173
- API: http://localhost:8112
- Postgres: localhost:5433

Para testar o build de produção localmente (sem override):
```bash
docker compose -f docker-compose.yml up --build
# Frontend em http://localhost:8111
```

## 7. Troubleshooting

- **Frontend 502 ao chamar /api**: o nginx faz proxy pra `api:8000`. Confira que o serviço `api` está healthy (`docker compose ps`).
- **API não sobe**: cheque os logs. Normalmente é `DATABASE_URL` errada ou migration faltando.
- **Postgres não persiste**: confira que o volume `postgres_data` está listado em **Persistent Storage** no Coolify.
- **CORS bloqueia**: adicione o domínio em `CORS_ALLOWED_ORIGINS`.

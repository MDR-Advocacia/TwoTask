# Migração de domínio do Flow — guia para integrações

> **Para quem chama a API do Flow** (OneSid, OneRequest, robôs de intake, e qualquer
> app que consome a Base Processual). Operadores humanos no navegador **não** precisam
> fazer nada — isto é só para integrações por **chave de API**.

## TL;DR

O Flow está mudando de endereço. Se a sua aplicação chama a API do Flow, troque
**apenas o domínio base** da URL. **Métodos, caminhos, headers e chaves de API
continuam exatamente iguais.**

| | Domínio base |
|---|---|
| ❌ **Antes** | `https://flow.mdradvocacia.com` |
| ✅ **Depois** | `https://flow.dunatecnologia.com` |

> ⏳ **Sem pressa:** os **dois** domínios funcionam ao mesmo tempo durante a transição.
> A data de desligamento do antigo será avisada com antecedência. Migre e teste com calma.

## Como ajustar (na prática, 1 troca)

Na maioria dos casos é um único *find-and-replace* na URL base / variável de ambiente
da sua aplicação:

```
flow.mdradvocacia.com   →   flow.dunatecnologia.com
```

As **chaves de API não mudam** — continue usando as mesmas.

---

## Tabela antes → depois (por integração)

### 1. Agendamento em lote (OneSid / OneRequest)
Header de auth: `X-Batch-Api-Key`

| Método | Antes | Depois |
|---|---|---|
| `POST` | `https://flow.mdradvocacia.com/api/v1/tasks/batch-create` | `https://flow.dunatecnologia.com/api/v1/tasks/batch-create` |

### 2. Prazos Iniciais — intake externo
Header de auth: `X-Intake-Api-Key`

| Método | Antes | Depois |
|---|---|---|
| `POST` | `https://flow.mdradvocacia.com/api/v1/prazos-iniciais/intake` | `https://flow.dunatecnologia.com/api/v1/prazos-iniciais/intake` |
| `POST` | `https://flow.mdradvocacia.com/api/v1/prazos-iniciais/intake/devolucao` | `https://flow.dunatecnologia.com/api/v1/prazos-iniciais/intake/devolucao` |

### 3. Classificador — intake do robô de entrega
Header de auth: `X-Classificador-Api-Key`

| Método | Antes | Depois |
|---|---|---|
| `POST` | `https://flow.mdradvocacia.com/api/v1/classificador/intake/pdf` | `https://flow.dunatecnologia.com/api/v1/classificador/intake/pdf` |

### 4. Base Processual — API pública (read-only)
Header de auth: `X-Base-Processual-Key` (o `/health` é aberto, sem auth)

| Método | Antes | Depois |
|---|---|---|
| `GET` | `https://flow.mdradvocacia.com/api/v1/public/base-processual/health` | `https://flow.dunatecnologia.com/api/v1/public/base-processual/health` |
| `GET` | `https://flow.mdradvocacia.com/api/v1/public/base-processual/processos` | `https://flow.dunatecnologia.com/api/v1/public/base-processual/processos` |
| `GET` | `https://flow.mdradvocacia.com/api/v1/public/base-processual/processos/by-cnj/{cnj}` | `https://flow.dunatecnologia.com/api/v1/public/base-processual/processos/by-cnj/{cnj}` |
| `GET` | `https://flow.mdradvocacia.com/api/v1/public/base-processual/processos/{cod_ajus}` | `https://flow.dunatecnologia.com/api/v1/public/base-processual/processos/{cod_ajus}` |
| `GET` | `https://flow.mdradvocacia.com/api/v1/public/base-processual/dashboard/resumo` | `https://flow.dunatecnologia.com/api/v1/public/base-processual/dashboard/resumo` |

---

## Teste rápido depois de trocar

**1) Conectividade (não precisa de chave):**
```bash
curl https://flow.dunatecnologia.com/api/v1/public/base-processual/health
# esperado: {"status":"ok","modulo":"base-processual-public"}
```

**2) Exemplo de chamada autenticada (agendamento em lote):**
```bash
curl -X POST https://flow.dunatecnologia.com/api/v1/tasks/batch-create \
  -H "X-Batch-Api-Key: SUA_CHAVE_AQUI" \
  -H "Content-Type: application/json" \
  -d '{ ...payload... }'
# esperado: HTTP 202 (aceito)
```

---

## Checklist por aplicação

- [ ] Atualizar a URL base: `flow.mdradvocacia.com` → `flow.dunatecnologia.com`
- [ ] Conferir que a chave de API continua a mesma (não precisa re-emitir)
- [ ] Rodar o teste de conectividade (`/health`)
- [ ] Rodar 1 chamada real de teste de cada endpoint usado
- [ ] Marcar como migrada ✅

## Observações
- **HTTPS** em ambos — certificado válido (Let's Encrypt).
- O endereço antigo **continua respondendo** até o desligamento avisado.
- Dúvidas / nova chave / escopos da Base Processual: falar com a TI (Dunatech).

"""
Constantes do portal AJUS — selectors XPath, paths e valores fixos
do cliente MDR (banco_master).

Motivação: ESSAS coisas não variam por instância e não são confidenciais.
Estavam no `.env`/`settings` por engano de portagem do projeto Mirror;
ficavam exigindo cadastro manual no painel do Coolify a cada nova
instância e atrapalhavam o teste com erros de "selector não configurado".

Os valores aqui foram validados em produção pelo projeto Mirror (rodava
classificação no AJUS com 100% de sucesso). Se o portal AJUS mudar
layout, é AQUI que se ajusta — um deploy resolve, não mexe em env.

CONFIDENCIAL ou que VARIA por instância continua em `app/core/config.py`
(ex.: `AJUS_FERNET_KEY`, tokens da API REST do AJUS, paths de volume).
"""

from __future__ import annotations


# ─── Portal e login ───────────────────────────────────────────────────

PORTAL_BASE_URL = "https://sistema.ajus.com.br"
LOGIN_PATH = "/#"
# MDR é cliente AJUS sob o domínio `banco_master`. Compartilhado por
# todas as contas humanas usadas pelo robô.
LOGIN_DOMAIN = "banco_master"

# Form de login (página inicial do portal)
DOMAIN_SELECTOR = "#dominioCliente"
USER_SELECTOR = "#username"
PASSWORD_SELECTOR = "#pwd"
LOGIN_BUTTON_SELECTOR = "button.login"


# ─── Validação de IP (2º passo após credenciais) ──────────────────────
# AJUS pede um código de validação quando detecta IP novo. Operador
# recebe via canal separado e digita pela UI do TwoTask; runner
# consome via polling do `pending_ip_code`.

IP_AUTH_INPUT_SELECTOR = "input[name='codigoAuth']"
IP_AUTH_CONFIRM_SELECTOR = "a[href='#finish']"
# Botao "Receber codigo" — primeiro click no flow de IP-auth, antes
# dos inputs aparecerem. Porte do Mirror.
IP_AUTH_REQUEST_SELECTOR = "xpath=//button[contains(normalize-space(.), 'Receber')]"


# ─── Busca rápida do processo ─────────────────────────────────────────
# AJUS não aceita URL direta com CNJ. O fluxo é: clicar no input de
# busca rápida (overlay esquerdo), digitar CNJ, esperar dropdown de
# resultados ExtJS aparecer, clicar no item correspondente.

PROCESS_SEARCH_INPUT_SELECTOR = (
    "xpath=(//div[@id='buscaRapida']"
    "//input[contains(@class,'x-form-text') "
    "and not(@type='hidden') and not(@readonly)])[1]"
)

# Marker secundario do workspace pronto: icone de lupa "a.search".
# Aparece ANTES do input de busca rapida ficar visivel (input pode estar
# colapsado no overlay esquerdo). Porte do Mirror.
PROCESS_SEARCH_TRIGGER_SELECTOR = "a.search"

# Tela de loading que o AJUS mostra apos login bem-sucedido enquanto
# carrega o workspace. Bloqueia decisao de "workspace ready" ate sumir.
WORKSPACE_LOADING_TEXT_SELECTOR = (
    "text=/aguarde, estamos preparando o seu AJUS/i"
)
WORKSPACE_BLOCKED_SELECTOR = "div.bloqueio-tela-login"

# Template — `{process_number}` é substituído pelo CNJ em runtime.
# Usa `last()` no Mirror não foi necessário; aqui pega o primeiro item
# do dropdown VISÍVEL (filtra `visibility: hidden`).
PROCESS_RESULT_SELECTOR_TEMPLATE = (
    "xpath=(//div[contains(@class,'x-layer') "
    "and contains(@class,'x-combo-list') "
    "and not(contains(@style,'visibility: hidden'))]"
    "//div[contains(@class,'x-combo-list-item')]"
    "[contains(normalize-space(.), '{process_number}')])[1]"
)


# ─── Capa do processo (5 campos + botão Salvar) ───────────────────────
# Os XPaths usam "input[name=…]/following-sibling::input[@type='text']"
# — padrão ExtJS onde o input visível (com display value) é irmão do
# hidden input que carrega o valor real.

PROCESS_UF_SELECTOR = (
    "xpath=(//label[contains(normalize-space(.), 'UF')]"
    "/following::input[@type='text' and not(@type='hidden')][1])[1]"
)
PROCESS_COMARCA_SELECTOR = (
    "xpath=(//label[contains(normalize-space(.), 'Comarca')]"
    "/following::input[@type='text' and not(@type='hidden')][1])[1]"
)
PROCESS_MATTER_SELECTOR = (
    "xpath=//input[@name='codClassificacaoAcaoJudicial']"
    "/following-sibling::input[@type='text']"
)
PROCESS_JUSTICE_FEE_SELECTOR = (
    "xpath=//input[@name='codTipoResultadoFinal']"
    "/following-sibling::input[@type='text']"
)
PROCESS_RISK_SELECTOR = (
    "xpath=//input[@name='codProbabilidadePerda']"
    "/following-sibling::input[@type='text']"
)
PROCESS_SAVE_SELECTOR = "button.disk_edit"

# ─── Fallbacks (porte do Mirror) ──────────────────────────────────────
# Quando o seletor exato falha (layout muda, ExtJS render lazy, etc),
# Mirror tenta esses xpaths genericos pra achar input/resultado.

PROCESS_QUICK_SEARCH_FALLBACK_SELECTORS = (
    "xpath=(//input[contains(@class,'x-form-text') "
    "and not(@type='hidden') and not(@readonly) "
    "and not(ancestor::*[contains(@style,'display:none')])])[1]",
    "xpath=(//input[not(@type='hidden') and not(@readonly) "
    "and not(ancestor::*[contains(@style,'display:none')])])[1]",
)

PROCESS_RESULT_FALLBACK_SELECTOR_TEMPLATE = (
    "xpath=(//*[self::a or self::div or self::span or self::td]"
    "[contains(normalize-space(.), '{process_number}') "
    "and not(ancestor::*[contains(@style,'display:none')])])[1]"
)

# Selector secundario do menu de processos (fallback se a busca rapida
# nao expandir). Pra MDR/banco_master nao costuma ser usado, mas mantem
# por compatibilidade com Mirror.
MENU_PROCESSES_SELECTOR = "text=Ações Judiciais"


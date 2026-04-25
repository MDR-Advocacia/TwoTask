const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const RUNNER_STATUS_PENDING = 'pending';
const RUNNER_STATUS_CANCELLED = 'cancelled';
const RUNNER_STATUS_ALREADY_CANCELLED = 'already_cancelled';
const RUNNER_STATUS_ERROR = 'error';

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const current = argv[index];
    if (!current.startsWith('--')) continue;
    const key = current.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    index += 1;
  }
  return args;
}

function requireEnvAny(names) {
  for (const name of names) {
    const value = process.env[name];
    if (value) {
      return value;
    }
  }
  throw new Error(`Missing required env var. Tried: ${names.join(', ')}`);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readJsonFile(filePath, fallback = null) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
    return JSON.parse(raw);
  } catch (error) {
    return fallback;
  }
}

function writeJsonFile(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

function normalizeSequenceNumber(value, fallback = 1) {
  const numeric = Number(value || fallback);
  return String(Number.isFinite(numeric) ? numeric : fallback).padStart(4, '0');
}

function sanitizeFileSegment(value) {
  const normalized = String(value ?? '')
    .normalize('NFKD')
    .replace(/[^\w.-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);
  return normalized || 'item';
}

function isRetryableError(error) {
  const text = String(error?.message || error || '').toLowerCase();
  return (
    text.includes('timeout') ||
    text.includes('navigation') ||
    text.includes('execution context was destroyed') ||
    text.includes('target page, context or browser has been closed') ||
    text.includes('401') ||
    text.includes('403') ||
    text.includes('unauthorized') ||
    text.includes('forbidden') ||
    text.includes('login') ||
    text.includes('signon')
  );
}

async function waitForPageSettle(page, delayMs = 0) {
  await page.waitForLoadState('domcontentloaded', { timeout: 120000 }).catch(() => {});
  if (delayMs > 0) {
    await page.waitForTimeout(delayMs);
  }
  await page.waitForLoadState('networkidle', { timeout: 45000 }).catch(() => {});
}

async function firstExistingSelector(page, selectors) {
  for (const selector of selectors) {
    const handle = await page.$(selector).catch(() => null);
    if (handle) {
      return selector;
    }
  }
  return null;
}

async function clickFirstAvailable(page, selectors) {
  const selector = await firstExistingSelector(page, selectors);
  if (!selector) {
    return false;
  }
  await page.click(selector, { timeout: 30000 });
  return true;
}

async function fillFirstAvailable(page, selectors, value) {
  const selector = await firstExistingSelector(page, selectors);
  if (!selector) {
    return false;
  }
  await page.fill(selector, value, { timeout: 30000 });
  return true;
}

async function completeKeySelectionIfPresent(page, keyLabel) {
  const body = await page.locator('body').innerText().catch(() => '');
  if (!body || (!/Selecione uma chave de registro/i.test(body) && !body.includes(keyLabel))) {
    return false;
  }

  await page.getByText(keyLabel, { exact: false }).first().click({ timeout: 30000 });
  await page.getByRole('button', { name: /Continuar/i }).click({ timeout: 30000 });
  return true;
}

async function login(page, { username, password, keyLabel, returnUrl }) {
  // Opening the destination page directly preserves the intended returnUrl
  // through the new Thomson Reuters + Novajus OnePass redirect chain.
  await page.goto(returnUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await waitForPageSettle(page, 4000);

  for (let attempt = 1; attempt <= 8; attempt += 1) {
    if (await completeKeySelectionIfPresent(page, keyLabel)) {
      await waitForPageSettle(page, 8000);
      continue;
    }

    if (await firstExistingSelector(page, ['#btn-login-onepass'])) {
      await clickFirstAvailable(page, ['#btn-login-onepass']);
      await waitForPageSettle(page, 4000);
      continue;
    }

    if (page.url().includes('/u/login/identifier')) {
      const filled = await fillFirstAvailable(
        page,
        ['input[name="username"]', 'input[name="email"]', 'input[type="email"]'],
        username,
      );
      if (filled) {
        await clickFirstAvailable(page, ['button[name="action"]', 'button[type="submit"]']);
        await waitForPageSettle(page, 4000);
        continue;
      }
    }

    if (page.url().includes('/u/login/password')) {
      const filled = await fillFirstAvailable(
        page,
        ['#password', 'input[name="password"]', '#Password'],
        password,
      );
      if (filled) {
        await clickFirstAvailable(page, ['button[name="action"]', 'button[type="submit"]', '#SignIn']);
        await waitForPageSettle(page, 6000);
        continue;
      }
    }

    if (
      (await firstExistingSelector(page, ['#Username'])) &&
      (await firstExistingSelector(page, ['#Password']))
    ) {
      const initialUrl = page.url();
      await page.fill('#Username', username, { timeout: 30000 });
      await page.locator('#Username').blur().catch(() => {});

      const redirected = await page
        .waitForURL((u) => u !== initialUrl, { timeout: 5000 })
        .then(() => true)
        .catch(() => false);

      if (redirected) {
        await waitForPageSettle(page, 4000);
        continue;
      }

      await page.fill('#Password', password, { timeout: 30000 });
      await page.click('#SignIn', { timeout: 30000 });
      await waitForPageSettle(page, 4000);
      continue;
    }

    const context = await capturePageContext(page);
    if (!isAuthenticationPage(context)) {
      return;
    }
  }

  const finalContext = await capturePageContext(page);
  if (isAuthenticationPage(finalContext)) {
    throw new Error(
      `Authentication flow did not finish | url=${finalContext.url} | title=${finalContext.title || ''} | body=${(finalContext.bodyStart || '').slice(0, 400)}`,
    );
  }
}

async function capturePageContext(page) {
  return page
    .evaluate(() => {
      const bodyText = document.body ? document.body.innerText || '' : '';
      return {
        url: window.location.href,
        title: document.title || '',
        bodyStart: bodyText.slice(0, 1500),
      };
    })
    .catch(() => ({
      url: page.url(),
      title: '',
      bodyStart: '',
    }));
}

function isAuthenticationPage(context) {
  const text = `${context.url}\n${context.title}\n${context.bodyStart}`.toLowerCase();
  return (
    text.includes('signon.thomsonreuters.com') ||
    text.includes('auth.thomsonreuters.com') ||
    text.includes('novajus.com.br/conta/login') ||
    text.includes('loginonepass') ||
    text.includes('onepass') ||
    text.includes('username') ||
    text.includes('password') ||
    text.includes('entrar') ||
    text.includes('autentica')
  );
}

async function writeDiagnosticArtifact(page, item, attemptNumber, artifactsDir, payload) {
  if (!artifactsDir) {
    return {};
  }

  fs.mkdirSync(artifactsDir, { recursive: true });
  const sequenceNumber = normalizeSequenceNumber(item.sequenceNumber || item.index);
  const baseName = `${sequenceNumber}-${sanitizeFileSegment(item.cnj || item.taskId)}-attempt-${attemptNumber}`;
  const jsonPath = path.join(artifactsDir, `${baseName}.json`);
  const screenshotPath = path.join(artifactsDir, `${baseName}.png`);

  const diagnostic = {
    capturedAt: new Date().toISOString(),
    item,
    attemptNumber,
    payload,
  };

  try {
    diagnostic.page = await capturePageContext(page);
  } catch (error) {
    diagnostic.pageError = error instanceof Error ? error.message : String(error);
  }

  try {
    if (page && !page.isClosed()) {
      await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 30000 });
      diagnostic.screenshotPath = screenshotPath;
    }
  } catch (error) {
    diagnostic.screenshotError = error instanceof Error ? error.message : String(error);
  }

  writeJsonFile(jsonPath, diagnostic);
  return {
    diagnosticJsonPath: jsonPath,
    diagnosticScreenshotPath: diagnostic.screenshotPath || null,
  };
}

async function createLoggedInSession(loginConfig) {
  const launchOptions = { headless: true };
  if (process.env.PLAYWRIGHT_CHANNEL) {
    launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
  }
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext();
  await context.route('**/*', (route) => {
    const resourceType = route.request().resourceType();
    if (resourceType === 'image' || resourceType === 'media' || resourceType === 'font') {
      return route.abort();
    }
    return route.continue();
  });

  const page = await context.newPage();
  await login(page, loginConfig);
  return { browser, context, page };
}

async function closeSession(session) {
  if (!session) return;
  await session.browser?.close().catch(() => {});
}

async function dismissCookieBanner(page) {
  // Banner Thomson Reuters intercepta cliques. Tenta fechar antes de
  // procurar o form. No-op se nao tiver o banner.
  try {
    for (const frame of page.frames()) {
      const accept = await frame
        .$('text=/Aceito esta pol[ií]tica/i')
        .catch(() => null);
      if (accept) {
        await accept.click({ timeout: 2000 }).catch(() => {});
        await page.waitForTimeout(250);
        return true;
      }
    }
  } catch (_) {}
  return false;
}

async function findFormInAnyFrame(page, selector) {
  // Novajus pode renderizar o conteudo da tela de edit dentro de um
  // iframe. page.$(selector) so olha o main frame; este helper busca
  // em main + todos os iframes.
  for (const frame of page.frames()) {
    try {
      const handle = await frame.$(selector);
      if (handle) return { frame, handle };
    } catch (_) {}
  }
  return null;
}

function describeFrames(page) {
  try {
    return page
      .frames()
      .map((f) => {
        try {
          return `${f.name() || '<root>'}:${(f.url() || '').slice(0, 120)}`;
        } catch (_) {
          return '<err>';
        }
      })
      .join(' || ');
  } catch (_) {
    return '<frames unreadable>';
  }
}

async function waitForTaskEditForm(page, editUrl, loginConfig) {
  let lastContext = null;
  // Action real do form Novajus eh "/processos/tarefas/Edit" (singular,
  // sem 'tarefa' no final, com querystring returnUrl). MAS o form nao
  // tem id nem name, e o action pode mudar com upgrades. O jeito mais
  // robusto: identificar o form pela presenca do hidden `#StatusId`
  // (campo do widget de lookup que so existe na tela de edit de tarefa).
  // CSS :has() funciona no Chromium recente do Playwright.
  const formSelector = 'form:has(#StatusId), form[action*="/processos/tarefas/Edit"], form[action*="/agenda/Tarefas/Edit"]';

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.goto(editUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
    await dismissCookieBanner(page);

    // 1) tentativa rapida no main frame
    const fastHandle = await page
      .waitForSelector(formSelector, { timeout: 5000 })
      .catch(() => null);
    if (fastHandle) {
      return { target: page, frame: page.mainFrame() };
    }

    // 2) aguarda networkidle e busca em qualquer frame (main + iframes)
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await dismissCookieBanner(page);
    let found = await findFormInAnyFrame(page, formSelector);
    if (found) {
      return { target: found.frame, frame: found.frame };
    }

    lastContext = await capturePageContext(page);
    if (isAuthenticationPage(lastContext)) {
      await login(page, loginConfig);
      continue;
    }

    // 3) ultima chance: espera mais um tico e tenta de novo
    await page.waitForTimeout(1500);
    found = await findFormInAnyFrame(page, formSelector);
    if (found) {
      return { target: found.frame, frame: found.frame };
    }
  }

  // Antes de falhar, faz inventario de TODOS os forms da pagina pra
  // descobrir o action real (nosso seletor pode estar desatualizado).
  let formInventory = '<no-forms>';
  try {
    const inventory = [];
    for (const frame of page.frames()) {
      const items = await frame
        .evaluate(() => {
          return Array.from(document.querySelectorAll('form')).map((f) => ({
            action: f.getAttribute('action') || '',
            method: f.getAttribute('method') || '',
            id: f.getAttribute('id') || '',
            name: f.getAttribute('name') || '',
            children: f.querySelectorAll('input, select, textarea, button').length,
          }));
        })
        .catch(() => []);
      for (const it of items) {
        inventory.push(
          `[${frame.name() || '<root>'}] action=${it.action} method=${it.method} id=${it.id} name=${it.name} fields=${it.children}`,
        );
      }
    }
    if (inventory.length) {
      formInventory = inventory.join(' || ');
    }
  } catch (_) {}

  throw new Error(
    `Task edit form not found | url=${lastContext?.url || editUrl} | title=${lastContext?.title || ''} | frames=${describeFrames(page)} | forms=${formInventory} | body=${(lastContext?.bodyStart || '').slice(0, 3000)}`,
  );
}

async function submitCancellation(page, item) {
  // 1) Le status atual via DOM (campo hidden #StatusId)
  const currentStatusId = await page
    .$eval('#StatusId', (el) => el.value)
    .catch(() => null);
  const currentStatusText = await page
    .$eval('#StatusText', (el) => el.value)
    .catch(() => '');

  if (currentStatusId !== null && String(currentStatusId) === String(item.targetStatusId)) {
    return {
      alreadyCancelled: true,
      currentStatusId,
      currentStatusText,
      verifiedStatusId: currentStatusId,
      verifiedStatusText: currentStatusText,
    };
  }

  // 2) Clica no widget de Status como um humano faria. O JS do widget
  // cuida de tudo: seta StatusId/StatusText, copia EnvolvidoId pra
  // EnvolvidoEfetivoId, dispara eventos. Zero patch manual de DOM.
  //   2a) Abre o dropdown via .lookup-show (NAO o icone (i) de info nem
  //       o lookup-filter que abre modal de busca).
  await page.click('#LookupStatusCompromissoTarefa .lookup-show', { timeout: 10000 });

  //   2b) O dropdown eh injetado no <body>, classe .lookup-dropdown.
  //       Clica na linha cuja data-val-id eh o targetStatusId.
  const targetRowSelector = `.lookup-dropdown tbody tr[data-val-id="${item.targetStatusId}"]`;
  await page.waitForSelector(targetRowSelector, { timeout: 8000 });
  await page.click(targetRowSelector, { timeout: 5000 });

  //   2c) Confirma que o hidden mudou — sanidade antes de submeter.
  await page.waitForFunction(
    (tgtId) => {
      const el = document.getElementById('StatusId');
      return el && String(el.value) === String(tgtId);
    },
    String(item.targetStatusId),
    { timeout: 5000 },
  );

  //   2d) Preenche os custom fields mandatorios (Sim/Não) com "Não".
  // Tasks de Workflow tem campos personalizados obrigatorios. Os hidden
  // `_Id` que aparecem com value (203881, 203883...) sao IDs do
  // CustomField (definicao), NAO do valor escolhido — por isso o server
  // ainda reclama "Campo obrigatorio".
  //
  // Pra popular `_Id` corretamente, o JS do widget jQuery UI autocomplete
  // precisa rodar:
  //   1. focus no `_Value`
  //   2. digita "Não" disparando input/keydown/keyup
  //   3. autocomplete abre (ul.ac_results)
  //   4. clica na opcao "Não" da lista (popula _Id)
  //   5. blur pra validar
  //
  // Filtramos por `.lookup-validation-error` — os mandatorios. O
  // "Produto" (opcional) nao tem essa classe.
  const customLookupIds = await page.evaluate(() => {
    return Array.from(
      document.querySelectorAll(
        '.lookup-validation-error[data-val-control="lookup"]',
      ),
    )
      .map((d) => d.id)
      .filter(Boolean);
  });
  for (const lookupId of customLookupIds) {
    try {
      // <id>_Lookup -> <id>_Value e <id>_Id
      const valueInputId = lookupId.replace(/_Lookup$/, '_Value');
      const valueSelector = `[id="${valueInputId}"]`;

      // 1) Focus + limpa qualquer texto que estiver
      await page.click(valueSelector, { timeout: 2000 });
      await page.fill(valueSelector, '');

      // 2) Digita "Não" devagar pra disparar keydown/keyup que aciona
      // o autocomplete jQuery UI.
      await page.type(valueSelector, 'Não', { delay: 60 });

      // 3) Espera ul.ac_results aparecer com a sugestao
      await page.waitForSelector('ul.ac_results:visible li', {
        timeout: 3000,
      });

      // 4) Clica na opcao "Não" — o JS do widget popula `_Id` aqui
      const naoSelector = 'ul.ac_results li:has-text("Não"), ul.ac_results li:has-text("Nao")';
      await page.click(naoSelector, { timeout: 2000 });

      // 5) Dispara blur explicito pra validar (caso o widget dependa)
      await page.evaluate((id) => {
        const el = document.getElementById(id);
        if (el) {
          el.dispatchEvent(new Event('change', { bubbles: true }));
          el.blur();
          el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
      }, valueInputId);

      await page.waitForTimeout(150);
    } catch (_) {
      // Lookup pode nao ter opcao "Não" — pula sem quebrar o fluxo.
    }
  }

  // 3) Aceita window.confirm/alert nativos (quem dispara o submit pode
  // pedir confirmacao via dialog nativo).
  const nativeDialogHandler = (dialog) => {
    dialog.accept().catch(() => {});
  };
  page.on('dialog', nativeDialogHandler);

  try {
    // 4) Click nativo no Salvar e fechar + waitForNavigation. O submit
    // do form gera um POST do navegador com TODOS os headers
    // (Origin/Referer/Cookies) que o servidor MVC do Novajus espera.
    //
    // ATENCAO: o botao "Salvar e fechar" eh um <button type="submit">
    // SEM atributo name. O `name="ButtonSave"` no form pertence a um
    // <input type="hidden">, nao ao botao. Identificamos o botao pelo
    // texto visivel, escopado pelo form que tem #StatusId, pra evitar
    // colisao com botoes "Salvar" de outros widgets/modais.
    const submitButtonSelector =
      'form:has(#StatusId) button[type="submit"]:has-text("Salvar e fechar")';

    // Handler do modal "Alerta" do Novajus (ex: "A data de Inicio... eh
    // anterior a data atual. Deseja salvar mesmo assim?") com botoes
    // Nao/Sim. Esse modal usa jQuery.alerts (lib antiga) — estrutura:
    //   <div id="popup_container">
    //     <h1 id="popup_title">Alerta</h1>
    //     <div id="popup_content">
    //       <div id="popup_message">...</div>
    //       <div id="popup_panel">
    //         <input type="button" id="popup_ok" value="Sim">
    //         <input type="button" id="popup_cancel" value="Nao">
    //       </div>
    //     </div>
    //   </div>
    // Seletor primario: `#popup_ok`. Os outros sao fallbacks defensivos.
    const alertModalSelectors = [
      // Modal jQuery.alerts do Novajus — id estavel
      '#popup_ok',
      // Fallbacks pra outros tipos de modal (defensivos)
      'div[role="dialog"] button:has-text("Sim")',
      'div[role="alertdialog"] button:has-text("Sim")',
      '.modal button:has-text("Sim")',
      '.ui-dialog-buttonpane button:has-text("Sim")',
      '.jconfirm .jconfirm-buttons button.btn-confirm',
      '.jconfirm .jconfirm-buttons button.btn-blue',
      'div[role="dialog"] button:has-text("OK")',
      'div[role="dialog"] button:has-text("Confirmar")',
    ];

    const watchAlertModal = async () => {
      // Patrulha por ate 8s detectando o modal aparecer e clicando "Sim"
      const deadline = Date.now() + 8000;
      while (Date.now() < deadline) {
        for (const sel of alertModalSelectors) {
          try {
            const handle = await page.$(sel);
            if (handle) {
              const visible = await handle.isVisible().catch(() => false);
              if (visible) {
                await handle.click({ timeout: 2000 }).catch(() => {});
                return true;
              }
            }
          } catch (_) {
            // proximo selector
          }
        }
        await page.waitForTimeout(150);
      }
      return false;
    };

    let navigationError = null;
    try {
      // Inicia patrulha do modal ANTES do click pra nao perder o
      // momento que ele aparece (pode ser muito rapido).
      const modalPromise = watchAlertModal();
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'load', timeout: 60000 }),
        page.click(submitButtonSelector, { timeout: 10000 }),
      ]);
      // Garante que a patrulha terminou (ja navegou — provavelmente nao
      // teve modal, ou foi clicado).
      await modalPromise.catch(() => false);
    } catch (err) {
      navigationError = err && err.message ? err.message : String(err);

      // Fallback: se o waitForNavigation expirou, tenta achar o modal
      // de novo (pode ter aparecido depois do timeout).
      const modalClicked = await watchAlertModal().catch(() => false);
      if (modalClicked) {
        try {
          await page.waitForNavigation({
            waitUntil: 'load',
            timeout: 30000,
          });
          navigationError = null;
        } catch (_) {
          // segue com erro original
        }
      }
    }

    // 5) Captura URL final do navegador + preview do conteudo que o
    // servidor retornou pos-submit. O finalUrl sozinho nao eh prova de
    // sucesso (pode redirecionar pra erro silencioso); usamos pra
    // diagnostico no log quando algo der errado.
    const finalUrl = page.url();
    const finalUrlLower = finalUrl.toLowerCase();
    const looksLikeSuccess =
      !finalUrlLower.includes('/tarefas/edit') &&
      !finalUrlLower.includes('createfromprocesso');

    // Captura erros + StatusId DIRETAMENTE na pagina pos-submit.
    // Quando o servidor recusa o save, re-renderiza o form na mesma
    // URL com .validation-summary-errors ou .field-validation-error
    // [data-valmsg-for] inline. Re-fetchar a editUrl depois falha em
    // capturar isso (URL muda de contexto). Tudo o que importa esta
    // na pagina ATUAL.
    const postPageInspection = await page
      .evaluate(() => {
        const title = document.title || '';
        const bodyText = (document.body?.innerText || '')
          .replace(/\s+/g, ' ')
          .trim();

        const validationSummary = Array.from(
          document.querySelectorAll('.validation-summary-errors li'),
        )
          .map((li) => (li.textContent || '').trim())
          .filter(Boolean);

        const formErrors = Array.from(
          document.querySelectorAll('span.field-validation-error[data-valmsg-for]'),
        )
          .map((el) => ({
            field: el.getAttribute('data-valmsg-for') || '',
            message: (el.textContent || '').trim(),
          }))
          .filter((e) => e.message && e.field);

        // Tenta ler o StatusId atual no form (se ainda existe).
        const liveStatusId =
          document.querySelector('#StatusId')?.value ||
          document.querySelector('[name="StatusId"]')?.value ||
          null;

        return {
          title,
          bodyPreview: bodyText.slice(0, 800),
          validationSummary,
          formErrors,
          liveStatusId,
        };
      })
      .catch(() => ({
        title: '',
        bodyPreview: '',
        validationSummary: [],
        formErrors: [],
        liveStatusId: null,
      }));

    const postPreview = `[title=${postPageInspection.title}] ${postPageInspection.bodyPreview}`;
    const postUrl = finalUrl;

    // 6) Verify confiavel: re-busca a edit URL via fetch (no contexto
    // logado da page) pra confirmar StatusId persistido = 3.
    const verify = await page.evaluate(async (currentItem) => {
      const normalizeText = (v) => String(v || '').replace(/\s+/g, ' ').trim();
      const textFromHtml = (html) => {
        const doc = new DOMParser().parseFromString(html, 'text/html');
        return doc.body ? doc.body.innerText || '' : '';
      };
      const collectFormMessages = (doc) => {
        const selectors = [
          '.validation-summary-errors li',
          '.validation-summary-errors',
          '.field-validation-error',
          '.alert-danger',
          '.alert-warning',
        ];
        const messages = [];
        for (const selector of selectors) {
          for (const node of doc.querySelectorAll(selector)) {
            const m = normalizeText(node.innerText || node.textContent || '');
            if (m && m.length > 2) messages.push(m);
          }
        }
        return [...new Set(messages)].slice(0, 12);
      };

      const verifyResponse = await fetch(currentItem.editUrl, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' },
      });
      const verifyHtml = await verifyResponse.text();
      const verifyDoc = new DOMParser().parseFromString(verifyHtml, 'text/html');
      const verifyMessages = collectFormMessages(verifyDoc);

      // Extrai pares (campo, mensagem) das `<span class="field-validation-error"
      // data-valmsg-for="<NAME>">` — diagnostico cirurgico em vez de "Campo
      // obrigatorio" repetido N vezes sem dizer qual campo.
      const formErrors = Array.from(
        verifyDoc.querySelectorAll('span.field-validation-error[data-valmsg-for]'),
      )
        .map((el) => ({
          field: el.getAttribute('data-valmsg-for') || '',
          message: (el.textContent || '').trim(),
        }))
        .filter((e) => e.message && e.field);

      // Mensagens de topo agregadas (`.validation-summary-errors li`).
      const validationSummary = Array.from(
        verifyDoc.querySelectorAll('.validation-summary-errors li'),
      )
        .map((li) => (li.textContent || '').trim())
        .filter(Boolean);

      const verifiedStatusId =
        verifyDoc.querySelector('#StatusId')?.value ||
        verifyDoc.querySelector('[name="StatusId"]')?.value ||
        null;
      const verifiedStatusText =
        verifyDoc.querySelector('#StatusText')?.value ||
        verifyDoc.querySelector('[name="StatusText"]')?.value ||
        '';

      const detailsResponse = await fetch(currentItem.detailsUrl, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' },
      });
      const detailsHtml = await detailsResponse.text();
      const detailsText = textFromHtml(detailsHtml);

      return {
        verifyStatus: verifyResponse.status,
        verifyMessages,
        formErrors,
        validationSummary,
        verifiedStatusId,
        verifiedStatusText,
        detailsStatus: detailsResponse.status,
        detailsHasTargetText: detailsText
          .toLowerCase()
          .includes(String(currentItem.targetStatusText || '').toLowerCase()),
        detailsPreview: detailsText.slice(0, 1500),
      };
    }, item);

    // Merge dos erros: prioriza os capturados na pagina ATUAL pos-submit
    // (quando o servidor recusa, ele re-renderiza la). Cai pra os do
    // verify (re-fetch da edit URL) como fallback.
    const mergedFormErrors =
      (postPageInspection.formErrors && postPageInspection.formErrors.length
        ? postPageInspection.formErrors
        : verify.formErrors) || [];
    const mergedValidationSummary =
      (postPageInspection.validationSummary && postPageInspection.validationSummary.length
        ? postPageInspection.validationSummary
        : verify.validationSummary) || [];
    // Se a pagina atual ainda tem #StatusId com o targetId, eh sucesso —
    // sobrescreve verifiedStatusId que pode ter vindo null do re-fetch.
    const liveMatchesTarget =
      postPageInspection.liveStatusId &&
      String(postPageInspection.liveStatusId) === String(item.targetStatusId);

    return {
      alreadyCancelled: false,
      navigationError,
      finalUrl,
      postUrl,
      postPreview,
      looksLikeSuccess,
      ...verify,
      // Sobrescreve com os erros/status da pagina atual (mais autoritativos).
      formErrors: mergedFormErrors,
      validationSummary: mergedValidationSummary,
      verifiedStatusId: liveMatchesTarget
        ? postPageInspection.liveStatusId
        : verify.verifiedStatusId,
      liveStatusIdAfterSubmit: postPageInspection.liveStatusId,
      postMessages: [],
    };
  } finally {
    try {
      page.off('dialog', nativeDialogHandler);
    } catch (_) {}
  }
}

async function cancelTask(session, item, loginConfig) {
  const editUrl = item.editUrl;
  // O form do edit esta sempre no main frame (verificado em prod). O
  // submitCancellation faz UI clicks e usa page.on('dialog') pra aceitar
  // popups nativos — ambos exigem a `Page`, nao um Frame. Por isso
  // passamos session.page direto.
  await waitForTaskEditForm(session.page, editUrl, loginConfig);
  const response = await submitCancellation(session.page, item);

  if (response.alreadyCancelled) {
    return {
      status: RUNNER_STATUS_ALREADY_CANCELLED,
      response,
    };
  }

  // Sucesso eh APENAS quando o re-fetch da editUrl retorna StatusId
  // igual ao target. Tentamos um fallback heuristico antes mas confirmou
  // falso-positivo em prod (submit redireciona mas task continua Pendente).
  if (String(response.verifiedStatusId) !== String(item.targetStatusId)) {
    const formErrorsDetail =
      response.formErrors && response.formErrors.length
        ? response.formErrors
            .map((e) => `${e.field}: ${e.message}`)
            .join(' | ')
        : null;
    // Inclui finalUrl + preview da pagina pos-submit pra diagnostico:
    // ajuda a entender se redirecionou pra erro/login/lista/etc.
    const diagnostic =
      `finalUrl=${response.finalUrl || '?'}` +
      ` looksLikeSuccess=${response.looksLikeSuccess}` +
      ` liveStatusIdAfterSubmit=${response.liveStatusIdAfterSubmit ?? 'null'}` +
      (response.postPreview
        ? ` postPreview="${String(response.postPreview).slice(0, 400).replace(/\s+/g, ' ')}"`
        : '');
    const errorDetail =
      formErrorsDetail ||
      response.validationSummary?.join(' | ') ||
      response.verifyMessages?.join(' | ') ||
      response.postMessages?.join(' | ') ||
      `Status verification failed for task ${item.taskId}: expected ${item.targetStatusId}, got ${response.verifiedStatusId} | ${diagnostic}`;
    throw new Error(errorDetail);
  }

  return {
    status: RUNNER_STATUS_CANCELLED,
    response,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = args.input;
  if (!inputPath) {
    throw new Error('Use --input <json>');
  }

  const items = readJsonFile(inputPath, []);
  if (!Array.isArray(items)) {
    throw new Error('Arquivo de entrada invalido.');
  }

  const username = requireEnvAny(['LEGALONE_WEB_USERNAME', 'LEGAL_ONE_WEB_USERNAME']);
  const password = requireEnvAny(['LEGALONE_WEB_PASSWORD', 'LEGAL_ONE_WEB_PASSWORD']);
  const keyLabel = requireEnvAny(['LEGALONE_WEB_KEY_LABEL', 'LEGAL_ONE_WEB_KEY_LABEL']);
  const maxAttempts = Math.max(1, Number(args['max-attempts'] || '2'));
  const outputPath =
    args.output || path.join(path.dirname(inputPath), `legacy-task-cancellation-${Date.now()}.json`);
  const artifactsDir = args['artifacts-dir'] || null;

  const loginConfig = {
    username,
    password,
    keyLabel,
    returnUrl: items[0]?.editUrl || 'https://mdradvocacia.novajus.com.br/home',
  };

  const resultsMap = new Map();
  const resultOrder = [];
  const upsertResult = (payload) => {
    const sequenceNumber = normalizeSequenceNumber(payload.sequenceNumber || payload.index, resultOrder.length + 1);
    const key = String(payload.taskId || sequenceNumber);
    const normalized = {
      ...payload,
      sequenceNumber,
    };
    if (!resultsMap.has(key)) {
      resultOrder.push(key);
    }
    resultsMap.set(key, normalized);
    return normalized;
  };

  for (const item of items) {
    upsertResult({
      ...item,
      status: RUNNER_STATUS_PENDING,
      attempts: 0,
      startedAt: null,
      finishedAt: null,
      error: null,
      response: null,
    });
  }

  const getResults = () => resultOrder.map((key) => resultsMap.get(key));
  const buildPayload = (state, extra = {}) => {
    const results = getResults();
    const successCount = results.filter((item) =>
      [RUNNER_STATUS_CANCELLED, RUNNER_STATUS_ALREADY_CANCELLED].includes(item.status),
    ).length;
    const failedCount = results.filter((item) => item.status === RUNNER_STATUS_ERROR).length;
    return {
      generatedAt: new Date().toISOString(),
      state,
      totalItems: items.length,
      processedItems: results.filter((item) => item.finishedAt).length,
      successCount,
      failedCount,
      remainingItems: Math.max(0, items.length - successCount - failedCount),
      maxAttempts,
      items: results,
      ...extra,
    };
  };
  const persistPayload = (state, extra = {}) => {
    writeJsonFile(outputPath, buildPayload(state, extra));
  };

  persistPayload('starting');
  let session = null;
  if (items.length > 0) {
    session = await createLoggedInSession(loginConfig);
  }

  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    let finalResult = null;

    for (let attemptNumber = 1; attemptNumber <= maxAttempts; attemptNumber += 1) {
      const startedAt = new Date().toISOString();

      try {
        finalResult = await cancelTask(session, item, loginConfig);
        finalResult.startedAt = startedAt;
        finalResult.finishedAt = new Date().toISOString();
        finalResult.attempts = attemptNumber;
        break;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        const diagnostics = await writeDiagnosticArtifact(session?.page, item, attemptNumber, artifactsDir, {
          error: message,
        });
        finalResult = {
          status: RUNNER_STATUS_ERROR,
          response: null,
          error: message,
          startedAt,
          finishedAt: new Date().toISOString(),
          attempts: attemptNumber,
          ...diagnostics,
        };

        if (attemptNumber < maxAttempts && isRetryableError(error)) {
          await closeSession(session);
          session = await createLoggedInSession(loginConfig);
          continue;
        }
        break;
      }
    }

    const result = upsertResult({
      ...item,
      status: finalResult.status,
      attempts: finalResult.attempts || 1,
      startedAt: finalResult.startedAt,
      finishedAt: finalResult.finishedAt,
      response: finalResult.response || null,
      error: finalResult.error || null,
      diagnosticJsonPath: finalResult.diagnosticJsonPath || null,
      diagnosticScreenshotPath: finalResult.diagnosticScreenshotPath || null,
    });
    persistPayload('running');
    console.log(JSON.stringify(result));
  }

  const finalPayload = buildPayload('running');
  persistPayload(finalPayload.failedCount > 0 ? 'failed' : 'completed');
  await closeSession(session);
}

main().catch((error) => {
  console.error(error);
  try {
    const args = parseArgs(process.argv.slice(2));
    if (args.output) {
      const payload = readJsonFile(args.output, {}) || {};
      payload.generatedAt = new Date().toISOString();
      payload.state = 'failed';
      payload.errorMessage = error instanceof Error ? error.message : String(error);
      writeJsonFile(args.output, payload);
    }
  } catch (persistError) {
    console.error('Failed to persist runner failure state:', persistError);
  }
  process.exitCode = 1;
});

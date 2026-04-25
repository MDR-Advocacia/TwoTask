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
  return page.evaluate(async (currentItem) => {
    const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const textFromHtml = (html) => {
      const doc = new DOMParser().parseFromString(html, 'text/html');
      return doc.body ? doc.body.innerText || '' : '';
    };

    const collectMessages = (doc, text) => {
      const selectors = [
        '.validation-summary-errors',
        '.field-validation-error',
        '.alert-danger',
        '.alert-warning',
        '.alert',
        '.message-error',
        '.message-warning',
        '.error-message',
        '.warning-message',
        '#msgErro',
        '#mensagemErro',
        '#mensagem',
      ];
      const messages = [];

      for (const selector of selectors) {
        for (const node of doc.querySelectorAll(selector)) {
          const message = normalizeText(node.innerText || node.textContent || '');
          if (message && message.length > 2) {
            messages.push(message);
          }
        }
      }

      if (!messages.length) {
        const patterns = [
          /nao[^.\n]{0,180}/ig,
          /erro[^.\n]{0,180}/ig,
          /obrigat[^\n.]{0,180}/ig,
          /invalid[^\n.]{0,180}/ig,
          /preencha[^.\n]{0,180}/ig,
          /campo[^.\n]{0,180}/ig,
        ];

        for (const pattern of patterns) {
          for (const match of text.matchAll(pattern)) {
            const snippet = normalizeText(match[0]);
            if (snippet && snippet.length > 2) {
              messages.push(snippet);
            }
          }
        }
      }

      return [...new Set(messages)].slice(0, 12);
    };

    // Identifica o form pela presenca do `#StatusId` (hidden do lookup
    // widget de status). Mais robusto que filtrar por action — a rota
    // real eh `/processos/tarefas/Edit`, mas isso pode mudar.
    let form = null;
    try {
      form = document.querySelector('form:has(#StatusId)');
    } catch (_) {
      // browser sem suporte a CSS :has — fallback manual
    }
    if (!form) {
      const statusIdInput = document.getElementById('StatusId');
      if (statusIdInput && statusIdInput.closest) {
        form = statusIdInput.closest('form');
      }
    }
    if (!form) {
      // ultimo fallback: action contem /tarefas/Edit (case-insensitive)
      form = Array.from(document.querySelectorAll('form')).find((candidate) => {
        const act = (candidate.getAttribute('action') || '').toLowerCase();
        return act.includes('/tarefas/edit') || act.includes('/agenda/tarefas/edit');
      });
    }
    if (!form) {
      throw new Error('Main task edit form not found');
    }

    const currentStatusId =
      form.querySelector('#StatusId')?.value ||
      form.querySelector('[name="StatusId"]')?.value ||
      null;
    const currentStatusText =
      form.querySelector('#StatusText')?.value ||
      form.querySelector('[name="StatusText"]')?.value ||
      '';

    if (String(currentStatusId) === String(currentItem.targetStatusId)) {
      return {
        alreadyCancelled: true,
        currentStatusId,
        currentStatusText,
        verifiedStatusId: currentStatusId,
        verifiedStatusText: currentStatusText,
      };
    }

    const params = new URLSearchParams();
    const elements = form.querySelectorAll('input, select, textarea, button');
    for (const element of elements) {
      const tag = element.tagName.toUpperCase();
      const type = (element.getAttribute('type') || '').toLowerCase();
      const name = element.getAttribute('name') || '';
      if (!name || element.disabled) continue;

      if (tag === 'BUTTON') {
        if (type === 'submit' && name === 'ButtonSave') {
          params.set(name, element.value || '0');
        }
        continue;
      }

      if ((type === 'checkbox' || type === 'radio') && !element.checked) {
        continue;
      }

      if (tag === 'SELECT' && element.multiple) {
        const selected = Array.from(element.options).filter((option) => option.selected);
        if (!selected.length) {
          params.append(name, '');
        } else {
          for (const option of selected) {
            params.append(name, option.value);
          }
        }
        continue;
      }

      params.append(name, element.value ?? '');
    }

    params.set('StatusId', String(currentItem.targetStatusId));
    params.set('StatusText', currentItem.targetStatusText);
    params.set('ButtonSave', '0');

    const actionUrl = new URL(form.getAttribute('action'), window.location.href).href;
    const postResponse = await fetch(actionUrl, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
      body: params.toString(),
    });
    const postHtml = await postResponse.text();
    const postDoc = new DOMParser().parseFromString(postHtml, 'text/html');
    const postText = textFromHtml(postHtml);
    const postMessages = collectMessages(postDoc, postText);

    const verifyResponse = await fetch(currentItem.editUrl, {
      method: 'GET',
      credentials: 'include',
      headers: { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' },
    });
    const verifyHtml = await verifyResponse.text();
    const verifyDoc = new DOMParser().parseFromString(verifyHtml, 'text/html');
    const verifyText = textFromHtml(verifyHtml);
    const verifyMessages = collectMessages(verifyDoc, verifyText);
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
      alreadyCancelled: false,
      postStatus: postResponse.status,
      postUrl: postResponse.url,
      postMessages,
      verifyStatus: verifyResponse.status,
      verifyMessages,
      verifiedStatusId,
      verifiedStatusText,
      detailsStatus: detailsResponse.status,
      detailsHasTargetText: detailsText.toLowerCase().includes(String(currentItem.targetStatusText || '').toLowerCase()),
      detailsPreview: detailsText.slice(0, 1500),
      postPreview: postText.slice(0, 1500),
    };
  }, item);
}

async function cancelTask(session, item, loginConfig) {
  const editUrl = item.editUrl;
  // waitForTaskEditForm devolve o frame (main ou iframe) onde o form foi
  // encontrado. submitCancellation roda evaluate nesse frame, nao na
  // session.page, pra garantir que `document` aponte pro form correto.
  const { target } = await waitForTaskEditForm(session.page, editUrl, loginConfig);
  const response = await submitCancellation(target, item);

  if (response.alreadyCancelled) {
    return {
      status: RUNNER_STATUS_ALREADY_CANCELLED,
      response,
    };
  }

  if (String(response.verifiedStatusId) !== String(item.targetStatusId)) {
    throw new Error(
      response.verifyMessages?.join(' | ') ||
      response.postMessages?.join(' | ') ||
      `Status verification failed for task ${item.taskId}: expected ${item.targetStatusId}, got ${response.verifiedStatusId}`,
    );
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

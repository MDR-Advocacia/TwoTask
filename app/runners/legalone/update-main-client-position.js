const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const current = argv[i];
    if (!current.startsWith('--')) continue;
    const key = current.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    i += 1;
  }
  return args;
}

function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return value;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readJsonFile(filePath) {
  const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
  return JSON.parse(raw);
}

function writeJsonFile(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
}

function loadSeedResults(seedPath) {
  if (!seedPath || !fs.existsSync(seedPath)) {
    return [];
  }
  const raw = readJsonFile(seedPath);
  if (Array.isArray(raw)) {
    return raw;
  }
  if (Array.isArray(raw.items)) {
    return raw.items;
  }
  return [];
}

function readControlSignal(controlFilePath) {
  if (!controlFilePath || !fs.existsSync(controlFilePath)) {
    return 'run';
  }
  const signal = fs.readFileSync(controlFilePath, 'utf8').trim().toLowerCase();
  if (!signal || signal === 'run' || signal === 'resume') {
    return 'run';
  }
  if (signal === 'pause') {
    return 'pause';
  }
  if (signal === 'stop') {
    return 'stop';
  }
  return 'run';
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

function isClosedContextErrorMessage(message) {
  return /Target page, context or browser has been closed/i.test(String(message || ''));
}

async function login(page, { username, password, keyLabel, returnUrl }) {
  const startUrl =
    `https://signon.thomsonreuters.com/?productId=L1NJ&returnto=https%3a%2f%2flogin.novajus.com.br%2fOnePass%2fLoginOnePass%2f%3freturnUrl%3d${encodeURIComponent(returnUrl)}&bhcp=1`;

  await page.goto(startUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.fill('#Username', username);
  await page.fill('#Password', password);
  await page.click('#SignIn');
  await page.waitForLoadState('domcontentloaded', { timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(7000);

  const body = await page.locator('body').innerText().catch(() => '');
  if (/Selecione uma chave de registro/i.test(body) || body.includes(keyLabel)) {
    await page.getByText(keyLabel, { exact: false }).first().click({ timeout: 30000 });
    await page.getByRole('button', { name: /Continuar/i }).click({ timeout: 30000 });
  }

  await page.waitForLoadState('domcontentloaded', { timeout: 120000 }).catch(() => {});
  await page.waitForTimeout(12000);
  await page.waitForLoadState('networkidle', { timeout: 45000 }).catch(() => {});
  await page.goto(returnUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await page.waitForTimeout(5000);
  await page.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
}

async function capturePageContext(page) {
  return page.evaluate(() => {
    const bodyText = document.body ? (document.body.innerText || '') : '';
    const title = document.title || '';
    return {
      url: window.location.href,
      title,
      hasForm: !!document.querySelector('#lawsuit-edit-form'),
      bodyStart: bodyText.slice(0, 1500),
    };
  }).catch(() => ({
    url: page.url(),
    title: '',
    hasForm: false,
    bodyStart: '',
  }));
}

async function captureDiagnosticArtifacts(page, item, attemptNumber, artifactsDir, rawStatus, details = {}) {
  if (!artifactsDir) {
    return {};
  }

  fs.mkdirSync(artifactsDir, { recursive: true });
  const sequenceNumber = String(item.sequenceNumber || item.seq).padStart(4, '0');
  const baseName =
    `${sequenceNumber}-${sanitizeFileSegment(item.cnj)}-attempt-${attemptNumber}-${sanitizeFileSegment(rawStatus)}`;
  const jsonPath = path.join(artifactsDir, `${baseName}.json`);
  const screenshotPath = path.join(artifactsDir, `${baseName}.png`);

  const payload = {
    capturedAt: new Date().toISOString(),
    sequenceNumber,
    cnj: item.cnj,
    lawsuitId: item.lawsuitId,
    attemptNumber,
    rawStatus,
    ...details,
  };

  try {
    payload.page = await capturePageContext(page);
  } catch (error) {
    payload.pageCaptureError = error instanceof Error ? error.message : String(error);
  }

  try {
    if (page && !page.isClosed()) {
      await page.screenshot({ path: screenshotPath, fullPage: true, timeout: 30000 });
      payload.screenshotPath = screenshotPath;
    }
  } catch (error) {
    payload.screenshotError = error instanceof Error ? error.message : String(error);
  }

  writeJsonFile(jsonPath, payload);

  return {
    diagnosticJsonPath: jsonPath,
    diagnosticScreenshotPath: payload.screenshotPath || null,
    diagnosticPageUrl: payload.page?.url || null,
    diagnosticPageTitle: payload.page?.title || null,
    diagnosticCaptureError: payload.pageCaptureError || payload.screenshotError || null,
  };
}

async function createLoggedInSession(loginConfig) {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
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
  if (!session) {
    return;
  }
  await session.browser?.close().catch(() => {});
}

function isAuthenticationPage(context) {
  const text = `${context.url}\n${context.title}\n${context.bodyStart}`.toLowerCase();
  return (
    text.includes('signon.thomsonreuters.com') ||
    text.includes('loginonepass') ||
    text.includes('username') ||
    text.includes('password') ||
    text.includes('entrar') ||
    text.includes('autentica')
  );
}

async function waitForEditForm(page, editUrl, loginConfig) {
  let lastContext = null;

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.goto(editUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
    const fastFormHandle = await page.waitForSelector('#lawsuit-edit-form', { timeout: 5000 }).catch(() => null);
    if (fastFormHandle) {
      return;
    }

    await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
    const settledFormHandle = await page.$('#lawsuit-edit-form');
    if (settledFormHandle) {
      return;
    }

    lastContext = await capturePageContext(page);
    if (isAuthenticationPage(lastContext)) {
      await login(page, loginConfig);
      continue;
    }

    await page.waitForTimeout(1500);
    const lateForm = await page.$('#lawsuit-edit-form');
    if (lateForm) {
      return;
    }
  }

  throw new Error(
    `Edit form not found | url=${lastContext?.url || editUrl} | title=${lastContext?.title || ''} | body=${(lastContext?.bodyStart || '').slice(0, 400)}`,
  );
}

async function submitEdit(page, item, config) {
  const editUrl = `https://mdradvocacia.novajus.com.br/processos/Processos/edit/${item.lawsuitId}`;
  const detailsUrl = `https://mdradvocacia.novajus.com.br/processos/Processos/details/${item.lawsuitId}`;

  return page.evaluate(
    async ({ detailsUrl: verifyUrl, item: current, config: currentConfig }) => {
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
          '.toast-error',
          '.toast-message',
          '.formError',
          '.error',
          '.warning',
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
            /n[aã]o[^.\n]{0,180}/ig,
            /erro[^.\n]{0,180}/ig,
            /obrigat[^\n.]{0,180}/ig,
            /inv[aá]lid[^\n.]{0,180}/ig,
            /preencha[^.\n]{0,180}/ig,
            /campo[^.\n]{0,180}/ig,
            /cliente[^.\n]{0,180}/ig,
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

      const buildParams = (doc) => {
        const form = doc.querySelector('#lawsuit-edit-form');
        if (!form) {
          throw new Error('Edit form not found');
        }
        const params = new URLSearchParams();
        const elements = form.querySelectorAll('input, select, textarea');
        for (const element of elements) {
          if (!element.name || element.disabled) continue;
          const tag = element.tagName.toUpperCase();
          const type = (element.getAttribute('type') || '').toLowerCase();
          if ((type === 'checkbox' || type === 'radio') && !element.checked) {
            continue;
          }
          if (tag === 'SELECT' && element.multiple) {
            const selected = Array.from(element.options).filter((option) => option.selected);
            if (!selected.length) {
              params.append(element.name, '');
            } else {
              for (const option of selected) {
                params.append(element.name, option.value);
              }
            }
            continue;
          }
          params.append(element.name, element.value ?? '');
        }
        const currentPositionField = form.querySelector('[name="Cliente.PosicaoEnvolvidoId"]');
        return {
          form,
          params,
          originalPositionId: currentPositionField ? currentPositionField.value ?? null : null,
        };
      };

      const { form, params, originalPositionId } = buildParams(document);

      params.set('Cliente.PosicaoEnvolvidoId', String(currentConfig.targetPositionId));
      params.set('Cliente.PosicaoEnvolvidoText', currentConfig.targetPositionText);
      params.set('DataDeTerceirizacaoRecebimento_ProcessoEntitySchema_p3691_o', currentConfig.terceirizacaoDate);
      params.set('NumeroDoCliente_ProcessoEntitySchema_p3687_o', current.sequenceNumber);
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
      const postPositionField = postDoc.querySelector('[name="Cliente.PosicaoEnvolvidoId"]');

      const detailsResponse = await fetch(verifyUrl, {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' },
      });
      const detailsHtml = await detailsResponse.text();
      const detailsText = textFromHtml(detailsHtml);
      const detailsDoc = new DOMParser().parseFromString(detailsHtml, 'text/html');
      const detailsMessages = collectMessages(detailsDoc, detailsText);

      const hasSuccessMessage = /alterado com sucesso/i.test(postHtml);
      const positionChanged = /Posição do cliente\s*Réu/i.test(detailsText);
      const clientLineMatch = detailsText.match(/Cliente principal[\s\S]{0,120}/i);
      const positionLineMatch = detailsText.match(/Posição do cliente[\s\S]{0,80}/i);

      return {
        cnj: current.cnj,
        lawsuitId: current.lawsuitId,
        sequenceNumber: current.sequenceNumber,
        postStatus: postResponse.status,
        postUrl: postResponse.url,
        postTitle: postDoc.title || null,
        postHasForm: !!postDoc.querySelector('#lawsuit-edit-form'),
        originalPositionId,
        targetPositionId: String(currentConfig.targetPositionId),
        postPositionId: postPositionField ? postPositionField.value ?? null : null,
        postMessages,
        detailsStatus: detailsResponse.status,
        detailsMessages,
        hasSuccessMessage,
        positionChanged,
        positionSnippet: positionLineMatch ? positionLineMatch[0] : null,
        clientSnippet: clientLineMatch ? clientLineMatch[0] : null,
        postErrorPreview: postText.slice(0, 1000),
      };
    },
    { detailsUrl, item, config },
  );
}

async function submitEditWithRetries(page, item, config, loginConfig) {
  const editUrl = `https://mdradvocacia.novajus.com.br/processos/Processos/edit/${item.lawsuitId}`;
  let lastError = null;

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      await waitForEditForm(page, editUrl, loginConfig);
      return await submitEdit(page, item, config);
    } catch (error) {
      lastError = error;
      const message = error instanceof Error ? error.message : String(error);
      const retryable =
        /Edit form not found|Failed to fetch|Execution context was destroyed|Navigation|Timeout/i.test(message);

      if (!retryable || attempt === 3) {
        break;
      }

      await sleep(2000 * attempt);
      await login(page, loginConfig).catch(() => {});
    }
  }

  throw lastError;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = args.input;
  if (!inputPath) {
    throw new Error('Use --input <json>');
  }

  const username = requireEnv('LEGALONE_WEB_USERNAME');
  const password = requireEnv('LEGALONE_WEB_PASSWORD');
  const keyLabel = process.env.LEGALONE_WEB_KEY_LABEL || 'MDR Advocacia (NJU69907701)';
  const terceirizacaoDate = process.env.LEGALONE_TERCEIRIZACAO_DATE || '27/03/2026';
  const targetPositionId = Number(process.env.LEGALONE_TARGET_POSITION_ID || '2');
  const targetPositionText = process.env.LEGALONE_TARGET_POSITION_TEXT || 'Réu';
  const limit = args.limit ? Number(args.limit) : null;
  const batchSize = Math.max(1, Number(args['batch-size'] || '10'));
  const maxAttempts = Math.max(1, Number(args['max-attempts'] || '3'));
  const pauseBetweenBatchesSeconds = Math.max(0, Number(args['pause-between-batches-seconds'] || '20'));
  const pauseBetweenBatchesMs = pauseBetweenBatchesSeconds * 1000;
  const seedResultsPath = args['seed-results'] || null;
  const artifactsDir = args['artifacts-dir'] || null;
  const offset = args.offset ? Number(args.offset) : 0;
  const outputPath =
    args.output ||
    path.join(path.dirname(inputPath), `results-${Date.now()}.json`);
  const controlFilePath =
    args['control-file'] ||
    path.join(path.dirname(outputPath), 'position-fix.control');

  const normalizeSequenceNumber = (value) => String(value).padStart(4, '0');
  const isRetryableStatus = (status) => status === 'error' || status === 'verify_failed';
  const dedupeBySequence = (entries) => {
    const map = new Map();
    for (const entry of entries) {
      const sequenceNumber = normalizeSequenceNumber(entry.sequenceNumber || entry.seq);
      const attemptNumber = Number(entry.attemptNumber || entry.attempts || 1);
      const normalized = {
        ...entry,
        sequenceNumber,
        attemptNumber,
      };
      const existing = map.get(sequenceNumber);
      if (!existing || attemptNumber >= existing.attemptNumber) {
        map.set(sequenceNumber, normalized);
      }
    }
    return [...map.entries()]
      .sort((a, b) => Number(a[0]) - Number(b[0]))
      .map(([, value]) => value);
  };

  const rawItems = readJsonFile(inputPath);
  const seededResults = dedupeBySequence(loadSeedResults(seedResultsPath)).map((item) => ({
    ...item,
    sequenceNumber: normalizeSequenceNumber(item.sequenceNumber || item.seq),
    attempts: Number(item.attempts || 1),
  }));
  const items = rawItems
    .slice(offset, limit ? offset + limit : undefined)
    .map((item, index) => ({
      ...item,
      sequenceNumber: normalizeSequenceNumber(item.seq || offset + index + 1),
      attemptNumber: 1,
    }));
  const totalItems = seededResults.length + items.length;
  const totalBatches = Math.max(1, Math.ceil(items.length / batchSize));
  const retrySeedItems = dedupeBySequence(
    seededResults
      .filter((item) => (item.retryPending || isRetryableStatus(item.status)) && Number(item.attempts || 1) < maxAttempts)
      .map((item) => ({
        cnj: item.cnj,
        lawsuitId: item.lawsuitId,
        seq: Number(item.sequenceNumber),
        sequenceNumber: normalizeSequenceNumber(item.sequenceNumber),
        attemptNumber: Number(item.attempts || 1) + 1,
      })),
  );

  const loginConfig = {
    username,
    password,
    keyLabel,
    returnUrl: 'https://mdradvocacia.novajus.com.br/home',
  };
  let session = await createLoggedInSession(loginConfig);

  const resultsMap = new Map();
  const resultOrder = [];
  const upsertResult = (result) => {
    const sequenceNumber = normalizeSequenceNumber(result.sequenceNumber || result.seq);
    if (!resultsMap.has(sequenceNumber)) {
      resultOrder.push(sequenceNumber);
    }
    const normalized = {
      ...result,
      sequenceNumber,
    };
    resultsMap.set(sequenceNumber, normalized);
    return normalized;
  };
  const getResults = () => resultOrder.map((sequenceNumber) => resultsMap.get(sequenceNumber));
  for (const item of seededResults) {
    upsertResult(item);
  }

  let activeQueueType = 'primary';
  let activeQueueProcessed = 0;
  let activeQueueTotal = items.length;
  let retryPass = 0;
  const buildPayload = (state, extra = {}) => {
    const results = getResults();
    const updatedCount = results.filter((item) => item.status === 'updated').length;
    const failedCount = results.filter((item) => item.status === 'error' || item.status === 'verify_failed').length;
    const retryPendingCount = results.filter((item) => item.status === 'scheduled_retry' || item.retryPending).length;
    return {
      generatedAt: new Date().toISOString(),
      state,
      batchSize,
      totalBatches,
      currentBatch: activeQueueTotal
        ? Math.min(Math.max(1, Math.ceil(activeQueueTotal / batchSize)), Math.floor(activeQueueProcessed / batchSize) + 1)
        : 1,
      controlFile: controlFilePath,
      totalItems,
      processedItems: results.length,
      updatedCount,
      failedCount,
      retryPendingCount,
      remainingItems: Math.max(0, totalItems - updatedCount - failedCount),
      activeQueueType,
      retryPass,
      maxAttempts,
      items: results,
      ...extra,
    };
  };
  const persistPayload = (state, extra = {}) => {
    fs.writeFileSync(outputPath, JSON.stringify(buildPayload(state, extra), null, 2));
  };
  const waitForRunSignal = async () => {
    while (true) {
      const signal = readControlSignal(controlFilePath);
      if (signal === 'stop') {
        persistPayload('stopped');
        return 'stop';
      }
      if (signal === 'pause') {
        persistPayload('paused');
        await sleep(2000);
        continue;
      }
      return 'run';
    }
  };
  const waitBetweenBatches = async () => {
    if (!pauseBetweenBatchesMs) {
      return 'run';
    }
    let remainingMs = pauseBetweenBatchesMs;
    while (remainingMs > 0) {
      const signal = readControlSignal(controlFilePath);
      if (signal === 'stop') {
        persistPayload('stopped');
        return 'stop';
      }
      if (signal === 'pause') {
        persistPayload('paused');
        await sleep(2000);
        continue;
      }
      const sleepWindow = Math.min(1000, remainingMs);
      persistPayload('sleeping', { sleepUntil: new Date(Date.now() + remainingMs).toISOString() });
      await sleep(sleepWindow);
      remainingMs -= sleepWindow;
    }
    return 'run';
  };

  persistPayload('running');

  let pendingItems = items;
  let deferredRetryItems = [...retrySeedItems];
  let stopRequested = false;

  while (pendingItems.length || deferredRetryItems.length) {
    if (!pendingItems.length) {
      pendingItems = dedupeBySequence(deferredRetryItems);
      deferredRetryItems = [];
      if (!pendingItems.length) {
        break;
      }
      activeQueueType = 'retry';
      retryPass += 1;
      activeQueueProcessed = 0;
      activeQueueTotal = pendingItems.length;
      persistPayload('running');
    }

    for (let index = 0; index < pendingItems.length; index += 1) {
      const signal = await waitForRunSignal();
      if (signal === 'stop') {
        stopRequested = true;
        break;
      }

      const item = pendingItems[index];
      const attemptNumber = Number(item.attemptNumber || 1);
      const startedAt = new Date().toISOString();
      let rawResult;
      let rawStatus;
      let restartSessionAfterItem = false;
      try {
        rawResult = await submitEditWithRetries(session.page, item, {
          terceirizacaoDate,
          targetPositionId,
          targetPositionText,
        }, loginConfig);
        rawStatus = rawResult.hasSuccessMessage && rawResult.positionChanged ? 'updated' : 'verify_failed';
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        rawResult = {
          cnj: item.cnj,
          lawsuitId: item.lawsuitId,
          sequenceNumber: item.sequenceNumber,
          error: errorMessage,
        };
        rawStatus = 'error';
        restartSessionAfterItem = isClosedContextErrorMessage(errorMessage);
      }

      const diagnosticArtifacts = rawStatus === 'updated'
        ? {}
        : await captureDiagnosticArtifacts(
          session?.page,
          item,
          attemptNumber,
          artifactsDir,
          rawStatus,
          {
            result: rawResult,
          },
        );
      const shouldRetry = isRetryableStatus(rawStatus) && attemptNumber < maxAttempts;
      const result = upsertResult({
        ...rawResult,
        ...diagnosticArtifacts,
        cnj: rawResult.cnj || item.cnj,
        lawsuitId: rawResult.lawsuitId || item.lawsuitId,
        sequenceNumber: item.sequenceNumber,
        status: shouldRetry ? 'scheduled_retry' : rawStatus,
        finalStatus: rawStatus,
        error: rawResult.error || null,
        retryPending: shouldRetry,
        nextAttemptNumber: shouldRetry ? attemptNumber + 1 : null,
        attempts: attemptNumber,
        maxAttempts,
        index: Number(item.sequenceNumber),
        startedAt,
        finishedAt: new Date().toISOString(),
      });

      if (shouldRetry) {
        deferredRetryItems.push({
          cnj: item.cnj,
          lawsuitId: item.lawsuitId,
          seq: Number(item.sequenceNumber),
          sequenceNumber: item.sequenceNumber,
          attemptNumber: attemptNumber + 1,
        });
      }

      activeQueueProcessed += 1;
      persistPayload('running');
      console.log(JSON.stringify(result));

      if (restartSessionAfterItem) {
        try {
          await closeSession(session);
          session = await createLoggedInSession(loginConfig);
        } catch (error) {
          console.error(`Falha ao recriar sessao apos fechamento inesperado: ${error instanceof Error ? error.message : String(error)}`);
          stopRequested = true;
          break;
        }
      }

      const isBatchBoundary = (index + 1) % batchSize === 0;
      const hasMoreItems = index + 1 < pendingItems.length;
      if (isBatchBoundary && hasMoreItems) {
        const batchSignal = await waitBetweenBatches();
        if (batchSignal === 'stop') {
          stopRequested = true;
          break;
        }
      }
    }

    if (stopRequested) {
      break;
    }

    pendingItems = [];
  }

  const finalPayload = buildPayload('running');
  const remainingItems = finalPayload.remainingItems;
  persistPayload(remainingItems > 0 ? 'stopped' : 'completed');
  await closeSession(session);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

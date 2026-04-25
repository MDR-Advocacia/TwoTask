const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const STATUS_UPLOADED = 'uploaded';
const STATUS_ERROR = 'error';
const ALLOWED_EXTENSIONS = new Set([
  'doc',
  'docx',
  'xls',
  'xlsx',
  'ppt',
  'pptx',
  'pdf',
  'png',
  'jpg',
  'jpeg',
  'bmp',
  'gif',
  'txt',
  'rtf',
  'eml',
  'msg',
  'zip',
  'rar',
  '7z',
  'html',
  'htm',
]);

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
    if (value) return value;
  }
  throw new Error(`Missing required env var. Tried: ${names.join(', ')}`);
}

function readJsonFile(filePath, fallback = null) {
  try {
    const raw = fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '');
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

function writeJsonFile(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(payload, null, 2));
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

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeDisplayName(value) {
  const parsed = path.parse(String(value || 'habilitacao.pdf'));
  const extension = parsed.ext || '.pdf';
  const stem = (parsed.name || 'habilitacao')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^\w.-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 120);
  return `${stem || 'habilitacao'}${extension.toLowerCase()}`;
}

function todayBrDate(timeZone = 'America/Fortaleza') {
  return new Intl.DateTimeFormat('pt-BR', {
    timeZone,
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(new Date());
}

async function waitForPageSettle(page, delayMs = 0) {
  await page.waitForLoadState('domcontentloaded', { timeout: 120000 }).catch(() => {});
  if (delayMs > 0) await page.waitForTimeout(delayMs);
  await page.waitForLoadState('networkidle', { timeout: 45000 }).catch(() => {});
}

async function firstExistingSelector(page, selectors) {
  for (const selector of selectors) {
    const handle = await page.$(selector).catch(() => null);
    if (handle) return selector;
  }
  return null;
}

async function clickFirstAvailable(page, selectors) {
  const selector = await firstExistingSelector(page, selectors);
  if (!selector) return false;
  await page.click(selector, { timeout: 30000 });
  return true;
}

async function fillFirstAvailable(page, selectors, value) {
  const selector = await firstExistingSelector(page, selectors);
  if (!selector) return false;
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

async function capturePageContext(page) {
  return page
    .evaluate(() => {
      const bodyText = document.body ? document.body.innerText || '' : '';
      return {
        url: window.location.href,
        title: document.title || '',
        bodyStart: bodyText.slice(0, 2500),
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

async function login(page, { username, password, keyLabel, returnUrl }) {
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
    if (!isAuthenticationPage(context)) return;
  }

  const finalContext = await capturePageContext(page);
  if (isAuthenticationPage(finalContext)) {
    throw new Error(
      `Authentication flow did not finish | url=${finalContext.url} | title=${finalContext.title || ''} | body=${(finalContext.bodyStart || '').slice(0, 400)}`,
    );
  }
}

async function writeDiagnosticArtifact(page, item, artifactsDir, payload) {
  if (!artifactsDir) return {};

  fs.mkdirSync(artifactsDir, { recursive: true });
  const baseName = `${sanitizeFileSegment(item.cnj || item.lawsuitId)}-${Date.now()}`;
  const jsonPath = path.join(artifactsDir, `${baseName}.json`);
  const screenshotPath = path.join(artifactsDir, `${baseName}.png`);
  const diagnostic = {
    capturedAt: new Date().toISOString(),
    item: { ...item, pdfPath: item.pdfPath },
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
  if (process.env.PLAYWRIGHT_CHANNEL) launchOptions.channel = process.env.PLAYWRIGHT_CHANNEL;
  const browser = await chromium.launch(launchOptions);
  const context = await browser.newContext({
    acceptDownloads: true,
    viewport: { width: 1440, height: 900 },
  });
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

async function clickByText(page, pattern, options = {}) {
  const locators = [
    page.getByRole('link', { name: pattern }),
    page.getByRole('button', { name: pattern }),
    page.getByText(pattern).first(),
  ];
  for (const locator of locators) {
    const count = await locator.count().catch(() => 0);
    if (!count) continue;
    await locator.first().click({ timeout: options.timeout || 12000 }).catch(() => null);
    await waitForPageSettle(page, options.delayMs || 1200);
    return true;
  }
  return false;
}

async function openLawsuit(page, item, webBaseUrl, loginConfig) {
  const detailsUrl = `${webBaseUrl}/processos/Processos/details/${item.lawsuitId}`;
  await page.goto(detailsUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await waitForPageSettle(page, 5000);

  let context = await capturePageContext(page);
  if (isAuthenticationPage(context)) {
    await login(page, { ...loginConfig, returnUrl: detailsUrl });
    await waitForPageSettle(page, 3000);
    context = await capturePageContext(page);
  }

  const body = context.bodyStart || '';
  const hasCnj = item.cnj && body.replace(/\D/g, '').includes(String(item.cnj).replace(/\D/g, ''));
  const looksLikeLawsuit = /processo|pasta|partes|andamentos|publica/i.test(body);
  if (!hasCnj && !looksLikeLawsuit) {
    throw new Error(
      `Tela do processo nao reconhecida | url=${context.url} | title=${context.title} | body=${body.slice(0, 500)}`,
    );
  }

  return detailsUrl;
}

async function discoverUploadArea(page) {
  const candidates = [
    /Documentos/i,
    /\bGED\b/i,
    /Arquivos/i,
    /Anexos/i,
    /Pasta digital/i,
  ];
  for (const pattern of candidates) {
    if (await clickByText(page, pattern)) return pattern.toString();
  }

  const clicked = await page.evaluate(() => {
    const links = Array.from(document.querySelectorAll('a,button'));
    const candidate = links.find((node) => {
      const text = `${node.innerText || ''} ${node.textContent || ''} ${node.getAttribute('href') || ''}`;
      return /document|ged|arquivo|anexo/i.test(text);
    });
    if (!candidate) return null;
    candidate.click();
    return (candidate.innerText || candidate.textContent || candidate.getAttribute('href') || '').trim();
  });
  if (clicked) {
    await waitForPageSettle(page, 2000);
    return clicked;
  }

  return null;
}

async function triggerNewDocumentFlow(page) {
  const patterns = [
    /Novo documento/i,
    /Adicionar documento/i,
    /Incluir documento/i,
    /Anexar documento/i,
    /Upload/i,
    /Enviar arquivo/i,
    /Adicionar/i,
    /Novo/i,
  ];
  for (const pattern of patterns) {
    if (await clickByText(page, pattern, { timeout: 7000, delayMs: 1500 })) return pattern.toString();
  }
  return null;
}

async function setFirstFileInput(page, filePath) {
  const input = await page.$('input[type="file"]').catch(() => null);
  if (!input) return false;
  await input.setInputFiles(filePath);
  await page.waitForTimeout(1500);
  return true;
}

async function fillUploadMetadata(page, item) {
  const archive = item.archive || path.basename(item.pdfPath);
  const description = item.description || archive;

  const filled = await page.evaluate(
    ({ archive: archiveValue, description: descriptionValue, typeId }) => {
      const normalize = (value) => String(value || '').toLowerCase();
      const setValue = (element, value) => {
        element.focus();
        element.value = value;
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
      };

      const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]), textarea'));
      const result = { archive: false, description: false, typeId: false };

      for (const input of inputs) {
        const label = normalize(
          `${input.name || ''} ${input.id || ''} ${input.placeholder || ''} ${input.getAttribute('aria-label') || ''}`,
        );
        if (!result.archive && /arquivo|archive|nome|titulo|título|documento/.test(label)) {
          setValue(input, archiveValue);
          result.archive = true;
          continue;
        }
        if (!result.description && /descri|observa|nota|notes|description/.test(label)) {
          setValue(input, descriptionValue);
          result.description = true;
        }
      }

      const selects = Array.from(document.querySelectorAll('select'));
      for (const select of selects) {
        const label = normalize(`${select.name || ''} ${select.id || ''} ${select.getAttribute('aria-label') || ''}`);
        if (!/tipo|type|document/.test(label)) continue;
        const exact = Array.from(select.options).find((option) => String(option.value) === String(typeId));
        const habilitacao = Array.from(select.options).find((option) => /habilita/i.test(option.textContent || ''));
        const chosen = exact || habilitacao;
        if (chosen) {
          select.value = chosen.value;
          select.dispatchEvent(new Event('change', { bubbles: true }));
          result.typeId = true;
          break;
        }
      }

      return result;
    },
    { archive, description, typeId: item.typeId },
  );

  await page.waitForTimeout(1000);
  return filled;
}

async function submitUpload(page) {
  const patterns = [/Salvar/i, /Gravar/i, /Enviar/i, /Concluir/i, /Confirmar/i, /Upload/i];
  for (const pattern of patterns) {
    if (await clickByText(page, pattern, { timeout: 7000, delayMs: 3000 })) return pattern.toString();
  }
  return null;
}

async function verifyUpload(page, item, detailsUrl) {
  const filename = path.basename(item.archive || item.pdfPath || '');
  const normalizedFilename = filename.normalize('NFKD').replace(/[^\w.-]+/g, '.*');
  const patterns = [
    filename ? new RegExp(normalizedFilename, 'i') : null,
    /Habilita/i,
    item.cnj ? new RegExp(String(item.cnj).replace(/\D/g, '').slice(-8)) : null,
  ].filter(Boolean);

  await waitForPageSettle(page, 3000);
  let context = await capturePageContext(page);
  let text = context.bodyStart || '';

  if (!patterns.some((pattern) => pattern.test(text))) {
    await page.goto(detailsUrl, { waitUntil: 'domcontentloaded', timeout: 120000 }).catch(() => {});
    await waitForPageSettle(page, 3000);
    await discoverUploadArea(page).catch(() => null);
    context = await capturePageContext(page);
    text = context.bodyStart || '';
  }

  const matched = patterns.find((pattern) => pattern.test(text));
  const idMatch = `${context.url}\n${text}`.match(/(?:Documento|Document|id)[^\d]{0,20}(\d{3,})/i);
  return {
    matched: !!matched,
    matchedPattern: matched ? String(matched) : null,
    documentId: idMatch ? Number(idMatch[1]) : null,
    page: context,
  };
}

async function assertNoLegalOneValidationErrors(page) {
  const errors = await page
    .locator('.validation-summary-errors, .field-validation-error')
    .allTextContents()
    .catch(() => []);
  const visibleErrors = errors.map((text) => text.trim()).filter(Boolean);
  if (visibleErrors.length) {
    throw new Error(`Erros do Legal One: ${visibleErrors.join(' | ')}`);
  }
}

async function openCreateArquivo(page, item, webBaseUrl, loginConfig) {
  const matterId = item.lawsuitId;
  const detailsGedUrl = `${webBaseUrl}/processos/processos/DetailsGED/${matterId}`;
  const createUrl = `${webBaseUrl}/processos/Arquivos/CreateArquivo/${matterId}?returnUrl=${encodeURIComponent(`/processos/processos/DetailsGED/${matterId}`)}`;

  const response = await page.goto(createUrl, { waitUntil: 'domcontentloaded', timeout: 120000 });
  await waitForPageSettle(page, 3000);

  let context = await capturePageContext(page);
  if (isAuthenticationPage(context)) {
    await login(page, { ...loginConfig, returnUrl: createUrl });
    await waitForPageSettle(page, 3000);
    context = await capturePageContext(page);
  }

  const status = response ? response.status() : null;
  if (status && status >= 400) {
    throw new Error(`CreateArquivo retornou HTTP ${status}`);
  }
  if (/\/login|loginonepass|signon\.thomsonreuters/i.test(page.url())) {
    throw new Error('Sessao expirada ao abrir CreateArquivo.');
  }
  if (/acesso negado|processo n[aã]o encontrado|not found|forbidden/i.test(context.bodyStart || '')) {
    throw new Error(
      `CreateArquivo sem permissao ou processo nao encontrado | url=${context.url} | body=${(context.bodyStart || '').slice(0, 500)}`,
    );
  }
  if (!/\/processos\/Arquivos\/CreateArquivo\//i.test(page.url())) {
    throw new Error(`URL inesperada ao abrir formulario GED: ${page.url()}`);
  }

  return { createUrl, detailsGedUrl };
}

async function uploadFileWithFineUploader(page, filePath) {
  const extension = path.extname(filePath).replace('.', '').toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) {
    throw new Error(`Extensao ${extension} nao permitida pelo GED.`);
  }

  const readUploadState = () => page.evaluate(() => {
    const read = (selector) => {
      const element = document.querySelector(selector);
      return element ? element.value || element.textContent || '' : null;
    };
    return {
      hasFile: read('#FileAzure_HasFile'),
      fileName: read('#FileAzure_FileName, #FileAzure_Name, input[name="FileAzure.FileName"]'),
      fileId: read('#FileAzure_FileId, #FileAzure_Id, input[name="FileAzure.FileId"], input[name="FileAzure.Id"]'),
      successCount: document.querySelectorAll('.qq-upload-list .qq-upload-success').length,
      failCount: document.querySelectorAll('.qq-upload-list .qq-upload-fail').length,
      uploaderText: Array.from(document.querySelectorAll('.qq-upload-list li'))
        .map((node) => (node.innerText || node.textContent || '').trim())
        .filter(Boolean)
        .join(' | '),
    };
  });

  await page.setInputFiles('input[type=file][name="qqfile"], input[type=file]', filePath);
  try {
    await page.waitForFunction(
      () => {
        const failed = document.querySelectorAll('.qq-upload-list .qq-upload-fail').length;
        if (failed > 0) return 'failed';

        const hasFile = document.querySelector('#FileAzure_HasFile');
        if (hasFile && /^true$/i.test(hasFile.value || '')) return 'ready';

        const success = document.querySelectorAll('.qq-upload-list .qq-upload-success').length;
        const fileName = document.querySelector('#FileAzure_FileName, #FileAzure_Name, input[name="FileAzure.FileName"]');
        const fileId = document.querySelector('#FileAzure_FileId, #FileAzure_Id, input[name="FileAzure.FileId"], input[name="FileAzure.Id"]');
        if (success > 0) return 'ready';
        if (success > 0 && ((fileName && fileName.value) || (fileId && fileId.value))) return 'ready';

        return false;
      },
      null,
      { timeout: 120000, polling: 500 },
    );
  } catch (error) {
    const uploadState = await readUploadState().catch(() => null);
    throw new Error(
      `Fine Uploader nao ficou pronto em 120s: ${JSON.stringify(uploadState)} | ${
        error instanceof Error ? error.message : String(error)
      }`,
    );
  }

  const uploadState = await readUploadState();

  if (uploadState.failCount > 0) {
    throw new Error(`Upload falhou no Fine Uploader: ${uploadState.uploaderText || '<sem detalhe>'}`);
  }

  if (uploadState.successCount <= 0 && !uploadState.fileName && !uploadState.fileId) {
    throw new Error(`Fine Uploader nao confirmou arquivo no formulario: ${JSON.stringify(uploadState)}`);
  }

  return uploadState;
}

async function expandLookupTree(page, tree) {
  for (let guard = 0; guard < 20; guard += 1) {
    const expanded = await page.evaluate(() => {
      const dropdown = document.querySelector('.lookup-dropdown table.treeTable');
      if (!dropdown) return 0;
      const candidates = Array.from(
        dropdown.querySelectorAll(
          'tr.collapsed .expander, tr.expandable.collapsed .expander, tr.parent.collapsed .expander, .expander:not(.expanded), .collapsed [class*="expand"]',
        ),
      );
      let count = 0;
      for (const node of candidates) {
        const style = window.getComputedStyle(node);
        const rect = node.getBoundingClientRect();
        if (style.display === 'none' || style.visibility === 'hidden' || rect.width === 0 || rect.height === 0) continue;
        node.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }));
        node.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true }));
        node.click();
        count += 1;
      }
      return count;
    });
    if (!expanded) return;
    await page.waitForTimeout(250);
  }
}

async function selectGedType(page, tipoPath = ['Documento', 'Habilitação']) {
  await page.locator('#lookup_tipo .lookup-show').click({ timeout: 30000 });
  const tree = page.locator('.lookup-dropdown table.treeTable');
  await tree.waitFor({ state: 'visible', timeout: 10000 });
  await expandLookupTree(page, tree);

  const selected = await page.evaluate(({ pathParts }) => {
    const leaf = String(pathParts[pathParts.length - 1] || 'Habilitação').trim().toLowerCase();
    const parent = pathParts.length > 1 ? String(pathParts[pathParts.length - 2]).trim().toLowerCase() : '';
    const dropdown = document.querySelector('.lookup-dropdown table.treeTable');
    if (!dropdown) return { clicked: false, reason: 'lookup-dropdown table.treeTable ausente' };

    const isVisible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };

    const cells = Array.from(dropdown.querySelectorAll('td')).filter(
      (cell) => (cell.textContent || '').trim().toLowerCase() === leaf,
    );
    const visibleCells = cells.filter(isVisible);
    const parentAnchored = visibleCells.find((cell) => {
      if (!parent) return false;
      let row = cell.closest('tr');
      for (let hops = 0; row && hops < 20; hops += 1) {
        const rowText = (row.textContent || '').trim().toLowerCase();
        if (rowText.includes(parent)) return true;
        const classes = Array.from(row.classList);
        const parentClass = classes.find((name) => name.startsWith('child-of-'));
        if (!parentClass) break;
        const parentId = parentClass.slice('child-of-'.length);
        row = dropdown.querySelector(`tr#${CSS.escape(parentId)}, tr.${CSS.escape(parentId)}`);
      }
      return false;
    });
    const cell = parentAnchored || visibleCells[0] || cells[0];
    if (!cell) {
      return {
        clicked: false,
        reason: `tipo nao encontrado: ${leaf}`,
        candidates: Array.from(dropdown.querySelectorAll('td'))
          .map((node) => (node.textContent || '').trim())
          .filter(Boolean)
          .slice(0, 80),
      };
    }

    cell.scrollIntoView({ block: 'center', inline: 'nearest' });
    cell.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
    cell.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
    cell.click();
    return {
      clicked: true,
      text: (cell.textContent || '').trim(),
      visible: isVisible(cell),
      rowText: (cell.closest('tr')?.textContent || '').trim(),
    };
  }, { pathParts: tipoPath });

  if (!selected.clicked) {
    throw new Error(`Tipo GED nao clicado: ${JSON.stringify(selected)}`);
  }

  await page.waitForTimeout(800);
  const tipoId = await page.locator('#TipoId').inputValue({ timeout: 10000 }).catch(() => '');
  const tipoText = await page.locator('#TipoText').inputValue({ timeout: 10000 }).catch(() => '');
  if (!tipoId || !/habilita/i.test(tipoText)) {
    throw new Error(`Tipo GED nao selecionado corretamente: TipoId=${tipoId || '<vazio>'} TipoText=${tipoText || '<vazio>'}`);
  }
  return { tipoId, tipoText };
}

async function fillGedForm(page, item, displayArchiveName) {
  const description = item.description || displayArchiveName;
  if ((await page.locator('#Descricao').count().catch(() => 0)) > 0) {
    await page.locator('#Descricao').fill(description);
  }

  const nameWithoutExtension = path.parse(displayArchiveName).name;
  if ((await page.locator('#Nome').count().catch(() => 0)) > 0) {
    await page.evaluate((value) => {
      const input = document.getElementById('Nome');
      if (!input) return;
      input.value = value;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }, nameWithoutExtension);
  }

  const observation = item.observation || item.observacao || item.notes;
  if (observation) {
    await page.getByText('Observações', { exact: true }).click({ timeout: 5000 }).catch(() => null);
    if ((await page.locator('#Observacao').count().catch(() => 0)) > 0) {
      await page.locator('#Observacao').fill(String(observation));
    }
  }

  return { descriptionFilled: description, nameFilled: nameWithoutExtension };
}

async function saveAndCloseGedForm(page, matterId) {
  const saveButton = page.getByRole('button', { name: /Salvar e fechar/i });
  const fallback = page.locator('input[type=submit][value*="Salvar"], button:has-text("Salvar")').first();
  const clickable = (await saveButton.count().catch(() => 0)) > 0 ? saveButton.first() : fallback;

  await Promise.all([
    page.waitForURL(new RegExp(`/processos/processos/DetailsGED/${matterId}`, 'i'), { timeout: 60000 }).catch(async () => {
      await waitForPageSettle(page, 5000);
    }),
    clickable.click({ timeout: 30000 }),
  ]);

  await assertNoLegalOneValidationErrors(page);
  if (/\/login/i.test(page.url())) {
    throw new Error('Sessao expirada apos salvar arquivo GED.');
  }
}

async function getRecentAttachmentId(page, displayArchiveName, item, tipo = 'Habilitação') {
  const nameStem = path.parse(displayArchiveName).name;
  const expectedDate = item.expectedUploadDate || todayBrDate(item.timeZone || 'America/Fortaleza');
  const expectedTipo = item.expectedAttachmentType || tipo;
  await page.locator('table a[href*="/Arquivos/Details/"]').first().waitFor({ timeout: 20000 }).catch(() => null);

  return page.evaluate(
    ({ expectedStem, expectedTipo, expectedDate, cnj }) => {
      const normalize = (value) =>
        String(value || '')
          .normalize('NFD')
          .replace(/[\u0300-\u036f]/g, '')
          .toLowerCase();
      const cnjDigits = String(cnj || '').replace(/\D/g, '');
      const anchors = Array.from(document.querySelectorAll('table a[href*="/Arquivos/Details/"]'));
      const candidates = anchors.map((anchor, index) => {
        const row = anchor.closest('tr');
        const href = anchor.getAttribute('href') || '';
        const text = (anchor.textContent || '').trim();
        const rowText = (row?.textContent || '').trim();
        const idMatch = href.match(/\/Arquivos\/Details\/(\d+)/i);
        const normalizedRow = normalize(rowText);
        const normalizedText = normalize(`${text} ${rowText}`);
        const hasExpectedType = normalizedRow.includes(normalize(expectedTipo));
        const hasExpectedDate = rowText.includes(expectedDate);
        let score = 0;
        if (hasExpectedType && hasExpectedDate) score += 20;
        if (hasExpectedDate) score += 8;
        if (hasExpectedType) score += 6;
        if (normalizedText.includes(normalize(expectedStem))) score += 5;
        if (cnjDigits && normalizedText.replace(/\D/g, '').includes(cnjDigits.slice(-8))) score += 2;
        return {
          index,
          href,
          text,
          rowText,
          documentId: idMatch ? Number(idMatch[1]) : null,
          score,
          hasExpectedType,
          hasExpectedDate,
        };
      });

      candidates.sort((left, right) => right.score - left.score || left.index - right.index);
      const chosen = candidates[0] || null;
      const confirmed = Boolean(chosen?.hasExpectedType && chosen?.hasExpectedDate);
      return {
        documentId: chosen?.documentId || null,
        href: chosen?.href || null,
        nameStem: expectedStem,
        expectedTipo,
        expectedDate,
        confirmed,
        matchedBy: confirmed ? 'type-and-date' : chosen?.score > 0 ? 'scored-table-link' : chosen ? 'first-table-link' : 'none',
        chosen,
        candidates: candidates.slice(0, 10),
      };
    },
    { expectedStem: nameStem, expectedTipo, expectedDate, cnj: item.cnj },
  );
}

async function uploadGedDocument(session, item, webBaseUrl, loginConfig) {
  if (!fs.existsSync(item.pdfPath)) {
    throw new Error(`PDF nao encontrado: ${item.pdfPath}`);
  }

  const displayArchiveName = normalizeDisplayName(item.archive || path.basename(item.pdfPath));
  const { createUrl, detailsGedUrl } = await openCreateArquivo(session.page, item, webBaseUrl, loginConfig);
  const uploadState = await uploadFileWithFineUploader(session.page, item.pdfPath);
  const selectedType = await selectGedType(session.page, item.tipoPath || item.typePath || ['Documento', 'Habilitação']);
  const metadata = await fillGedForm(session.page, item, displayArchiveName);
  await saveAndCloseGedForm(session.page, item.lawsuitId);
  const attachment = await getRecentAttachmentId(session.page, displayArchiveName, item);
  if (!attachment.confirmed) {
    throw new Error(
      `Upload salvo, mas nao confirmei linha GED por tipo/data: ${JSON.stringify(attachment)}`,
    );
  }

  return {
    status: STATUS_UPLOADED,
    response: {
      createUrl,
      detailsGedUrl,
      displayArchiveName,
      uploadState,
      selectedType,
      metadata,
      attachment,
      documentId: attachment.documentId,
      pageUrl: session.page.url(),
    },
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputPath = args.input;
  if (!inputPath) throw new Error('Use --input <json>');

  const item = readJsonFile(inputPath, null);
  if (!item || typeof item !== 'object') throw new Error('Arquivo de entrada invalido.');

  const outputPath = args.output || path.join(path.dirname(inputPath), `ged-upload-${Date.now()}.json`);
  const artifactsDir = args['artifacts-dir'] || null;
  const webBaseUrl = (process.env.LEGAL_ONE_WEB_URL || process.env.LEGALONE_WEB_URL || item.webBaseUrl || 'https://mdradvocacia.novajus.com.br').replace(/\/+$/, '');
  const username = requireEnvAny(['LEGALONE_WEB_USERNAME', 'LEGAL_ONE_WEB_USERNAME']);
  const password = requireEnvAny(['LEGALONE_WEB_PASSWORD', 'LEGAL_ONE_WEB_PASSWORD']);
  const keyLabel = requireEnvAny(['LEGALONE_WEB_KEY_LABEL', 'LEGAL_ONE_WEB_KEY_LABEL']);
  const returnUrl = `${webBaseUrl}/processos/Processos/details/${item.lawsuitId}`;
  const loginConfig = { username, password, keyLabel, returnUrl };

  writeJsonFile(outputPath, {
    generatedAt: new Date().toISOString(),
    state: 'starting',
    item: { ...item, pdfPath: item.pdfPath },
  });

  let session = null;
  try {
    session = await createLoggedInSession(loginConfig);
    const result = await uploadGedDocument(session, item, webBaseUrl, loginConfig);
    const payload = {
      generatedAt: new Date().toISOString(),
      state: 'completed',
      status: result.status,
      item: { ...item, pdfPath: item.pdfPath },
      response: result.response,
      error: null,
    };
    writeJsonFile(outputPath, payload);
    console.log(JSON.stringify(payload));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const diagnostics = await writeDiagnosticArtifact(session?.page, item, artifactsDir, { error: message });
    const payload = {
      generatedAt: new Date().toISOString(),
      state: 'failed',
      status: STATUS_ERROR,
      item: { ...item, pdfPath: item.pdfPath },
      response: null,
      error: message,
      ...diagnostics,
    };
    writeJsonFile(outputPath, payload);
    console.error(message);
    process.exitCode = 1;
  } finally {
    await closeSession(session);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

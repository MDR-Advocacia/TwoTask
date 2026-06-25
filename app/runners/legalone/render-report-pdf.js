// Renderiza um HTML em PDF A4 usando o Chromium do Playwright que já vive na
// imagem da API (instalado para o RPA). Invocado pelo Python via subprocess:
//   node render-report-pdf.js <caminho-html> <caminho-pdf-saida>
//
// Sem dependências novas: reusa o pacote `playwright` deste runner.

const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const htmlPath = process.argv[2];
  const pdfPath = process.argv[3];
  if (!htmlPath || !pdfPath) {
    console.error('uso: render-report-pdf.js <html> <pdf>');
    process.exit(2);
  }

  const html = fs.readFileSync(htmlPath, 'utf-8');
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'networkidle', timeout: 60000 });
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      printBackground: true,
      preferCSSPageSize: true,
      margin: { top: '0', right: '0', bottom: '0', left: '0' },
    });
  } finally {
    await browser.close();
  }
})().catch((err) => {
  console.error((err && err.stack) || String(err));
  process.exit(1);
});

const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const out = path.resolve('pr-pipeline-hub/.runtime/ci-acceptance');
  const batch = JSON.parse(fs.readFileSync(path.join(out, 'batch.json')));
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(batch.web_url, {waitUntil: 'networkidle', timeout: 60000});
    await page.getByRole('button', {name: '运行日志', exact: true}).waitFor();
    for (const width of [1440, 1920, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.screenshot({path: path.join(out, `batch-${width}.png`), fullPage: true});
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) {
        throw new Error(`Report overflow at ${width}`);
      }
    }
    await page.getByRole('button', {name: '运行日志', exact: true}).click();
    await page.getByLabel('日志阶段').selectOption('build');
    await page.waitForFunction(() => [...document.querySelectorAll('pre')].some(p => p.textContent.length > 100));
    await page.screenshot({path: path.join(out, 'batch-logs.png'), fullPage: true});
    const base = new URL(batch.web_url).origin;
    const unauth = await page.request.get(base + '/submit/');
    const internal = await page.request.post(base + '/internal/claim', {data: {}});
    if (unauth.status() !== 401 || internal.status() !== 404) throw new Error('Public write boundary failed');
    if (errors.length) throw new Error(errors.join('; '));
    console.log(JSON.stringify({id: batch.id, report_visible: true, logs_visible: true,
      viewports: [1440, 1920, 390], anonymous_submit: unauth.status(), internal: internal.status(), errors}));
  } finally { await browser.close(); }
})().catch(e => {console.error(e.message); process.exitCode = 1;});

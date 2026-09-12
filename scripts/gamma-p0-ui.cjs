const fs = require('node:fs');
const {chromium} = require('/var/lib/pr-e2e/state/playwright/node_modules/@playwright/test');
(async () => {
  const token = fs.readFileSync('/etc/pr-e2e/secrets/worker-token', 'utf8').trim();
  const out = '/opt/gamma-p0-validation/ui';
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const checks = [];
  try {
    for (const width of [1440, 1920, 390]) {
      const page = await browser.newPage({viewport: {width, height: 1000}, extraHTTPHeaders: {'X-Worker-Token': token}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('requestfailed', request => errors.push(`${request.url()}: ${request.failure()?.errorText || 'request failed'}`));
      await page.route('http://127.0.0.1:8792/pipeline/**', route => route.continue({
        url: route.request().url().replace('http://127.0.0.1:8792/pipeline/', 'http://127.0.0.1:8792/'),
      }));
      const response = await page.goto('http://127.0.0.1:8792/runs/' + process.argv[2]);
      await page.waitForTimeout(2000);
      await page.screenshot({path: `${out}/${process.argv[2]}-${width}.png`, fullPage: true});
      const layout = await page.evaluate(() => ({viewport: innerWidth, content: document.documentElement.scrollWidth, text: document.body.innerText.slice(0, 160)}));
      checks.push({width, status: response.status(), errors, ...layout});
      await page.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify(checks));
  if (checks.some(c => c.status !== 200 || c.errors.length || c.content > c.viewport || !c.text.trim())) process.exitCode = 1;
})().catch(e => { console.error(e.message); process.exitCode = 1; });

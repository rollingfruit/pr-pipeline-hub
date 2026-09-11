const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {chromium} = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const config = JSON.parse(fs.readFileSync(path.join(root, '.runtime/pipeline-server.json'), 'utf8'));
  const cert = new crypto.X509Certificate(fs.readFileSync(path.join(root, '.runtime/ecs-share.crt')));
  const pin = crypto.createHash('sha256').update(cert.publicKey.export({type: 'spki', format: 'der'})).digest('base64');
  // A tunnel override is diagnostic only; default verification uses public HTTPS.
  const origin = process.env.SHARE_TEST_ORIGIN || config.public_base_url;
  const browser = await chromium.launch({headless: true, channel: 'msedge', args: origin.startsWith('https:') ? [`--ignore-certificate-errors-spki-list=${pin}`] : []});
  try {
    for (const width of [1440, 390]) {
      const context = await browser.newContext({viewport: {width, height: 950}});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const unauthorized = await page.goto(origin + '/api/runs');
      if (unauthorized.status() !== 401) throw Error('Anonymous results must be blocked');
      await page.goto(origin + '/runs/20260908-203211-6bb7f6?access_token=' + encodeURIComponent(config.view_token));
      await page.locator('#run-title').filter({hasText: /.+/}).waitFor();
      await page.waitForFunction(() => document.querySelectorAll('#e2e-links a').length >= 6);
      if (page.url().includes('access_token')) throw Error('Token not exchanged for cookie');
      if (await page.locator('#run-form').isVisible()) throw Error('Remote build form must be hidden');
      const reports = page.locator('#e2e-links a').filter({hasText: '回放'});
      if (await reports.count() !== 6) throw Error('Expected six actual browser reports');
      const report = await reports.first().getAttribute('href');
      await page.screenshot({path: path.join(root, `.runtime/ecs-share-${width}.png`), fullPage: true});
      await page.goto(report);
      await page.getByText('E01', {exact: false}).first().waitFor({timeout: 20000});
      await page.getByText('[E01] {create} Browser creates a durable robot and opens its conversation', {exact: true}).click();
      const video = page.locator('video').first();
      await video.waitFor();
      await video.evaluate(element => element.load());
      await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
      const traceLink = page.getByRole('link', {name: 'View trace'}).first();
      const traceHref = await traceLink.getAttribute('href');
      if (!traceHref) throw Error('Missing trace URL');
      await page.screenshot({path: path.join(root, `.runtime/ecs-report-${width}.png`), fullPage: true});
      const traceUrl = new URL(traceHref, page.url());
      if (traceUrl.origin !== origin) throw Error('Trace must be served by ECS, not a third-party viewer');
      if (origin.startsWith('https:')) {
        await page.goto(traceUrl.href);
        await page.getByText('Browser creates', {exact: false}).first().waitFor({timeout: 30000});
        await page.screenshot({path: path.join(root, `.runtime/ecs-trace-${width}.png`), fullPage: true});
      } else {
        const run = await page.evaluate(async () => (await fetch('/api/runs/20260908-203211-6bb7f6')).json());
        if (run.trace_downloads.length !== 6) throw Error('Expected six downloadable traces');
        const zip = await page.evaluate(async url => {
          const r = await fetch(url);
          const bytes = new Uint8Array(await r.arrayBuffer());
          return {status: r.status, valid: bytes[0] === 80 && bytes[1] === 75, size: bytes.length};
        }, run.trace_downloads[0].url);
        if (zip.status !== 200 || !zip.valid) throw Error('Trace archive download failed');
      }
      if (errors.length) throw Error(errors.join('\n'));
      console.log(JSON.stringify({origin, width, archive: 'ok', browserReports: 6, reportLoaded: true, videoLoaded: true,
        traceLoaded: origin.startsWith('https:'), traceDownload: origin.startsWith('http:'), anonymousBlocked: true}));
      await context.close();
    }
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });

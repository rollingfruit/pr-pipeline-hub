const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const password = execFileSync('ssh', ['-o', 'BatchMode=yes', 'root@119.8.233.58',
    'cat /etc/pr-e2e/secrets/submit-password'], {encoding: 'utf8'}).trim();
  const out = path.resolve('pr-pipeline-hub/.runtime/ci-acceptance');
  fs.mkdirSync(out, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: 'chrome'});
  try {
    const context = await browser.newContext({httpCredentials: {username: process.env.PIPELINE_TEST_USER || 'root', password}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://119.8.233.58:8080/submit/', {waitUntil: 'networkidle', timeout: 60000});
    await page.locator('#suites input').first().waitFor();
    for (const width of [1440, 1920, 390]) {
      await page.setViewportSize({width, height: 1000});
      await page.screenshot({path: path.join(out, `submit-${width}.png`), fullPage: true});
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      if (overflow) throw new Error(`Page overflow at ${width}`);
    }
    await page.setViewportSize({width: 1440, height: 1000});
    await page.locator('#name').fill('CI OpenCode DeepSeek cross-repository acceptance');
    await page.locator('#urls').fill('https://github.com/rollingfruit/agent-governance-gw/pull/105\nhttps://github.com/rollingfruit/semantic-schedule/pull/155');
    const response = page.waitForResponse(r => r.url().endsWith('/api/batches/resolve'));
    await page.locator('#resolve').click();
    const resolved = await (await response).json();
    if (resolved.results.length !== 2 || resolved.results.some(r => !r.ok || r.member.risky_files.length)) {
      throw new Error('PR selection contains unsupported or unapproved changes');
    }
    await page.screenshot({path: path.join(out, 'resolved.png'), fullPage: true});
    if (errors.length) throw new Error(errors.join('; '));
    const submitted = page.waitForResponse(r => r.url().endsWith('/api/batches'), {timeout: 180000});
    await page.locator('#submit').click();
    const result = await submitted;
    const batch = await result.json();
    if (!result.ok()) throw new Error(batch.error || 'Submission failed');
    fs.writeFileSync(path.join(out, 'batch.json'), JSON.stringify(batch, null, 2));
    console.log(JSON.stringify({browser_submission: true, id: batch.id, url: batch.web_url, page_errors: errors}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });

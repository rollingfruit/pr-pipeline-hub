const {chromium} = require('/var/lib/pr-e2e/state/playwright/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    await page.goto('http://127.0.0.1:8080/');
    console.log(JSON.stringify({browser: browser.version(), title: await page.title(), status: 'browser-smoke-only'}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });

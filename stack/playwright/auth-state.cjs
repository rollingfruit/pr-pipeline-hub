const {chromium} = require('@playwright/test');
const fs = require('node:fs');

(async () => {
  const settings = JSON.parse(fs.readFileSync(process.env.E2E_SETTINGS, 'utf8'));
  const browser = await chromium.launch();
  const context = await browser.newContext({baseURL: process.env.E2E_APP_URL});
  const page = await context.newPage();
  await page.goto('/login');
  const webChoice = page.getByRole('link', {name: /在浏览器查看|View in Browser/i});
  await page.locator('#input_loginId').or(webChoice).first().waitFor({state: 'visible'});
  if (await webChoice.isVisible()) await webChoice.click();
  await page.locator('#input_loginId').waitFor({state: 'visible'});
  const usernameTab = page.getByRole('tab', {name: /用户名登录|Username sign-in/i});
  if (await usernameTab.isVisible()) await usernameTab.click();
  await page.locator('#input_loginId').fill(settings.TEST_ADMIN_USER);
  await page.locator('#input_password-input').fill(settings.TEST_ADMIN_PASSWORD);
  await page.locator('button[type=submit]').click();
  await page.waitForFunction(async () => (await fetch('/api/v4/users/me')).status === 200);
  await context.storageState({path: process.env.E2E_AUTH_STATE});
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });

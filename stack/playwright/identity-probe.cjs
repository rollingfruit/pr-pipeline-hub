const {chromium, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
    const cfg = JSON.parse(fs.readFileSync(process.env.E2E_SETTINGS_FILE, 'utf8'));
    const browser = await chromium.launch({headless: true});
    let page;
    try {
        page = await browser.newPage({baseURL: process.env.E2E_APP_URL, viewport:{width:1440,height:1000}});
        await page.goto('/login');
        const web = page.getByRole('link', {name: /在浏览器查看|View in Browser/i});
        await page.locator('#input_loginId').or(web).first().waitFor();
        if (await web.isVisible()) await web.click();
        await page.locator('#input_loginId').waitFor({state: 'visible'});
        const tab = page.getByRole('tab', {name: /用户名登录|Username sign-in/i});
        if (await tab.isVisible()) await tab.click();
        await page.locator('#input_loginId').fill(cfg.TEST_ADMIN_USER);
        await page.locator('#input_password-input').fill(cfg.TEST_ADMIN_PASSWORD);
        await page.locator('button[type=submit]').click();
        await expect.poll(async () => (await page.request.get('/api/v4/users/me')).status(), {timeout: 30000}).toBe(200);
        const me = await (await page.request.get('/api/v4/users/me')).json();
        if (me.username !== cfg.TEST_ADMIN_USER || !me.id) throw Error('Browser identity mismatch');
        const request = page.waitForRequest(r => new URL(r.url()).pathname === '/v1/agent/managed-platforms');
        await page.goto('/hw/agents-manage');
        const identity = new URL((await request).url()).searchParams.get('user_id');
        if (identity !== me.id && !(identity?.startsWith(me.id + '@') && /^[A-Za-z0-9@._-]+$/.test(identity))) {
            throw Error('Browser did not expose a recognized identity for the test account');
        }
        fs.writeFileSync(path.join(process.env.E2E_PRIVATE_DIR, 'browser-identity.json'),
            JSON.stringify({user_id: me.id, control_user_id: identity, username: me.username}), {mode: 0o600});
        console.log('Browser identity verified for dedicated test account');
    } catch (error) {
        if (page) {
            await page.screenshot({path:path.join(process.env.E2E_PRIVATE_DIR,'identity-failed.png')});
            console.error((await page.locator('body').innerText()).slice(-2000));
        }
        throw error;
    } finally { await browser.close(); }
})().catch(error => {console.error(error.message); process.exit(1);});

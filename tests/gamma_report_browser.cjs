// UI verification against real archived data; this does not test Robot CI login.
const {chromium, expect} = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
    const id = process.argv[2];
    const suite = process.argv[3] || 'E02';
    if (!/^E0[1-6]$/.test(suite)) throw Error('Registered suite required');
    if (!/^gamma-check-[a-zA-Z0-9-]+$/.test(id || '')) throw Error('Diagnostic run ID required');
    const token = fs.readFileSync('/etc/pr-e2e/secrets/worker-token', 'utf8').trim();
    const output = '/var/lib/pr-e2e/gamma-ui-qa';
    fs.mkdirSync(output, {recursive: true, mode: 0o700});
    const browser = await chromium.launch({headless: true});
    try {
        for (const width of [1440, 1920, 390]) {
            const page = await browser.newPage({viewport: {width, height: 1000}});
            const errors = [];
            page.on('pageerror', e => errors.push(e.message));
            await page.route('http://gamma-qa.local/**', async route => {
                const url = new URL(route.request().url());
                const pathname = url.pathname.replace(/^\/pipeline(?=\/)/, '');
                const response = await page.request.get('http://127.0.0.1:8792' + pathname + url.search,
                    {headers: {'X-Worker-Token': token}});
                await route.fulfill({response});
            });
            await page.goto(`http://gamma-qa.local/pipeline/runs/${id}`);
            await expect(page.getByRole('heading', {name: '实测环境镜像'})).toBeVisible();
            await page.getByRole('button', {name: 'E2E 证据', exact: true}).click();
            await expect(page.getByRole('heading', {name: '当前环境执行证据'})).toBeVisible();
            await page.getByRole('button', {name: new RegExp('^'+suite+' ')}).first().click();
            await expect(page.locator('.evidence-tool h3')).toContainText(suite);
            const image = page.locator('.evidence-grid img');
            if (await image.count()) await expect.poll(() => image.evaluate(e => e.naturalWidth)).toBeGreaterThan(0);
            const video = page.locator('.evidence-grid video');
            if (await video.count()) await expect.poll(() => video.evaluate(e => e.readyState)).toBeGreaterThan(0);
            await page.screenshot({path: path.join(output, `${id}-${width}.png`), fullPage: true});
            const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
            if (overflow || errors.length) throw Error(JSON.stringify({width, overflow, errors}));
            await page.getByRole('button', {name: '运行日志', exact: true}).click();
            await expect(page.locator('.console.full')).not.toHaveText('');
            console.log(JSON.stringify({width, realArchive: id, evidence: true, logs: true, errors}));
            await page.close();
        }
    } finally { await browser.close(); }
})().catch(error => {console.error(error.message); process.exitCode = 1;});

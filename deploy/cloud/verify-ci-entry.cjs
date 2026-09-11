const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const base = 'http://119.8.233.58:8080';
  const username = process.env.PIPELINE_TEST_USER || 'root';
  const password = execFileSync('ssh', ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
    'root@119.8.233.58', 'cat /etc/pr-e2e/secrets/submit-password'], {encoding:'utf8', timeout:20000}).trim();
  const output = path.resolve('pr-pipeline-hub/.runtime/ci-entry');
  fs.mkdirSync(output, {recursive:true});
  const browser = await chromium.launch({headless:true, channel:'chrome'});
  const network = process.env.PIPELINE_TEST_PROXY ? {proxy:{server:process.env.PIPELINE_TEST_PROXY}} : {};
  try {
    const anonymous = await browser.newContext(network);
    if ((await anonymous.request.get(base+'/submit/')).status() !== 401) throw Error('Anonymous submission page must require login');
    const context = await browser.newContext({...network,httpCredentials:{username, password}});
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    for (const width of [1440,1920,390]) {
      await page.setViewportSize({width,height:1000});
      await page.goto(base+'/', {waitUntil:'networkidle'});
      const entry = page.getByRole('link', {name:'新建 PR 验证',exact:true});
      await entry.waitFor();
      if (await entry.getAttribute('href') !== base+'/submit/') throw Error('Dashboard points to the wrong editor');
      await page.screenshot({path:path.join(output,`dashboard-${width}.png`),fullPage:true});
      await entry.click();
      await page.locator('#suites input').first().waitFor();
      if (!await page.getByRole('heading',{name:'新建 PR 联合验证',exact:true}).isVisible()) throw Error('Missing editor title');
      if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)) throw Error('Editor overflow at '+width);
      await page.screenshot({path:path.join(output,`editor-${width}.png`),fullPage:true});
      await page.getByRole('link',{name:'返回联合验证看板'}).click();
      await page.getByRole('heading',{name:'联合验证',exact:true}).waitFor();
    }
    if (errors.length) throw Error(errors.join('; '));
    console.log(JSON.stringify({entry:base+'/submit/',widths:[1440,1920,390],anonymous_status:401,submitted:false,errors}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error.message);process.exitCode=1;});

const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const output = path.resolve('.runtime/single-branch-proof');
  fs.mkdirSync(output,{recursive:true});
  try {
    const page = await browser.newPage();
    const errors=[];page.on('pageerror', e=>errors.push(e.message));
    const html = fs.readFileSync('static/branch-editor.html','utf8')
      .replaceAll('__PIPELINE_BASE__','/pipeline').replaceAll('__EDITOR_API_BASE__','/submit')
      .replaceAll('__TOKEN__','fixture-only');
    let parsed;
    await page.route('http://fixture.test/**', async route => {
      const pathname = new URL(route.request().url()).pathname;
      let data;
      if (pathname==='/submit/') return route.fulfill({contentType:'text/html',body:html});
      if (pathname==='/submit/api/catalog') data={supported:['agent-governance-gw','multica-aiwelink'],
        suites:['E01','E02','E03'].map(id=>({id,name:id,implemented:true}))};
      if (pathname==='/submit/api/branches') data={default_branch:'main',branches:[{name:'main'},{name:'feature/test'}]};
      if (pathname==='/submit/api/branches/resolve') {
        parsed=route.request().postDataJSON();
        data={results:parsed.members.map(m=>({ok:true,member:{...m,head_sha:'a'.repeat(40),base_ref:'main',base_sha:'b'.repeat(40),risky_files:[]}}))};
      }
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data||{})});
    });
    await page.goto('http://fixture.test/submit/');
    await page.locator('.repo').selectOption('rollingfruit/agent-governance-gw');
    await page.locator('.head').selectOption('feature/test');
    await page.locator('#add').click();
    await page.locator('.repo').nth(1).selectOption('rollingfruit/multica-aiwelink');
    await page.locator('.head').nth(1).selectOption('main');
    assert.equal(await page.locator('.base').count(),0);
    await page.locator('#resolve').click();
    await page.locator('#versions table').waitFor();
    assert.equal(parsed.members.length,2);
    assert(parsed.members.every(m=>!('base_ref' in m)));
    for (const width of [1440,1920,390]) {
      await page.setViewportSize({width,height:1000});
      await page.screenshot({path:path.join(output,`submit-${width}.png`),fullPage:true});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    await page.locator('.head').first().selectOption('main');
    assert(await page.locator('#submit').isDisabled());
    assert.deepEqual(errors,[]);
    console.log('PASS fixture UI: one branch, multi-repo resolve, invalidation, 1440/1920/390; NOT live E2E');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});

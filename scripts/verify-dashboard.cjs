const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const config = JSON.parse(fs.readFileSync(path.join(root, '.runtime/pipeline-server.json'), 'utf8'));
  const origin = config.public_base_url;
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    for (const width of [1440,1920,390]) {
      const context = await browser.newContext({viewport:{width,height:1000}});
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', e=>errors.push(e.message));
      if ((await page.goto(origin+'/api/runs')).status() !== 401) throw Error('Anonymous access');
      await page.goto(origin+'/?access_token='+encodeURIComponent(config.view_token));
      await page.locator('tbody tr').first().waitFor();
      await page.getByRole('button',{name:'PR 检视',exact:true}).click();
      await page.waitForURL(/\/reviews$/);
      await page.getByRole('heading',{name:'PR 检视',exact:true}).waitFor();
      await page.locator('details summary').first().click();
      await page.locator('details button').first().click();
      await page.waitForURL(/\/runs\/[A-Za-z0-9-]+$/);
      await page.getByRole('button',{name:'代码发现',exact:true}).waitFor();
      await page.goto(origin+'/reviews');
      await page.getByRole('heading',{name:'PR 检视',exact:true}).waitFor();
      await page.locator('tbody tr').first().waitFor();
      const inventory=await page.evaluate(async()=> (await fetch('/api/monitors')).json());
      const total=inventory.monitors.reduce((n,m)=>n+(m.pull_requests||[]).length,0);
      if (!total || await page.locator('tbody tr').count()!==total) throw Error('PR snapshot rows missing');
      if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('PR inventory overflow');
      await page.screenshot({path:path.join(root,`.runtime/reviews-${width}.png`)});
      await page.goto(origin+'/runs/20260908-203211-6bb7f6?access_token='+encodeURIComponent(config.view_token));
      await page.getByRole('heading',{name:/#101/}).waitFor();
      await page.locator('.suite-table tbody tr').first().waitFor();
      await page.waitForFunction(()=>Array.from(document.querySelectorAll('.evidence-grid img')).every(img=>img.complete&&img.naturalWidth>0));
      await page.waitForFunction(()=>document.querySelector('.console pre')?.textContent.includes('playwright'));
      await page.screenshot({path:path.join(root,`.runtime/dashboard-${width}.png`),fullPage:true});
      const run=await page.evaluate(async()=> (await fetch('/api/runs/20260908-203211-6bb7f6')).json());
      if (run.evidence_cases.length !== 6) throw Error('Expected six real cases, got '+run.evidence_cases.length);
      if (page.url().includes('access_token')) throw Error('Token remains in URL');
      await page.getByRole('button',{name:'E2E 证据',exact:true}).click();
      if (await page.locator('.report-links a').count() !== 12) throw Error('Expected six reports and six traces');
      const zip=await context.request.get(origin+run.trace_downloads[0].url);
      if (!zip.ok() || (await zip.body()).subarray(0,2).toString()!=='PK') throw Error('Trace download');
      const video = run.evidence_cases[0].attachments.find(a=>a.type==='video');
      const videoResponse=await context.request.get(origin+video.url,{headers:{Range:'bytes=0-127'}});
      if (videoResponse.status()!==206) throw Error('Video byte-range streaming');
      if (width===1440) {
        const report=await context.newPage();
        report.on('pageerror',e=>console.error('Report:',e.message));
        report.on('console',m=>{if(m.type()==='error')console.error('Report console:',m.text().slice(0,300));});
        await report.goto(origin+run.test_reports[0].url);
        await report.getByText('[E01] {create} Browser creates a durable robot and opens its conversation',{exact:true}).click();
        await report.locator('video').first().waitFor();
        await report.locator('video').first().evaluate(element=>element.load());
        await report.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
        await report.close();
      }
      await page.getByRole('button',{name:'运行日志',exact:true}).click();
      await page.getByLabel('日志阶段').selectOption('E03');
      await page.waitForFunction(()=>document.querySelector('.console pre')?.textContent.includes('playwright'));
      await page.getByRole('button',{name:'代码发现',exact:true}).click();
      await page.getByText('尚无结构化 Agent 检视记录',{exact:true}).first().waitFor();
      await page.getByRole('button',{name:'交付记录',exact:true}).click();
      await page.getByRole('button',{name:'关键能力',exact:true}).click();
      await page.getByRole('heading',{name:'关键能力与门禁'}).waitFor();
      await page.getByRole('button',{name:'检视总览',exact:true}).click();
      await page.getByPlaceholder('搜索仓库、PR 或标题').fill('101');
      if (!await page.locator('tbody tr').count()) throw Error('Filter lost actual run');
      if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('Page overflow');
      await page.getByRole('button',{name:'运行环境',exact:true}).click();
      await page.getByRole('heading',{name:'GitHub 本地监听'}).waitFor();
      await page.getByText('监听中',{exact:true}).waitFor();
      await page.screenshot({path:path.join(root,`.runtime/monitor-${width}.png`),fullPage:true});
      if (await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('Monitor page overflow');
      if (errors.length) throw Error(errors.join('\n'));
      console.log(JSON.stringify({width,realCases:6,auth:true,tabs:true,logs:true,trace:true,overflow:false}));
      await context.close();
    }
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

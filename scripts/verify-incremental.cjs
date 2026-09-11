const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const config=JSON.parse(fs.readFileSync(path.join(root,'.runtime/pipeline-server.json'),'utf8'));
 const origin=config.public_base_url;
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  for(const width of [1440,1920,390]){
   const context=await browser.newContext({viewport:{width,height:1000}});
   const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(origin+'/?access_token='+encodeURIComponent(config.view_token));
   await page.getByRole('heading',{name:'PR 增量动态'}).waitFor();
   await page.waitForFunction(()=>document.querySelector('.history-toggle')?.textContent.match(/\d+ 条/));
   if(await page.locator('.repo').count()!==12)throw Error('Expected all + 11 repos');
   if(await page.locator('.history-toggle').getAttribute('aria-expanded')!=='false')throw Error('History not collapsed');
   await page.getByRole('button',{name:'PR 检视',exact:true}).click();
   await page.waitForURL(/\/reviews$/);
   await page.locator('.history-toggle').click();
   await page.waitForTimeout(500);
   await page.locator('.event-list').evaluate(e=>{e.scrollTop=0;});
   await page.screenshot({path:path.join(root,`.runtime/incremental-${width}.png`),fullPage:true});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width);
   const inv=await page.evaluate(async()=>(await fetch('/api/monitors')).json());
   console.log(JSON.stringify({width,monitors:inv.monitors.length,rows:await page.locator('.pr-event').count(),overflow:false}));
   await page.getByLabel('搜索 PR').fill('101');
   await page.locator('.repo').filter({hasText:'agent-governance-gw'}).click();
   await page.locator('.pr-event').filter({hasText:'#101'}).first().waitFor();
   await page.locator('.pr-event .event-main > .text-button').first().click();
   await page.waitForURL(/\/runs\//);
   await page.goto(origin+'/runs/20260908-203211-6bb7f6');
   await page.getByRole('heading',{name:/#101/}).waitFor();
   await page.getByRole('button',{name:'E2E 证据',exact:true}).click();
   await page.locator('.report-links a').first().waitFor();
   if(await page.locator('.report-links a').count()!==12)throw Error('Old evidence links lost');
   if(errors.length)throw Error(errors.join('\n'));
   await context.close();
  }
  // Isolated UI fixture: never submit or modify server records.
  const context=await browser.newContext({viewport:{width:1440,height:1000}});const page=await context.newPage();
  await page.goto(origin+'/?access_token='+encodeURIComponent(config.view_token));
  const run={id:'ui-fixture',repo:'rollingfruit/agent-governance-gw',pr_number:999,title:'UI fixture',status:'running',created_at:'2020-01-01T00:00:00Z',stages:[{id:'E02',name:'E02 私聊执行',status:'running'}],suites:[],evidence_cases:[]};
  await page.route('**/api/runs',r=>r.fulfill({json:{runs:[run]}}));
  await page.route('**/api/runs/ui-fixture',r=>r.fulfill({json:run}));
  await page.route('**/api/runs/ui-fixture/stages/E02/log',r=>r.fulfill({body:'fixture-only tool execution log'}));
  await page.reload();
  await page.locator('.live-title').click();
  await page.getByLabel('执行详情预览').waitFor();
  await page.waitForFunction(()=>document.querySelector('.preview-log')?.textContent.includes('fixture-only'));
  await page.screenshot({path:path.join(root,'.runtime/incremental-drawer-fixture.png')});
  if(await page.locator('.history-toggle').getAttribute('aria-expanded')!=='false')throw Error('Old active task hidden');
  await page.getByRole('button',{name:'打开完整检视详情'}).click();await page.waitForURL(/runs\/ui-fixture$/);
  console.log(JSON.stringify({fixtureOnly:true,oldRunningPinned:true,drawerLog:true,detailNavigation:true}));
  await context.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

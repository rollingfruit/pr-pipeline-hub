const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const output=path.resolve(__dirname,'../verification/batches');fs.mkdirSync(output,{recursive:true});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8793/');
  await page.locator('#suites input').first().waitFor();
  if(await page.locator('#codex').isChecked())throw Error('Code review must default off');
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Editor overflow '+width);
   await page.screenshot({path:path.join(output,'editor-'+width+'.png'),fullPage:true});
  }
  if(process.argv.includes('--submit')){
   await page.locator('#urls').fill('https://github.com/rollingfruit/agent-governance-gw/pull/104\nhttps://github.com/rollingfruit/semantic-schedule/pull/161');
   await page.locator('#resolve').click();
   await page.waitForFunction(()=>document.querySelector('#result').textContent.includes('解析完成'),{},{timeout:120000});
   if(await page.locator('#members tbody input:checked').count()!==2)throw Error('Expected two resolved members');
   if(!(await page.locator('#members tbody').innerText()).includes('可纳入'))throw Error('Unsafe selection');
   const response=page.waitForResponse(r=>r.url().endsWith('/api/batches')&&r.request().method()==='POST');
   await page.locator('#submit').click();
   const submitted=await response;if(!submitted.ok())throw Error(await submitted.text());
   await page.locator('#result a').waitFor({timeout:180000});
   const url=await page.locator('#result a').getAttribute('href');
   fs.writeFileSync(path.join(output,'submitted.json'),JSON.stringify({url}));
   console.log(JSON.stringify({submitted:url}));
  }
  await page.goto('http://119.8.233.58:8080/batches');
  await page.getByRole('heading',{name:'联合验证',exact:true}).waitFor();
  await page.locator('tbody tr').first().waitFor();
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Dashboard overflow '+width);
   await page.screenshot({path:path.join(output,'dashboard-'+width+'.png'),fullPage:true});
  }
  await page.locator('tbody tr .text-button').first().click();
  await page.getByRole('button',{name:'运行日志',exact:true}).waitFor();
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Detail overflow '+width);
   await page.screenshot({path:path.join(output,'detail-'+width+'.png'),fullPage:true});
  }
  for(const tab of ['运行日志','交付记录','E2E 证据','代码发现','总览']){
   await page.getByRole('button',{name:tab,exact:true}).click();
  }
  const batchId=new URL(page.url()).pathname.split('/')[2];
  const detail=await (await page.request.get('http://119.8.233.58:8080/api/batches/'+batchId)).json();
  const evidence={id:batchId,status:detail.status,failure_kind:detail.failure_kind,publication:detail.publication,archive:detail.archive,
    members:detail.members,deliveries:detail.deliveries};
  fs.writeFileSync(path.join(output,'latest-result.json'),JSON.stringify(evidence,null,2));
  if(detail.report_url&&!(await page.request.get(new URL(detail.report_url,'http://119.8.233.58:8080').href)).ok())throw Error('Report unavailable');
  if(!(await page.request.get('http://119.8.233.58:8080/api/runs/'+batchId+'/stages/build/log')).ok())throw Error('Build log unavailable');
  await page.goto('http://119.8.233.58:8080/history');
  await page.getByRole('heading',{name:'执行记录',exact:true}).waitFor();
  for(const endpoint of ['/internal/batches','/api/batches','/api/runs']){
   if((await page.request.post('http://119.8.233.58:8080'+endpoint,{data:{}})).ok())throw Error('Anonymous write exposed '+endpoint);
  }
  if((await page.request.post('http://127.0.0.1:8793/api/batches',{data:{}})).status()!==403)throw Error('Missing local token allowed');
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Batch editor/dashboard responsive checks and write protections passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

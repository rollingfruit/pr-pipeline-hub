const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const origin=JSON.parse(fs.readFileSync(path.join(root,'.runtime/pipeline-server.json'),'utf8')).public_base_url;
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const context=await browser.newContext();const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin+'/reviews');
  await page.getByRole('heading',{name:'PR 增量动态'}).waitFor();
  await page.locator('.pr-event').first().waitFor();
  const api=context.request;
  for(const url of ['/api/runs','/api/monitors','/api/e2e/suites']){
   if((await api.get(origin+url)).status()!==200)throw Error('Anonymous GET failed: '+url);
  }
  const run=await (await api.get(origin+'/api/runs/20260908-203211-6bb7f6')).json();
  for(const url of [run.test_reports[0].url,run.trace_downloads[0].url,'/api/runs/'+run.id+'/stages/E03/log']){
   if(!(await api.get(new URL(url,origin).href)).ok())throw Error('Artifact/log denied');
  }
  const worker=await api.post(origin+'/internal/claim',{data:{}});
  if(![401,403,404].includes(worker.status()))throw Error('Worker exposed');
  if((await api.post(origin+'/webhooks/github',{data:{}})).status()!==401)throw Error('Unsigned webhook accepted');
  if((await api.post(origin+'/api/runs',{data:{}})).ok())throw Error('Anonymous enqueue accepted');
  await page.goto(origin+'/reviews?access_token=obsolete');
  await page.getByRole('heading',{name:'PR 增量动态'}).waitFor();
  if(page.url().includes('access_token'))throw Error('Legacy token not stripped');
  if((await context.cookies()).some(c=>c.name==='pipeline_view_http'))throw Error('Viewer cookie still required');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({anonymousDashboard:true,anonymousReports:true,anonymousLogs:true,workerDenied:worker.status(),unsignedWebhookDenied:true,anonymousEnqueueDenied:true,legacyLinkClean:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

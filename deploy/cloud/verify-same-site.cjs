const {chromium}=require('playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 const out='D:/code/welink-micro/pr-pipeline-hub/.runtime/same-site-proof';fs.mkdirSync(out,{recursive:true});
 try{
 const context=await browser.newContext({proxy:{server:'http://127.0.0.1:15715'},viewport:{width:1440,height:1000}});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const host='http://119.8.233.58';
 for(const path of ['/pipeline/api/runs','/submit/api/catalog']){
  const r=await context.request.get(host+path);assert.equal(r.status(),401);
 }
 const forged=await context.request.get(host+'/pipeline/api/runs',{headers:{'X-Pipeline-User':'root','X-Worker-Token':'forged'}});assert.equal(forged.status(),401);
 await page.goto(host+'/pipeline/');await page.locator('#authUser').waitFor();
 await page.locator('#authUser').fill(process.env.ROBOT_CI_USER);
 await page.locator('#authPass').fill(process.env.ROBOT_CI_PASSWORD);
 await page.locator('#authPass').press('Enter');
 await page.waitForURL('**/pipeline/');await page.waitForTimeout(2000);
 assert.equal((await context.request.get(host+'/pipeline/api/runs')).status(),200);
 await page.goto(host+'/submit/');await page.locator('.repo').waitFor();
 await page.locator('.repo').first().selectOption('rollingfruit/agent-governance-gw');
 await page.waitForFunction(()=>document.querySelector('.head').options.length>0);
 await page.locator('.head').first().selectOption('main');
 await page.locator('#add').click();await page.locator('.repo').nth(1).selectOption('rollingfruit/multica-aiwelink');
 await page.waitForFunction(()=>document.querySelectorAll('.head')[1].options.length>0);
 await page.locator('.head').nth(1).selectOption('main');
 await page.locator('#resolve').click();await page.locator('#versions table').waitFor({timeout:180000});
 for(const width of [1440,1920,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:out+'/submit-'+width+'.png',fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
 console.log('resolved',await page.locator('#versions').innerText());
 if(process.env.PIPELINE_SUBMIT==='1'){
  assert(await page.locator('#risk').isHidden(),'High-risk confirmation required; do not auto approve');
  const receipt=page.waitForResponse(r=>r.url().endsWith('/submit/api/batches')&&r.request().method()==='POST');
  await page.locator('#submit').click();const response=await receipt;console.log('SUBMISSION',response.status());if(!response.ok())throw Error(await response.text());
  await page.waitForURL('**/pipeline/batches/**',{timeout:180000});
  console.log('BATCH_URL',page.url());fs.writeFileSync(out+'/batch-url.txt',page.url());
 }
 await page.goto(host+'/pipeline/runs/20260908-203211-6bb7f6');await page.waitForTimeout(1500);
 await page.screenshot({path:out+'/history.png',fullPage:true});
 const cross=await context.request.post(host+'/submit/api/batches',{headers:{Origin:'https://invalid.example'},data:{}});assert.equal(cross.status(),403);
 await context.request.post(host+'/api/auth/logout',{data:{}});
 assert.equal((await context.request.get(host+'/pipeline/api/runs')).status(),401);
 assert.equal(errors.length,0,errors.join('\n'));
 console.log('PASS login, identity rejection, branches, responsive layout, legacy route, cross-site denial, logout');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});

const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const out=path.resolve('pr-pipeline-hub/.runtime/robot-gamma');
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({storageState:path.join(out,'auth.json'),proxy:{server:'http://127.0.0.1:15715'}});
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://119.8.233.58/#/build/agent-governance-gw',{waitUntil:'networkidle'});
  const link=page.getByRole('link',{name:'查看 Gamma E2E 流程与报告',exact:true});
  await link.waitFor({timeout:60000});
  const href=await link.getAttribute('href');console.log('GAMMA_URL',href);
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   await page.screenshot({path:path.join(out,`result-${width}.png`),fullPage:true});
  }
  const popupPromise=context.waitForEvent('page');await link.click();const report=await popupPromise;
  await report.waitForLoadState('domcontentloaded');
  await report.getByText('构建产物验证：运行已交付的确切镜像；不代表 PR 合入验收，不修改 CCE 环境。',{exact:true}).waitFor({timeout:60000});
  console.log('REPORT', (await report.locator('body').innerText()).slice(0,11000));
  for(const width of [1440,1920,390]){
   await report.setViewportSize({width,height:1000});
   await report.screenshot({path:path.join(out,`evidence-${width}.png`),fullPage:true});
  }
  await report.getByRole('button',{name:'E2E 证据',exact:true}).click();
  const picker=report.locator('select').first();
  const option=await picker.locator('option').filter({hasText:'基线 E02'}).getAttribute('value');
  await picker.selectOption(option);
  await report.screenshot({path:path.join(out,'failed-e02.png'),fullPage:true});
  for(const name of ['video','trace']){
   const artifact=report.getByRole('link',{name,exact:true}).first();
   const url=await artifact.getAttribute('href');
   const response=await context.request.get(new URL(url,report.url()).href,{headers:{Range:'bytes=0-31'}});
   if(!response.ok())throw Error(name+' artifact HTTP '+response.status());
   console.log('ARTIFACT',name,response.status());
  }
  console.log('PAGE_ERRORS',errors);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

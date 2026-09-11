const {chromium}=require('playwright');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
 const output=path.resolve('pr-pipeline-hub/.runtime/robot-gamma');
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try{
  const context=await browser.newContext({storageState:path.join(output,'auth.json'),proxy:{server:'http://127.0.0.1:15715'},viewport:{width:1440,height:1000}});
  const page=await context.newPage();
  await page.goto('http://119.8.233.58/#/build/agent-governance-gw/job/3fe4149627dc',{waitUntil:'domcontentloaded'});
  await page.locator('.pl-title').filter({hasText:'gamma集成测试'}).click({timeout:60000});
  const link=page.locator('.step-log a').filter({hasText:'/batches/gamma-3fe4149627dc'});
  await link.waitFor({timeout:30000});
  assert.equal(await link.getAttribute('rel'),'noopener noreferrer');
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   await page.screenshot({path:path.join(output,`clickable-log-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  const opening=context.waitForEvent('page');await link.click();const report=await opening;
  await report.waitForLoadState('domcontentloaded');
  assert.equal(report.url(),'http://119.8.233.58:8080/batches/gamma-3fe4149627dc');
  console.log('PASS: deployed step-log link opens actual Gamma report in a new tab');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});

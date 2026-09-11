const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const out=path.resolve('pr-pipeline-hub/.runtime/robot-gamma');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'chrome'});
 try {
  const context=await browser.newContext({viewport:{width:1440,height:1000},proxy:{server:'http://127.0.0.1:15715'}});
  const page=await context.newPage();
  await page.goto('http://119.8.233.58/#/build/agent-governance-gw',{waitUntil:'networkidle'});
  if(await page.locator('#authUser').isVisible()){
   if(!process.env.ROBOT_CI_USER || !process.env.ROBOT_CI_PASSWORD)throw Error('Provide Robot CI credentials through the process environment');
   await page.locator('#authUser').fill(process.env.ROBOT_CI_USER);
   await page.locator('#authPass').fill(process.env.ROBOT_CI_PASSWORD);
   await page.locator('#authPass').press('Enter');
   await page.waitForTimeout(2500);
  }
  await page.getByText('个人构建流水线',{exact:true}).first().waitFor({timeout:60000});
  await page.getByRole('button',{name:'运行',exact:true}).click();
  await page.getByText('选择任务',{exact:true}).waitFor({timeout:90000});
  await page.locator('.pl-env-trigger').click();
  await page.getByRole('option',{name:'CI 隔离 E2E · 不修改 CCE',exact:true}).click();
  await page.getByRole('button',{name:'gamma测试',exact:true}).click();
  await page.waitForTimeout(4000);
  await page.locator('#previewBranchPicker .branch-trigger').click();
  await page.getByRole('option',{name:'main',exact:true}).click();
  console.log('BRANCH',await page.locator('#previewBranchPicker').innerText());
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   await page.screenshot({path:path.join(out,`configure-${width}.png`),fullPage:true});
  }
  await page.setViewportSize({width:1440,height:1000});
  if(process.env.ROBOT_GAMMA_SUBMIT==='1'){
   const response=page.waitForResponse(r=>r.url().endsWith('/api/push') && r.request().method()==='POST');
   await page.locator('#btnRunPreviewConfirm').click();
   const receipt=await (await response).json();
   fs.writeFileSync(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2));console.log('RECEIPT',JSON.stringify(receipt));
  }
  console.log((await page.locator('body').innerText()).slice(0,12000));
  await page.screenshot({path:path.join(out,'initial.png'),fullPage:true});
  await context.storageState({path:path.join(out,'auth.json')});
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});

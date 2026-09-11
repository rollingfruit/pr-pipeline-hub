// Isolated browser smoke test. No GitHub writes, queue submission or real E2E.
const {spawn}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const python=process.env.TEST_PYTHON;
if(!python)throw Error('Set TEST_PYTHON');
const source=`
import os
os.environ.update(PIPELINE_CLOUD_PROFILE='1',PIPELINE_SUBMIT_USER='operator',PIPELINE_SUBMIT_PASSWORD='browser-test',PIPELINE_EDITOR_URL='http://127.0.0.1:18973/submit/',PIPELINE_PUBLIC_BASE_URL='http://127.0.0.1:18973')
import control_client
control_client.rpc=lambda *args,**kwargs: {'monitors':[]}
from local_selection import Handler,ThreadingHTTPServer
class ProxyHandler(Handler):
    def do_GET(self):
        if self.path.startswith('/submit/'):self.path=self.path[len('/submit'):]
        super().do_GET()
server=ThreadingHTTPServer(('127.0.0.1',18973),ProxyHandler)
print('READY',flush=True)
server.serve_forever()
`;
(async()=>{
 const server=spawn(python,['-u','-c',source],{cwd:root,windowsHide:true});
 let browser;
 try{
  await new Promise((resolve,reject)=>{
   const timer=setTimeout(()=>reject(Error('Server timeout')),10000);
   server.stdout.on('data',data=>{if(data.toString().includes('READY')){clearTimeout(timer);resolve();}});
   server.once('exit',code=>{clearTimeout(timer);reject(Error('Server exit '+code));});
  });
  const unauthorized=await fetch('http://127.0.0.1:18973/submit/');
  if(unauthorized.status!==401)throw Error('Anonymous editor was accessible');
  browser=await chromium.launch({channel:'msedge',headless:true});
  const context=await browser.newContext({httpCredentials:{username:'operator',password:'browser-test'}});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  fs.mkdirSync(path.join(__dirname,'cloud'),{recursive:true});
  for(const width of [1440,1920,390]){
   await page.setViewportSize({width,height:1000});
   await page.goto('http://127.0.0.1:18973/submit/');
   await page.waitForFunction(()=>document.querySelectorAll('#suites input').length>0);
   for(const id of ['codex','github'])if(!await page.locator('#'+id).isDisabled()||await page.locator('#'+id).isChecked())throw Error(id+' not disabled');
   if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Horizontal overflow '+width);
   await page.screenshot({path:path.join(__dirname,'cloud',width+'.png'),fullPage:true});
  }
  if(errors.length)throw Error(errors.join('\n'));
  console.log('PASS cloud editor authentication, optional switches and layouts 1440/1920/390; no real E2E executed');
 }finally{
  if(browser)await browser.close();
  server.kill();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});

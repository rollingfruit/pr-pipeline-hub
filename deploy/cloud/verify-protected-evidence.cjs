const {chromium}=require('playwright');const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({headless:true,channel:'chrome'});try{
 const c=await b.newContext({storageState:'D:/code/welink-micro/pr-pipeline-hub/.runtime/robot-gamma/auth.json',proxy:{server:'http://127.0.0.1:15715'}});
 const host='http://119.8.233.58';
 const r=await c.request.get(host+'/pipeline/api/runs/gamma-5262d20a0486');assert.equal(r.status(),200);const run=await r.json();
 const items=(run.evidence_cases||[]).flatMap(t=>t.attachments||[]);
 const video=items.find(a=>a.type==='video');assert(video,'Archived video required');
 const range=await c.request.get(host+'/pipeline'+video.url,{headers:{Range:'bytes=0-31'}});assert.equal(range.status(),206);assert.equal((await range.body()).length,32);
 const report=await c.request.get(host+'/pipeline/artifacts/gamma-5262d20a0486/report.html');assert.equal(report.status(),200);assert.match(report.headers()['content-disposition'],/attachment/);
 const anonymous=await b.newContext({proxy:{server:'http://127.0.0.1:15715'}});
 const denied=await anonymous.request.get(host+'/pipeline'+video.url,{maxRedirects:0});assert.equal(denied.status(),302);
 const hook=await c.request.post(host+'/pipeline/webhooks/github',{data:{}});assert.equal(hook.status(),404);
 console.log('PASS protected video Range, HTML download, anonymous denial, retired webhook');
}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});

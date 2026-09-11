const {chromium}=require('playwright');
(async()=>{const b=await chromium.launch({headless:true,channel:'chrome'});try{
 const c=await b.newContext({storageState:'D:/code/welink-micro/pr-pipeline-hub/.runtime/robot-gamma/auth.json',proxy:{server:'http://127.0.0.1:15715'}});
 const r=await c.request.get('http://119.8.233.58/api/jobs/'+process.argv[2]);const j=await r.json();
 console.log(JSON.stringify({status:j.status,stage:j.stage,error:j.error,gamma:j.gamma_e2e,logs:j.logs?.slice(-5)},null,2));
}finally{await b.close()}})().catch(e=>{console.error(e);process.exit(1)});

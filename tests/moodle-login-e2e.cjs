// Fast login regression: isolated browser cookies, no proctoring/OS restrictions.
const {chromium}=require('@playwright/test');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const hash=v=>crypto.createHash('sha256').update(v||'').digest('hex').slice(0,8);
(async()=>{
 const root=path.resolve(__dirname,'..'),lab=path.resolve(root,'../../work/local-moodle');
 const c=JSON.parse(fs.readFileSync(path.join(lab,'credentials.json')));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const results=[];
 try {
  for(let i=0;i<10;i++){
   const context=await browser.newContext({ignoreHTTPSErrors:true});const page=await context.newPage();const trace=[];
   page.on('response',async r=>{
    try {
     const url=new URL(r.url());if(!url.pathname.endsWith('.php'))return;
     const cookies=(await r.request().allHeaders()).cookie||'';
     const sid=cookies.match(/MoodleSession=([^;]+)/)?.[1];
     const set=(await r.headersArray()).filter(h=>h.name.toLowerCase()==='set-cookie').map(h=>h.value.match(/^MoodleSession=([^;]*)/)?.[1]).filter(v=>v!==undefined);
     if(set.length||url.pathname.includes('/login/')||url.pathname==='/my/')trace.push({path:url.pathname,method:r.request().method(),status:r.status(),requestSid:hash(sid),setSids:set.map(hash)});
    }catch{}
   });
   await page.goto('https://localhost/login/index.php',{waitUntil:'domcontentloaded'});
   await page.locator('#username').fill(c.student);await page.locator('#password').fill(c.studentpass);await page.locator('#loginbtn').click();
   await page.waitForTimeout(1500);
   const ok=await page.locator('a[href*="/login/logout.php"]').count()>0;
   results.push({iteration:i+1,ok,url:new URL(page.url()).pathname,trace});console.log(JSON.stringify(results.at(-1)));
   await context.close();
  }
 } finally{await browser.close();}
 fs.writeFileSync(path.join(root,'tests/moodle-login-v140.json'),JSON.stringify(results,null,2));
 if(results.some(r=>!r.ok))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});

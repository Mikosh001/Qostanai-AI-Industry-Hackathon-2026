// Real Electron UI, local Moodle and AI/evidence pipeline; opt-in camera fixtures.
const { _electron: electron, expect: baseExpect } = require('@playwright/test');
const expect = baseExpect.configure({ timeout: 25000 });
const fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '..');
const work = path.resolve(root, '../../work/demo-v142');
const lab = path.resolve(root, '../../work/local-moodle');
const python = path.resolve(root, '../../work/sergek-venv/Scripts/python.exe');
const creds = JSON.parse(fs.readFileSync(path.join(lab,'credentials.json')));
const meta = JSON.parse(fs.readFileSync(path.join(lab,'lab.json')));
const output = path.join(work,'recording-'+Date.now());
fs.mkdirSync(output,{recursive:true});
const phases=[], frames=[];
let app, local, recording=false, captureTask, phase, elapsed, sid;
const pause = ms => new Promise(r=>setTimeout(r,ms));
async function capture() {
  const stamp = Date.now()-elapsed;
  const parts = await app.evaluate(async ({BrowserWindow})=>{
    const w=BrowserWindow.getAllWindows()[0];if(!w||w.isDestroyed())return [];
    const result=[];
    const base=await w.webContents.capturePage();result.push({bounds:{x:0,y:0,...base.getSize()},image:base.toPNG().toString('base64')});
    for(const view of w.contentView.children) {
      if(!view.webContents || view.webContents===w.webContents || !view.getVisible())continue;
      const image=await view.webContents.capturePage();if(image.isEmpty())continue;
      result.push({bounds:view.getBounds(),image:image.toPNG().toString('base64')});
    }
    return result;
  });
  if(!parts.length)return;
  const index=frames.length;
  frames.push({stamp,phase:phase?.id,parts:parts.map((p,i)=>{
    const name=`${String(index).padStart(5,'0')}-${i}.png`;fs.writeFileSync(path.join(output,name),Buffer.from(p.image,'base64'));return {bounds:p.bounds,file:name};
  })});
}
async function stage(title,text,target,action) {
  phase={id:phases.length,title,text,target,start:Date.now()-elapsed};phases.push(phase);
  await action();await pause(2200);phase.end=Date.now()-elapsed;
}
async function call(route,method='GET',body) {
  return local.evaluate(async ({route,method,body})=>{
    const r=await fetch('/api'+route,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    if(!r.ok)throw new Error(route+' '+await r.text());return r.json();
  },{route,method,body});
}
async function type(locator,text) {await locator.click();await locator.pressSequentially(text,{delay:110});}
(async()=>{
  app=await electron.launch({acceptDownloads:true,args:[root],cwd:root,env:{...process.env,SERGEK_TESTING:'1',SERGEK_DATA:path.join(output,'data'),SERGEK_PYTHON:python,SERGEK_CA_FILE:path.join(lab,'localhost.crt'),
    PYTHONPATH:path.join(root,'tests/fixtures/video-camera'),SERGEK_VIDEO_FIXTURE:path.join(work,'camera')},timeout:60000});
  local=await app.firstWindow();local.setDefaultTimeout(25000);
  await expect(local.getByRole('button',{name:'Moodle-ға кіру'})).toBeVisible();
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].setContentSize(1600,900));
  await local.evaluate(async password=>{
    let r=await fetch('/api/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password})});
    if(!r.ok)throw new Error(await r.text());
  },creds.teacherpass).catch(async()=>{
    // Desktop-authorized setup is performed via the normal UI if required.
    await local.getByRole('button',{name:'Мұғалім панелі'}).click();
    await local.getByLabel('Құпиясөз',{exact:true}).fill(creds.teacherpass);
    await local.getByRole('button',{name:'Құпиясөзді орнату'}).click();
    await expect(local.getByRole('heading',{name:'Бәрі бір панельде.'})).toBeVisible();
  });
  await call('/auth/login','POST',{password:creds.teacherpass});
  const p=await call('/profile');p.exam_mode='monitor';p.policy.camera_required=true;p.policy.microphone_required=false;p.policy.screen_recording=true;
  p.allowed_hosts=['localhost'];p.moodle_url='https://localhost/';p.platonus_url='https://localhost/';p.tls_pins={localhost:meta.fingerprint};
  await call('/profile','PUT',p);await call('/integration/moodle','PUT',{key:creds.sharedkey});
  await call('/integration/hub','PUT',{enabled:true,url:meta.hub,pairing_key:creds.hubkey});await call('/auth/logout','POST');
  await local.goto(local.url().split('?')[0]);
  fs.writeFileSync(path.join(work,'camera/choice.txt'),'portrait.jpg');
  elapsed=Date.now();recording=true;
  captureTask=(async()=>{while(recording){try{await capture();}catch(e){console.error('capture:',e.message);}await pause(240);}})();
  await stage('Sergек','Емтиханды қорғау мен дәлелдерді қарау — бір жүйеде.',4,async()=>{});
  let portal;
  await stage('01 · Студенттің кіруі','Moodle аккаунтымен қосымша ішінде кіру.',7,async()=>{
    await local.getByRole('button',{name:'Moodle-ға кіру'}).click();
    await expect.poll(()=>app.context().pages().some(p=>p.url().startsWith('https://localhost/')),{timeout:25000}).toBe(true);
    portal=app.context().pages().find(p=>p.url().startsWith('https://localhost/'));
    await type(portal.locator('#username'),creds.student);await type(portal.locator('#password'),creds.studentpass);await portal.locator('#loginbtn').click();
    await expect(portal.locator('a[href*="/login/logout.php"]').first()).toBeAttached();
  });
  await stage('02 · Moodle тестін таңдау','Sergек таңдалған емтиханнан автоматты ашылады.',5,async()=>{
    await portal.goto('https://localhost/course/view.php?id=2');
    await pause(1400);
    await portal.goto('https://localhost/mod/quiz/view.php?id=2').catch(e=>{if(!portal.isClosed()&&!String(e).includes('ERR_ABORTED'))throw e;});
    await expect(local.getByRole('button',{name:'Фотоға өту'})).toBeVisible();
  });
  await stage('03 · Бастапқы фото','Бір фото емтихан кезіндегі тұлғаны салыстыруға сақталады.',7,async()=>{
    await local.getByRole('checkbox').check();await local.getByRole('button',{name:'Фотоға өту'}).click();
    await expect(local.getByRole('button',{name:'Фотоға түсіру',exact:true})).toBeEnabled({timeout:30000});
    await local.getByRole('button',{name:'Фотоға түсіру',exact:true}).click();
    await expect(local.getByText('Бастапқы фото сақталды',{exact:true})).toBeVisible();
    sid=(await local.evaluate(async()=>(await window.sergek.invoke('snapshot')).session)).id;
  });
  let quiz;
  await stage('04 · Тестті бастау','Қорғаныс пен жазба Moodle-дегі Start attempt кезінде қосылады.',8,async()=>{
    await local.getByRole('button',{name:'Тест бетіне өту'}).click();
    await expect.poll(()=>app.context().pages().some(p=>p.url().startsWith('https://localhost/')),{timeout:25000}).toBe(true);
    quiz=app.context().pages().find(p=>p.url().startsWith('https://localhost/'));quiz.setDefaultTimeout(25000);
    await quiz.getByRole('button',{name:/Attempt quiz|Re-attempt quiz|Continue your attempt/}).click();
    const start=quiz.getByRole('button',{name:'Start attempt',exact:true});
    await expect.poll(async()=>await start.isVisible()||await quiz.locator('.que').count()>0,{timeout:25000}).toBe(true);
    if(await start.isVisible())await start.click();
    await expect(quiz.locator('.que').first()).toBeVisible();
    await quiz.locator('.que').first().locator('input[type=radio]').first().check();
    const snapshot=await local.evaluate(async()=>await window.sergek.invoke('snapshot'));if(snapshot.session.status!=='active')throw new Error('Exam not active');
  });
  await stage('05 · Телефон анықталды','Оқиға уақыты және камера мен экран үзіндісі сақталады.',6,async()=>{
    fs.writeFileSync(path.join(work,'camera/choice.txt'),'phone.jpg');
    await expect(local.getByText('Телефон байқалды',{exact:true})).toBeVisible({timeout:30000});
    await pause(7000);fs.writeFileSync(path.join(work,'camera/choice.txt'),'portrait.jpg');
  });
  await stage('06 · Жауаптарды тапсыру','Бес сұрақ аяқталады. Сессия автоматты жабылады.',6,async()=>{
    for(let i=1;i<5;i++){await quiz.getByRole('button',{name:'Next page',exact:true}).click();await expect(quiz.locator('.que').first()).toBeVisible();await quiz.locator('.que').first().locator('input[type=radio]').first().check();}
    await quiz.getByRole('button',{name:'Finish attempt ...',exact:true}).click();await quiz.getByRole('button',{name:'Submit all and finish',exact:true}).click();
    await quiz.getByRole('dialog').last().getByRole('button',{name:'Submit all and finish',exact:true}).click();
    await expect(local.getByRole('heading',{name:'Сессия аяқталды'})).toBeVisible({timeout:30000});
  });
  await stage('07 · Мұғалім панелі','Мұғалім қорғалған панельге кіріп, сессияны ашады.',6,async()=>{
    await local.getByRole('button',{name:'Басты бетке оралу'}).click();await local.getByRole('button',{name:'Мұғалім панелі'}).click();
    await type(local.getByLabel('Құпиясөз',{exact:true}),creds.teacherpass);await local.getByRole('button',{name:'Панельге кіру'}).click();
    await expect(local.locator('tbody tr').first()).toBeVisible();await local.locator('tbody tr').first().click();
    await local.locator('.timeline-event').filter({hasText:'Телефон анықталды'}).first().scrollIntoViewIfNeeded();
  });
  await stage('08 · Бейнедәлел және шешім','Камера, экран және уақыт белгісі мұғалімнің қарауына беріледі.',8,async()=>{
    await local.locator('.timeline-event').filter({hasText:'Телефон анықталды'}).first().click();
    await expect(local.locator('.evidence-view img')).toBeVisible();
    await local.locator('.player-controls button').click();await pause(2000);
    const screenButton=local.getByRole('button',{name:'Компьютер экраны',exact:true});if(await screenButton.count())await screenButton.first().click();
    await pause(1800);await local.getByLabel('Мұғалім пікірі').fill('Телефон камерада анық көрінеді. Үзінді тексерілді.');
    await local.getByRole('button',{name:'Растау',exact:true}).click();
    await expect(local.locator('.modal')).toHaveCount(0);
  });
  await stage('09 · Есеп дайын','Нақты басталу мен аяқталу уақыты. PDF есебін жүктеу.',3,async()=>{
    await local.evaluate(()=>window.scrollTo(0,0));
    const download=local.waitForEvent('download');
    await local.getByRole('link',{name:'PDF',exact:true}).click();
    await (await download).saveAs(path.join(output,'demo-report.pdf'));
  });
  recording=false;await captureTask;
  const report=await call('/sessions/'+sid);if(!report.events.some(e=>e.kind==='phone_detected'&&e.media&&e.verdict==='confirmed'))throw new Error('Confirmed phone evidence missing');
  fs.writeFileSync(path.join(output,'recording.json'),JSON.stringify({version:'1.4.2',source:'Real Electron UI + real local Moodle; opt-in camera fixture; OS restrictions disabled administrative recording profile',phases,frames,sid,started:report.session.started,ended:report.session.ended,phoneEvidenceConfirmed:true},null,2));
  fs.writeFileSync(path.join(work,'latest-recording.txt'),output);
  console.log(JSON.stringify({passed:true,output,frames:frames.length,phases:phases.length,phoneEvidenceConfirmed:true}));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{recording=false;if(captureTask)await captureTask;if(app)await app.close();});

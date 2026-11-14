/* The sign-in link, walked end to end (agentos/handoff.py).

   A real `bento serve` on a throwaway home with remote access OFF, the real shared Chromium,
   and stand-ins for the three things that aren't ours (stand_ins.py): a site with a sign-in
   wall, a brain that only calls Bento's tools, and Telegram's Bot API. A phone-sized browser
   plays the person's phone.

       node packaging/dev/handoff-e2e/run.js [out-dir]

   It prints FINDINGS (empty when everything held) and writes screenshots to out-dir. */
const {chromium}=require('playwright');
const {spawn,execFileSync}=require('child_process');
const fs=require('fs'),path=require('path'),net=require('net'),os=require('os');
const ROOT=path.resolve(__dirname,'../../..');
const OUT=path.resolve(process.argv[2]||fs.mkdtempSync(path.join(os.tmpdir(),'handoff-e2e-')));
const HOME=path.join(OUT,'home');
const P={server:8671,site:8672,brain:8673,tg:8674,door:8677};
const PY=fs.existsSync(path.join(ROOT,'.venv/bin/python'))?path.join(ROOT,'.venv/bin/python'):'python3';
const PASSWORD='correct-horse-battery';
const FINDINGS=[];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const j=async(url,opt)=>{const r=await fetch(url,opt);return r.json()};
const api=(p,method,body)=>j(`http://127.0.0.1:${P.server}${p}`,{method:method||'GET',
  headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
const sent=()=>j(`http://127.0.0.1:${P.tg}/sent`);
const inject=b=>j(`http://127.0.0.1:${P.tg}/inject`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const check=(ok,what)=>{console.log((ok?'  ✓ ':'  ✗ ')+what);if(!ok)FINDINGS.push(what)};
async function until(fn,what,ms=40000){const end=Date.now()+ms;for(;;){const v=await fn().catch(()=>null);if(v)return v;
  if(Date.now()>end){FINDINGS.push('timed out: '+what);throw new Error('timed out: '+what)}await sleep(250)}}
const portOpen=port=>new Promise(res=>{const s=net.connect(port,'127.0.0.1');s.on('connect',()=>{s.destroy();res(true)});s.on('error',()=>res(false))});

(async()=>{
  fs.rmSync(HOME,{recursive:true,force:true});fs.mkdirSync(path.join(HOME,'work'),{recursive:true});
  fs.writeFileSync(path.join(HOME,'config.json'),JSON.stringify({
    agent_name:'Aria',setup_complete:true,permissions_migrated:true,autonomy:'full',
    default_model:'custom/fake-1',workspace:path.join(HOME,'work'),port:P.server,
    handoff:{enabled:true,port:P.door},
    telegram:{enabled:true,bot_token:'123:TEST',owner_chat_id:0},
    providers:{custom:{enabled:true,base_url:`http://127.0.0.1:${P.brain}/v1`,api_key:'',models:['fake-1']}}}));
  const env=Object.assign({},process.env,{AGENTOS_HOME:HOME,AGENTOS_VAULT_KEYRING:'0',NO_PROXY:'127.0.0.1,localhost,hubgit.localhost',
    no_proxy:'127.0.0.1,localhost,hubgit.localhost',AGENTOS_TELEGRAM_API:`http://127.0.0.1:${P.tg}`,
    AGENTOS_CHROMIUM:'/opt/pw-browsers/chromium'});
  // no AGENTOS_HANDOFF_BASE: the link carries this machine's own network address, as a real one does
  const kids=[
    spawn(PY,[path.join(__dirname,'stand_ins.py'),P.site,P.brain,P.tg,OUT],{env,stdio:['ignore',fs.openSync(path.join(OUT,'stand-ins.log'),'w'),2]}),
    spawn(PY,['-m','agentos','serve','--port',String(P.server)],{cwd:ROOT,env,stdio:['ignore',fs.openSync(path.join(OUT,'server.log'),'w'),fs.openSync(path.join(OUT,'server.err'),'w')]})];
  const stop=()=>kids.forEach(k=>{try{k.kill('SIGTERM')}catch(e){}});
  process.on('exit',stop);
  let browser;
  try{
    await until(()=>api('/api/platform'),'the server answers',90000);
    await api('/api/pricing','PUT',{model:'custom/fake-1',in:0,out:0});
    console.log('1. A machine with remote access off');
    const st=await api('/api/handoff');
    check(st.enabled&&st.how==='door'&&st.can.ok,'sign-in links are offered, through a door for one page (remote access is off)');
    check(!(await portOpen(P.door)),'nothing listens on the door\'s port before anybody asks');

    console.log('2. A Telegram turn meets a sign-in wall');
    await inject({text:'/start'});
    await until(async()=>(await sent()).some(m=>/Linked/.test(m.text||'')),'the chat is paired');
    await inject({text:'Push my branch and open the PR on Hubgit'});
    const wall=await until(async()=>(await sent()).find(m=>m.method==='sendPhoto'),'the wall is asked in the chat',90000);
    const rows=(wall.reply_markup||{}).inline_keyboard||[];
    check(/needs you on hubgit\.localhost/.test(wall.caption||''),'the chat is told which site needs them');
    check(/opens a door on your network for this one page/.test(wall.caption||''),'the offer says what opening it does, before any tap');
    check(/Passwords don't go through chat/.test(wall.caption||''),'a password is still never taken in the chat');
    check(rows.length===2&&rows[0][0].callback_data==='bw:open'&&rows[1][0].callback_data==='bw:done','two buttons: Open on this phone, and Done');
    check(!(await portOpen(P.door)),'offering it opened nothing');

    console.log('3. The person taps "Open on this phone"');
    await inject({tap:'bw:open',label:'Open on this phone'});
    const linkMsg=await until(async()=>(await sent()).find(m=>/\/handoff\//.test(m.text||'')),'the link arrives');
    const link=(linkMsg.text.match(/http:\/\/\S+\/handoff\/\S+/)||[])[0];
    check(!!link&&new RegExp(`^http://[0-9.]+:${P.door}/handoff/`).test(link)&&!link.includes('127.0.0.1'),'the link points at the door, on this machine\'s network address and its own port');
    check(/isn't encrypted beyond your Wi-Fi/.test(linkMsg.text),'the chat says a plain network address is not encrypted');
    check(!linkMsg.parse_mode,'it is sent as plain text (a link has underscores a formatter would eat)');
    check(await portOpen(P.door),'the door is open now');
    const cli=execFileSync(PY,['-m','agentos','handoff'],{cwd:ROOT,env}).toString();
    fs.writeFileSync(path.join(OUT,'terminal.txt'),'$ bento handoff\n'+cli);
    check(/Open now: hubgit\.localhost · sent, not opened yet/.test(cli),'`bento handoff` says what is open');

    // straight to this machine's own address: a sandbox's outbound proxy refuses a WebSocket to it
    browser=await chromium.launch({args:['--proxy-server=direct://','--proxy-bypass-list=*']});
    // the desk sees it too
    const desk=await browser.newContext({viewport:{width:1440,height:900},deviceScaleFactor:2});
    const dp=await desk.newPage();
    await dp.goto(`http://127.0.0.1:${P.server}/`);
    await dp.waitForFunction(()=>typeof openApp==='function');
    await dp.evaluate(()=>openApp('browser'));
    await dp.waitForSelector('.bw-hand',{timeout:20000}).catch(async e=>{await dp.screenshot({path:path.join(OUT,'debug-desk.png')});
      console.log('   debug:',await dp.evaluate(()=>({ask:(document.querySelector('.bw-ask')||{}).outerHTML||'no ask',wins:winsOf('browser').length})));throw e});
    await sleep(1500);
    await dp.screenshot({path:path.join(OUT,'handoff-desk-web-window.png')});
    check(/sign-in link for this page was sent to your phone/.test(await dp.textContent('.bw-hand')),'the Web window says a link was sent, with Close it');
    await dp.evaluate(()=>{closeWin&&winsOf('browser').forEach(w=>closeWin(w));openApp('syssettings')});
    await sleep(800);
    await dp.evaluate(()=>{const t=[...document.querySelectorAll('.wbody [data-t],.wbody button,.wbody a')].find(e=>/Remote access/i.test(e.textContent||''));t&&t.click()});
    await dp.waitForSelector('#rm-handoff',{timeout:15000}).catch(()=>FINDINGS.push('Settings → Remote access has no sign-in links card'));
    await dp.evaluate(()=>{const e=document.getElementById('rm-handoff');e&&e.scrollIntoView({block:'center'})});
    await sleep(600);
    await dp.screenshot({path:path.join(OUT,'handoff-settings.png')});
    await desk.close();

    console.log('4. The link is opened on the phone');
    const phoneCtx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,hasTouch:true,isMobile:true});
    const phone=await phoneCtx.newPage();
    const said=[];phone.on('console',m=>said.push(m.type()+': '+m.text()));phone.on('pageerror',e=>said.push('pageerror: '+e.message));
    phone.on('websocket',w=>{said.push('ws open '+w.url().replace(/handoff\/[^/]+/,'handoff/…'));w.on('close',()=>said.push('ws close'));w.on('socketerror',e=>said.push('ws error '+e))});
    // a chat app's preview is a GET: it must bind nothing
    const peek=await fetch(link);check(peek.status===200,'a preview fetch gets a page');
    await phone.goto(link);
    await phone.waitForSelector('text=Show the page');
    await phone.screenshot({path:path.join(OUT,'handoff-phone-1-landing.png')});
    await phone.tap('text=Show the page');
    await phone.waitForSelector('.code');
    const code=(await phone.textContent('.code')).trim();
    await phone.screenshot({path:path.join(OUT,'handoff-phone-2-code.png')});
    const ask=await until(async()=>(await sent()).find(m=>/Is that your screen/.test(m.text||'')),'the chat asks whose screen it is');
    check(ask.text.includes(code),'the chat names the number the phone shows');
    check(JSON.stringify(ask.reply_markup||{}).includes('bw:yes')&&JSON.stringify(ask.reply_markup||{}).includes('bw:no'),'with Yes and No under it');

    console.log('5. Somebody else has the link');
    const thiefCtx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,hasTouch:true,isMobile:true});
    const thief=await thiefCtx.newPage();
    await thief.goto(link);await thief.tap('text=Show the page');
    await thief.waitForSelector('text=This link is in use');
    await thief.screenshot({path:path.join(OUT,'handoff-phone-other-device.png')});
    check(true,'a second device is refused');
    await until(async()=>(await sent()).some(m=>/second device tried/.test(m.text||'')),'the chat hears about the second device');
    await thiefCtx.close();

    console.log('6. The person says it is their screen, and signs in');
    await inject({tap:'bw:yes',label:'Yes, that\'s my screen'});
    await phone.waitForSelector('.sv.live',{timeout:30000}).catch(async e=>{await phone.screenshot({path:path.join(OUT,'debug-phone.png')});console.log('   phone said:',said.slice(-12));throw e});
    await sleep(1500);
    await phone.screenshot({path:path.join(OUT,'handoff-phone-3-live.png')});
    const box=await phone.locator('.sv-cv').boundingBox();
    check(Math.abs(box.width-390)<2,'the page fills the phone, at the phone\'s width');
    // the stand-in site's fields sit at fixed places: username at y 148-196, password at 240-288
    await phone.touchscreen.tap(box.x+150,box.y+172);await sleep(300);
    await phone.keyboard.type('octo-ada',{delay:20});
    await phone.touchscreen.tap(box.x+150,box.y+264);await sleep(300);
    await phone.keyboard.type(PASSWORD,{delay:20});
    await sleep(700);
    const pic=await phone.evaluate(()=>{const c=document.querySelector('.sv-cv');return [c.width,c.height,c.clientWidth,c.clientHeight]});
    check(pic[0]===pic[2]&&pic[1]===pic[3],'the picture is still the page\'s size after a password is typed ('+pic.join('x')+')');
    await phone.screenshot({path:path.join(OUT,'handoff-phone-4-typed.png')});
    await phone.keyboard.press('Enter');
    await phone.waitForSelector('text=All done',{timeout:30000});
    await sleep(400);
    await phone.screenshot({path:path.join(OUT,'handoff-phone-5-done.png')});
    check(true,'the phone signed in on the real page, and the link closed by itself');

    console.log('7. The agent carries on, and nothing is left behind');
    await until(async()=>(await sent()).some(m=>/pushing the branch and opening the PR/.test(m.text||'')),'the agent carries on in the same session',60000);
    check(true,'the agent carried on in the signed-in session');
    await until(async()=>!(await portOpen(P.door)),'the door closes',15000);
    check(true,'the door is gone');
    const led=((await api('/api/audit?limit=200')).entries||[]).filter(r=>/^handoff\./.test(r.action)).reverse();
    const acts=led.map(r=>r.action);
    check(led.every(r=>r.surface==='telegram'),'each on the channel it was asked from');
    check(JSON.stringify(acts)===JSON.stringify(['handoff.open','handoff.join','handoff.refused','handoff.confirm','handoff.end']),
      'the ledger has every step: '+acts.join(', '));
    const all=await sent();
    fs.writeFileSync(path.join(OUT,'telegram.json'),JSON.stringify(all,null,1));
    const ticket=link.split('/handoff/')[1];
    stop();await sleep(2500);
    // what was typed, and the link, are nowhere on disk outside the browser's own profile
    const grep=(needle)=>{try{return execFileSync('grep',['-rIl','--exclude-dir=browser',needle,HOME]).toString().trim()}catch(e){return ''}};
    check(!grep(PASSWORD),'the password is in no file of the home (chat, diary, ledger, config)');
    check(!grep(ticket),'the link is in no file of the home');
  }catch(e){console.error(e);FINDINGS.push(String(e.message||e))}
  finally{if(browser)await browser.close();stop()}
  console.log('\nFINDINGS: '+(FINDINGS.length?'\n  - '+FINDINGS.join('\n  - '):'none'));
  console.log('screenshots in '+OUT);
  process.exit(FINDINGS.length?1:0);
})();

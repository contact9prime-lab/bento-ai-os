/* The sign-in link, walked end to end (agentos/handoff.py).

   A real `bento serve` on a throwaway home with remote access ON behind a passphrase, the
   real shared Chromium, and stand-ins for the three things that aren't ours (stand_ins.py):
   a site with a sign-in wall, a brain that only calls Bento's tools, and Telegram's Bot API.
   A phone-sized browser plays the person's phone: it opens the link, meets remote access's
   own sign-in page, signs in there, and only then gets the page.

       node packaging/dev/handoff-e2e/run.js [out-dir]

   It prints FINDINGS (empty when everything held) and writes screenshots to out-dir. */
const {chromium}=require('playwright');
const {spawn,execFileSync}=require('child_process');
const fs=require('fs'),path=require('path'),net=require('net'),os=require('os');
const ROOT=path.resolve(__dirname,'../../..');
const OUT=path.resolve(process.argv[2]||fs.mkdtempSync(path.join(os.tmpdir(),'handoff-e2e-')));
const HOME=path.join(OUT,'home');
const P={server:8671,site:8672,brain:8673,tg:8674,olddoor:8327};
const PY=fs.existsSync(path.join(ROOT,'.venv/bin/python'))?path.join(ROOT,'.venv/bin/python'):'python3';
const PASSWORD='correct-horse-battery';
const PASSPHRASE='walnut-harbour-lantern-42';   // remote access's lock, set at the machine
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
    handoff:{enabled:true},
    telegram:{enabled:true,bot_token:'123:TEST',owner_chat_id:0},
    providers:{custom:{enabled:true,base_url:`http://127.0.0.1:${P.brain}/v1`,api_key:'',models:['fake-1']}}}));
  const env=Object.assign({},process.env,{AGENTOS_HOME:HOME,AGENTOS_VAULT_KEYRING:'0',NO_PROXY:'127.0.0.1,localhost,hubgit.localhost',
    no_proxy:'127.0.0.1,localhost,hubgit.localhost',AGENTOS_TELEGRAM_API:`http://127.0.0.1:${P.tg}`,
    AGENTOS_CHROMIUM:'/opt/pw-browsers/chromium'});
  // no AGENTOS_HANDOFF_BASE: the link carries this machine's own network address, as a real one does
  const bento=(...args)=>execFileSync(PY,['-m','agentos',...args],{cwd:ROOT,env}).toString();
  console.log('1. With remote access off, nothing is offered');
  const off=bento('handoff');
  fs.writeFileSync(path.join(OUT,'terminal-remote-off.txt'),'$ bento handoff\n'+off);
  check(/Can't be offered now: Remote access is off/.test(off)&&/bento remote --on/.test(off),'`bento handoff` says remote access is off, and what turns it on');
  bento('remote','--on','--passphrase',PASSPHRASE);
  const kids=[
    spawn(PY,[path.join(__dirname,'stand_ins.py'),P.site,P.brain,P.tg,OUT],{env,stdio:['ignore',fs.openSync(path.join(OUT,'stand-ins.log'),'w'),2]}),
    spawn(PY,['-m','agentos','serve','--port',String(P.server)],{cwd:ROOT,env,stdio:['ignore',fs.openSync(path.join(OUT,'server.log'),'w'),fs.openSync(path.join(OUT,'server.err'),'w')]})];
  const stop=()=>kids.forEach(k=>{try{k.kill('SIGTERM')}catch(e){}});
  process.on('exit',stop);
  let browser;
  try{
    await until(()=>api('/api/platform'),'the server answers',90000);
    await api('/api/pricing','PUT',{model:'custom/fake-1',in:0,out:0});
    console.log('2. Remote access on, behind a passphrase');
    const st=await api('/api/handoff');
    check(st.enabled&&st.remote===true&&st.can.ok,'sign-in links are offered, through remote access');
    check(!(await portOpen(P.olddoor)),'there is no second door: nothing listens on a port of its own');

    console.log('3. A Telegram turn meets a sign-in wall');
    await inject({text:'/start'});
    await until(async()=>(await sent()).some(m=>/Linked/.test(m.text||'')),'the chat is paired');
    await inject({text:'Push my branch and open the PR on Hubgit'});
    const wall=await until(async()=>(await sent()).find(m=>m.method==='sendPhoto'),'the wall is asked in the chat',90000);
    const rows=(wall.reply_markup||{}).inline_keyboard||[];
    check(/needs you on hubgit\.localhost/.test(wall.caption||''),'the chat is told which site needs them');
    check(/sign in to your Bento's remote access, then the page opens/.test(wall.caption||''),'the offer says you sign in to remote access first, before any tap');
    check(/Passwords don't go through chat/.test(wall.caption||''),'a password is still never taken in the chat');
    check(rows.length===2&&rows[0][0].callback_data==='bw:open'&&rows[1][0].callback_data==='bw:done','two buttons: Open on this phone, and Done');

    console.log('4. The person taps "Open on this phone"');
    await inject({tap:'bw:open',label:'Open on this phone'});
    const linkMsg=await until(async()=>(await sent()).find(m=>/\/handoff\//.test(m.text||'')),'the link arrives');
    const link=(linkMsg.text.match(/http:\/\/\S+\/handoff\/\S+/)||[])[0];
    check(!!link&&new RegExp(`^http://[0-9.]+:${P.server}/handoff/`).test(link)&&!link.includes('127.0.0.1'),'the link is this Bento\'s own remote address: its network address and its own port');
    check(/You sign in to your Bento first/.test(linkMsg.text),'the chat says you sign in to your Bento first');
    check(/isn't encrypted beyond your Wi-Fi/.test(linkMsg.text),'the chat says a plain network address is not encrypted');
    check(!linkMsg.parse_mode,'it is sent as plain text (a link has underscores a formatter would eat)');
    const cli=bento('handoff');
    fs.writeFileSync(path.join(OUT,'terminal.txt'),'$ bento handoff\n'+cli);
    check(/Open now: hubgit\.localhost · sent, not opened yet/.test(cli)&&/goes through remote access/.test(cli),'`bento handoff` says what is open, and how a link gets in');

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

    console.log('5. Somebody who only has the link');
    // a chat app's preview is a GET with no session: it gets remote access's sign-in page
    const peek=await fetch(link);const peekText=await peek.text();
    check(peek.status===200&&/id="pw"/.test(peekText)&&!/BOOT=\{/.test(peekText)&&!/hubgit/i.test(peekText),'the link alone shows the sign-in page, with nothing of the page in it');
    const blind=await fetch(link+'/join',{method:'POST'});
    check(!/"state"/.test(await blind.text()),'and its routes answer nobody who is not signed in');
    const strangerCtx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,hasTouch:true,isMobile:true});
    const stranger=await strangerCtx.newPage();
    await stranger.goto(link);
    await stranger.waitForSelector('#pw');
    await stranger.fill('#pw','not-the-passphrase');await stranger.tap('#go');
    await stranger.waitForFunction(()=>(document.getElementById('err').textContent||'').length>0);
    await stranger.screenshot({path:path.join(OUT,'handoff-phone-stranger.png')});
    check(!(await stranger.$('.sv')),'a wrong passphrase stays on the sign-in page');
    check((await api('/api/handoff')).open.state==='sent','and the link is still unopened');
    await strangerCtx.close();

    console.log('6. The person opens it, signs in to remote access, and gets the page');
    const phoneCtx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:2,hasTouch:true,isMobile:true});
    const phone=await phoneCtx.newPage();
    const said=[];phone.on('console',m=>said.push(m.type()+': '+m.text()));phone.on('pageerror',e=>said.push('pageerror: '+e.message));
    phone.on('websocket',w=>{said.push('ws open '+w.url().replace(/handoff\/[^/]+/,'handoff/…'));w.on('close',()=>said.push('ws close'));w.on('socketerror',e=>said.push('ws error '+e))});
    await phone.goto(link);
    await phone.waitForSelector('#pw');
    await sleep(500);
    await phone.screenshot({path:path.join(OUT,'handoff-phone-1-remote-signin.png')});
    check(phone.url()===link,'the sign-in page is at the link\'s own address');
    await phone.fill('#pw',PASSPHRASE);
    await phone.screenshot({path:path.join(OUT,'handoff-phone-2-passphrase.png')});
    await phone.tap('#go');
    await phone.waitForSelector('.sv.live',{timeout:30000}).catch(async e=>{await phone.screenshot({path:path.join(OUT,'debug-phone.png')});console.log('   phone said:',said.slice(-12));throw e});
    check(phone.url()===link,'after signing in, the phone is back at the link');
    await until(async()=>(await sent()).some(m=>/open on your phone/.test(m.text||'')),'the chat hears it was opened');
    check(true,'the chat hears the page is open on the phone');
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
    check(!(await portOpen(P.olddoor)),'still no port of its own');
    const led=((await api('/api/audit?limit=200')).entries||[]).filter(r=>/^handoff\./.test(r.action)).reverse();
    const acts=led.map(r=>r.action);
    check(led.every(r=>r.surface==='telegram'),'each on the channel it was asked from');
    check(JSON.stringify(acts)===JSON.stringify(['handoff.open','handoff.join','handoff.end']),
      'the ledger has every step: '+acts.join(', '));
    const all=await sent();
    fs.writeFileSync(path.join(OUT,'telegram.json'),JSON.stringify(all,null,1));
    const ticket=link.split('/handoff/')[1];
    stop();await sleep(2500);
    // what was typed, and the link, are nowhere on disk outside the browser's own profile
    const grep=(needle)=>{try{return execFileSync('grep',['-rIl','--exclude-dir=browser',needle,HOME]).toString().trim()}catch(e){return ''}};
    check(!grep(PASSWORD),'the password is in no file of the home (chat, diary, ledger, config)');
    check(!grep(PASSPHRASE),'the remote passphrase is in no file of the home (only its hash)');
    check(!grep(ticket),'the link is in no file of the home');
  }catch(e){console.error(e);FINDINGS.push(String(e.message||e))}
  finally{if(browser)await browser.close();stop()}
  console.log('\nFINDINGS: '+(FINDINGS.length?'\n  - '+FINDINGS.join('\n  - '):'none'));
  console.log('screenshots in '+OUT);
  process.exit(FINDINGS.length?1:0);
})();

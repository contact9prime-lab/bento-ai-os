/* ================= terminal app ================= */
let xtermLoading=null;
function loadXterm(){
  if(window.Terminal&&window.FitAddon)return Promise.resolve();
  if(xtermLoading)return xtermLoading;
  xtermLoading=new Promise((res,rej)=>{
    const l=document.createElement('link');l.rel='stylesheet';l.href='/assets/xterm.css';document.head.appendChild(l);
    const s=document.createElement('script');s.src='/assets/xterm.js';
    s.onload=()=>{const s2=document.createElement('script');s2.src='/assets/xterm-addon-fit.js';
      s2.onload=res;s2.onerror=rej;document.head.appendChild(s2)};
    s.onerror=rej;document.head.appendChild(s);
  });
  return xtermLoading;
}
/* A Terminal window is a view onto a SESSION (agentos/ptyhub.py) that outlives it: close
   the window and the shell keeps running; open the Terminal again and it reattaches to
   the newest session nobody is watching, screen and all. The agent reads and types into
   the same sessions (terminal_read / terminal_send, through the gate), and when it types
   the window says so. Faces: GUI/SUI here; TUI `bento terminal` lists and ends sessions. */
async function renderTerminal(body,w,want){
  body.innerHTML='<div class="term-wrap"><div class="term-agent" hidden></div><div class="term-holder" style="flex:1;min-height:0;background:#0b0d10;padding:6px 2px 4px 8px"></div></div>';
  const holder=body.querySelector('.term-holder'),agentLine=body.querySelector('.term-agent');
  try{await loadXterm()}catch(e){holder.innerHTML='<p class="mut" style="padding:16px">could not load terminal assets</p>';return}
  if(want===undefined&&!w._session){
    // reattach to the newest session nobody is watching, if there is one
    try{const d=await apiJSON('/api/terminal/sessions');
      const free=(d.sessions||[]).filter(x=>x.alive&&!x.watching).pop();
      if(free){want=free.id;toast('Back in '+free.name+', still running')}}catch(e){}
  }
  want=want||w._session||'new';
  const term=new Terminal({fontSize:13,cursorBlink:true,scrollback:4000,
    fontFamily:"'SF Mono',ui-monospace,'Cascadia Code',Menlo,Consolas,monospace",
    theme:{background:'#0b0d10',foreground:'#e6ebf2',cursor:'#5eead4',cursorAccent:'#0b0d10',
      selectionBackground:'#234a55',black:'#171b22',brightBlack:'#5c6577'}});
  const fit=new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(holder);
  const tws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/terminal?session='+encodeURIComponent(want));
  const sendResize=()=>{if(tws.readyState===1)tws.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}))};
  tws.onopen=()=>{fit.fit();sendResize();term.focus()};
  tws.onmessage=e=>{
    if(e.data.charCodeAt(0)===0){            // control, never screen output
      let m;try{m=JSON.parse(e.data.slice(1))}catch(err){return}
      if(m.type==='session'){w._session=m.id;w._sname=m.name;const t=w.el.querySelector('.tname');if(t)t.textContent='Terminal · '+m.name}
      else if(m.type==='agent'){agentLine.hidden=false;agentLine.textContent=(m.who||'Agent')+' typed: '+m.text;
        clearTimeout(w._at);w._at=setTimeout(()=>{agentLine.hidden=true},6000)}
      return;
    }
    term.write(e.data);
  };
  tws.onclose=()=>{try{term.write('\r\n\x1b[90m[detached; the session may still be running. Reopen the Terminal to attach]\x1b[0m\r\n')}catch(e){}};
  term.onData(d=>{if(tws.readyState===1)tws.send(JSON.stringify({type:'input',data:d}))});
  const ro=new ResizeObserver(()=>{try{fit.fit();sendResize()}catch(e){}});
  ro.observe(holder);
  w.term=term;w.tws=tws;w.ro=ro;
  setTimeout(()=>{try{fit.fit();sendResize();term.focus()}catch(e){}},80);
}
/* Switch this window to another session (or a new one), keeping the window. */
function terminalAttach(w,id){
  try{w.ro?.disconnect();w.tws?.close();w.term?.dispose()}catch(e){}
  w._session=id==='new'?'':id;renderTerminal(w.el.querySelector('.wbody'),w,id);
}
async function terminalSessionsMenu(w){
  let d={sessions:[]};try{d=await apiJSON('/api/terminal/sessions')}catch(e){}
  const items=(d.sessions||[]).filter(x=>x.alive).map(x=>({label:esc((x.id===w._session?'● ':'')+x.name+
      (x.by!=='you'?' · by '+x.by:'')+(x.foreground?' · '+x.foreground:'')+(x.watching&&x.id!==w._session?' · open elsewhere':'')),
    fn:()=>terminalAttach(w,x.id)}));
  return items.concat([{label:'New session',fn:()=>terminalAttach(w,'new')},
    {label:'End this session',fn:async()=>{if(!w._session)return;
      await fetch('/api/terminal/sessions/'+encodeURIComponent(w._session),{method:'DELETE'});toast('Session ended')}}]);
}

/* ================= about app ================= */
function renderAbout(body){
  body.innerHTML=`<div class="pad" style="max-width:640px;margin:0 auto">
    <div style="text-align:center;padding-top:26px">
      <div style="width:64px;height:64px;border-radius:18px;margin:0 auto 14px;background:var(--acc-grad);display:flex;align-items:center;justify-content:center;color:var(--on-acc);font-size:30px;font-weight:900">▲</div>
      <div style="font-size:20px;font-weight:800">Bento Box AI</div>
      <div id="ab-ver" class="ab-ver">…</div>
      <p class="mut" style="margin:6px 0 16px">Your machine, with a brain.<br>Local or cloud AI — real actions, your approval.</p>
      <p class="mut" id="ab-info">…</p>
    </div>
    <div class="sect" style="margin-top:22px">What's new</div>
    <div id="ab-log" class="ab-log mut">…</div>
  </div>`;
  fetch('/api/system').then(r=>r.json()).then(d=>{
    const el=$('#ab-info');if(!el)return;
    el.textContent=`${d.cores} CPU cores · ${fmtBytes(d.mem.total_kb*1024)} RAM · ${fmtBytes(d.disk.total)} disk`;
  }).catch(()=>{});
  aboutVersion();
}
/* The version, whether there is a newer one, and what this build actually
   contains. About is where people look for "which one am I running" — answering
   only "AgentOS" was the version of that question nobody needed. The changelog
   is read from disk, so it describes the code that is running rather than
   whatever the website says. */
async function aboutVersion(){
  const v=$('#ab-ver'), log=$('#ab-log');
  try{
    const d=await (await fetch('/api/changelog?limit=4')).json();
    if(v)v.innerHTML=`<b>${esc(d.version||'?')}</b>`;
    if(log)log.innerHTML=(d.entries||[]).map(e=>
      `<details class="ab-entry"${(d.entries||[])[0]===e?' open':''}>
         <summary>${esc(e.title)}</summary>
         <div class="body">${md(e.body||'')}</div></details>`).join('')
      ||'<p class="mut">No changelog on this install.</p>';
  }catch(e){ if(log)log.textContent='could not read the changelog' }
  try{
    const u=await (await fetch('/api/update')).json();
    if(!v)return;
    if(u.update_available)
      v.innerHTML+=` <span class="ab-new">${esc(updWord(u))}</span>`
        +` <button class="endbtn" onclick="openApp('settings');SETTAB='system';localStorage.setItem('settab','system');refreshApp('settings')">Update…</button>`;
    else v.innerHTML+=` <span class="mut">· <a href="#" onclick="aboutCheck(this);return false">check for updates</a></span>`;
  }catch(e){}
}
/* What the news actually is. A version bump is a release; commits waiting on the
   tracked branch are the code — and between releases only the second one moves,
   so "0.2.0 available" while running 0.2.0 was the panel's way of saying nothing
   had happened when eight commits had. */
function updWord(u){
  const bumped=u.latest&&u.latest!==u.current;
  if(bumped)return `${u.latest} available`;
  const n=u.behind||0;
  return `${n} change${n===1?'':'s'} waiting on ${u.tracks||'the update branch'}`;
}
async function aboutCheck(a){
  a.textContent='checking…';
  try{
    const u=await (await fetch('/api/update?check=true')).json();
    a.parentElement.innerHTML=u.update_available
      ? `· <b style="color:var(--acc)">${esc(updWord(u))}</b>`
      // Up to date WITH WHAT — and a checkout on another branch says so, because
      // that is the commonest reason a push looks like it did nothing.
      : `· ${esc(u.error||(u.mismatch
            ? `up to date with ${u.tracks} — this copy is on ${u.on_branch}`
            : `up to date with ${u.tracks||'the update branch'}`))}`;
  }catch(e){a.textContent='could not check'}
}


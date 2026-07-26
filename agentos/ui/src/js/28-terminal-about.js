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
async function renderTerminal(body,w){
  body.innerHTML='<div style="flex:1;min-height:0;background:#0b0d10;padding:6px 2px 4px 8px"></div>';
  const holder=body.firstChild;
  try{await loadXterm()}catch(e){holder.innerHTML='<p class="mut" style="padding:16px">could not load terminal assets</p>';return}
  const term=new Terminal({fontSize:13,cursorBlink:true,scrollback:4000,
    fontFamily:"'SF Mono',ui-monospace,'Cascadia Code',Menlo,Consolas,monospace",
    theme:{background:'#0b0d10',foreground:'#e6ebf2',cursor:'#5eead4',cursorAccent:'#0b0d10',
      selectionBackground:'#234a55',black:'#171b22',brightBlack:'#5c6577'}});
  const fit=new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(holder);
  const tws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/terminal');
  const sendResize=()=>{if(tws.readyState===1)tws.send(JSON.stringify({type:'resize',cols:term.cols,rows:term.rows}))};
  tws.onopen=()=>{fit.fit();sendResize();term.focus()};
  tws.onmessage=e=>term.write(e.data);
  tws.onclose=()=>{try{term.write('\r\n\x1b[90m[session ended — close and reopen the Terminal to start a new one]\x1b[0m\r\n')}catch(e){}};
  term.onData(d=>{if(tws.readyState===1)tws.send(JSON.stringify({type:'input',data:d}))});
  const ro=new ResizeObserver(()=>{try{fit.fit();sendResize()}catch(e){}});
  ro.observe(holder);
  w.term=term;w.tws=tws;w.ro=ro;
  setTimeout(()=>{try{fit.fit();sendResize();term.focus()}catch(e){}},80);
}

/* ================= about app ================= */
function renderAbout(body){
  body.innerHTML=`<div class="pad" style="text-align:center;padding-top:30px">
    <div style="width:64px;height:64px;border-radius:18px;margin:0 auto 14px;background:linear-gradient(135deg,var(--acc),var(--acc2));display:flex;align-items:center;justify-content:center;color:#04211c;font-size:30px;font-weight:900">▲</div>
    <div style="font-size:20px;font-weight:800">AgentOS</div>
    <p class="mut" style="margin:6px 0 16px">Your machine, with a brain.<br>Local or cloud AI — real actions, your approval.</p>
    <p class="mut" id="ab-info">…</p>
  </div>`;
  fetch('/api/system').then(r=>r.json()).then(d=>{
    const el=$('#ab-info');if(!el)return;
    el.textContent=`${d.cores} CPU cores · ${fmtBytes(d.mem.total_kb*1024)} RAM · ${fmtBytes(d.disk.total)} disk`;
  }).catch(()=>{});
}


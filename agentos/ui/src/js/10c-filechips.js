/* ================= files a reply names: open them from where you read it =================
   Reported as: "it created the deck but I can't open it by clicking the file or the link in
   the chat". A reply that names a file now gets a chip for each one that really exists in a
   folder you can reach, with Open and Download. The server decides which names are files
   (/api/files/which over the reply's text, outputs.mentioned), so the page never probes the
   disk path by path, and a path a model invented outside your folders stays plain text.

   Open does what makes sense where you are. At the machine it opens in the app that owns
   the file (Keynote, PowerPoint, Preview) through /api/open. From a phone or another
   computer that would start the app in another room, so there it shows the file in the
   browser when a browser can show it, and downloads it when it cannot (a .pptx).
   The code span naming the file becomes a link that does the same.

   Faces: GUI and SUI (this page). The TUI prints the path, and `bento files` lists recent
   ones. Telegram and WhatsApp get the files themselves as documents after the reply
   (telegram.py / whatsapp.py send_files). `var`, not `let`: the bundle is one script. */
var FILECHIP_INLINE=/^(png|jpe?g|gif|webp|svg|pdf|txt|md|csv|json|log|html?)$/;
function fileChipIcon(ext){
  const c={pptx:'#f97316',ppt:'#f97316',key:'#f97316',docx:'#3b82f6',doc:'#3b82f6',pages:'#3b82f6',
    xlsx:'#22c55e',xls:'#22c55e',csv:'#22c55e',numbers:'#22c55e',pdf:'#ef4444',png:'#14b8a6',jpg:'#14b8a6',
    jpeg:'#14b8a6',gif:'#14b8a6',webp:'#14b8a6',svg:'#14b8a6',md:'#a5b4fc',txt:'#94a3b8',html:'#38bdf8',
    zip:'#eab308',json:'#fbbf24',py:'#60a5fa',js:'#fde047'}[ext]||'#94a3b8';
  return `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M6 3h8l5 5v13H6Z" fill="${c}" opacity=".18"/><path d="M6 3h8l5 5v13H6Z M14 3v5h5" fill="none" stroke="${c}" stroke-width="1.6" stroke-linejoin="round"/><text x="12.5" y="18" text-anchor="middle" font-size="5.2" font-weight="800" fill="${c}" font-family="system-ui,sans-serif">${esc((ext||'').slice(0,4).toUpperCase())}</text></svg>`;
}
function fileChipSize(n){return n<1024?n+' B':n<1e6?Math.round(n/1024)+' KB':(n/1e6).toFixed(1)+' MB'}
function fileGetURL(path,download){return '/api/files/get?path='+encodeURIComponent(path)+(download?'&download=1':'')}
async function fileOpen(path,ext){
  if(typeof remoteClient==='function'&&remoteClient()){
    // opening on the host would start an app in another room: show it here instead
    if(FILECHIP_INLINE.test(ext||''))window.open(fileGetURL(path),'_blank','noopener');
    else fileDownload(path);
    return;
  }
  try{
    const r=await fetch('/api/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:path})});
    const d=await r.json().catch(()=>({}));
    if(d.ok)toast('opened '+path.split('/').pop());
    else{toast('could not open it here, so it is downloading: '+(d.error||''));fileDownload(path)}
  }catch(e){fileDownload(path)}
}
function fileDownload(path){
  const a=document.createElement('a');a.href=fileGetURL(path,1);a.download=path.split('/').pop();
  document.body.appendChild(a);a.click();a.remove();
}
function fileChipHTML(f){
  return `<div class="fc" data-path="${esc(f.path)}" data-ext="${esc(f.ext)}">
    <button type="button" class="fc-main" title="${esc(f.path)}">${fileChipIcon(f.ext)}
      <span class="fc-txt"><b>${esc(f.name)}</b><small>${esc(fileChipSize(f.size))}</small></span></button>
    <button type="button" class="fc-act fc-open">Open</button>
    <button type="button" class="fc-act fc-dl" aria-label="Download ${esc(f.name)}">Download</button></div>`;
}
function fileChipWire(root){
  root.querySelectorAll('.fc:not([data-w])').forEach(c=>{
    c.dataset.w='1';const p=c.dataset.path,x=c.dataset.ext;
    c.querySelector('.fc-main').onclick=()=>fileOpen(p,x);
    c.querySelector('.fc-open').onclick=()=>fileOpen(p,x);
    c.querySelector('.fc-dl').onclick=()=>fileDownload(p);
  });
}
/* Every reply body under `root` that has not been looked at yet. One request per reply,
   and only for a reply that mentions something with a file extension at all. */
function fileChips(root){
  if(!root||!root.querySelectorAll)return;
  const bodies=root.matches&&root.matches('.body')?[root]:[...root.querySelectorAll('.body')];
  bodies.forEach(async b=>{
    if(b.dataset.fc)return;b.dataset.fc='1';
    const text=b.textContent||'';
    if(!/\.[A-Za-z0-9]{1,8}\b/.test(text))return;
    let d;
    try{const r=await fetch('/api/files/which',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:text.slice(0,20000)})});if(!r.ok)return;d=await r.json()}catch(e){return}
    const files=(d&&d.files)||[];if(!files.length||!b.isConnected)return;
    // the code span that names a file becomes a link to it
    b.querySelectorAll('code').forEach(c=>{
      if(c.closest('pre'))return;
      const t=c.textContent.trim(),f=files.find(x=>x.path===t||t.endsWith('/'+x.rel)||t===x.rel||t===x.name);
      if(!f)return;
      c.classList.add('fc-link');c.setAttribute('role','link');c.tabIndex=0;c.title='Open '+f.name;
      c.onclick=()=>fileOpen(f.path,f.ext);
      c.onkeydown=e=>{if(e.key==='Enter')fileOpen(f.path,f.ext)};
    });
    b.insertAdjacentHTML('beforeend',`<div class="fc-row">${files.map(fileChipHTML).join('')}</div>`);
    fileChipWire(b);
  });
}

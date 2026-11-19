/* ---------------- Settings → Permissions → Ethics (agentos/ethics.py) ----------------
   Asked for as "ethics has to be built somewhere for people to enable or disable". The answer
   drawn here: harm to YOU is yours to switch (typed confirmation before deleting a lot of your
   own things), harm to OTHERS and wiping the machine have no switch, because nobody's yes covers
   somebody else. The card says which is which, lists the sites you proved are yours, and lets you
   ask what the check would say about a command without running anything.

   Text nodes only: verdicts carry paths and commands. GUI and SUI: this card. TUI: `bento ethics`
   (show, check, own on|off, prove, proved, forget), and the approval card in `bento tui` and the
   terminal chat asks for the phrase the same way. */
var ETHICS={data:null,check:null,prove:null,busy:false};
function ethEl(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e}
function ethRow(label,desc,control,more){
  const r=ethEl('div','prow'),pl=ethEl('div','pl');
  pl.appendChild(ethEl('b','',label));
  if(more){const i=ethEl('button','pinfo','i');i.type='button';i.dataset.tip=more;i.setAttribute('aria-label',more);pl.appendChild(i)}
  if(desc)pl.appendChild(ethEl('small','',desc));
  r.appendChild(pl);
  const pc=ethEl('div','pc');if(control)pc.appendChild(control);r.appendChild(pc);
  return r;
}
function ethTag(text,kind){return ethEl('span','eth-tag '+(kind||''),text)}
async function ethicsPaint(){
  const box=document.getElementById('s-ethics');if(!box)return;
  let d;
  try{d=ETHICS.data=await apiJSON('/api/ethics')}
  catch(e){box.replaceChildren(ethEl('div','ghint mut',e.message||String(e)));return}
  const kids=[];
  // the one switch: your own things
  const sw=ethEl('label','psw'),cb=ethEl('input');cb.type='checkbox';cb.id='eth-own';cb.checked=!!d.own;
  sw.append(cb,ethEl('i'));
  cb.onchange=async()=>{
    try{await apiJSON('/api/ethics',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({own:cb.checked})});
      toast(cb.checked?'Deleting a lot of your own things is typed to confirm':'Your own deletes go through the ordinary gate',{kind:'ok'})}
    catch(e){cb.checked=!cb.checked;toast(e.message||String(e),{kind:'err'})}
  };
  kids.push(ethRow('Your own files','Type to confirm before an agent deletes a lot of your things.',sw,
    'Over 200 files or 200 MB, or anything outside your workspace. Bento counts them itself, so the AI can’t talk it down. This one is yours to switch off.'));
  const fixed=[['Someone else’s machines','Scanning, breaking into or flooding a machine that isn’t shown to be yours.','Refused',
                 'Nobody’s yes covers someone else, so there is no switch, at any autonomy level.'],
               ['Wiping the machine','Deleting the system, a disk or a whole home folder.','Refused','Refused whoever asks.'],
               ['Force pushes, and deletes it can’t read','History others share, or a delete whose target is hidden in a variable.','Typed',
                'A person types the words at a screen. A tap on a phone or a remembered grant never answers it.']];
  fixed.forEach(([l,desc,tag,more])=>kids.push(ethRow(l,desc,ethTag(tag,tag==='Refused'?'no':'typed'),more)));
  // your sites
  const sites=d.sites||[];
  const sl=ethEl('div','eth-sites');
  if(sites.length)sites.forEach(s=>{
    const t=ethEl('span','eth-site',s.host);
    const x=ethEl('button','endbtn','Forget');x.type='button';
    x.onclick=async()=>{try{await apiJSON('/api/ethics/sites/'+encodeURIComponent(s.host),{method:'DELETE'});ethicsPaint()}
      catch(e){toast(e.message||String(e),{kind:'err'})}};
    const w=ethEl('div','eth-siterow');w.append(t,x);sl.appendChild(w)});
  else sl.appendChild(ethEl('small','mut','None yet. This machine and the ones Bento set up already count.'));
  const pv=ethEl('button','endbtn','Prove a site…');pv.type='button';pv.onclick=()=>{ETHICS.prove=ETHICS.prove||{host:'',step:0};ethicsPaint()};
  const sitesRow=ethRow('Sites that are yours','Security tools may point only at machines shown to be yours.',pv,
    'Bento gives you a line to put at /.well-known/bento-proof.txt on the site, then fetches it. A sentence from you or the AI doesn’t count.');
  sitesRow.querySelector('.pl').appendChild(sl);
  kids.push(sitesRow);
  if(ETHICS.prove)kids.push(ethProveBox(d));
  kids.push(ethCheckBox());
  box.replaceChildren(...kids);
}
function ethProveBox(d){
  const p=ETHICS.prove,r=ethEl('div','prow stack eth-prove'),pl=ethEl('div','pl');
  const inp=ethEl('input');inp.type='text';inp.placeholder='example.com';inp.value=p.host||'';inp.autocomplete='off';
  const go=ethEl('button','endbtn',p.token?'Check it':'Get the line');go.type='button';
  const msg=ethEl('small','');
  if(p.token){
    msg.append(ethEl('span','','Put this line in '),ethEl('code','',p.url),ethEl('span','',': '),ethEl('code','',p.token));
  }
  if(p.err)msg.appendChild(ethEl('span','err',' '+p.err));
  go.onclick=async()=>{
    p.host=inp.value.trim();p.err='';
    try{const j=await apiJSON('/api/ethics/prove',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({host:p.host,check:!!p.token})});
      if(p.token){ETHICS.prove=null;toast(j.said||'Proved',{kind:'ok'})}else{p.token=j.token;p.url=j.url}}
    catch(e){p.err=e.message||String(e)}
    ethicsPaint();
  };
  const row=ethEl('div','eth-line');row.append(inp,go);
  pl.append(ethEl('b','','Prove a site is yours'),row,msg);r.appendChild(pl);return r;
}
function ethCheckBox(){
  const c=ETHICS.check||{line:'',v:null},r=ethEl('div','prow stack eth-check'),pl=ethEl('div','pl');
  const inp=ethEl('input');inp.type='text';inp.placeholder='rm -rf ~/Documents';inp.value=c.line;inp.autocomplete='off';inp.spellcheck=false;
  const go=ethEl('button','endbtn','Check');go.type='button';
  const run=async()=>{
    const line=inp.value.trim();if(!line)return;
    try{const v=await apiJSON('/api/ethics/check?command='+encodeURIComponent(line));ETHICS.check={line,v}}
    catch(e){ETHICS.check={line,v:{level:'error',why:e.message||String(e),facts:[]}}}
    ethicsPaint();
  };
  go.onclick=run;inp.onkeydown=k=>{if(k.key==='Enter')run()};
  const row=ethEl('div','eth-line');row.append(inp,go);
  pl.append(ethEl('b','','Try a command'),ethEl('small','','What the check would say. Nothing runs.'),row);
  if(c.v){
    const v=c.v,out=ethEl('div','eth-verdict '+v.level);
    out.appendChild(ethEl('b','',v.level==='ok'?'Nothing for the ethics check':v.level==='refuse'?'Refused':v.level==='caution'?'Typed to confirm':'Couldn’t check'));
    if(v.why)out.appendChild(ethEl('div','',v.why));
    const ul=ethEl('ul');(v.facts||[]).forEach(f=>ul.appendChild(ethEl('li','',f)));if(ul.children.length)out.appendChild(ul);
    if(v.confirm)out.appendChild(ethEl('div','mut','A person would type “'+v.confirm+'” at a screen.'));
    pl.appendChild(out);
  }
  r.appendChild(pl);return r;
}

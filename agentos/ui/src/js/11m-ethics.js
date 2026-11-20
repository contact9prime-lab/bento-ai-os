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
  // the second reading, by the machine's brain with no tools: it can only add typing
  const sel=ethEl('select');sel.id='eth-eval';
  [['flagged','When there are flags'],['risky','Every risky step'],['off','Off']].forEach(([v,l])=>{
    const o=ethEl('option','',l);o.value=v;if((d.evaluator||'flagged')===v)o.selected=true;sel.appendChild(o)});
  sel.onchange=async()=>{
    try{await apiJSON('/api/ethics',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({evaluator:sel.value})});
      toast('The ethics reviewer: '+sel.options[sel.selectedIndex].textContent.toLowerCase(),{kind:'ok'})}
    catch(e){toast(e.message||String(e),{kind:'err'})}
  };
  kids.push(ethRow('Ethics reviewer','A second reading of risky steps by your brain, with no tools.',sel,
    'It can only ask for typing, never allow anything. It costs a model call each time it reads.'));
  kids.push(ethEl('div','eth-sub'),ethEl('div','eth-lib'));
  box.replaceChildren(...kids);
  ethReportPaint(box.querySelector('.eth-sub'));
  ethLibraryPaint(box.querySelector('.eth-lib'));
}
const ETH_CLEAR='clear the flags';
async function ethReportPaint(el){
  if(!el)return;
  let rep;try{rep=await apiJSON('/api/ethics/report')}catch(e){return}
  const r=ethEl('div','prow stack eth-report'),pl=ethEl('div','pl');
  pl.append(ethEl('b','','This week'),
    ethEl('small','',rep.flags?(rep.flags+' flag'+(rep.flags===1?'':'s')+'. Your account’s score today is '+rep.account+' ('+rep.account_level+').'):'No flags this week.'));
  if(rep.by_category&&rep.by_category.length){
    const ul=ethEl('ul','eth-cats');
    rep.by_category.slice(0,5).forEach(c=>{const li=ethEl('li');li.append(ethEl('span','eth-n','+'+c.weight),ethEl('span','',c.words));ul.appendChild(li)});
    pl.appendChild(ul);
  }
  (rep.conversations||[]).filter(c=>c.ctx).slice(0,6).forEach(c=>{
    const w=ethEl('div','eth-conv');
    w.append(ethTag(c.score+' · '+c.level,'lv-'+c.level),ethEl('span','eth-ct',c.title||c.ctx));
    if(!c.cleared){const b=ethEl('button','endbtn','Clear…');b.type='button';b.onclick=()=>ethClearAsk(c.ctx,w);w.appendChild(b)}
    else w.appendChild(ethEl('small','mut','reviewed'));
    pl.appendChild(w);
  });
  r.appendChild(pl);el.replaceWith(r);
}
function ethClearAsk(cid,row){
  const box=ethEl('div','eth-line');
  const inp=ethEl('input');inp.type='text';inp.placeholder=ETH_CLEAR;inp.autocomplete='off';inp.spellcheck=false;
  inp.setAttribute('aria-label','Type '+ETH_CLEAR+' to clear');
  const go=ethEl('button','endbtn','Clear');go.type='button';go.disabled=true;
  inp.oninput=()=>{go.disabled=inp.value.trim().toLowerCase()!==ETH_CLEAR};
  go.onclick=async()=>{
    try{const j=await apiJSON('/api/ethics/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conversation:cid,typed:inp.value})});
      toast(j.cleared+' flag'+(j.cleared===1?'':'s')+' cleared for that conversation',{kind:'ok'});
      if(cid===currentConv)ethChipPaint(j);ethicsPaint()}
    catch(e){toast(e.message||String(e),{kind:'err'})}
  };
  box.append(ethEl('small','','Type “'+ETH_CLEAR+'”'),inp,go);row.after(box);inp.focus();
}
async function ethLibraryPaint(el){
  if(!el)return;
  let lib;try{lib=await apiJSON('/api/ethics/library')}catch(e){return}
  const up=ethEl('button','endbtn','Update');up.type='button';
  up.onclick=async()=>{up.disabled=true;up.textContent='Fetching…';
    try{const j=await apiJSON('/api/ethics/library/update',{method:'POST'});toast('Added '+j.added_programs+' programs and '+j.added_phrases+' phrases',{kind:'ok'});ethicsPaint()}
    catch(e){toast(e.message||String(e),{kind:'err'});up.disabled=false;up.textContent='Update'}};
  const row=ethRow('Library',lib.programs+' programs and '+lib.phrases+' phrases it recognises, from public sources.',up,
    'Updating fetches MITRE ATT&CK and ATLAS again and only adds to what shipped. Admins only.');
  const ul=ethEl('ul','eth-srcs');
  (lib.sources||[]).forEach(s=>{const li=ethEl('li');li.append(ethEl('b','',s.name),ethEl('small','',' '+s.licence));
    if(s.notice)li.appendChild(ethEl('div','mut',s.notice));ul.appendChild(li)});
  row.querySelector('.pl').appendChild(ul);
  el.replaceWith(row);
}
/* The chat's chip: the open conversation's ethics score, shown once it is above nothing.
   Tap it for the flags that built it. */
var ETH_CHIP={cid:'',st:null};
async function ethChipLoad(cid){
  ETH_CHIP.cid=cid||'';ETH_CHIP.st=null;ethChipPaint(null);
  if(!cid)return;
  try{const st=await apiJSON('/api/ethics/score?conversation='+encodeURIComponent(cid));if(ETH_CHIP.cid===cid)ethChipPaint(st)}catch(e){}
}
function ethChipPaint(st){
  const chip=document.getElementById('ethchip');if(!chip)return;
  if(st)ETH_CHIP.st=st;
  const s=ETH_CHIP.st;
  if(!s||(!s.score&&(s.account_level||'ok')==='ok')){chip.hidden=true;return}
  const lv=s.level||'ok';
  chip.hidden=false;chip.className='endbtn ethchip lv-'+lv;
  chip.textContent='⚖ '+s.score+(lv==='ok'?'':' · '+lv);
  chip.title='Ethics score '+s.score+' here ('+(s.conversation_level||lv)+'), '+s.account+' across your account. Tap for the flags.';
}
async function ethChipOpen(){
  const feed=document.getElementById('feed');if(!feed||!currentConv)return;
  const old=feed.querySelector('.eth-flagcard');if(old){old.remove();return}
  let st;try{st=await apiJSON('/api/ethics/score?conversation='+encodeURIComponent(currentConv))}catch(e){toast(e.message||String(e),{kind:'err'});return}
  ethChipPaint(st);
  const c=ethEl('div','eth-flagcard'),t=st.thresholds||{};
  c.append(ethEl('b','','⚖ Ethics score '+st.score+' ('+st.conversation_level+')'),
    ethEl('small','','Typed from '+t.caution+', and past '+t.hold+' no risky step runs. Your account today: '+st.account+'.'));
  const ul=ethEl('ul');
  (st.flags||[]).forEach(f=>{const li=ethEl('li');li.append(ethEl('span','eth-n','+'+f.weight),ethEl('span','',f.words+(f.detail?': '+f.detail:'')));ul.appendChild(li)});
  if(!ul.children.length)ul.appendChild(ethEl('li','mut','Only your account’s score is up.'));
  const rv=ethEl('button','endbtn','Review in Settings');rv.type='button';rv.onclick=()=>placeSettings('permissions','Ethics');
  c.append(ul,rv);feed.prepend(c);
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

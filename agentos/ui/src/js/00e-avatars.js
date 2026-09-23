/* ================= Characters: one face per agent, everywhere =================
   Every agent on this machine — your agent, you, and each specialist — has a small
   pixel-art character, and this file is how the DESKTOP shows it. It does not draw
   anybody: the server does (agentos/avatars.py), once, from one stored recipe, and
   every surface here asks it for the same PNG. That is the whole point — the
   specialist on the Crew stage, beside its message in Chat, on its line in Logs, on
   its card in Missions and on an approval card is the same person, because there is
   only one painter and one recipe, and a second painter here would be a second
   definition of a face waiting to drift.

   What lives here: the list (`/api/avatars`, loaded once and again on the
   `avatars` / `fabric_defs` events), `avatarImg()` which every surface calls, the
   repaint that swaps every face on screen in place after an edit, and the editor.
   An edit is saved on every click, so the whole desktop — chat, logs, the stage —
   changes while you watch; there is no Save button to forget.

   Faces — GUI/SUI: this. TUI: `bento avatar` prints the same characters as
   half-block pixels from the same grid. The characters are per person (your own
   database) and never per space: switching project does not change who your
   colleagues look like.

   Loaded before 01d (the Crew scene reads AVATARS). `var`, not `let`. */
var AVATARS={list:[],by:{},pal:null,loaded:false,pending:null,
  off:(()=>{try{return localStorage.getItem('avatars.off')==='1'}catch(e){return false}})()};

function avatarsLoad(){
  if(AVATARS.pending)return AVATARS.pending;
  AVATARS.pending=fetch('/api/avatars').then(r=>r.json()).then(d=>{
    AVATARS.list=d.avatars||[];AVATARS.pal=d.palette||null;
    AVATARS.by=Object.fromEntries(AVATARS.list.map(a=>[a.key,a]));
    AVATARS.loaded=true;
  }).catch(()=>{}).finally(()=>{AVATARS.pending=null});
  return AVATARS.pending;
}
/* Whose face a principal gets. Only CHARACTERS get one: your agent (the `user`
   principal is your agent acting for you), you, and specialists. A flow, an app or
   the system is not a person, and giving one a face would be claiming it was. */
function avatarKeyOf(principal){
  const p=String(principal||'');
  if(p==='user'||p==='@agent')return '@agent';
  if(p==='@me')return '@me';
  if(p.startsWith('subagent:'))return p.slice(9);
  return '';
}
function avatarSrc(key,o){
  o=o||{};
  const a=AVATARS.by[key],v=a?a.v:0;
  return '/api/avatar.png?key='+encodeURIComponent(key)
    +(o.sheet?'&sheet=1':o.crop===''?'':'&crop='+(o.crop||'face'))
    +(o.frame?'&frame='+o.frame:'')+'&v='+v;
}
/* The one way a face goes on screen. `data-av` is what the repaint looks for; the
   alt text is the character in words, which is also what a screen reader hears. */
function avatarImg(key,cls,o){
  if(!key||AVATARS.off)return '';
  const a=AVATARS.by[key];
  const label=a?a.label:key, about=a?a.about:'';
  return `<img class="av ${cls||''}" data-av="${esc(key)}" src="${avatarSrc(key,o)}" alt="${esc(about||label)}" title="${esc(label)}${about?' — '+esc(about):''}" draggable="false">`;
}
/* A chat header: the face, then the label. The live relabel (engine_info) goes
   through here too, or it would wipe the face it did not know was there. */
function chatWho(key,label){return avatarImg(key,'av-who')+label}
/* After an edit, every face already on screen changes in place — chat history,
   log rows, cards — rather than on the next render. */
function avatarsRepaint(){
  document.querySelectorAll('img.av[data-av]').forEach(img=>{
    const k=img.dataset.av,a=AVATARS.by[k];if(!a)return;
    const u=new URL(img.src,location.href);
    if(u.searchParams.get('v')!==String(a.v)){u.searchParams.set('v',a.v);img.src=u.pathname+u.search}
    img.alt=a.about||a.label;img.title=a.label+(a.about?' — '+a.about:'');
  });
  document.querySelectorAll('.av-sprite[data-av]').forEach(el=>{
    const a=AVATARS.by[el.dataset.av];if(a)el.style.backgroundImage=`url("${avatarSrc(el.dataset.av,{sheet:1})}")`;
  });
  if(typeof crewAvatarsChanged==='function')crewAvatarsChanged();
}
function avatarsChanged(){return avatarsLoad().then(avatarsRepaint)}
function setAvatarsOff(off){
  AVATARS.off=!!off;try{localStorage.setItem('avatars.off',off?'1':'0')}catch(e){}
  if(typeof refreshApp==='function'){refreshApp('chat');refreshApp('logs');refreshApp('settings')}
}
/* A full, animated figure: the four-frame sheet as a background, stepped by CSS —
   stand, blink, wave one arm, then the other. No timer, so nothing to stop when it
   is removed, and reduced motion holds it on the first frame (21-avatars.css). */
function avatarSprite(key,px){
  const u=Math.max(2,Math.round((px||104)/26));
  return `<div class="av-sprite" data-av="${esc(key)}" style="--u:${u}px;background-image:url('${avatarSrc(key,{sheet:1})}')" role="img" aria-label="${esc((AVATARS.by[key]||{}).about||key)}"></div>`;
}

/* ---- the editor ----
   One dialog, the dialog kit every other prompt uses. Each choice is saved the
   moment it is clicked and the whole desktop repaints, so the thing you are
   editing changes in Chat, in Logs and on the stage behind the dialog while you
   pick. The options are the server's own closed set (`palette`), so nothing can be
   offered here that the server would then refuse. */
async function avatarEdit(key){
  await avatarsLoad();
  const a=AVATARS.by[key];if(!a||!AVATARS.pal){if(typeof toast==='function')toast('No character called '+key);return}
  const P=AVATARS.pal;
  const scr=document.createElement('div');scr.className='dlg-scrim';
  const sw=(field,items,cur,rgbOf)=>items.map(it=>{
    const val=field==='hue'?it.hue:it.i;const on=val===cur;
    return `<button class="ave-sw${on?' on':''}" data-f="${field}" data-v="${val}" title="${esc(it.name)}" aria-label="${esc(it.name)}" aria-pressed="${on}" style="--c:rgb(${rgbOf(it).join(',')})"></button>`}).join('');
  const draw=()=>{
    const r=AVATARS.by[key].recipe;
    scr.querySelector('.ave-stage').innerHTML=avatarSprite(key,208);
    scr.querySelector('.ave-about').textContent=AVATARS.by[key].about;
    scr.querySelector('.ave-rows').innerHTML=`
      <div class="ave-row"><span>Skin</span><div>${sw('skin',P.skin,r.skin,x=>x.rgb)}</div></div>
      <div class="ave-row"><span>Hair</span><div>${sw('hair',P.hair,r.hair,x=>x.rgb)}</div></div>
      <div class="ave-row"><span>Style</span><div class="ave-chips">${P.style.map(s=>`<button class="ave-chip${s===r.style?' on':''}" data-f="style" data-v="${s}" aria-pressed="${s===r.style}">${s}</button>`).join('')}</div></div>
      <div class="ave-row"><span>Shirt</span><div>${sw('hue',P.shirt,r.hue,x=>x.rgb)}</div></div>
      <div class="ave-row"><span>Trousers</span><div>${sw('pants',P.pants,r.pants,x=>x.rgb)}</div></div>
      <div class="ave-row"><span>Extras</span><div class="ave-chips">
        <button class="ave-chip${r.glasses?' on':''}" data-f="glasses" data-v="${!r.glasses}" aria-pressed="${!!r.glasses}">glasses</button>
        <button class="ave-chip${r.blush?' on':''}" data-f="blush" data-v="${!r.blush}" aria-pressed="${!!r.blush}">blush</button></div></div>`;
    scr.querySelectorAll('[data-f]').forEach(b=>b.onclick=async()=>{
      const f=b.dataset.f;let v=b.dataset.v;
      v=(f==='style')?v:(f==='glasses'||f==='blush')?(v==='true'):Number(v);
      const res=await fetch('/api/avatars/'+encodeURIComponent(key),{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({[f]:v})}).then(r=>r.json()).catch(()=>({error:'the server did not answer'}));
      if(res.error){if(typeof toast==='function')toast(res.error);return}
      await avatarsChanged();draw();
    });
  };
  scr.innerHTML=`<div class="dlg ave" role="dialog" aria-modal="true" aria-label="Character of ${esc(a.label)}">
      <div class="dlg-t">${esc(a.key==='@me'?'Your character':a.label)}</div>
      <div class="dlg-m">${a.key==='@me'?'You, as the crew sees you — beside your messages.'
        :a.key==='@agent'?'Your agent — in the middle of the stage, and beside every reply.'
        :'This specialist, everywhere it appears: the stage, chat, logs and Missions.'}</div>
      <div class="ave-body"><div class="ave-stage"></div><div class="ave-rows"></div></div>
      <div class="ave-about mut"></div>
      <div class="dlg-b"><button class="ave-reroll" title="A new look, keeping the shirt colour">Surprise me</button><button class="dlg-ok">Done</button></div></div>`;
  document.body.appendChild(scr);
  draw();
  const close=()=>scr.remove();
  scr.querySelector('.dlg-ok').onclick=close;
  scr.onclick=e=>{if(e.target===scr)close()};
  scr.addEventListener('keydown',e=>{if(e.key==='Escape')close()});
  scr.querySelector('.ave-reroll').onclick=async()=>{
    await fetch('/api/avatars/'+encodeURIComponent(key)+'/reroll',{method:'POST'});
    await avatarsChanged();draw();
  };
  scr.querySelector('.dlg-ok').focus();
}
avatarsLoad();

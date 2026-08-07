/* ================= app icon system =================
   Squircle tiles: a curated duotone gradient + a white SVG glyph per app.
   Unknown / user-built apps fall back to their emoji on a generated gradient tile. */
const ICONS={
  chat:['#4AA9FF','#0A5FD9','<path d="M12 4.3c-4.5 0-8.1 2.9-8.1 6.5 0 2 1.1 3.9 2.9 5.1l-.6 3.6 3.6-1.9c.7.1 1.4.2 2.2.2 4.5 0 8.1-2.9 8.1-6.5S16.5 4.3 12 4.3Z"/><path d="M8.6 10.8h.01M12 10.8h.01M15.4 10.8h.01" stroke-width="2.3"/>'],
  taskmgr:['#6B7684','#39414E','<path d="M3.8 12.2h3.6l2.4-5.8 4.2 11.2 2.4-5.4h3.8"/>'],
  terminal:['#4A5160','#1E222B','<path d="M6.5 8.2l4 3.8-4 3.8"/><path d="M12.8 16.4h4.7"/>'],
  browser:['#38BDF8','#0369A1','<circle cx="12" cy="12" r="7.8"/><path d="M4.2 12h15.6"/><path d="M12 4.2c2.3 2.2 3.6 4.9 3.6 7.8s-1.3 5.6-3.6 7.8c-2.3-2.2-3.6-4.9-3.6-7.8S9.7 6.4 12 4.2Z"/>'],
  files:['#60A5FA','#2563EB','<path d="M4 7.3c0-.8.6-1.4 1.4-1.4h4.1l1.9 2.4h7.2c.8 0 1.4.6 1.4 1.4v7.9c0 .8-.6 1.4-1.4 1.4H5.4c-.8 0-1.4-.6-1.4-1.4Z"/><path d="M4 10.7h16"/>'],
  apps:['#A78BFA','#6D28D9','<rect x="4.6" y="4.6" width="6" height="6" rx="1.7"/><rect x="13.4" y="4.6" width="6" height="6" rx="1.7"/><rect x="4.6" y="13.4" width="6" height="6" rx="1.7"/><rect x="13.4" y="13.4" width="6" height="6" rx="1.7"/>'],
  control:['#94A3B8','#475569','<path d="M4.5 8.2h6.6m4.2 0h4.2M4.5 15.8h2.4m4.2 0h8.4"/><circle cx="13.5" cy="8.2" r="2.1"/><circle cx="9" cy="15.8" r="2.1"/>'],
  models:['#C084FC','#7C3AED','<rect x="7.2" y="7.2" width="9.6" height="9.6" rx="2"/><path d="M10 4.2v3M14 4.2v3M10 16.8v3M14 16.8v3M4.2 10h3M4.2 14h3M16.8 10h3M16.8 14h3"/>'],
  memory:['#2DD4BF','#0D9488','<path d="M12 4.4 19 8l-7 3.6L5 8Z"/><path d="M5 12l7 3.6L19 12M5 16l7 3.6 7-3.6"/>'],
  profile:['#22D3EE','#0891B2','<rect x="3.8" y="5.8" width="16.4" height="12.4" rx="2"/><circle cx="9" cy="10.8" r="1.7"/><path d="M6.3 15.6c.5-1.4 1.5-2.1 2.7-2.1s2.2.7 2.7 2.1M14.6 9.8h3.6M14.6 13h3.6"/>'],
  flowrun:['#FDBA74','#C2410C','<circle cx="5.6" cy="12" r="2"/><circle cx="18.4" cy="7.4" r="2"/><circle cx="18.4" cy="16.6" r="2"/><path d="M7.5 11.2l9-3.2M7.5 12.8l9 3.2"/>'],
  fabric:['#FB923C','#EA580C','<circle cx="9.2" cy="8.8" r="2.5"/><path d="M4.6 18c.6-2.7 2.4-4.1 4.6-4.1s4 1.4 4.6 4.1"/><circle cx="16.6" cy="9.4" r="2"/><path d="M15.7 13.7c1.8.3 3.2 1.5 3.8 3.4"/>'],
  kg:['#4ADE80','#16A34A','<circle cx="6.3" cy="7" r="2"/><circle cx="17.7" cy="6.6" r="2"/><circle cx="12" cy="17" r="2"/><path d="M7.2 8.8l3.8 6.4M16.8 8.4l-3.6 6.7M8.3 6.9l7.4-.3"/>'],
  spaces:['#F472B6','#BE185D','<rect x="4" y="4.6" width="7" height="7" rx="1.6"/><rect x="13" y="4.6" width="7" height="7" rx="1.6"/><rect x="4" y="13.4" width="7" height="7" rx="1.6"/><path d="M16.5 13.8v6.4M13.3 17h6.4"/>'],
  timeline:['#38BDF8','#1D4ED8','<path d="M6.4 4.4v15.2"/><circle cx="6.4" cy="8" r="1.8"/><circle cx="6.4" cy="16" r="1.8"/><path d="M10 8h9.6M10 16h6.4"/>'],
  gallery:['#F59E0B','#B45309','<rect x="3.6" y="5.2" width="16.8" height="13.6" rx="2"/><circle cx="8.6" cy="10" r="1.6"/><path d="M3.9 16.4l4.5-4.2 3.4 3.1 3-2.7 5.1 4.5"/>'],
  audit:['#94A3B8','#334155','<path d="M12 4.2v15.4M6.8 19.6h10.4"/><path d="M4 9.4h6.2l-3.1 5.2Z"/><path d="M13.8 9.4H20l-3.1 5.2Z"/><path d="M4.6 8.6 12 6.4l7.4 2.2"/>'],
  soul:['#818CF8','#4F46E5','<circle cx="12" cy="12" r="7.8"/><path d="M12 4.2a3.9 3.9 0 0 1 0 7.8 3.9 3.9 0 0 0 0 7.8"/><circle cx="12" cy="8.1" r=".95" fill="#fff" stroke="none"/><circle cx="12" cy="15.9" r=".95" fill="#fff" stroke="none"/>'],
  mcp:['#FBBF24','#D97706','<path d="M9.2 4.4v3.4M14.8 4.4v3.4"/><path d="M7 7.8h10v3.2a5 5 0 0 1-10 0Z"/><path d="M12 16v3.6"/>'],
  telegram:['#3EB6F1','#1D6FD2','<path d="M20.3 4.6 4.2 11.4l4.8 1.8 1.9 4.9 2.8-3.5 4.3 2Z"/><path d="M9 13.2l10.4-8"/>'],
  logs:['#A8A29E','#57534E','<path d="M7 4.6h6.8l3.8 3.8v11H7Z"/><path d="M13.6 4.8v3.8h3.8"/><path d="M9.6 12.6h4.8M9.6 15.6h4.8"/>'],
  tasks:['#F87171','#DC2626','<circle cx="12" cy="12" r="7.8"/><path d="M12 7.6V12l3 1.8"/>'],
  remotedesk:['#34D399','#064E3B','<rect x="2.6" y="4.4" width="13.4" height="9.2" rx="1.6"/><path d="M6.6 16.6h5.4"/><rect x="15.6" y="10.4" width="5.8" height="9.6" rx="1.6"/><path d="M17.9 18.2h1.2"/>'],
  hostscreen:['#38BDF8','#0C4A6E','<rect x="3.2" y="5" width="17.6" height="11.4" rx="1.8"/><path d="M8.4 19.4h7.2M12 16.4v3"/><path d="M6.6 12.6l2.6-2.6 2 2 3.2-3.4 3 3.2"/>'],
  automations:['#F0A93B','#C2410C','<path d="M13.2 3.6 5.4 13.4h5.1l-.7 7 7.8-9.8h-5.1Z"/>'],
  skills:['#34D399','#059669','<path d="M5.4 5.6c0-.9.7-1.6 1.6-1.6h11.6v14.4H7a1.6 1.6 0 0 0-1.6 1.6Z"/><path d="M5.4 5.6V20M9.3 8h5.4"/>'],
  policies:['#7C8CA3','#3A4759','<path d="M12 4.2 18.8 6.6v5c0 4-2.7 6.9-6.8 8.2-4.1-1.3-6.8-4.2-6.8-8.2v-5Z"/><path d="M9.3 12l1.9 1.9 3.5-3.7"/>'],
  store:['#3B82F6','#1E40AF','<path d="M6.2 8.6h11.6l-1 10.8H7.2Z"/><path d="M9.1 8.6V7.2a2.9 2.9 0 0 1 5.8 0v1.4"/>'],
  studio:['#FB7185','#E11D48','<path d="M14.9 6.1a4 4 0 0 0-5.3 5L4.5 16.2l3.3 3.3 5.1-5.1a4 4 0 0 0 5-5.3l-2.7 2.7-2-2Z"/>'],
  themes:['#F472B6','#DB2777','<path d="M12 4.2a7.8 7.8 0 1 0 0 15.6c1.2 0 1.9-.7 1.9-1.7 0-.6-.3-1-.7-1.4-.3-.4-.5-.7-.5-1.1 0-.9.8-1.6 1.9-1.6h1.6a3.5 3.5 0 0 0 3.5-3.4C19.6 6.9 16.1 4.2 12 4.2Z"/><circle cx="8.2" cy="9" r=".9" fill="#fff" stroke="none"/><circle cx="12" cy="7.4" r=".9" fill="#fff" stroke="none"/><circle cx="15.8" cy="9" r=".9" fill="#fff" stroke="none"/><circle cx="7.6" cy="13" r=".9" fill="#fff" stroke="none"/>'],
  personalize:['#2DD4BF','#0EA5E9','<rect x="4" y="5.2" width="16" height="13.6" rx="2"/><circle cx="9" cy="9.8" r="1.5"/><path d="M4.4 16.2l4.3-3.8 3.4 2.9 3-2.5 4.5 3.6"/>'],
  snapshots:['#67E8F9','#0E7490','<path d="M5.4 5.6v3.8h3.8"/><path d="M5.7 9.2A7.8 7.8 0 1 1 4.2 12"/><path d="M12 8.6V12l2.6 1.6"/>'],
  tokens:['#86EFAC','#16A34A','<path d="M5.2 19.4v-5.6M9.8 19.4V9.4M14.4 19.4v-7.6M19 19.4V5.2"/>'],
  settings:['#9CA3AF','#4B5563','<circle cx="12" cy="12" r="3.1"/><path d="M12 3.8v2.4M12 17.8v2.4M20.2 12h-2.4M6.2 12H3.8M17.8 6.2l-1.7 1.7M7.9 16.1l-1.7 1.7M17.8 17.8l-1.7-1.7M7.9 7.9 6.2 6.2"/>'],
  about:['#5EEAD4','#0D9488','<path d="M12 4.8 19.4 18.2H4.6Z"/><circle cx="12" cy="9.6" r="1" fill="#fff" stroke="none"/>'],
  docs:['#D9A66C','#A16207','<path d="M12 6.6C10.6 5.5 8.7 4.9 6.6 4.9c-.9 0-1.8.1-2.6.4v13c.8-.3 1.7-.4 2.6-.4 2.1 0 4 .6 5.4 1.7 1.4-1.1 3.3-1.7 5.4-1.7.9 0 1.8.1 2.6.4v-13c-.8-.3-1.7-.4-2.6-.4-2.1 0-4 .6-5.4 1.7Z"/><path d="M12 6.6v13"/>'],
};
/* A built app may choose one of the SAME glyph tiles the OS uses for itself, by
   storing `glyph:<key>` as its icon. That is the whole reason this is not an
   emoji field: a user app picking "tasks" gets the real duotone tile, so a built
   app sits on the desktop looking like it belongs there rather than like a
   sticker. An empty icon still means "monogram", which stays the default. */
function glyphTile(key,px,cls){
  const ic=ICONS[key];if(!ic)return '';
  return `<span class="aicon${cls?' '+cls:''}" style="width:${px}px;height:${px}px;background:linear-gradient(180deg,${ic[0]},${ic[1]})">`+
    `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ic[2]}</svg></span>`;
}
/* One place that turns a stored icon value into a tile, for anything that holds
   an app record rather than an app id (App Studio, the Store, import previews). */
function iconTile(icon,label,seed,px,cls){
  px=px||46;const v=String(icon||'').trim();
  if(v.startsWith('glyph:')){const t=glyphTile(v.slice(6),px,cls);if(t)return t}
  const st=`width:${px}px;height:${px}px`;
  if(v)return `<span class="aicon${cls?' '+cls:''}" style="${st};background:${tileBg(seed||label||'?')}">`+
    `<span class="em" style="font-size:${Math.round(px*.5)}px">${v}</span></span>`;
  const ch=(String(label||seed||'?').trim().charAt(0)||'?').toUpperCase();
  return `<span class="aicon${cls?' '+cls:''}" style="${st};background:${tileBg(seed||label||'?')}">`+
    `<span class="em" style="font-size:${Math.round(px*.44)}px;font-weight:800;color:#fff">${ch}</span></span>`;
}
function appIcon(id,px,cls){
  px=px||46;
  const st=`width:${px}px;height:${px}px`;
  const ic=ICONS[id];
  if(ic)return `<span class="aicon${cls?' '+cls:''}" style="${st};background:linear-gradient(180deg,${ic[0]},${ic[1]})">`+
    `<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ic[2]}</svg></span>`;
  const a=(APPS_READY&&APPS[id])||null;   // APPS is a const in TDZ until defined — gate on APPS_READY first
  // the monogram falls back to the id with its `ua_` prefix stripped, never "u"
  return iconTile((a&&a.icon)||'',(a&&a.title)||String(id).replace(/^ua_/,''),id,px,cls);
}
function emojiIcon(emoji,px,cls){
  return `<span class="aicon${cls?' '+cls:''}" style="width:${px}px;height:${px}px;background:linear-gradient(180deg,#3f4653,#242a34)">`+
    `<span class="em" style="font-size:${Math.round(px*.5)}px">${emoji||'▭'}</span></span>`;
}


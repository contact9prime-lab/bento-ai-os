/* ================= places: the parts inside apps, findable by the words people use =================
   Reported as: "when I type something like channel it is not indexed; I say flow and it
   should relate to jobs". The launchers only knew app NAMES, and half of what a person
   looks for lives inside an app: Telegram and WhatsApp are a pane in Settings called
   Channels, flows are a tab in Missions, a model is a pane in Settings. Typing "channel"
   found nothing, and typing "flow" found nothing better than a description that happened
   to contain the word.

   PLACES is that index: each entry is one place inside an app, the words people use for
   it (including the old names: workflow, fabric, jobs), and how to go there. It is read
   by every launcher, so they cannot disagree about what a word finds:
   - the prompt bar (palActions / omniScore, 29 and 28a), under "In apps";
   - the wall launcher (deckPlacesHTML in 06a), shown only while you search;
   - the Jarvis shell's box (02), which opens the best match on Enter.
   Apps get words too (APP_WORDS), so "flow" finds Missions itself as well as its tab.

   A word only counts whole or as the start of a word ("chan" finds Channels, "annel"
   does not), which keeps this a launcher rather than a full-text search.

   Faces: GUI and SUI (this page). TUI: not applicable. The terminal's own index is
   `bento help --all`, and each place here has a verb there (bento telegram, bento flow,
   bento job, bento mail…). `var`, not `let`: the bundle is one script. */
var APP_WORDS={
  jobs:['mission','missions','job','jobs','flow','flows','workflow','workflows','fabric','orchestrator','recipe'],
  settings:['preferences','prefs','config','configuration','options'],
  office:['crew','team','playground','floor','lounge','meeting room','company','departments'],
  brief:['inbox','today','digest','summary'],
  permissions:['grants','grant','allow','deny','matrix','consent','policy','policies'],
  profile:['about me','what it knows','knowledge','memory','memories'],
  mcp:['tools','tool server','connectors'],
  telegram:['bot'],
  teamchat:['messages','linked team','people'],
  files:['documents','folder','workspace','downloads','deck','pptx'],
  chat:['conversation','conversations','talk','ask'],
  store:['install','marketplace','extensions'],
  studio:['build an app','make an app','editor'],
  models:['ollama','gpu','local model','llm'],
  logs:['diary','events','errors'],
  tokens:['usage','cost','spend','billing'],
};
function placeSettings(tab){return ()=>{
  SETTAB=tab;try{localStorage.setItem('settab',tab)}catch(e){}
  openApp('settings');
  // an open Settings window is already painted on another pane: move it
  setTimeout(()=>{if(typeof settingsGo==='function')settingsGo(tab)},60);
}}
/* A folded app's tab (APP_FOLD in 04-wm.js): opening the old id picks the tab. */
function placeFold(id){return ()=>openApp(id)}
function placeMissions(tab,sub){return ()=>{
  if(typeof JOBS!=='undefined')JOBS.tab=tab;
  if(sub&&typeof fabTab!=='undefined')fabTab=sub;
  openApp('jobs');refreshApp('jobs');
}}
/* The Office's company panel (24g-company.js), opened once the window has painted. */
function placeCompany(){return ()=>{openApp('office');setTimeout(()=>{if(typeof officeCompany==='function')officeCompany(true)},500)}}
// [label, the app it lives in, where it is in words, words, go]
var PLACES=[
  ['AI providers','settings','Settings → AI providers',['provider','providers','model','models','brain','api key','key','openai','anthropic','claude','gemini','ollama','openrouter','llm'],placeSettings('ai')],
  ['Agents','settings','Settings → Agents',['agent','agents','specialist','specialists','lead','persona','team','swarm','huddle','talk','working together'],placeSettings('agent')],
  ['Free talk','settings','Settings → Agents → Working together',['free talk','let them talk','agent talk','agent to agent','agents talking','talk log','open floor'],placeSettings('agent')],
  ['Executors','settings','Settings → Executors',['executor','executors','hands','folders','folder access','claude code','codex','gemini cli','sandbox','reach'],placeSettings('executors')],
  ['Channels','settings','Settings → Channels',['channel','channels','telegram','whatsapp','messaging','phone','bot','notify','notifications'],placeSettings('channels')],
  ['Accounts','settings','Settings → Accounts',['account','accounts','mail','email','gmail','outlook','calendar','imap','caldav','sign in','google','microsoft'],placeSettings('accounts')],
  ['Locale','settings','Settings → Locale',['language','country','timezone','time zone','units','clock','region'],placeSettings('locale')],
  ['Shortcuts','settings','Settings → Shortcuts',['shortcut','shortcuts','keyboard','keys','hotkey','hotkeys','key binding'],placeSettings('keys')],
  ['Voice','settings','Settings → Voice',['voice','speech','speak','tts','microphone','mic','wake word','dictation'],placeSettings('voice')],
  ['Appearance','settings','Settings → Appearance',['appearance','look','theme','immersive','scene','dark mode','font','wallpaper','office look','mind','brain','neural'],placeSettings('look')],
  ['System','settings','Settings → System',['system','update','updates','version','reset','factory reset','remote','remote access','passphrase','lock','autonomy','light mode','profile','security'],placeSettings('system')],
  ['Run missions','jobs','Missions → Run',['mission','missions','job','jobs','recipe','recipes','daily','describe a mission','catalogue'],placeMissions('run')],
  ['Flows','jobs','Missions → Build → Flows',['flow','flows','workflow','workflows','trigger','triggers','webhook','cron','schedule','orchestrator','fabric','automation'],placeMissions('build','flows')],
  ['Mission agents','jobs','Missions → Build → Agents',['roster','specialist','specialists','subagent','subagents','new agent'],placeMissions('build','agents')],
  ['Company','office','Office → Company',['company','departments','department','org','organisation','organization','startup','business','hr','finance','sales','marketing','admin','supply','operations'],placeCompany()],
  ['Mission runs','jobs','Missions → Build → Runs',['run','runs','run history','history','what ran'],placeMissions('build','runs')],
  ['Schedule','jobs','Missions → Schedule',['scheduler','schedule','scheduled','cron','timer','task','tasks','reminder'],placeFold('tasks')],
  ['Routines','jobs','Missions → Routines',['automation','automations','routine','routines','hot corner','hot corners','macro','sequence'],placeFold('automations')],
  ['Memory','profile','Profile → Memory',['memory','memories','remember','remembers','forget','pinned'],placeFold('memory')],
  ['Knowledge graph','profile','Profile → Graph',['knowledge graph','graph','kg','entities','facts','connections'],placeFold('kg')],
  ['Soul','profile','Profile → Soul',['soul','identity','personality','who it is'],placeFold('soul')],
  ['Rules','permissions','Permissions → Rules',['policies','policy','rules','always allow','always deny'],placeFold('policies')],
  ['Ledger','permissions','Permissions → Ledger',['audit','ledger','decisions','history of decisions','who did what'],placeFold('audit')],
  ['Quarantine','permissions','Permissions → Quarantine',['quarantine','held','stopped','blocked','suspended','runaway'],placeFold('quarantine')],
].map(([label,app,hint,words,go])=>({label,app,hint,words,go}));

/* How well `q` names a place or an app by one of its words: 2.6 a whole word, 2.2 the
   start of one. The same scale as palScore, so a word hit ranks with a name hit. */
function placeWordScore(q,words){
  q=String(q||'').toLowerCase().trim();if(q.length<2||!words)return 0;
  let best=0;
  for(const w of words){
    if(w===q)return 2.6;
    if(w.startsWith(q)||w.split(' ').some(p=>p.startsWith(q)))best=Math.max(best,2.2);
    else if(q.length>=4&&q.startsWith(w)&&w.length>=4)best=Math.max(best,2.1);   // "flows?" "channels!"
  }
  return best;
}
function placeScore(q,p){return Math.max(typeof palScore==='function'?(palScore(q,p.label)>=2?palScore(q,p.label):0):0,placeWordScore(q,p.words))}
/* The places a query finds, best first. */
function placesFind(q,max){
  return PLACES.map(p=>({p,s:placeScore(q,p)})).filter(x=>x.s>=2).sort((a,b)=>b.s-a.s)
    .slice(0,max||5).map(x=>x.p);
}

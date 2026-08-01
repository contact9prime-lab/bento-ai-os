/* ================= themes ================= */
// A theme is not just colors — it can carry a web font and extra CSS that restyles the whole
// desktop (taskbar, windows, icons, widgets). Built-in themes:
const THEMES={
  agentos:{label:'AgentOS (teal)',mode:'dark',v:{bg:'#0b0d10',bg2:'#111419',bg3:'#171b22',bg4:'#1e242e',line:'#232a35',txt:'#e6ebf2',dim:'#8a94a6',dim2:'#5c6577',acc:'#5eead4',acc2:'#22d3ee',warn:'#fbbf24',err:'#f87171',ok:'#4ade80',glass:'rgba(17,20,25,.82)'}},
  ubuntu:{label:'Ember (dark)',mode:'dark',v:{bg:'#1c1a1b',bg2:'#242021',bg3:'#2c2727',bg4:'#383231',line:'#3a3433',txt:'#ffffff',dim:'#c7c2bf',dim2:'#8f8987',acc:'#E95420',acc2:'#F29879',warn:'#f9c74f',err:'#f87171',ok:'#26a269',glass:'rgba(36,32,33,.86)'}},
  'ubuntu-light':{label:'Ember (light)',mode:'light',v:{bg:'#faf9f8',bg2:'#f2f0ee',bg3:'#ecebe9',bg4:'#e0ddda',line:'#d3cfcb',txt:'#1d1b19',dim:'#5e5b58',dim2:'#8f8b87',acc:'#E95420',acc2:'#c7451d',warn:'#b98900',err:'#c01c28',ok:'#26a269',glass:'rgba(245,243,241,.92)'}},
  dracula:{label:'Dracula',mode:'dark',v:{bg:'#191a21',bg2:'#21222c',bg3:'#282a36',bg4:'#343746',line:'#3b3d4d',txt:'#f8f8f2',dim:'#b8bcc8',dim2:'#6272a4',acc:'#bd93f9',acc2:'#ff79c6',warn:'#f1fa8c',err:'#ff5555',ok:'#50fa7b',glass:'rgba(33,34,44,.86)'}},
  nord:{label:'Nord',mode:'dark',v:{bg:'#242933',bg2:'#2e3440',bg3:'#3b4252',bg4:'#434c5e',line:'#4c566a',txt:'#eceff4',dim:'#d8dee9',dim2:'#7b88a1',acc:'#88c0d0',acc2:'#81a1c1',warn:'#ebcb8b',err:'#bf616a',ok:'#a3be8c',glass:'rgba(46,52,64,.86)'}},
  aero:{label:'Frost (glass)',mode:'dark',font:{url:'https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600&display=swap',family:'Space Grotesk'},
    v:{bg:'#141628',bg2:'#1b2036',bg3:'#222844',bg4:'#2b3352',line:'#3a4470',txt:'#eef1f8',dim:'#aab2c8',dim2:'#6b7699',acc:'#7aa2f7',acc2:'#b892f6',warn:'#f6c177',err:'#f26d6d',ok:'#7bd88f',glass:'rgba(28,32,52,.62)'},
    css:`#desktop{background:radial-gradient(1200px 700px at 70% 110%,rgba(150,90,220,.42),transparent 60%),radial-gradient(900px 600px at 15% -10%,rgba(70,120,230,.42),transparent 55%),linear-gradient(170deg,#181c30,#141628 45%,#201a33)}
#taskbar{background:rgba(20,24,40,.5);backdrop-filter:blur(24px)}
.win{background:rgba(28,32,52,.66)!important;backdrop-filter:blur(26px);border:1px solid rgba(255,255,255,.12)}
.win .ttl{background:rgba(255,255,255,.05)}
.dicon .aicon{box-shadow:0 10px 26px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.28)}
.widget{border:1px solid rgba(255,255,255,.12)}`},
  field:{label:'Field (warm light)',mode:'light',
    v:{bg:'#f6f2e9',bg2:'#fffdf7',bg3:'#f1ece0',bg4:'#e9e2d2',line:'#e4dcc9',txt:'#2b2620',dim:'#6f6656',dim2:'#8a8172',acc:'#b0693a',acc2:'#c98a4a',warn:'#b98900',err:'#c0492c',ok:'#5a8a3c',glass:'rgba(255,253,247,.92)'},
    css:`#desktop{background:linear-gradient(180deg,#f6f2e9,#f1ece0)}
#taskbar{background:#fffdf7;border-top:1px solid #e4dcc9}
.win{background:#fffdf7!important;border:1px solid #e4dcc9}
.win .ttl{background:#f7f2e6}
.dicon .aicon{box-shadow:0 3px 10px rgba(60,50,30,.14),inset 0 1px 0 rgba(255,255,255,.5)}`},
  shell:{label:'Shell (terminal)',mode:'dark',font:{url:'https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap',family:'JetBrains Mono'},
    v:{bg:'#0a0e0b',bg2:'#0d130f',bg3:'#111a13',bg4:'#16231a',line:'#1e3323',txt:'#a7c4ad',dim:'#6f9578',dim2:'#46614d',acc:'#86efac',acc2:'#4ade80',warn:'#e3d34d',err:'#f87171',ok:'#4ade80',glass:'rgba(13,19,15,.9)'},
    css:`#desktop{background:#070a08}
#taskbar{background:#0a0e0b;border-top:1px solid #1e3323}
.win{background:#0a0e0b!important;border:1px solid #1e3323}
.win .ttl{background:#0d130f}
.dicon .aicon{border-radius:7px}
*{letter-spacing:.1px}`},
  /* ---- the five design-language themes ----
     Each one restyles the whole desktop, not just its hues: `v` also carries the
     radius/elevation/glass tokens (any key in `v` becomes a --custom property),
     and `css` re-cuts the chrome so the language actually reads on screen.

     Two things every theme below has to respect:
      · --wall is the wallpaper, painted on BOTH #desktop and body with
        background-attachment:fixed. #desktop starts below the menu bar, so
        without the body copy the bar would float over bare --bg; with it, and
        with the background locked to the viewport, the two line up seamlessly
        and the bar reads as part of the wallpaper.
      · light themes must out-specify 06-light.css, which targets
        :root[data-theme=light] #desktop and friends — a bare #desktop loses. */
  bento:{label:'Bento (grid)',mode:'dark',wall_img:'bento',font:{url:'https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;700;800&display=swap',family:'Plus Jakarta Sans'},
    v:{bg:'#221f2b',bg2:'#332e42',bg3:'#3f3852',bg4:'#4c4363',line:'#4f4767',txt:'#f6f3fd',dim:'#c9bfe6',dim2:'#a79ccb',
       acc:'#6d4aeb',acc2:'#a78bfa',warn:'#fbbf24',err:'#fb7185',ok:'#4ade80',glass:'rgba(51,46,66,.96)',
       wall:'#1c1926',
       'glass-tint':'#332e42','glass-blur':'none','glass-edge':'none',
       'r-sm':'10px','r-md':'16px','r-lg':'22px','r-xl':'28px',
       'el-2':'0 3px 0 rgba(0,0,0,.3)','el-3':'0 5px 0 rgba(0,0,0,.32)','el-4':'0 9px 0 rgba(0,0,0,.34)','el-5':'0 13px 0 rgba(0,0,0,.4)'},
    // flat, chunky, gapped tiles with a hard offset shadow — no blur anywhere
    css:`body,#desktop{background:var(--wall);background-attachment:fixed}
#desktop::after{display:none}
#menubar{background:#2b2636;backdrop-filter:none;border-bottom:none;padding:0 14px}
#taskbar{background:#332e42;backdrop-filter:none;border:none;box-shadow:0 7px 0 rgba(0,0,0,.34);padding:9px 12px;gap:7px}
.dsep{background:rgba(255,255,255,.14)}
.win{background:#332e42!important;backdrop-filter:none;border:none;box-shadow:0 11px 0 rgba(0,0,0,.34)}
.win.active{box-shadow:0 15px 0 rgba(0,0,0,.4)}
.win .ttl{background:#453d5c;border-bottom:none;height:44px}
.win .tname{font-weight:800;letter-spacing:-.01em;color:#f6f3fd}
/* the bento signature: neighbouring tiles carry different weights */
.deck-group{background:#332e42;backdrop-filter:none;border:none;box-shadow:0 7px 0 rgba(0,0,0,.32);padding:12px 14px 14px}
.deck-group:nth-of-type(3n+2){background:#5b3fd4;box-shadow:0 7px 0 #3d2a92}
.deck-group:nth-of-type(3n+3){background:#e6e0fb;box-shadow:0 7px 0 #b8aede}
.deck-group:nth-of-type(3n+3) .deck-gname{color:#4b3a86}
.deck-group:nth-of-type(3n+3) .deck-tile span{color:#2f2650}
.deck-group:nth-of-type(3n+3) .deck-tile:hover{background:rgba(0,0,0,.08)}
.deck-gname{color:#cdc3ea;font-weight:800;letter-spacing:.1em}
.deck-tile{border-radius:16px}
.deck-tile:hover{background:rgba(255,255,255,.14);transform:none}
#omnibar{background:#453d5c;backdrop-filter:none;border:none;box-shadow:0 7px 0 rgba(0,0,0,.32);border-radius:22px;height:52px}
#omnilist,#startmenu,.ocard,#ctxmenu,#powermenu,#notifpanel{background:#332e42;backdrop-filter:none;border:none;box-shadow:0 11px 0 rgba(0,0,0,.36)}
.widget{background:#332e42;backdrop-filter:none;border:none;box-shadow:0 7px 0 rgba(0,0,0,.32)}
.smapp{border-radius:18px}
.dicon .aicon,.dockb .aicon,.tbwin .aicon,#startbtn .mark{border-radius:26%;box-shadow:0 3px 0 rgba(0,0,0,.36)}`},
  liquid:{label:'Liquid Glass',mode:'dark',wall_img:'liquid',font:{url:'https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&display=swap',family:'Outfit'},
    v:{bg:'#1a1016',bg2:'#2a1a22',bg3:'#3a2430',bg4:'#4b303e',line:'rgba(255,255,255,.2)',txt:'#fff6f3',dim:'#f0d6ce',dim2:'#d8b6ac',
       acc:'#ffb08c',acc2:'#ffd9b8',warn:'#ffd166',err:'#ff8080',ok:'#8ee6a8',glass:'rgba(28,14,20,.42)',
       wall:'radial-gradient(1000px 800px at 20% 12%,#ff9a76,transparent 60%),radial-gradient(1100px 900px at 82% 26%,#c4443c,transparent 56%),radial-gradient(900px 800px at 55% 105%,#2f4a5c,transparent 62%),linear-gradient(158deg,#e0674f,#7d2f33 46%,#1e1622)',
       'glass-tint':'rgba(24,12,18,.34)','glass-blur':'blur(44px) saturate(1.6)',
       'glass-edge':'inset 0 1px 0 rgba(255,255,255,.45),inset 0 -1px 0 rgba(255,255,255,.12)',
       hairline:'rgba(255,255,255,.3)','hairline-strong':'rgba(255,255,255,.46)',
       'r-sm':'12px','r-md':'18px','r-lg':'26px','r-xl':'34px'},
    // a lens, not a pane: the wallpaper bends through every surface, and a bright
    // rim plus a light inner scrim is what keeps text readable on top of it
    css:`body,#desktop{background:var(--wall);background-attachment:fixed}
#desktop::after{display:none}
#menubar,#taskbar,.win,#omnibar,#omnilist,#startmenu,.ocard,.deck-group,.widget,#ctxmenu,#powermenu,#notifpanel{
  background:linear-gradient(160deg,rgba(255,255,255,.20),rgba(20,10,16,.42))!important;
  backdrop-filter:blur(44px) saturate(1.7);-webkit-backdrop-filter:blur(44px) saturate(1.7);
  border:1px solid rgba(255,255,255,.42);
  box-shadow:0 26px 60px rgba(40,10,20,.4),inset 0 1px 0 rgba(255,255,255,.55),inset 0 -1px 0 rgba(255,255,255,.14)}
#menubar{border-width:0 0 1px 0;box-shadow:inset 0 1px 0 rgba(255,255,255,.35)}
#taskbar{border-radius:34px}
.win .ttl{background:rgba(255,255,255,.09);border-bottom:1px solid rgba(255,255,255,.2);height:44px}
.win .tname{font-weight:500;letter-spacing:.01em;text-shadow:0 1px 3px rgba(0,0,0,.5)}
#omnibar{height:52px}
.deck-gname{color:rgba(255,255,255,.82);text-shadow:0 1px 3px rgba(0,0,0,.55)}
.deck-tile span,.smapp .n,.dicon .dlbl{text-shadow:0 1px 4px rgba(0,0,0,.6)}
.deck-tile,.smapp,.dockb,.tbwin{border-radius:22px}
.deck-tile:hover,.smapp:hover{background:rgba(255,255,255,.24)}
.dicon .aicon,.dockb .aicon,.tbwin .aicon,#startbtn .mark{box-shadow:0 10px 24px rgba(0,0,0,.4),inset 0 1px 0 rgba(255,255,255,.55)}
input,textarea,select{background:rgba(255,255,255,.14);border-color:rgba(255,255,255,.36)}`},
  spatial:{label:'Spatial (depth)',mode:'dark',wall_img:'spatial',font:{url:'https://fonts.googleapis.com/css2?family=Inter+Tight:wght@300;400;500;600&display=swap',family:'Inter Tight'},
    v:{bg:'#0d0f11',bg2:'#16191d',bg3:'#1e2226',bg4:'#282d33',line:'rgba(255,255,255,.14)',txt:'#eef1f4',dim:'#b3bbc4',dim2:'#8b949d',
       acc:'#4aa3ff',acc2:'#7ec8ff',warn:'#f5c26b',err:'#ff7a7a',ok:'#6ee7a0',glass:'rgba(28,32,37,.55)',
       wall:'radial-gradient(1300px 900px at 50% -8%,#39424c,transparent 66%),radial-gradient(900px 700px at 88% 88%,#22303b,transparent 60%),linear-gradient(180deg,#1c2126,#101316 58%,#08090b)',
       'glass-tint':'rgba(42,48,55,.46)','glass-blur':'blur(50px) saturate(1.4)','glass-edge':'inset 0 .5px 0 rgba(255,255,255,.24)',
       hairline:'rgba(255,255,255,.14)','hairline-strong':'rgba(255,255,255,.24)',
       'r-sm':'10px','r-md':'16px','r-lg':'24px','r-xl':'32px',
       'el-3':'0 20px 50px rgba(0,0,0,.6)','el-4':'0 34px 80px rgba(0,0,0,.68)','el-5':'0 50px 120px rgba(0,0,0,.75)'},
    // panes floating in a room: heavy blur, deep drop shadows, nothing opaque
    css:`body,#desktop{background:var(--wall);background-attachment:fixed}
#desktop::after{opacity:.5}
#menubar{background:rgba(30,35,41,.42);backdrop-filter:blur(50px) saturate(1.4);border-bottom:1px solid rgba(255,255,255,.09)}
#taskbar,.win,#omnibar,#omnilist,#startmenu,.ocard,.deck-group,.widget,#ctxmenu,#powermenu,#notifpanel{
  background:rgba(42,48,55,.46)!important;backdrop-filter:blur(50px) saturate(1.4);-webkit-backdrop-filter:blur(50px) saturate(1.4);
  border:1px solid rgba(255,255,255,.17);
  box-shadow:0 36px 84px rgba(0,0,0,.7),inset 0 .5px 0 rgba(255,255,255,.24)}
#taskbar{border-radius:32px;padding:9px 14px}
.win{box-shadow:0 46px 104px rgba(0,0,0,.74),inset 0 .5px 0 rgba(255,255,255,.22)}
.win.active{border-color:rgba(255,255,255,.28);box-shadow:0 62px 132px rgba(0,0,0,.8),inset 0 .5px 0 rgba(255,255,255,.3)}
.win .ttl{background:rgba(255,255,255,.05);border-bottom:1px solid rgba(255,255,255,.09);height:44px}
.win .tname{font-weight:500;color:var(--txt)}
.win .tbtns button{width:14px;height:14px}
#omnibar{height:52px}
.deck-tile,.smapp{border-radius:20px}
.deck-tile:hover,.smapp:hover{background:rgba(255,255,255,.11)}
.dockb .aicon,.tbwin .aicon,.dicon .aicon,#startbtn .mark{box-shadow:0 16px 34px rgba(0,0,0,.62),inset 0 .5px 0 rgba(255,255,255,.3)}`},
  clay:{label:'Claymorphism',mode:'light',wall_img:'clay',font:{url:'https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap',family:'Nunito'},
    v:{bg:'#e6dfff',bg2:'#ffffff',bg3:'#f4f1ff',bg4:'#e6e0ff',line:'#ddd5ff',txt:'#2a2352',dim:'#5e5595',dim2:'#8a80bd',
       acc:'#6c4ef0',acc2:'#f7889f',warn:'#e0952b',err:'#ef5f72',ok:'#3fbd87',glass:'rgba(255,255,255,.92)',
       wall:'radial-gradient(900px 760px at 16% 6%,#b9a4ff,transparent 62%),radial-gradient(880px 720px at 88% 90%,#ffc2d8,transparent 60%),linear-gradient(158deg,#d9ccff,#c9b9ff 52%,#e7dcff)',
       'glass-tint':'rgba(255,255,255,.9)','glass-blur':'blur(10px)','glass-edge':'inset 0 2px 4px rgba(255,255,255,.9)',
       hairline:'rgba(108,78,240,.12)','hairline-strong':'rgba(108,78,240,.2)',
       'r-sm':'14px','r-md':'20px','r-lg':'28px','r-xl':'36px',
       'el-1':'0 4px 10px rgba(78,52,180,.16)','el-2':'0 8px 18px rgba(78,52,180,.18)',
       'el-3':'0 14px 30px rgba(78,52,180,.2)','el-4':'0 20px 44px rgba(78,52,180,.22)','el-5':'0 28px 64px rgba(78,52,180,.26)'},
    // puffed-up clay: fat radii, a soft outer shadow AND an inner highlight, so
    // every surface looks pressed out of the background rather than laid on it
    css:`body,:root[data-theme=light] #desktop{background:var(--wall);background-attachment:fixed}
:root[data-theme=light] #desktop::after{display:none}
:root[data-theme=light] #menubar{background:rgba(255,255,255,.76);backdrop-filter:blur(18px);border-bottom:none;box-shadow:0 4px 16px rgba(78,52,180,.12);color:#2a2352}
:root[data-theme=light] #taskbar{background:#fff;backdrop-filter:none;border:none;border-radius:36px;padding:10px 14px;
  box-shadow:0 18px 40px rgba(78,52,180,.26),inset 0 3px 6px rgba(255,255,255,.95),inset 0 -4px 8px rgba(108,78,240,.1)}
.dsep{background:rgba(108,78,240,.16)}
.win{background:#fff!important;backdrop-filter:none;border:none;
  box-shadow:0 24px 54px rgba(78,52,180,.26),inset 0 3px 6px rgba(255,255,255,.95),inset 0 -4px 10px rgba(108,78,240,.08)}
.win.active{box-shadow:0 32px 72px rgba(78,52,180,.32),inset 0 3px 6px rgba(255,255,255,.95),inset 0 -4px 10px rgba(108,78,240,.09)}
:root[data-theme=light] .win .ttl{background:linear-gradient(180deg,#faf8ff,#efeaff);border-bottom:none;height:46px}
:root[data-theme=light] .win.active .ttl{background:linear-gradient(180deg,#f7f4ff,#e9e2ff)}
.win .tname{font-weight:800;color:#2a2352}
#omnibar,#omnilist,#startmenu,.ocard,.deck-group,.widget,#ctxmenu,#powermenu,#notifpanel{
  background:#fff;backdrop-filter:none;border:none;
  box-shadow:0 18px 40px rgba(78,52,180,.24),inset 0 3px 6px rgba(255,255,255,.95),inset 0 -4px 8px rgba(108,78,240,.09)}
#omnibar{height:54px}
.deck-gname{color:#6c4ef0;font-weight:800}
.deck-tile,.smapp{border-radius:22px}
.deck-tile:hover,.smapp:hover{background:#f1ecff;transform:translateY(-3px)}
.dicon .aicon,.dockb .aicon,.tbwin .aicon,#startbtn .mark{border-radius:30%;
  box-shadow:0 10px 20px rgba(78,52,180,.3),inset 0 3px 5px rgba(255,255,255,.7),inset 0 -4px 7px rgba(0,0,0,.16)}
input,textarea,select{background:#f4f1ff;border:none;box-shadow:inset 0 3px 7px rgba(108,78,240,.16)}
.save,#send{box-shadow:0 8px 18px rgba(108,78,240,.42),inset 0 2px 4px rgba(255,255,255,.5)}`},
  minimal:{label:'Minimalism',mode:'light',wall_img:'minimal',font:{url:'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap',family:'Inter'},
    v:{bg:'#ffffff',bg2:'#ffffff',bg3:'#f6f6f6',bg4:'#ededed',line:'#e6e6e6',txt:'#0b0b0b',dim:'#5f5f5f',dim2:'#8c8c8c',
       acc:'#4d9d2f',acc2:'#111111',warn:'#a97800',err:'#c8342a',ok:'#4d9d2f',glass:'rgba(255,255,255,.97)',
       wall:'#f4f4f2',
       'glass-tint':'rgba(255,255,255,.95)','glass-blur':'blur(6px)','glass-edge':'none',
       hairline:'#e6e6e6','hairline-strong':'#d6d6d6',
       'r-sm':'4px','r-md':'6px','r-lg':'8px','r-xl':'10px',
       'el-1':'none','el-2':'0 1px 2px rgba(0,0,0,.05)','el-3':'0 2px 8px rgba(0,0,0,.06)',
       'el-4':'0 6px 22px rgba(0,0,0,.08)','el-5':'0 12px 40px rgba(0,0,0,.1)'},
    // paper: hairlines instead of shadows, one accent, and nothing else
    css:`body,:root[data-theme=light] #desktop{background:var(--wall);background-attachment:fixed}
:root[data-theme=light] #desktop::after{display:none}
:root[data-theme=light] #menubar{background:#fff;backdrop-filter:none;border-bottom:1px solid #e6e6e6;color:#0b0b0b}
#mb-brand{font-weight:800;letter-spacing:-.02em}
:root[data-theme=light] #taskbar{background:#fff;backdrop-filter:none;border:1px solid #e6e6e6;border-radius:10px;
  box-shadow:0 2px 10px rgba(0,0,0,.05);padding:6px 8px;gap:2px}
.dsep{background:#ececec}
.win{background:#fff!important;backdrop-filter:none;border:1px solid #e2e2e2;box-shadow:0 6px 24px rgba(0,0,0,.08)}
.win.active{border-color:#cfcfcf;box-shadow:0 12px 40px rgba(0,0,0,.1)}
:root[data-theme=light] .win .ttl{background:#fff;border-bottom:1px solid #eee;height:38px}
:root[data-theme=light] .win.active .ttl{background:#fff}
.win .tname{font-weight:600;color:#0b0b0b;letter-spacing:-.01em}
.win .tbtns button{width:11px;height:11px}
#omnibar,#omnilist,#startmenu,.ocard,.deck-group,.widget,#ctxmenu,#powermenu,#notifpanel{
  background:#fff;backdrop-filter:none;border:1px solid #e6e6e6;box-shadow:0 6px 24px rgba(0,0,0,.07)}
#omnibar{height:46px;border-radius:8px}
#omni-orb{background:var(--acc);box-shadow:none;animation:none;width:9px;height:9px}
.deck-group{box-shadow:none}
.deck-gname{color:#8c8c8c;letter-spacing:.14em}
.deck-tile,.smapp{border-radius:6px}
.deck-tile:hover,.smapp:hover{background:#f2f2f2;transform:none}
.dicon .aicon,.dockb .aicon,.tbwin .aicon,#startbtn .mark{border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.12)}
.dockb:hover,.tbwin:hover,#startbtn:hover{transform:translateY(-3px) scale(1.04)}
.dicon .dlbl{color:#0b0b0b;text-shadow:none}`},
  jarvis:{label:'Aura (Voice OS)',mode:'dark',exp:'jarvis',font:{url:'https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700&family=IBM+Plex+Mono:wght@400;500&display=swap',family:'IBM Plex Mono'},
    v:{bg:'#03060c',bg2:'#061019',bg3:'#0a1722',bg4:'#10222e',line:'#15353c',txt:'#c8e6f2',dim:'#6fa8b8',dim2:'#3d6a75',acc:'#5eead4',acc2:'#22d3ee',warn:'#f6c177',err:'#f87171',ok:'#4ade80',glass:'rgba(4,14,20,.78)'},
    css:`#desktop{background:radial-gradient(900px 600px at 72% 55%,rgba(30,74,94,.5),transparent 60%),linear-gradient(160deg,#040810,#03060c 60%,#051018)}
#taskbar{background:rgba(4,12,18,.72);backdrop-filter:blur(14px);border-top:1px solid rgba(94,234,212,.16)}
.win{background:rgba(6,16,24,.82)!important;backdrop-filter:blur(10px);border:1px solid rgba(94,234,212,.18);box-shadow:0 0 40px rgba(94,234,212,.07)}
.win.active{box-shadow:0 0 50px rgba(94,234,212,.14)}
.win .ttl{background:rgba(94,234,212,.04);border-bottom:1px solid rgba(94,234,212,.14)}
.win .tname{font-family:'Orbitron',sans-serif;letter-spacing:.12em;font-size:11px;text-transform:uppercase}
#welcome h1,#startbtn{font-family:'Orbitron',sans-serif;letter-spacing:.12em}
.widget{border:1px solid rgba(94,234,212,.18);box-shadow:0 0 26px rgba(94,234,212,.07)}
.dicon .aicon{border:1px solid rgba(94,234,212,.2);box-shadow:0 0 18px rgba(94,234,212,.16),inset 0 1px 0 rgba(255,255,255,.14)}
.dicon .dlbl{letter-spacing:.04em}
.tbwin.on{box-shadow:inset 0 -2px 0 var(--acc),0 0 14px rgba(94,234,212,.25)}`},
};
const CUSTOM_THEMES={};   // name -> theme object, loaded from the server
function allThemes(){const m={};for(const k in THEMES)m[k]={...THEMES[k],id:k};for(const n in CUSTOM_THEMES)m[n]={...CUSTOM_THEMES[n],id:n};return m}
let CURRENT_THEME=localStorage.getItem('theme')||'agentos';
function applyThemeObj(t){
  // crossfade the whole desktop through the theme change instead of hard-cutting
  if(document.startViewTransition&&!matchMedia('(prefers-reduced-motion: reduce)').matches&&document.body.dataset.themed){
    const apply=()=>_applyThemeObj(t);
    try{document.startViewTransition(apply);return}catch(e){}
  }
  document.body.dataset.themed='1';
  _applyThemeObj(t);
}
let THEME_VARS=[];   // custom properties the previous theme set, so switching away clears them
function _applyThemeObj(t){
  const r=document.documentElement,v=t.v||t.vars||{};
  // a theme may override any token (radii, elevation, glass recipe — not just hues),
  // so drop the last theme's overrides first or they leak into the next one
  THEME_VARS.forEach(k=>{if(!(k in v))r.style.removeProperty('--'+k)});
  THEME_VARS=Object.keys(v);
  Object.entries(v).forEach(([k,val])=>r.style.setProperty('--'+k,val));
  r.dataset.theme=(t.mode==='light')?'light':'dark';
  let fl=document.getElementById('theme-font');
  if(t.font&&t.font.url){
    if(!fl){fl=document.createElement('link');fl.id='theme-font';fl.rel='stylesheet';document.head.appendChild(fl)}
    fl.href=t.font.url;
    if(t.font.family)r.style.setProperty('--sans',"'"+t.font.family+"',system-ui,sans-serif");
  }else{if(fl)fl.remove();r.style.removeProperty('--sans')}
  let st=document.getElementById('theme-extra');
  if(!st){st=document.createElement('style');st.id='theme-extra';document.head.appendChild(st)}
  st.textContent=t.css||'';
  setExperience(t.shell?'custom':(t.exp||'standard'),t.shell);
}

/* ================= experience shells ================= */
let EXPERIENCE='standard';
function setExperience(exp,shellHtml){
  const cs=$('#custom-shell');
  if(exp==='custom'&&cs){
    // An AI-designed shell fully replaces the desktop. It runs in a same-origin iframe:
    // its scripts get their own global scope (no collisions with the desktop's globals)
    // while keeping full access to the REST API and the /ws websocket.
    try{
      cs.innerHTML='';
      const f=document.createElement('iframe');
      f.style.cssText='flex:1;width:100%;height:100%;border:none;background:var(--bg)';
      cs.appendChild(f);
      f.contentDocument.open();
      f.contentDocument.write(shellHtml||'');
      f.contentDocument.close();
    }catch(e){cs.innerHTML='';toast('shell failed to load: '+e.message);exp='standard'}
  }else if(cs){cs.innerHTML=''}
  if(exp===EXPERIENCE&&exp!=='custom')return;
  EXPERIENCE=exp;
  document.body.classList.toggle('exp-jarvis',exp==='jarvis');
  document.body.classList.toggle('exp-custom',exp==='custom');
  if(exp==='jarvis')buildJarvisShell();
  else{const sh=$('#jarvis-shell');if(sh){clearInterval(sh._t);sh.innerHTML=''}}
}
const JS_RING=['chat','models','scheduler','kg','memory','files','logs','terminal'];
function buildJarvisShell(){
  const sh=$('#jarvis-shell');if(!sh||!APPS_READY)return;   // APPS loads later; init re-builds
  sh.innerHTML=`
    <button id="js-exit" onclick="applyTheme('agentos')">⊞ Standard desktop</button>
    <div id="js-top">
      <div style="display:flex;align-items:center"><span class="brand">AGENTOS</span><span class="tag">VOICE CORE</span></div>
      <div class="stats"><span>MCP <b id="js-mcp">–</b></span><span>MODEL <b id="js-model">–</b></span><span id="js-clock">–</span></div>
    </div>
    <div id="js-mid">
      <div id="js-side">
        <div class="js-panel"><div class="h">VOICE LINK</div><div id="js-voice" style="font-size:13px;color:var(--acc)">tap the orb to speak</div></div>
        <div class="js-panel" style="flex:1;display:flex;flex-direction:column;min-height:0"><div class="h">ACTIVITY STREAM</div><div id="js-stream"></div></div>
      </div>
      <div id="js-stage">
        <div id="js-ring"></div>
        <div id="js-orb"><span class="rg a"></span><span class="rg b"></span><span class="rg c"></span><span class="core"></span><span class="lbl">TAP TO SPEAK</span></div>
      </div>
    </div>
    <div id="js-bottom"><div id="js-ask">
      <span style="color:var(--acc);font-size:15px">⌕</span>
      <input id="js-input" placeholder="Ask ${esc(agentName())} or search apps… (Enter)">
      <span class="mic" onclick="jarvisMode(true)">${svgMic(16)}</span>
    </div></div>`;
  // ring of app nodes
  const ring=$('#js-ring');
  JS_RING.forEach((id,i)=>{
    const a=APPS[id];if(!a)return;
    const ang=(i/JS_RING.length)*2*Math.PI - Math.PI/2;
    const rx=50+Math.cos(ang)*34, ry=50+Math.sin(ang)*40;   // % of stage
    const n=document.createElement('div');n.className='js-node';
    n.style.left=rx+'%';n.style.top=ry+'%';
    n.innerHTML=`${appIcon(id,36)}<span class="n">${esc(a.title)}</span>`;
    n.onclick=()=>openApp(id);
    ring.appendChild(n);
  });
  $('#js-orb').onclick=()=>jarvisMode(true);
  const inp=$('#js-input');
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){const q=inp.value.trim();if(!q)return;
    const app=Object.keys(APPS).find(k=>APPS[k].title.toLowerCase()===q.toLowerCase());
    if(app){openApp(app)}else{openApp('chat');if(input){input.value=q;input.dispatchEvent(new Event('input'));send()}}
    inp.value='';}});
  jarvisShellRefresh();
  clearInterval(sh._t);sh._t=setInterval(jarvisShellRefresh,4000);
}
async function jarvisShellRefresh(){
  if(EXPERIENCE!=='jarvis')return;
  const cl=$('#js-clock');if(cl)cl.textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
  const mo=$('#js-model');if(mo)mo.textContent=((((typeof cfg!=='undefined'&&cfg&&(cfg.engine!=='aria'&&cfg.engine||cfg.default_model))||'')+'').split('/').pop()||'–').slice(0,14);
  try{const m=await (await fetch('/api/mcp')).json();const c=$('#js-mcp');if(c)c.textContent=(m.servers||[]).filter(s=>s.status==='connected').length}catch(e){}
  try{const d=await (await fetch('/api/logs?limit=8')).json();const s=$('#js-stream');
    if(s)s.innerHTML=(d.logs||[]).slice(0,8).map(l=>`<div class="ln"><span class="t">${new Date(l.created_at*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span><span>${esc((l.kind+' · '+l.message).slice(0,60))}</span></div>`).join('');
  }catch(e){}
}
function applyTheme(name){
  const t=allThemes()[name];if(!t)return;
  const changed=name!==CURRENT_THEME;
  applyThemeObj(t);CURRENT_THEME=name;localStorage.setItem('theme',name);
  // a theme can ship a wallpaper; picking the theme should dress the desktop for
  // it too, unless the user's own wallpaper (a file, or a built-in they chose)
  // already outranks it — loadWallpaper owns that precedence
  if(changed&&typeof loadWallpaper==='function'&&document.body.dataset.themed)loadWallpaper();
  // a glass theme costs orders of magnitude more to draw than a flat one, so the
  // machine gets re-measured whenever the material changes
  if(changed&&typeof glassProbe==='function')glassProbe(true);
  // a theme can resize the menu bar and the dock; in the session UI those
  // heights are reserved with the compositor, so they must be re-sent
  if(typeof suiSyncStruts==='function')suiSyncStruts();
}
async function loadThemes(){
  try{const d=await (await fetch('/api/themes')).json();
    for(const k in CUSTOM_THEMES)delete CUSTOM_THEMES[k];
    (d.themes||[]).forEach(t=>{CUSTOM_THEMES[t.name]=t});
  }catch(e){}
  if(allThemes()[CURRENT_THEME])applyTheme(CURRENT_THEME);   // re-apply if it's a custom theme
}
applyTheme(THEMES[CURRENT_THEME]?CURRENT_THEME:'agentos');

/* ================= fullscreen ================= */
function toggleFullscreen(){
  if(document.fullscreenElement)document.exitFullscreen();
  else document.documentElement.requestFullscreen?.().catch(()=>toast('fullscreen blocked by the browser'));
}


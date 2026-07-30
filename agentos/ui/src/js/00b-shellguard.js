/* ================= shell guard: stop being a web page =================
   In session mode AgentOS IS the desktop, but Chromium is still drawing it —
   and Chromium keeps its own affordances on top of ours. That is what makes the
   session feel "like an interface in the browser", and some of it is worse than
   cosmetic:

     Ctrl+W          closes the Chromium window. Not an app window — the whole
                     desktop goes black and sway is left with nothing on it.
                     AgentOS binds Ctrl+W to "close the active window", but that
                     binding stands aside when there is no window open and inside
                     the Terminal (where Ctrl+W is delete-word) — which is
                     exactly when the browser gets it instead.
     Ctrl+N / Ctrl+T open a browser window on top of the desktop.
     F5 / Ctrl+R     reload the shell, dropping every open window.
     right-click     "Back / Reload / Inspect" wherever we have not put a menu of
                     our own — the loudest single tell that this is a page.
     Ctrl+P/S/O      print, save-page-as and open-file dialogs.
     Ctrl +/-/0      browser zoom, which desynchronises every pixel the window
                     manager measures.
     Alt+←/→         history navigation, off the desktop entirely.

   This is a BACKSTOP, not a keymap. It runs on `window` in the bubble phase, so
   every AgentOS handler (they are on `document`) and every app widget has
   already had the key; anything already handled is left alone. It only acts on
   what would otherwise reach Chromium.

   And only when AgentOS is the session. In hosted mode the browser belongs to
   the user — taking Ctrl+W out of somebody's own tab would be hostile.

   Escape hatches stay: Ctrl+Shift+R reloads the shell (the recovery move when
   the desktop itself is wedged), and the power menu has "Restart AgentOS". */

function shellOwnsScreen(){
  // PLATFORM loads async; until it answers, assume hosted and take nothing away
  return typeof PLATFORM!=='undefined' && (PLATFORM.mode==='de'||PLATFORM.mode==='kiosk');
}

/* Browser-owned keys with no meaning for a desktop. Deliberately narrow: keys
   AgentOS or an app might legitimately want (Ctrl+F, Ctrl+U, Ctrl+J, …) are not
   here — if the OS wants them it has already claimed them above us, and if an
   app wants them it should get them. */
function browserOnlyKey(e){
  const k=(e.key||'').toLowerCase(), ctrl=e.ctrlKey||e.metaKey;
  if(ctrl&&e.shiftKey&&k==='r')return false;                        // deliberate reload
  if(k==='f5')return true;
  if(ctrl&&!e.altKey&&!e.shiftKey&&['w','n','t','p','s','o','r'].includes(k))return true;
  if(ctrl&&!e.altKey&&['+','-','=','0'].includes(k))return true;    // zoom
  if(ctrl&&e.shiftKey&&['n','t','i','j'].includes(k))return true;   // incognito, devtools, downloads
  if(e.altKey&&!ctrl&&(k==='arrowleft'||k==='arrowright'))return true;
  return false;
}

addEventListener('keydown',e=>{
  if(e.defaultPrevented)return;          // AgentOS, xterm or an app already took it
  if(!shellOwnsScreen())return;
  if(!browserOnlyKey(e))return;
  e.preventDefault();
  // Ctrl+W is muscle memory from a browser and would take the desktop with it.
  // Swallowing it silently would look like a broken key, so say what it does
  // here — the binding itself lives in the shortcuts table, not in this guard.
  if((e.key||'').toLowerCase()==='w'&&typeof toast==='function')
    toast('Ctrl+W closes a window — there isn’t one focused. The desktop stays.');
});

/* The browser's context menu only earns its place where text is edited (paste,
   spellcheck, emoji). Everywhere else the desktop either put a menu there
   itself — in which case it already called preventDefault — or should show
   nothing at all. */
addEventListener('contextmenu',e=>{
  if(e.defaultPrevented)return;
  if(!shellOwnsScreen())return;
  const t=e.target;
  if(t&&t.closest('input,textarea,[contenteditable="true"],.xterm'))return;
  if(t&&t.closest('iframe'))return;      // a user app owns what happens inside it
  e.preventDefault();
});

/* A desktop does not drag its own chrome into a download, and it never
   navigates away from itself because something was dropped on it. */
addEventListener('dragstart',e=>{
  if(e.defaultPrevented||!shellOwnsScreen())return;
  if(e.target&&e.target.closest('[draggable="true"]'))return;   // ours
  e.preventDefault();
});
addEventListener('dragover',e=>{if(shellOwnsScreen()&&!e.defaultPrevented)e.preventDefault()});
addEventListener('drop',e=>{if(shellOwnsScreen()&&!e.defaultPrevented)e.preventDefault()});
addEventListener('wheel',e=>{
  if(shellOwnsScreen()&&(e.ctrlKey||e.metaKey))e.preventDefault();   // pinch/ctrl zoom
},{passive:false});

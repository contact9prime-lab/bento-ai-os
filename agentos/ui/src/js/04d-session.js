/* ================= the desktop you left =================
   The shell is a page, and a page reloads. Until now a reload — Ctrl+R, a
   deploy, waking a dead socket, and now an update — closed every window and
   dropped you on an empty desktop. Window GEOMETRY was remembered per app, so
   the pieces knew where to sit; nothing remembered that they were there at all.

   That is the difference between "my desktop came back" and "my work is gone",
   and it matters most exactly when the reload was not your idea. An update that
   swept away eight open windows would be a worse feature than no update.

   What is kept is the arrangement, not the contents: which apps were open, on
   which desktop, minimised or maximised, and in what stacking order. Each app
   restores its own contents the way it already does — a conversation from the
   server, a folder from its own memory. Two things are deliberately not
   restored: a Terminal's shell (the pty died with the connection, and pretending
   otherwise would show a dead prompt) and anything a modal was in the middle of.

   `var`, not `let`: the bundle is one script and earlier files reach in here. */
var SESSION_KEY = 'session:desktop';
var SESSION_TEXT = 'session:draft:';       // per-conversation composer drafts
var _sessionT = null;
var SESSION_RESTORING = false;

/* Debounced: window moves fire continuously, and this is a localStorage write,
   not a render. */
function sessionSave() {
  if (SESSION_RESTORING) return;           // restoring is not a user arrangement
  clearTimeout(_sessionT);
  _sessionT = setTimeout(sessionSaveNow, 400);
}
function sessionSaveNow() {
  try {
    const wins = [];
    WM.wins.forEach(w => {
      if (!w || !w.id || !APPS[w.id]) return;
      wins.push({id: w.id, desk: w.desk || 1, min: !!w.min, max: !!w.max,
                 z: +(w.el && w.el.style.zIndex) || 0});
    });
    wins.sort((a, b) => a.z - b.z);        // reopen bottom-up so the stack lands right
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      v: 1, at: Date.now(), desk: (typeof curDesk !== 'undefined' ? curDesk : 1), wins}));
  } catch (e) {}
}

/* Reopen what was open. Never throws: one app that cannot start must not cost
   you the other seven. */
function sessionRestore() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null') } catch (e) {}
  if (!s || !Array.isArray(s.wins) || !s.wins.length) return 0;
  SESSION_RESTORING = true;
  let n = 0;
  try {
    s.wins.forEach(rec => {
      try {
        if (!APPS[rec.id]) return;         // an app that was uninstalled since
        const w = openApp(rec.id);
        if (!w) return;
        n++;
        if (rec.desk && rec.desk !== w.desk) w.desk = rec.desk;
        if (rec.max && typeof toggleMax === 'function' && !w.max) toggleMax(w);
        if (rec.min && typeof minimizeWin === 'function') minimizeWin(w);
      } catch (e) {}
    });
    if (s.desk && typeof switchDesk === 'function' && s.desk !== curDesk) switchDesk(s.desk);
    else if (typeof applyDeskVisibility === 'function') applyDeskVisibility();
  } catch (e) {}
  SESSION_RESTORING = false;
  return n;
}

/* ---- composer drafts ----
   A half-typed message is work too, and losing it to a reload is the small
   version of the same complaint. Kept per conversation so switching chats does
   not shuffle drafts between them, and cleared the moment it is sent. */
function draftKey(cid) { return SESSION_TEXT + (cid || 'new') }
function draftSave(cid, text) {
  try {
    if ((text || '').trim()) localStorage.setItem(draftKey(cid), text);
    else localStorage.removeItem(draftKey(cid));
  } catch (e) {}
}
function draftLoad(cid) {
  try { return localStorage.getItem(draftKey(cid)) || '' } catch (e) { return '' }
}
function draftClear(cid) {
  try { localStorage.removeItem(draftKey(cid)) } catch (e) {}
}

/* A reload can arrive with no warning (a deploy, an update, a crashed socket),
   so the last state is written on the way out as well as on every change. */
window.addEventListener('beforeunload', () => {
  try {
    sessionSaveNow();
    if (typeof currentConv !== 'undefined' && typeof input !== 'undefined' && input)
      draftSave(currentConv, input.value);
  } catch (e) {}
});

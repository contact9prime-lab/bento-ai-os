/* ================= what the agent is doing, right now =================
   A turn is mostly waiting, and every surface that showed the waiting showed
   the same three words — "Aria is working" — for as long as it lasted. A model
   thinking for forty seconds and a run that has silently died look identical
   under that label, so the only honest thing a watcher can do is stare at it.

   The stream already carries the answer: turn_start, status, thinking_delta,
   tool_start/tool_end and text_delta say which step is live and since when.
   This file is the one place that turns them into a sentence and a clock, and
   every surface (chat, copilot panel, omnibar card, presence bubble, voice
   overlay, menu-bar spinner) reads it rather than inventing its own wording.

   `var`, not `let`: the bundle is one script and earlier files reach in here.

   Not applicable to the TUI — it has no repainting surface to drive. It gets
   the same information as printed lines (tool detail + step duration), from
   the same events; see `tui_app.py`. */
var ACT = {};              // conversation_id -> live record
var ACT_TICK = null;       // the ONE repaint interval for every waiting surface

/* Verbs for the calls that are actually slow enough to be waited on. Anything
   missing falls back to its own name with the underscores taken out — a tool
   named `generate_image` needs no table entry to read as "generate image". */
var ACT_VERB = {
  Read:'reading', Write:'writing', Edit:'editing', NotebookEdit:'editing',
  Bash:'running', Glob:'looking for files', Grep:'searching', Task:'delegating',
  WebFetch:'fetching', WebSearch:'searching the web', TodoWrite:'planning',
  run_command:'running', read_file:'reading', write_file:'writing',
  list_dir:'listing', search_files:'searching', fetch_url:'fetching',
  llm_generate:'asking another model', delegate:'delegating',
  create_app:'building the app', develop_agentos:'changing AgentOS',
  read_source:'reading its own source', run_python:'running Python',
  generate_image:'generating an image', generate_wallpaper:'painting a wallpaper',
  take_screenshot:'looking at the screen', remember:'remembering',
  recall:'searching its memory', kg_query:'searching what it knows',
  run_tests:'running the tests', schedule_task:'scheduling it',
};

/* The argument that identifies a call, in a few words. The server sends this as
   `detail` on every tool_start; this mirror exists for events that predate it
   (a reconnect replaying an older server) so a surface never falls back to a
   bare tool name. Same shapes as `executors.tool_detail`. */
function actDetail(name, args) {
  args = args || {};
  const s = (...keys) => {
    for (const k of keys) {
      const v = args[k];
      if (typeof v === 'string' && v.trim()) return v.split(/\s+/).join(' ');
    }
    return '';
  };
  const base = p => String(p).split('/').filter(Boolean).pop() || p;
  const cut = (t, n) => t.length > n ? t.slice(0, n) + '…' : t;
  if (/^(Read|Write|Edit|NotebookEdit|read_file|write_file|list_dir|read_source)$/.test(name)) {
    const p = s('file_path', 'path', 'notebook_path'); return p ? base(p) : '';
  }
  if (name === 'Bash' || name === 'run_command') return cut(s('description', 'command'), 90);
  if (name === 'Glob' || name === 'Grep' || name === 'search_files') {
    const pat = s('pattern', 'query'), where = s('path', 'glob');
    return cut(pat + (where ? ' in ' + base(where) : ''), 90);
  }
  if (/^(WebFetch|WebSearch|fetch_url)$/.test(name)) {
    const u = s('url', 'query', 'prompt');
    try { return u.startsWith('http') ? new URL(u).hostname : cut(u, 90) } catch (e) { return cut(u, 90) }
  }
  for (const k in args) {
    const v = args[k];
    if (typeof v === 'string' && v.trim() && v.length <= 90) return v.split(/\s+/).join(' ');
  }
  return '';
}

/* A tool call id inside a RegExp — ids come from the model's provider, so they
   are not ours to assume are word characters. */
function reEsc(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }

/* ---- the record: begin, move, end ---- */
function actBegin(cid) {
  const now = Date.now();
  // A reconnect mid-turn must not reset the clock to zero and claim the run
  // just started — keep whatever start we already had for this conversation.
  const prev = ACT[cid];
  ACT[cid] = {t0: prev ? prev.t0 : now, since: now, phase: 'start',
              name: '', detail: '', msg: '', step: 0};
  actSync();
  return ACT[cid];
}
function actMove(cid, phase, extra) {
  if (!cid) return null;
  const a = ACT[cid] || actBegin(cid);
  // Re-entering the same phase (delta after delta) must not restart its clock.
  // Moving on drops the server's last sentence with it: "starting Claude Code…"
  // left standing after the first tool call is worse than no sentence at all.
  if (a.phase !== phase) { a.phase = phase; a.since = Date.now(); a.msg = '' }
  Object.assign(a, extra || {});
  actSync();
  return a;
}
function actDone(cid) { delete ACT[cid]; actSync() }

/* ---- wording ---- */
function actDur(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  return m < 60 ? m + 'm ' + (s % 60) + 's' : Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
}
/* What it is doing, as a phrase — no clock, no agent name. */
function actText(cid) {
  const a = ACT[cid]; if (!a) return '';
  switch (a.phase) {
    case 'tool': {
      const verb = ACT_VERB[a.name] || String(a.name || 'tool').replace(/_/g, ' ');
      return a.detail ? verb + ' ' + a.detail : verb;
    }
    case 'approve': return 'waiting for you to approve ' + (a.name || 'something');
    case 'think':   return a.msg || 'thinking';
    case 'after':   return a.msg || 'reading the result';
    case 'write':   return 'writing the reply';
    case 'queued':  return a.msg || 'waiting its turn';
    default:        return a.msg || 'getting started';
  }
}
/* The clock: how long in THIS step, and how long the turn has taken. Both,
   because a 4s step inside a 6-minute turn and a 4s turn are not the same. */
function actClock(cid) {
  const a = ACT[cid]; if (!a) return '';
  const now = Date.now(), step = now - a.since, total = now - a.t0;
  const parts = [actDur(step)];
  if (total - step > 4000) parts.push(actDur(total) + ' total');
  if (a.step > 0) parts.unshift('step ' + a.step);
  return parts.join(' · ');
}
/* One line for the cramped surfaces (bubble, placeholder, tooltips). */
function actLine(cid) {
  if (!ACT[cid]) return '';
  const t = actText(cid);
  return t ? t + ' · ' + actDur(Date.now() - ACT[cid].since) : '';
}
/* Whichever turn a surface with no conversation of its own should speak for. */
function actAny() {
  if (typeof currentConv !== 'undefined' && currentConv && ACT[currentConv]) return currentConv;
  for (const k in ACT) return k;
  return '';
}

/* ---- one interval, every surface ----
   Ticking is per second because that is the resolution of the clock being
   shown; it runs only while something is actually running, and stops itself
   the moment nothing is. */
function actSync() {
  // A waiting row counts as live even with no record behind it yet: the gap
  // between pressing send and the server's first event is exactly the one that
  // used to show nothing. Both surfaces have such a row — the copilot mini-feed
  // (.mf-working) AND the Chat window's own #working row. Missing the latter is
  // why a Claude Code turn, which cold-starts silently for a minute or more
  // before its first event, sat frozen at "0s": the ticker had stopped itself.
  const live = Object.keys(ACT).length > 0
    || !!document.querySelector('.mf-working')
    || !!document.querySelector('#working');
  if (live && !ACT_TICK) ACT_TICK = setInterval(actTick, 1000);
  if (!live && ACT_TICK) { clearInterval(ACT_TICK); ACT_TICK = null }
  actTick();
}
function actTick() {
  actPaintTimers();
  if (typeof tickWorking === 'function') tickWorking();
  if (typeof mfPaint === 'function') mfPaint();
  if (typeof aiBubble === 'function') aiBubble();
  if (typeof omniPresence === 'function') omniPresence();
  // the voice overlay is a waiting surface too — it just has no feed to read
  if (typeof JARVIS !== 'undefined' && JARVIS.busy && JARVIS.phase === 'thinking') {
    const line = actLine(JARVIS.cid || actAny());
    const st = $('#j-status'); if (st && line) st.textContent = line;
    const jv = $('#js-voice'); if (jv && line) jv.textContent = line;
  }
}
/* A tool card that says "running" for four minutes is the gap this closes:
   every open call carries its own age, wherever it was drawn. */
function actPaintTimers() {
  document.querySelectorAll('.tstat.run[data-t0]').forEach(el => {
    el.textContent = 'running · ' + actDur(Date.now() - (+el.dataset.t0 || Date.now()));
  });
}

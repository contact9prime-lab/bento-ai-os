"""An app's source, edited by hand: App Studio's code editor and `bento studio`.

A build is not the only way an app changes any more. A person can open the file, change
a line and save it, and that save is a version like any other. Three things keep a hand
edit honest, and both faces (the IDE's Save and `bento studio push`) go through `save`:

- **A save names the version it was edited from.** A build, a chat turn or another window
  can change the app while somebody is typing. Saving over that silently loses the other
  change, so a stale `base` is refused (`Conflict`) and the person chooses: load theirs,
  or keep theirs and save again with `force`.
- **The checker reads the text being edited, not only what was saved.** `problems` is
  `appcheck.check` with a line number on each finding where the rule can point at one,
  so the Problems list can jump to it.
- **A change in what the app asks for is reviewed again.** The grants decide what an app
  may do, and they are not touched here. But a manifest approved for the old source says
  nothing about an `appTool('run_command')` added by hand, so when the capability calls
  change, the manifest goes back to unreviewed and the Studio asks.

No HTTP and no asyncio, like jobs.py: `bento studio` works with the server down.
"""

from __future__ import annotations

import re

from . import appcheck

NOTE = "edited by hand in App Studio"
MAX_BYTES = 2_000_000          # an app is one HTML file; a paste of a video is not an app

# Where a finding can be pointed at. A rule missing here is about the whole file
# (no widget view, no copilot) and has no line.
_LOCATE = {
    "external-asset": r"<(?:script|link|img|iframe)\b[^>]*?(?:src|href)\s*=\s*[\"']https?://",
    "unknown-tool": None,                       # found by name, below
    "modal-dialog": r"(?<![\w.$])(?:window\.)?(?:confirm|prompt)\s*\(",
    "localstorage-not-appdata": r"\blocalStorage\b",
    "position-fixed": r"position\s*:\s*fixed",
    "position-absolute": r"position\s*:\s*absolute",
    "rotated-text": r"writing-mode|text-orientation|rotate\(\s*-?9[05]",
    "unstreamed-llm": r"\bawait\s+appLLM\s*\(",
}

# What an app asks the OS for, read the way the manifest scan reads it. A change here
# is a change in what somebody approved.
_ASKS = (r"appTool\(\s*['\"]([\w.-]+)['\"]", r"\b(appLLM|appChat|appAgent)\b",
         r"\b(appData)\b", r"fetch\(\s*['\"](/api/[\w/-]+)")


class Conflict(Exception):
    """The app moved on since the editor loaded it."""

    def __init__(self, current: int):
        super().__init__(f"the app changed since you opened it (now v{current})")
        self.current = current


def _line_at(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _script_starts(html: str) -> list[int]:
    """The line each classic inline <script>'s content starts on, in appcheck's order."""
    out = []
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html or "", re.I | re.S):
        attrs = m.group(1)
        if re.search(r"\bsrc\s*=|type\s*=\s*[\"']?(module|application/json|text/template|importmap)",
                     attrs, re.I) or not m.group(2).strip():
            out.append(0)
            continue
        out.append(_line_at(html, m.start(2)))
    return out


def problems(html: str, known_tools: set[str] | None = None) -> list[dict]:
    """Every appcheck finding as {severity, rule, message, fix, line}; line 0 means
    the whole file. Worst first, then by line."""
    rep = appcheck.check(html or "", known_tools)
    starts = None
    out = []
    for i in rep.issues:
        line = 0
        if i.rule == "js-syntax":
            m = re.search(r"script (\d+)(?: line (\d+))?", i.message)
            if m:
                starts = starts if starts is not None else _script_starts(html)
                # appcheck numbers the blocks it parsed, skipping none: the same list
                k = int(m.group(1)) - 1
                parsed = [s for s in starts if s]
                if 0 <= k < len(parsed):
                    line = parsed[k] + (int(m.group(2)) - 1 if m.group(2) else 0)
        elif i.rule == "unknown-tool":
            name = re.search(r"appTool\('([\w.-]+)'\)", i.message)
            if name:
                hit = re.search(r"appTool\(\s*['\"]" + re.escape(name.group(1)), html)
                line = _line_at(html, hit.start()) if hit else 0
        elif i.rule == "external-asset":
            url = i.message.rsplit(": ", 1)[-1]
            pos = html.find(url[:60])
            line = _line_at(html, pos) if pos >= 0 else 0
        elif i.rule == "top-level-await":
            hit = re.search(r"^\s*(?:const|let|var)?[^\n]*\bawait\b", html, re.M)
            line = _line_at(html, hit.start()) if hit else 0
        elif _LOCATE.get(i.rule):
            hit = re.search(_LOCATE[i.rule], html, re.I)
            line = _line_at(html, hit.start()) if hit else 0
        out.append({"severity": i.severity, "rule": i.rule, "message": i.message,
                    "fix": i.fix, "line": line})
    rank = {appcheck.BROKEN: 0, appcheck.CONTRACT: 1, appcheck.POLISH: 2}
    out.sort(key=lambda p: (rank.get(p["severity"], 3), p["line"] or 10**9))
    return out


def asks(html: str) -> set[str]:
    """What this source asks the OS for: tools by name, the AI runtime, its data, routes."""
    found = set()
    for pat in _ASKS:
        found.update(re.findall(pat, html or ""))
    return found


def current_version(store, aid: str) -> int:
    vs = store.app_versions(aid)
    return int(vs[0]["version"]) if vs else 0


def load(store, aid: str) -> dict | None:
    """The app's saved source and the version it is, for an editor to start from."""
    a = store.get_app(aid)
    if not a:
        return None
    return {"id": aid, "name": a["name"], "icon": a.get("icon") or "",
            "html": a.get("html") or "", "version": current_version(store, aid),
            "manifest_status": a.get("manifest_status") or "none"}


def save(store, aid: str, html: str, base: int | None = None, force: bool = False,
         note: str = "") -> dict:
    """Save edited source as the app's next version.

    Raises Conflict when `base` is older than the app's newest version (unless `force`),
    ValueError for something that is not an app. Returns {version, changed, review}:
    `review` is True when what the app asks for changed, so its manifest went back to
    unreviewed and the person should be asked again."""
    a = store.get_app(aid)
    if not a:
        raise ValueError("no such app")
    if not isinstance(html, str) or not html.strip():
        raise ValueError("an app can't be empty")
    if len(html.encode("utf-8", "replace")) > MAX_BYTES:
        raise ValueError(f"an app is one HTML file of at most {MAX_BYTES // 1_000_000} MB")
    now = current_version(store, aid)
    if base is not None and not force and int(base) != now:
        raise Conflict(now)
    before = a.get("html") or ""
    if before == html:
        return {"version": now, "changed": False, "review": False}
    store.save_app(a["name"], a.get("icon") or "", a.get("description") or "", html,
                   note=(note or NOTE)[:300])
    review = asks(before) != asks(html)
    if review and (a.get("manifest_status") or "none") != "none":
        # the grants stay as they are; the approved list no longer describes the source
        store.set_app_manifest(aid, a.get("manifest") or "{}", "none")
    store.log("system", f"app {a['name']}: {(note or NOTE)} (v{current_version(store, aid)})")
    return {"version": current_version(store, aid), "changed": True, "review": review}


# What a new app starts as, when somebody would rather write it than describe it. It is
# held to the same contract as a built one, so it starts with no findings worth a fix.
BLANK = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{name}</title>
<style>
  .big {{ font-size: 28px; font-weight: 700; }}
</style>
</head>
<body>
<div class="desktop-only">
  <div class="card">
    <h2>{name}</h2>
    <p class="mut">Edit this file, then press Save. The preview shows your saved version.</p>
    <div class="row">
      <button id="add">Add one</button>
      <span class="big" id="count">0</span>
    </div>
  </div>
</div>
<div class="widget-only">
  <div class="big" id="wcount">0</div>
</div>
<script>
(async () => {{
  const state = (await appData.get()) || {{ count: 0 }};
  const show = () => {{
    document.getElementById('count').textContent = state.count;
    document.getElementById('wcount').textContent = state.count;
  }};
  document.getElementById('add').onclick = async () => {{
    state.count += 1;
    show();
    await appData.set(state);
  }};
  show();
  appCopilot.mount({{ starters: ['What does this app do?'] }});
}})();
</script>
</body>
</html>
"""


def blank(name: str) -> str:
    safe = re.sub(r"[<>&\"']", "", name or "My app").strip()[:60] or "My app"
    return BLANK.format(name=safe)

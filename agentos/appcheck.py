"""Does a built app honour the app contract? One place that answers, for every build path.

`BUILDER_PERSONA` states a contract in some detail — two surfaces, `appData` rather than
localStorage, `appCopilot.mount`, no external assets, the AI runtime is not optional. Until
now that contract was **advice**: the one-shot builder was checked for truncation and a few
layout smells, and the Claude Code executor path — the good one, the one that writes the app
as a file and iterates — returned at `server.py:8457` before the verification block at 8529
and was checked for almost nothing at all. So the better the build path, the less anyone
looked at what came out of it.

This module is the checker both paths call, and the reason it is a module rather than two
more functions in server.py is that `executors.py` needs it too and server.py already
imports executors. A second copy over there would drift, and the half that drifted would be
whichever one nobody was demoing.

Three severities, and the distinction is the whole design:

- `broken`   — it will fail at runtime. A blocked CDN, a tool that does not exist, JS that
               cannot parse. Worth another build turn on its own.
- `contract` — it runs, but it is not a Bento app: no widget surface, state in localStorage
               where neither the agent nor another device can reach it, no copilot. This is
               the band that was invisible, and it is exactly where "why do generated apps
               feel generic?" lives.
- `polish`   — real but small. Reported, never worth a rebuild by itself.

Nothing here deletes or refuses an app. The expensive failure in this codebase has always
been throwing away work that was already done and paid for; findings feed a fix pass and
then ship as honest warnings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Severity ordering, worst first — used for sorting and for "is this worth a fix turn?"
BROKEN, CONTRACT, POLISH = "broken", "contract", "polish"
_RANK = {BROKEN: 0, CONTRACT: 1, POLISH: 2}


@dataclass
class Issue:
    severity: str
    rule: str
    message: str          # what is wrong, in the user's terms
    fix: str = ""         # what to do about it, concretely

    def line(self) -> str:
        return f"{self.message}{(' — ' + self.fix) if self.fix else ''}"


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.issues)

    def of(self, *severities: str) -> list[Issue]:
        return [i for i in self.issues if i.severity in severities]

    @property
    def worth_fixing(self) -> list[Issue]:
        """What justifies spending another executor turn: anything that breaks at
        runtime, plus contract violations. Polish rides along in the same pass but
        never triggers one on its own — a rebuild costs the user real money."""
        return self.of(BROKEN, CONTRACT)

    def lines(self) -> list[str]:
        return [i.line() for i in sorted(self.issues, key=lambda i: _RANK[i.severity])]

    def brief(self, limit: int = 12) -> str:
        """The findings as a prompt fragment, worst first."""
        return "\n".join(f"- [{i.severity}] {i.line()}" for i in
                         sorted(self.issues, key=lambda i: _RANK[i.severity])[:limit])


# --------------------------------------------------------------------------- helpers

def _scripts(html: str) -> list[str]:
    """The contents of every <script> block (inline only — external ones are a separate
    finding, and their source is not ours to read)."""
    return re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.I | re.S)


def _strip_strings_and_comments(js: str) -> str:
    """JS with string/template/comment bodies blanked, so a rule cannot be fooled by the
    word it is looking for appearing inside a string. Crude but stable: it preserves
    offsets, which is what the brace-depth walk below depends on."""
    out = list(js)
    i, n = 0, len(js)
    while i < n:
        c = js[i]
        if c in "\"'`":
            q, j = c, i + 1
            while j < n:
                if js[j] == "\\":
                    j += 2
                    continue
                if js[j] == q:
                    break
                j += 1
            for k in range(i, min(j + 1, n)):
                out[k] = " " if js[k] not in "\n" else "\n"
            i = j + 1
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "/":
            j = js.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and js[i + 1] == "*":
            j = js.find("*/", i)
            j = n if j == -1 else j + 2
            for k in range(i, min(j, n)):
                out[k] = " " if js[k] != "\n" else "\n"
            i = j
            continue
        i += 1
    return "".join(out)


def _top_level_awaits(js: str) -> bool:
    """`await` at brace depth 0 of a classic <script>.

    This is the single most common way a generated app dies completely: a plain script
    is not a module, so top-level await is a SyntaxError and the whole file stops
    executing — a blank window with one line in a console nobody has open. The persona
    warns about it in prose; prose is not a check.
    """
    src = _strip_strings_and_comments(js)
    depth = 0
    for m in re.finditer(r"[{}]|\bawait\b", src):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth = max(0, depth - 1)
        elif depth == 0:
            return True
    return False


def _has(html: str, pattern: str) -> bool:
    return re.search(pattern, html, re.I) is not None


# ----------------------------------------------------------------------------- rules

def check(html: str, known_tools: set[str] | None = None) -> Report:
    """Every contract check, in one pass. `known_tools` enables the appTool name check;
    omit it where the toolbox is not to hand and that one rule is simply skipped."""
    issues: list[Issue] = []
    h = html or ""
    add = issues.append

    # ---- broken: it will not work -------------------------------------------------
    for m in re.finditer(
            r"<(?:script|link|img|iframe)\b[^>]*?(?:src|href)\s*=\s*[\"'](https?://[^\"']+)",
            h, re.I):
        add(Issue(BROKEN, "external-asset",
                  f"external asset is blocked at runtime: {m.group(1)[:100]}",
                  "inline the code/style, or embed the asset as a data: URI"))

    if known_tools:
        for m in re.finditer(r"appTool\(\s*['\"]([\w.-]+)['\"]", h):
            if m.group(1) not in known_tools:
                add(Issue(BROKEN, "unknown-tool",
                          f"appTool('{m.group(1)}') names a tool that does not exist",
                          "use a name from the API registry"))

    for js in _scripts(h):
        if _top_level_awaits(js):
            add(Issue(BROKEN, "top-level-await",
                      "a plain <script> uses top-level await — a SyntaxError that stops "
                      "the whole app from running",
                      "wrap startup in (async () => { … })();"))
            break

    # ---- contract: it runs, but it is not a Bento app ------------------------------
    # Both surfaces. An app with no widget view is not pinnable in any useful way: the
    # OS renders the whole desktop application into a 260x170 tile and the user sees a
    # scrollbar where the one glanceable fact should be.
    if not _has(h, r"class\s*=\s*[\"'][^\"']*\bwidget-only\b"):
        add(Issue(CONTRACT, "no-widget-surface",
                  "no widget view — pinned to the desktop this shows the full app "
                  "squeezed into a tile",
                  'wrap a glanceable view in <div class="widget-only">…</div>'))
    if not _has(h, r"class\s*=\s*[\"'][^\"']*\bdesktop-only\b") and \
            _has(h, r"class\s*=\s*[\"'][^\"']*\bwidget-only\b"):
        add(Issue(CONTRACT, "no-desktop-surface",
                  "a widget view exists but the full application is not wrapped as the "
                  "desktop surface",
                  'wrap the application in <div class="desktop-only">…</div>'))

    # State the agent cannot read is state the OS cannot act on. localStorage is also
    # per-browser, so the same app on the user's phone is empty.
    uses_appdata = _has(h, r"\bappData\s*\.\s*(get|set)\b")
    if _has(h, r"\blocalStorage\b") and not uses_appdata:
        add(Issue(CONTRACT, "localstorage-not-appdata",
                  "user data is kept in localStorage, so the agent cannot read it and it "
                  "does not follow the user to another device",
                  "persist with await appData.set({…}) / await appData.get()"))

    if not _has(h, r"\bappCopilot\s*\.\s*mount\b"):
        add(Issue(CONTRACT, "no-copilot",
                  "the app has no resident agent (the ✦ corner button)",
                  "call appCopilot.mount({starters:[…]}) once at startup"))

    # The AI runtime is the reason this is not a static page. An app that touches none
    # of it is a web page that happens to live in Bento.
    if not _has(h, r"\bapp(LLM|Chat|Agent)\b") and not _has(h, r"\bappCopilot\b"):
        add(Issue(CONTRACT, "no-ai",
                  "the app uses none of the built-in AI runtime",
                  "appLLM.stream for visible output, appChat for conversation, "
                  "appAgent when it should act"))

    # Layout rules the design system exists to make unnecessary.
    if _has(h, r"position\s*:\s*fixed"):
        add(Issue(CONTRACT, "position-fixed",
                  "uses position:fixed for layout",
                  "restructure with .card / .row / .cols / .grid2"))
    if len(re.findall(r"position\s*:\s*absolute", h, re.I)) > 2:
        add(Issue(CONTRACT, "position-absolute",
                  "layout leans on position:absolute",
                  "restructure with .card / .row / .cols / .grid2"))
    if _has(h, r"writing-mode|text-orientation|rotate\(\s*-?9[05]"):
        add(Issue(CONTRACT, "rotated-text",
                  "rotated or vertical text", "use a normal horizontal label"))

    # ---- polish -------------------------------------------------------------------
    # A list with no empty state is the first thing a new user sees, and it is blank.
    renders_list = _has(h, r"\.(map|forEach)\s*\(") or _has(h, r"<(ul|ol|tbody)\b")
    if renders_list and not _has(h, r"class\s*=\s*[\"'][^\"']*\bempty\b"):
        add(Issue(POLISH, "no-empty-state",
                  "a list is rendered with no empty state",
                  'add <div class="empty">…</div> saying what to do first'))
    if _has(h, r"\bappTool\s*\(") and not _has(h, r"\bcatch\b"):
        add(Issue(POLISH, "no-error-handling",
                  "appTool is called with no catch — a failing tool leaves the UI blank",
                  "wrap calls in try/catch and show a .err state"))
    if _has(h, r"\bawait\s+appLLM\s*\(") and not _has(h, r"appLLM\s*\.\s*stream"):
        add(Issue(POLISH, "unstreamed-llm",
                  "user-visible AI output uses appLLM instead of appLLM.stream",
                  "stream it — a live-updating element beats a spinner"))

    return Report(issues)


def structural(html: str) -> list[str]:
    """Truncation / malformed-output checks, kept separate because they answer a
    different question: not "is this a good app" but "did the model finish writing it".
    Delegates to server's implementation, which owns the HTML parse."""
    from .server import _validate_app_html
    return _validate_app_html(html)

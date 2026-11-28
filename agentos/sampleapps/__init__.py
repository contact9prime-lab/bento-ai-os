"""Bento's own sample apps: small productivity apps, published to the Bento Registry
as "bento".

Each app is one HTML file in this folder, written to the same bar App Studio holds a
build to (the design kit, both surfaces, appData, an AI feature, the copilot). This
module turns it into the package the rest of the OS already speaks: an
`agentos-app/1` file with its manifest, its permissions in words, a fresh security
scan and the checksum over all of it (`appregistry.package_checksum`). Nothing here
is a second format or a second install path: a package built here imports through
Store → Import and publishes through `bento registry push app FILE`, like any app
exported from a machine.

The built packages live in `registry/apps/<slug>/` and are checked in, like the UI
bundle: `tests/test_sample_apps.py` fails when one is stale. Rebuild with
`bento apps samples build`.

Stdlib only, and no import of the server: building a package must not open anyone's
database.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = REPO / "registry" / "apps"

# Who wrote them, said the way the commons says it (appregistry.AUTHOR_KINDS).
AUTHOR = {"kind": "agent", "name": "Bento: written with an AI agent and checked by the Bento team"}

_DATA = [
    {"action": "app.data.read", "resource": "app:self/data", "reason": "load what you saved when the app opens",
     "required": True},
    {"action": "app.data.write", "resource": "app:self/data", "reason": "save what you add and change",
     "required": True},
]
_AI = {"action": "tool.use", "resource": "tool:llm_generate*", "required": False}
_AGENT = {"action": "agent.invoke", "resource": "agent:main", "required": False,
          "reason": "the ✦ assistant in the corner, which can act for you inside this app"}

# One row per app. `summary` is the registry's one line; `about` is the manifest's
# description, shown on the consent screen.
APPS = [
    {"slug": "focus-sessions", "name": "Focus Sessions",
     "summary": "Calm focus sessions with breaks, a daily goal and a week at a glance",
     "about": "A focus timer with short and long breaks, a daily goal, a streak and a chart of your week. "
              "The AI plans a session's steps and looks back on where your time went.",
     "permissions": [*_DATA, {**_AI, "reason": "plan a session's steps and look back on your week"},
                     {"action": "tool.use", "resource": "tool:notify*", "required": False,
                      "reason": "a desktop notification when a session or break ends"}, _AGENT]},
    {"slug": "habit-tracker", "name": "Habit Tracker",
     "summary": "Daily habits with streaks, a four-week grid and a coach",
     "about": "Tick off daily habits, keep your streaks and see the last four weeks at a glance. "
              "The AI coach reads your history and suggests one small change.",
     "permissions": [*_DATA, {**_AI, "reason": "the coach, which reads your habit history"}, _AGENT]},
    {"slug": "kanban-board", "name": "Kanban Board",
     "summary": "A to do, doing and done board you can type tasks into",
     "about": "A three-column board for your tasks, with due dates, priorities and a limit on work in progress. "
              "Type a task in plain words and the AI fills in the details, or ask it to break a card into steps.",
     "permissions": [*_DATA, {**_AI, "reason": "read a task typed in plain words, and break a card into steps"},
                     _AGENT]},
    {"slug": "meeting-notes", "name": "Meeting Notes",
     "summary": "Agenda, notes, decisions and actions, summarised for you",
     "about": "Keep each meeting's agenda, notes, decisions and action items with owners and dates. "
              "The AI writes the summary and pulls the actions out of your notes; every open action is in one list.",
     "permissions": [*_DATA, {**_AI, "reason": "summarise a meeting and pull the actions out of your notes"},
                     _AGENT]},
    {"slug": "daily-planner", "name": "Daily Planner",
     "summary": "Your day as time blocks, with your top three and a plan drafted for you",
     "about": "Plan today as time blocks around your top three priorities, see what's now and next, "
              "and carry unfinished priorities to tomorrow. The AI drafts the day's blocks for you to keep or change.",
     "permissions": [*_DATA, {**_AI, "reason": "draft a plan for your day from your priorities"}, _AGENT]},
]
BY_SLUG = {a["slug"]: a for a in APPS}


def html_of(slug: str) -> str:
    return (HERE / f"{slug}.html").read_text()


def _scanned_at(slug: str, block: dict) -> float:
    """When it was scanned: kept from the checked-in package while its findings are the
    same, so rebuilding unchanged sources writes the same bytes."""
    try:
        old = json.loads(path_of(slug).read_text())["manifest"]["security"]
        if old.get("findings") == block["findings"] and old.get("scanner") == block["scanner"]:
            return old["scanned_at"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return round(block["scanned_at"])


def manifest(slug: str, html: str | None = None) -> dict:
    from .. import appregistry
    a = BY_SLUG[slug]
    html = html_of(slug) if html is None else html
    sec = appregistry.scan_block(html)
    sec["scanned_at"] = _scanned_at(slug, sec)
    return {"format": 1, "name": a["name"], "icon": "", "description": a["about"], "version": "1",
            "permissions": [dict(p) for p in a["permissions"]], "prerequisites": {},
            "security": sec, "author": dict(AUTHOR)}


def package(slug: str) -> dict:
    """The `agentos-app/1` package for one sample app, byte for byte what is checked in."""
    from .. import appregistry
    if slug not in BY_SLUG:
        raise KeyError(f"there is no sample app called {slug!r}; there are {', '.join(BY_SLUG)}")
    html = html_of(slug)
    man = manifest(slug, html)
    return {"format": appregistry.PACKAGE_FORMAT, "manifest": man, "html": html,
            "checksum": appregistry.package_checksum(man, html), "signature": None}


def text_of(pkg: dict) -> str:
    return json.dumps(pkg, indent=1, ensure_ascii=False) + "\n"


def path_of(slug: str) -> Path:
    return OUT / slug / f"{slug}.agentapp.json"


def build(slugs: list[str] | None = None) -> list[Path]:
    """Write the packages into registry/apps. Returns what was written."""
    out = []
    for slug in slugs or list(BY_SLUG):
        p = path_of(slug)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text_of(package(slug)))
        out.append(p)
    return out


def stale() -> list[str]:
    """The sample apps whose checked-in package no longer matches their source."""
    bad = []
    for slug in BY_SLUG:
        p = path_of(slug)
        if not p.is_file() or p.read_text() != text_of(package(slug)):
            bad.append(slug)
    return bad


def checked_in(slug: str) -> dict:
    """The package as checked in under registry/apps, else built: the bytes `bento registry push`
    sends, so the Store's Publish and the terminal publish the same thing."""
    p = path_of(slug)
    if p.is_file():
        return json.loads(p.read_text())
    return package(slug)


def summary_of(pkg: dict) -> str:
    """The registry's one line for an app: a sample app's own, else the first sentence of
    what its manifest says it does."""
    man = pkg.get("manifest") or {}
    for a in APPS:
        if a["name"] == man.get("name") and pkg.get("html") == html_of(a["slug"]):
            return a["summary"]
    about = (man.get("description") or "").strip()
    return about.split(". ")[0].rstrip(".")[:280]

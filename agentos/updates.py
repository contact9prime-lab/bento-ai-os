"""Staying current: is there a new version, and may I install it?

The shape of the problem is unusual. AgentOS is not an app somebody quits and
reopens — it is a service holding conversations, a desktop drawn as a page, and
possibly the user's whole session. So "update" is three things that must all
happen, in order, or the machine ends up in a state nobody chose:

    the code on disk  ->  the running service  ->  the page on screen

Miss the second and the new code is on disk but not answering. Miss the third
and the user is looking at the old shell talking to the new server, which is the
worst of the three because it looks like it worked.

Four rules this module keeps:

- **Never without being asked.** A check is automatic; an install never is. An
  agentic OS that could silently replace its own code is a different product
  from the one somebody agreed to run, and the user's own consent model
  (`policy.py`) would be pointless if the code implementing it could rewrite
  itself overnight.
- **Refuse rather than guess.** A checkout with local edits, a detached HEAD, no
  git, no network: each gets a sentence naming what is wrong instead of a
  half-applied update. Somebody developing against their own install must not
  lose work to a version check.
- **A failed update rolls back.** The commit before the pull is recorded, and if
  the test suite does not pass against the new code the checkout goes back to
  it. A machine that cannot answer is worse than a machine one version behind.
- **The version is read, never inferred.** Local and remote are the same file at
  the same path, so comparing them cannot drift with packaging.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path

import httpx

from . import __version__

#: Where the published version lives. The repo is public, so this needs no
#: credentials — an updater that required a token would be one most installs
#: could not use.
RAW = "https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os"
DEFAULT_BRANCH = "master"          # HEAD on this remote; `main` is stale (see install.sh)

CHECK_TIMEOUT = 10.0
#: How long an install may take before we stop waiting on it. A dependency sync
#: over a slow link is the long pole; the test run after it is seconds.
APPLY_TIMEOUT = 900


def _run(args: list[str], cwd: Path | None = None, timeout: int = 60) -> tuple[bool, str]:
    try:
        p = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def current() -> str:
    return __version__


def parse(v: str) -> tuple:
    """'0.2.10-rc1' -> (0, 2, 10). Trailing labels are ignored for ordering: a
    release and its candidate are the same version as far as "is there something
    newer" is concerned, and pretending to a total order over arbitrary suffixes
    is how a machine decides a release is older than itself."""
    nums = re.findall(r"\d+", (v or "").split("-")[0].split("+")[0])
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse(remote) > parse(local)


def conf(cfg: dict) -> dict:
    c = (cfg or {}).setdefault("updates", {})
    c.setdefault("enabled", True)          # checking is on; installing still asks
    c.setdefault("branch", DEFAULT_BRANCH)
    c.setdefault("check_interval_hours", 24)
    c.setdefault("last_check", 0.0)
    c.setdefault("last_seen", "")          # the newest version we have told them about
    c.setdefault("skipped", "")            # a version the user said no to
    return c


# ---------------------------------------------------------------- where we live

def install_dir() -> Path | None:
    """The git checkout this code is running from, if it is one.

    A pip/wheel install has no checkout and cannot be updated this way; it says
    so rather than pretending, because `git pull` in a site-packages directory
    is the kind of thing that half-works and then cannot be explained.
    """
    root = Path(__file__).resolve().parent.parent
    return root if (root / ".git").exists() else None


def can_apply(cfg: dict) -> tuple[bool, str]:
    """May an update be installed right now? Returns (ok, why not)."""
    root = install_dir()
    if not root:
        return False, ("This copy was not installed from git, so it cannot update itself. "
                       "Reinstall with the installer, or update however you installed it.")
    ok, _ = _run(["git", "--version"])
    if not ok:
        return False, "git is not available on this machine."
    # `--untracked-files=no` matters more than it looks. An UNTRACKED file is not
    # work a fast-forward can clobber — git will not touch it — but almost every
    # real checkout has some: __pycache__, an editor backup, a stray log, a tool's
    # dotfolder. Counting those as "uncommitted changes" made the machine this was
    # written on permanently un-updatable, and it would have done the same to most
    # installs. If an incoming commit does add a file at that path the merge fails
    # on its own, cleanly, having changed nothing — which is the honest place for
    # that collision to be reported.
    ok, out = _run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root)
    if not ok:
        return False, f"could not read the checkout: {out[:200]}"
    if out.strip():
        n = len(out.strip().splitlines())
        return False, (f"There are {n} uncommitted change(s) to tracked files in {root}. "
                       f"Updating would pull on top of your own work, so it is refused — "
                       f"commit or stash them first.")
    ok, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    want = conf(cfg).get("branch") or DEFAULT_BRANCH
    if not ok or branch.strip() != want:
        return False, (f"The checkout is on '{branch.strip() or 'an unknown ref'}', not "
                       f"'{want}'. Switch to it first, or change the update branch in "
                       f"Settings.")
    return True, ""


# ------------------------------------------------------------------- the check

async def check(cfg: dict, force: bool = False) -> dict:
    """Is there a newer published version? Never raises: a machine with no
    network must not have a broken Settings page."""
    c = conf(cfg)
    now = time.time()
    state = {"current": current(), "latest": "", "update_available": False,
             "notes": "", "checked_at": c.get("last_check") or 0.0, "error": ""}
    if not force and not c.get("enabled", True):
        state["error"] = "update checks are switched off"
        return state
    branch = c.get("branch") or DEFAULT_BRANCH
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            r = await client.get(f"{RAW}/{branch}/agentos/VERSION")
            r.raise_for_status()
            latest = r.text.strip().splitlines()[0].strip()
    except httpx.HTTPStatusError as e:
        state["error"] = (f"the '{branch}' branch does not publish a version file "
                          f"(HTTP {e.response.status_code}) — nothing to compare against")
        return state
    except Exception as e:
        state["error"] = f"could not reach the update server ({type(e).__name__})"
        return state
    if not re.match(r"^\d+(\.\d+)*", latest or ""):
        state["error"] = "the update server returned something that is not a version"
        return state
    c["last_check"] = now
    state["checked_at"] = now
    state["latest"] = latest
    state["update_available"] = is_newer(latest, current())
    if state["update_available"]:
        state["notes"] = await _notes(branch)
    return state


def entries(text: str, limit: int = 3) -> list[dict]:
    """Split a changelog into its most recent entries.

    Shared by the update card (which reads the PUBLISHED changelog to say what a
    new version would bring) and the About tab (which reads the LOCAL one to say
    what this build already has). Same parser, so the two can never describe the
    same release differently.
    """
    head = re.compile(r"^#{2,}\s+(.*)$")
    out: list[dict] = []
    cur: dict | None = None
    for ln in (text or "").splitlines():
        m = head.match(ln)
        if m:
            if cur:
                out.append(cur)
                if len(out) >= limit:
                    break
            cur = {"title": m.group(1).strip(), "body": []}
            continue
        if cur is not None:
            cur["body"].append(ln)
    if cur and len(out) < limit:
        out.append(cur)
    # One exit, so a truncated list is finished the same way a complete one is —
    # the early return left `body` as a list of lines for every caller that
    # asked for fewer entries than the file has.
    for e in out:
        e["body"] = "\n".join(e["body"]).strip()
    return out


def local_notes(limit: int = 3) -> list[dict]:
    """What this build contains, from the changelog on disk."""
    root = install_dir() or Path(__file__).resolve().parent.parent
    try:
        return entries((root / "CHANGELOG.md").read_text(), limit)
    except OSError:
        return []


async def _notes(branch: str) -> str:
    """The top of the changelog — what this version actually changes.

    "A new version is available" is not a reason to restart the machine you are
    working on; what changed is. Best-effort: no changelog, no card copy, and
    the update still offers itself.
    """
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            r = await client.get(f"{RAW}/{branch}/CHANGELOG.md")
            r.raise_for_status()
    except Exception:
        return ""
    # The first heading BELOW the title is the newest entry; everything until the
    # next one is what changed. Matched by depth rather than by "## " exactly,
    # because this project's changelog uses "### " and a literal prefix check
    # silently returned the title and nothing else.
    head = re.compile(r"^#{2,}\s")
    out, started = [], False
    for ln in r.text.splitlines():
        if head.match(ln):
            if started:
                break
            started = True
        if started:
            out.append(ln)
            if len(out) > 40:
                break
    return "\n".join(out).strip()[:1500]


# ------------------------------------------------------------------- the install

def commits(a: str, b: str, limit: int = 20, root: Path | None = None) -> list[dict]:
    """The commits between two revisions, newest first.

    The changelog nobody has to remember to write. CHANGELOG.md is still read for
    the published release notes, but it is a file somebody maintains by hand, so
    on any branch that is not a tagged release it says nothing about what is
    actually arriving. Git already knows.

    Merges are skipped: a merge commit's subject is "Merge pull request #11",
    which is true and tells you nothing about what changed. The commits it brought
    in are in the range anyway.
    """
    root = root or install_dir()
    if not root or not a or not b or a == b:
        return []
    sep, rec = "\x1f", "\x1e"
    ok, out = _run(["git", "log", "--no-merges", f"-{max(1, int(limit))}",
                    f"--pretty=format:%h{sep}%s{sep}%an{sep}%ct{rec}", f"{a}..{b}"],
                   cwd=root)
    if not ok:
        return []
    rows = []
    for chunk in out.split(rec):
        parts = chunk.strip().strip("\n").split(sep)
        if len(parts) < 4 or not parts[0]:
            continue
        try:
            when = int(parts[3])
        except ValueError:
            when = 0
        # The subject only. A body in this repo runs to forty lines of reasoning,
        # which is right in `git log` and wrong in a list of what an update brings.
        rows.append({"hash": parts[0], "title": parts[1][:160],
                     "author": parts[2][:60], "at": when})
    return rows


async def pending(cfg: dict, limit: int = 20) -> list[dict]:
    """What an update WOULD bring, straight from the branch it would pull.

    Fetches, because "what is waiting for me" cannot be answered from a checkout
    that has not looked. It never merges — this is the read half, and it stays
    safe to call from a status route.
    """
    root = install_dir()
    if not root:
        return []
    branch = conf(cfg).get("branch") or DEFAULT_BRANCH
    if not _run(["git", "fetch", "origin", branch], cwd=root, timeout=120)[0]:
        return []
    return commits("HEAD", f"origin/{branch}", limit=limit, root=root)


async def apply(cfg: dict, run_tests: bool = True, log=None) -> dict:
    """Pull, sync dependencies, verify, and report what to do next.

    Restarting is deliberately NOT done here. This function's caller owns the
    order — the HTTP response has to reach the browser before the service that
    is sending it goes away, or the page never learns the update succeeded and
    shows a network error for something that worked.
    """
    def say(msg):
        if log:
            log(msg)

    ok, why = can_apply(cfg)
    if not ok:
        return {"ok": False, "error": why}
    root = install_dir()
    branch = conf(cfg).get("branch") or DEFAULT_BRANCH

    got, before = _run(["git", "rev-parse", "HEAD"], cwd=root)
    if not got:
        return {"ok": False, "error": f"could not read the current commit: {before[:200]}"}
    before = before.strip()

    say("fetching…")
    ok, out = _run(["git", "fetch", "origin", branch], cwd=root, timeout=180)
    if not ok:
        return {"ok": False, "error": f"fetch failed: {out[-400:]}"}

    say("applying…")
    # --ff-only: an update is meant to be what upstream published, not a merge
    # somebody has to resolve on a machine they are not sitting at.
    ok, out = _run(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=root, timeout=120)
    if not ok:
        return {"ok": False, "error": (f"could not fast-forward to origin/{branch}: "
                                       f"{out[-400:]}")}

    def rollback(reason: str) -> dict:
        _run(["git", "reset", "--hard", before], cwd=root, timeout=120)
        return {"ok": False, "rolled_back": True, "from": before[:8],
                "error": f"{reason} — rolled back to {before[:8]}, nothing changed."}

    changed = _run(["git", "diff", "--name-only", before, "HEAD"], cwd=root)[1].splitlines()
    if any(f in ("pyproject.toml", "uv.lock") for f in changed):
        say("updating dependencies…")
        ok, out = _run(["uv", "sync"], cwd=root, timeout=APPLY_TIMEOUT)
        if not ok:
            ok, out = _run([_python(root), "-m", "pip", "install", "-e", "."],
                           cwd=root, timeout=APPLY_TIMEOUT)
        if not ok:
            return rollback(f"dependencies could not be installed: {out[-300:]}")

    if run_tests:
        # The same guard `restart_agentos` uses, for the same reason: code that
        # cannot pass its own tests must not become the code answering turns.
        say("verifying…")
        ok, out = _run([_python(root), "-m", "pytest", "tests/", "-q", "-x"],
                       cwd=root, timeout=APPLY_TIMEOUT)
        if not ok:
            return rollback(f"the new version fails its own tests: {out[-300:]}")

    after = _run(["git", "rev-parse", "HEAD"], cwd=root)[1].strip()
    # What was actually pulled, from git rather than from a file somebody has to
    # remember to write. Computed AFTER the merge, so it describes what landed
    # rather than what was expected to.
    return {"ok": True, "from": before[:8], "to": after[:8],
            "changes": commits(before, after, limit=20, root=root),
            "version": _version_on_disk(root) or current(),
            "unchanged": after == before,
            "files": len(changed)}


def _python(root: Path) -> str:
    venv = root / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else "python3"


def _version_on_disk(root: Path) -> str:
    try:
        return (root / "agentos" / "VERSION").read_text().strip()
    except OSError:
        return ""


async def watch(cfg, store, broadcast, save_config) -> None:
    """Check on a schedule and tell the desktop when there is something new.

    Announced ONCE per version, not once per check: a card that reappears every
    day for a version somebody already declined is how people learn to dismiss
    cards without reading them.
    """
    await asyncio.sleep(90)                 # let the machine finish starting
    while True:
        try:
            c = conf(cfg)
            hours = max(1, int(c.get("check_interval_hours") or 24))
            due = time.time() - float(c.get("last_check") or 0) >= hours * 3600
            if c.get("enabled", True) and due:
                res = await check(cfg)
                if res["update_available"] and res["latest"] not in (c.get("skipped"),
                                                                     c.get("last_seen")):
                    c["last_seen"] = res["latest"]
                    store.log("system", f"update available: {res['latest']} "
                                        f"(running {res['current']})")
                    await broadcast({"type": "update", **res})
                save_config(cfg)
        except Exception as e:                 # never let the loop die
            with_store = getattr(store, "log", None)
            if with_store:
                store.log("error", f"update check: {type(e).__name__}: {e}")
        await asyncio.sleep(3600)

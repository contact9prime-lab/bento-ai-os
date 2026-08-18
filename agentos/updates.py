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
import os
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


def _run(args: list[str], cwd: Path | None = None, timeout: int = 60,
         env: dict | None = None) -> tuple[bool, str]:
    try:
        full_env = {**os.environ, **env} if env else None
        p = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout, env=full_env)
        return p.returncode == 0, (p.stdout + p.stderr).strip()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _fresh_pyc_env() -> dict:
    """A private bytecode-cache directory for one pytest run.

    The regression gate runs the suite on the new code, then `git reset --hard`
    to the old code and runs it again. Those two checkouts can land in the SAME
    second, and git stamps the restored file with the checkout time — so Python,
    which decides a `.pyc` is fresh by comparing that mtime, happily reuses the
    bytecode it just compiled from the NEW source while running the OLD source.
    The old code then "fails" a test it actually passes, and the gate mistakes a
    real regression for a pre-existing failure. A fresh `PYTHONPYCACHEPREFIX` per
    run points each invocation at an empty cache, so every import compiles from
    the source actually on disk. Found the hard way, in exactly this file's tests.
    """
    import tempfile
    return {"PYTHONPYCACHEPREFIX": tempfile.mkdtemp(prefix="agentos-pyc-")}


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
    c.setdefault("last_mark", "")          # version + newest waiting commit, told once
    c.setdefault("last_behind", 0)         # commits waiting at the last check
    c.setdefault("last_on_branch", "")     # the branch the checkout was on then
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

def git_state(cfg: dict, limit: int = 20) -> dict:
    """What the CHECKOUT knows: which branch it is on, which one updates track,
    and exactly how many commits are waiting on it.

    This exists because the version file lied by omission. `agentos/VERSION` is
    written by hand at a release; between releases it does not move, so a machine
    could be twenty commits behind the branch it tracks and be told, truthfully
    about the file and uselessly about the code, that it was up to date. Git
    already knows the answer — this asks it.

    Blocking: it fetches. Callers on the event loop must use a thread.
    """
    out = {"root": "", "on_branch": "", "tracks": conf(cfg).get("branch") or DEFAULT_BRANCH,
           "behind": 0, "ahead": 0, "commits": [], "error": ""}
    root = install_dir()
    if not root:
        # Not a git install. Not an error — it simply has no second source of
        # truth, and the version comparison is all it can do.
        return out
    out["root"] = str(root)
    ok, branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    out["on_branch"] = branch.strip() if ok else ""
    want = out["tracks"]
    if not _run(["git", "fetch", "origin", want], cwd=root, timeout=120)[0]:
        out["error"] = f"could not fetch origin/{want} — no network, or the branch is gone"
        return out
    def count(rng: str) -> int:
        # Counted the way `commits()` LISTS: non-merges, falling back to the full
        # count when merges are all there is. A number that does not match the
        # list under it is how "2 changes waiting" appeared above nothing.
        for args in (["--count", "--no-merges", rng], ["--count", rng]):
            ok, n = _run(["git", "rev-list", *args], cwd=root)
            try:
                got = int(n.strip()) if ok else 0
            except ValueError:
                got = 0
            if got:
                return got
        return 0

    out["behind"] = count(f"HEAD..origin/{want}")
    out["ahead"] = count(f"origin/{want}..HEAD")
    if out["behind"]:
        out["commits"] = commits("HEAD", f"origin/{want}", limit=limit, root=root)
    return out


async def check(cfg: dict, force: bool = False) -> dict:
    """Is there anything newer? Never raises: a machine with no network must not
    have a broken Settings page.

    TWO sources, because they answer for different installs. The published
    `VERSION` file is the only thing a pip/wheel install can compare against; the
    checkout's own git is the only thing that knows about commits between
    releases. An update is available if EITHER says so — reporting only the file
    is how "up to date" survived twenty pushed commits.
    """
    c = conf(cfg)
    now = time.time()
    state = {"current": current(), "latest": "", "update_available": False,
             "notes": "", "checked_at": c.get("last_check") or 0.0, "error": "",
             # git's half, always present so no caller has to branch on its absence
             "on_branch": "", "tracks": c.get("branch") or DEFAULT_BRANCH,
             "behind": 0, "ahead": 0, "commits": [], "mismatch": False, "mark": ""}
    if not force and not c.get("enabled", True):
        state["error"] = "update checks are switched off"
        return state
    branch = c.get("branch") or DEFAULT_BRANCH
    # The checkout first, in a thread: `git fetch` is a blocking subprocess and
    # awaiting it on the loop stalls every request and every turn.
    g = await asyncio.to_thread(git_state, cfg, 20)
    state.update({k: g[k] for k in ("on_branch", "tracks", "behind", "ahead", "commits")})
    # On another branch, the version file at the tip of the tracked one is not a
    # statement about this code. Say which branch we are on rather than comparing
    # against something the checkout is not following — that mismatch is itself
    # the answer to "why does it say up to date after I pushed".
    state["mismatch"] = bool(g["root"] and g["on_branch"] and g["on_branch"] != branch)
    git_error = g["error"]
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
            r = await client.get(f"{RAW}/{branch}/agentos/VERSION")
            r.raise_for_status()
            latest = r.text.strip().splitlines()[0].strip()
    except httpx.HTTPStatusError as e:
        latest = ""
        state["error"] = (f"the '{branch}' branch does not publish a version file "
                          f"(HTTP {e.response.status_code}) — nothing to compare against")
    except Exception as e:
        latest = ""
        state["error"] = f"could not reach the update server ({type(e).__name__})"
    if latest and not re.match(r"^\d+(\.\d+)*", latest or ""):
        latest = ""
        state["error"] = "the update server returned something that is not a version"
    c["last_check"] = now
    # Remembered so the instant path (`GET /api/update` with no check) can still
    # say "8 changes waiting, as of the last look" instead of "up to date" —
    # answering from a cache that only held a version number was the same lie in
    # a cheaper place.
    c["last_behind"] = state["behind"]
    c["last_on_branch"] = state["on_branch"]
    state["checked_at"] = now
    state["latest"] = latest
    # EITHER source may say yes. A version bump is the release; commits waiting on
    # the tracked branch are the code — and between releases only the second one
    # moves, which is most of the time.
    state["update_available"] = bool((latest and is_newer(latest, current()))
                                     or state["behind"])
    # Two half-failures, reported rather than blended: the version file could not
    # be read, or the checkout could not be fetched. Either alone still leaves a
    # usable answer, so the check does not bail on the first one.
    if git_error and not state["error"]:
        state["error"] = git_error
    elif git_error:
        state["error"] += f"; {git_error}"
    # Release notes only when there IS a release. The published changelog's top
    # entry describes the version at the branch tip — which, when the version has
    # not moved, is the one already installed: notes for what you are running,
    # printed as if they were arriving.
    if latest and is_newer(latest, current()):
        state["notes"] = await _notes(branch)
    # What "we already told them about this" means. The version alone was the key,
    # so once a version had been announced no amount of new commits under it could
    # ever be announced again — which is the same bug as "up to date", wearing the
    # watcher's clothes.
    state["mark"] = f"{latest or current()}@{(state['commits'] or [{}])[0].get('hash', '')}"
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
    fmt = f"--pretty=format:%h{sep}%s{sep}%an{sep}%ct{rec}"
    n = f"-{max(1, int(limit))}"
    ok, out = _run(["git", "log", "--no-merges", n, fmt, f"{a}..{b}"], cwd=root)
    if not ok:
        return []
    # Nothing but merges separates the two? Then show the merges. Dropping them
    # unconditionally is right when they sit alongside the commits they brought —
    # "Merge pull request #14" tells you nothing the real commits do not — but a
    # checkout that is two merge commits behind was then told "2 changes waiting"
    # above an empty list, which reads as the update system being broken. Between
    # a useless subject and no answer at all, the subject wins.
    if not out.strip():
        ok, out = _run(["git", "log", n, fmt, f"{a}..{b}"], cwd=root)
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
        # Code that cannot pass its own tests must not become the code answering
        # turns — but "its own tests" has to mean the tests the UPDATE affected,
        # not every test in a developer suite that also runs on this machine.
        # A test can fail here for reasons the update never touched: pytest's
        # temp dir resolves under a system directory on a Mac, a cloud-provider
        # test needs an API this box cannot reach, a browser test needs a
        # browser. Rolling the update back for those strands the machine on old
        # code forever, for something the update did not cause. `bento update`
        # rolling back on a Mac with "fails its own tests" pointing at a folder
        # nobody would share is exactly how this was reported.
        #
        # So the gate is REGRESSION-only: run the suite, and if anything fails,
        # ask whether it also failed BEFORE the update. A test that was already
        # red on this machine is not the update's fault; only a test the update
        # turned from green to red is.
        say("verifying…")
        ok, out = _run([_python(root), "-m", "pytest", "tests/", "-q", "--tb=line",
                        "-p", "no:cacheprovider"], cwd=root, timeout=APPLY_TIMEOUT,
                       env=_fresh_pyc_env())
        if not ok:
            failed = _failed_nodes(out)
            if not failed:
                # non-zero with nothing parseable is a crash or a collection error
                # in the new code itself — that IS the update's fault.
                return rollback(f"the new version could not run its tests: {out[-300:]}")
            say(f"{len(failed)} test(s) failed — checking whether the update caused them…")
            regressions = _regressions_only(root, before, branch, failed, say)
            if regressions is None:
                return rollback("could not verify the update against the previous "
                                "version (git state) — nothing changed")
            if regressions:
                return rollback("the update turns passing tests red: "
                                + ", ".join(sorted(regressions)[:8])
                                + (f" (+{len(regressions) - 8} more)" if len(regressions) > 8 else ""))
            say(f"all {len(failed)} failing test(s) failed on the previous version "
                f"too — the update did not cause them, so it stands")

    after = _run(["git", "rev-parse", "HEAD"], cwd=root)[1].strip()
    # What was actually pulled, from git rather than from a file somebody has to
    # remember to write. Computed AFTER the merge, so it describes what landed
    # rather than what was expected to.
    return {"ok": True, "from": before[:8], "to": after[:8],
            "changes": commits(before, after, limit=20, root=root),
            "version": _version_on_disk(root) or current(),
            "unchanged": after == before,
            "files": len(changed)}


def _failed_nodes(pytest_out: str) -> set[str]:
    """The test node ids pytest reported as FAILED or ERROR, from `-q` output.

    Parsed from the short summary lines (`FAILED tests/x.py::name - reason`)
    rather than an exit code, because the gate needs to know WHICH tests failed,
    not merely that some did.
    """
    nodes: set[str] = set()
    for line in (pytest_out or "").splitlines():
        m = re.match(r"^(?:FAILED|ERROR)\s+(\S+)", line.strip())
        if m and "::" in m.group(1):
            nodes.add(m.group(1))
    return nodes


def _blob_exists(root: Path, rev: str, path: str) -> bool:
    """Did this file exist at that revision? A test whose FILE is new cannot have
    passed before the update, so it is not a regression — it is new behaviour the
    dev CI already vetted, and blocking on it here would strand the machine."""
    return _run(["git", "cat-file", "-e", f"{rev}:{path}"], cwd=root)[0]


def _regressions_only(root: Path, before: str, branch: str,
                      failed: set[str], say) -> set[str] | None:
    """Of the tests that failed on the NEW code, which passed on the OLD code.

    Those — and only those — are the update's fault. Leaves the checkout back on
    the new code when it returns (so `apply` can continue), or on the old code
    only if it could not re-apply, in which case it returns None to signal that
    the caller must roll back and refuse. Returns a (possibly empty) set of
    regressed node ids otherwise.
    """
    # A test whose file is new to this update never passed before it: not a
    # regression. Only the ones in files that already existed can be compared.
    comparable = {n for n in failed if _blob_exists(root, before, n.split("::")[0])}
    new_only = failed - comparable

    if comparable:
        say("running the previous version to compare…")
        if not _run(["git", "reset", "--hard", before], cwd=root, timeout=120)[0]:
            return None
        # Run EXACTLY the failed nodes on the old code. Anything that also fails
        # here was already broken on this machine.
        _ok, old_out = _run([_python(root), "-m", "pytest", *sorted(comparable),
                             "-q", "--tb=no", "-p", "no:cacheprovider"],
                            cwd=root, timeout=APPLY_TIMEOUT, env=_fresh_pyc_env())
        old_failed = _failed_nodes(old_out)
        # back to the new code so the update can proceed
        if not _run(["git", "merge", "--ff-only", f"origin/{branch}"], cwd=root, timeout=120)[0]:
            return None
        regressions = comparable - old_failed
    else:
        regressions = set()

    if new_only:
        # Said, never silent: a new test failing on this machine is tolerated, but
        # the operator should be able to see it happened.
        say(f"note: {len(new_only)} newly added test(s) fail here and are new to this "
            f"update, so they are not treated as regressions")
    return regressions


def _python(root: Path) -> str:
    """The interpreter to run the checkout's tests with.

    Windows puts the venv's Python in `Scripts\\python.exe`, POSIX in
    `bin/python` — looking only under `bin/` meant every Windows update fell
    through to `python3`, which is not even a command on a default Windows box,
    so the verify gate could never launch pytest and the update rolled back with
    "could not run its tests". The fallback is `sys.executable` — the interpreter
    running THIS process, which by definition exists and carries AgentOS's own
    dependencies (pytest among them) — rather than a `python3` that may not.
    """
    import sys

    cand = (root / ".venv" / "Scripts" / "python.exe") if os.name == "nt" \
        else (root / ".venv" / "bin" / "python")
    if cand.exists():
        return str(cand)
    return sys.executable or "python3"


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
                # Keyed on the MARK (version + newest waiting commit), not on the
                # version: between releases the version does not move, so a
                # version key announced once and then never again.
                mark = res.get("mark") or res["latest"]
                if res["update_available"] and mark not in (c.get("skipped"),
                                                            c.get("last_mark")):
                    c["last_mark"] = mark
                    c["last_seen"] = res["latest"] or res["current"]
                    n = res.get("behind") or 0
                    store.log("system", f"update available: {res['latest'] or res['current']}"
                                        + (f", {n} commit(s) waiting" if n else "")
                                        + f" (running {res['current']})")
                    await broadcast({"type": "update", **res})
                save_config(cfg)
        except Exception as e:                 # never let the loop die
            with_store = getattr(store, "log", None)
            if with_store:
                store.log("error", f"update check: {type(e).__name__}: {e}")
        await asyncio.sleep(3600)

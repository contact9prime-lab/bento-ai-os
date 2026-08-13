"""The AgentOS installer — a terminal UI that sets this machine up.

    agentos installer

WHY IT IS A PLAIN TERMINAL UI AND NOT THE TEXTUAL TUI
=====================================================
`tui_app.py` is a Textual application that talks to a *running* AgentOS server
over HTTP. That is the right shape for managing a working install and the wrong
shape for creating one: an installer runs on a machine where the session
packages are missing, the server may never have started, and Textual itself may
not be importable yet. So this is ANSI escape codes and `input()` — the same
dependency-free approach as `clitui.py` — and it works over SSH on a headless
box that has nothing on it but Python.

It is also re-runnable, which matters more than it sounds. The thing people
actually need is not a one-shot install; it is "something is missing and I want
to be told what". Running it on a finished machine shows a list of ticks, and
running it on a broken one shows exactly which component is absent and the
command that fixes it.

WHAT IT WILL NOT DO
===================
It never installs anything without a keystroke agreeing to that specific set,
with the licences on screen — the licensing rule in CLAUDE.md is not advisory.
It uses the same privilege ladder as every other system change (passwordless
sudo, then polkit, then hand back the command) by delegating to
`components.install`, so there is exactly one implementation of "become root"
and no second one to drift.

THE THREE FACES
===============
GUI  — the same catalogue is already Settings -> Components, and it now shows
       per-distro package names and an honest reason when a thing cannot be
       installed here (see components.catalog).
TUI  — this file. The only face that works before anything is set up.
SUI  — not applicable as a separate surface: when AgentOS IS the desktop it is
       already installed. Running `agentos installer` from a terminal inside the
       session is a supported way to add components afterwards, and it behaves
       identically.
"""

from __future__ import annotations

import asyncio
import shutil
import sys

from . import components, osdetect

C = {
    "acc": "\033[38;5;80m", "acc2": "\033[38;5;44m", "dim": "\033[90m",
    "b": "\033[1m", "r": "\033[0m", "warn": "\033[33m", "err": "\033[31m",
    "ok": "\033[32m",
}

GROUP_TITLE = {
    "required": "Required — without these there is no session",
    "recommended": "Recommended — a desktop that behaves like one",
    "optional": "Optional",
}


def _plain() -> bool:
    """No colour when this is not a terminal (CI, a pipe, a log)."""
    return not sys.stdout.isatty()


def _c(key: str) -> str:
    return "" if _plain() else C.get(key, "")


def _w() -> int:
    try:
        import os
        return max(60, min(os.get_terminal_size().columns, 100))
    except OSError:
        return 80


def _rule(ch: str = "─") -> None:
    print(f"{_c('dim')}{ch * _w()}{_c('r')}")


def _wrap(text: str, indent: int = 6) -> str:
    import textwrap
    return textwrap.fill(text, width=_w() - indent,
                         initial_indent=" " * indent, subsequent_indent=" " * indent)


def _ask(prompt: str, default: str = "") -> str | None:
    """One line of input, or None when there is nobody to ask.

    The None matters and is not tidiness. `_ask` used to return the default on
    EOF, and the default for "install which?" is "all" whenever something
    required is missing — so piping this installer into a script with no stdin
    would have installed packages that nobody agreed to, which is the one thing
    it must never do. No terminal is not a silent yes; it is no answer, and
    every caller here treats it as "change nothing".

    An empty line is different: that IS a person, pressing Enter, accepting the
    default they can see on screen.
    """
    try:
        got = input(f"{_c('acc')}?  {prompt}{_c('r')} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return got or default


def _yes(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    ans = _ask(f"{prompt} [{hint}]", "")
    if ans is None:
        return False                      # nobody to ask → do not act
    if not ans:
        return default
    return ans[0].lower() == "y"


# ---------------------------------------------------------------------------
# the screens
# ---------------------------------------------------------------------------

def _header() -> dict:
    d = osdetect.detect(refresh=True)
    print()
    print(f"{_c('acc')}{_c('b')}▲ AgentOS installer{_c('r')}")
    _rule()
    print(f"   {_c('dim')}Detected{_c('r')}  {osdetect.describe()}")
    if d["os"] == "linux" and not d["manager"]:
        print(f"   {_c('warn')}!{_c('r')}  {_wrap(d['why'], 7).lstrip()}")
    elif d["os"] != "linux":
        print(f"   {_c('warn')}!{_c('r')}  {_wrap(d['why'], 7).lstrip()}")
    print()
    return d


def _show(rows: list[dict], groups: tuple) -> list[dict]:
    """Print the component list; return the selectable (missing) rows in order."""
    selectable: list[dict] = []
    for group in groups:
        in_group = [r for r in rows if r["group"] == group]
        if not in_group:
            continue
        # What you can act on goes first. Sorting purely by title scattered the
        # numbered lines between the ticks, so choosing "3 5" meant hunting.
        in_group.sort(key=lambda r: (r["installed"], not r["available"], r["title"]))
        missing = [r for r in in_group if not r["installed"]]
        head = GROUP_TITLE.get(group, group)
        count = (f"{_c('ok')}all present{_c('r')}" if not missing
                 else f"{_c('warn')}{len(missing)} missing{_c('r')}")
        print(f" {_c('b')}{head}{_c('r')}  {count}")
        for r in in_group:
            if r["installed"]:
                print(f"   {_c('ok')}✓{_c('r')} {_c('dim')}{r['title']}{_c('r')}")
                continue
            if not r["available"]:
                print(f"   {_c('dim')}·{_c('r')} {r['title']}  "
                      f"{_c('dim')}— {r['reason']}{_c('r')}")
                continue
            selectable.append(r)
            n = len(selectable)
            print(f"   {_c('acc')}{n:>2}.{_c('r')} {r['title']}  "
                  f"{_c('dim')}· {r['licence']}{_c('r')}")
            print(_wrap(r["unlocks"], 8))
            print(f"        {_c('dim')}{r['command']}{_c('r')}")
        print()
    return selectable


def _pick(selectable: list[dict], default_all: bool) -> list[dict]:
    """Which of the offered components to install. Empty list means none."""
    if not selectable:
        return []
    hint = ("Enter installs everything above" if default_all
            else "Enter skips; list numbers to choose")
    print(f" {_c('dim')}{hint}. Examples: 'all', '1 3', 'none'.{_c('r')}")
    raw = _ask("Install which?", "all" if default_all else "none")
    if raw is None:
        print(f" {_c('dim')}No terminal to ask on — nothing was installed. "
              f"Run `agentos installer` from a terminal, or `--yes` to accept "
              f"everything listed above.{_c('r')}")
        return []
    raw = raw.lower()
    if raw in ("none", "no", "n", "skip", ""):
        return []
    if raw in ("all", "a", "y", "yes"):
        return list(selectable)
    chosen = []
    for tok in raw.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= len(selectable):
            chosen.append(selectable[int(tok) - 1])
        else:
            print(f"   {_c('warn')}ignoring '{tok}' — not one of 1..{len(selectable)}{_c('r')}")
    # de-duplicate, keep the order shown
    seen, out = set(), []
    for r in chosen:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


async def _install_all(chosen: list[dict]) -> tuple[int, list[str]]:
    """Install each choice, reporting per component. Returns (ok_count, manual)."""
    if not chosen:
        return 0, []
    print()
    _rule()
    print(f" {_c('b')}Installing {len(chosen)} component(s){_c('r')}")
    print(f" {_c('dim')}Each one is the distribution's own package, installed with "
          f"{osdetect.manager() or 'your package manager'}.{_c('r')}")
    print()

    # Refresh the index once, not per component. On Debian a stale index is the
    # commonest cause of "package not found" on a machine that has been off.
    ok, why = await components.refresh_index()
    if not ok and why:
        print(f"   {_c('dim')}(index refresh skipped: {why}){_c('r')}")

    done, manual = 0, []
    for r in chosen:
        print(f"   {_c('acc')}→{_c('r')} {r['title']} … ", end="", flush=True)
        res = await components.install(r["id"])
        if res.get("ok"):
            done += 1
            print(f"{_c('ok')}done{_c('r')}")
        else:
            print(f"{_c('warn')}needs you{_c('r')}")
            msg = (res.get("message") or "").strip()
            if msg:
                print(_wrap(msg, 6))
            if res.get("command"):
                print(f"      {_c('b')}{res['command']}{_c('r')}")
                manual.append(res["command"])
    return done, manual


def _offer_session(d: dict) -> None:
    """The last step: put AgentOS on the login screen.

    Deliberately separate from the packages. Installing a compositor changes
    nothing about how you log in; adding a session entry does, and it deserves
    its own yes.
    """
    from . import session

    print()
    _rule()
    if not d["session_capable"]:
        print(f" {_c('dim')}The login session is Linux-only, so there is nothing to add "
              f"here. AgentOS itself runs on this machine as an app window "
              f"— `agentos serve`.{_c('r')}")
        return

    if not shutil.which("sway"):
        print(f" {_c('warn')}!{_c('r')} The compositor is still missing, so a session entry "
              f"would fail at login.")
        print(f"   {_c('dim')}Install the required components above first, then run "
              f"`agentos installer` again.{_c('r')}")
        return

    installed = False
    try:
        installed = session.WL_STAGE.exists() or session.SWAY_CONF.is_file()
    except Exception:
        pass

    if installed:
        print(f" {_c('ok')}✓{_c('r')} AgentOS is already a login session on this machine.")
        stale = False
        try:
            stale = session.config_is_stale()
        except Exception:
            pass
        if stale:
            print(f"   {_c('warn')}Its generated config is older than this build{_c('r')} — "
                  f"window rules and fixes shipped since are not on disk.")
            if _yes("   Refresh it now?", True):
                changed, msg = session.refresh_config(reload_now=False)
                print(f"   {_c('ok' if changed else 'dim')}{msg}{_c('r')}")
        return

    print(f" {_c('b')}Make AgentOS a login session?{_c('r')}")
    print(_wrap("Adds AgentOS to the list at your login screen, alongside whatever "
                "you use now. Nothing is replaced and nothing is removed — you pick "
                "it, or don't, at every login.", 3))
    if not _yes("   Add it?", False):
        print(f"   {_c('dim')}Later: agentos install-session{_c('r')}")
        return
    try:
        session.install(wayland=True)
    except Exception as e:                                  # pragma: no cover
        print(f"   {_c('err')}could not add the session: {e}{_c('r')}")
        print(f"   {_c('dim')}Try `agentos install-session` for the full output.{_c('r')}")


def _summary(d: dict, manual: list[str]) -> None:
    print()
    _rule()
    # Both branches below are about the LOGIN SESSION, so neither is true on an OS
    # that has none. "Still missing for the session: sway" is a to-do list nobody
    # can act on, and "everything required for the session is present" is worse —
    # it claims a thing that does not exist here is ready.
    #
    # And it says NOTHING here rather than repeating it: `_offer_session` has just
    # printed the same sentence two lines up, with the useful half attached ("AgentOS
    # runs here as an app window — `agentos serve`"). Saying it twice more is how a
    # true sentence turns into noise people learn to skip.
    if not d.get("session_capable"):
        pass
    else:
        rows = components.catalog(session_only=True)
        still = [r for r in rows if r["group"] == "required" and not r["installed"]]
        if still:
            print(f" {_c('warn')}Still missing for the session:{_c('r')} "
                  f"{', '.join(r['title'] for r in still)}")
        else:
            print(f" {_c('ok')}Everything required for the AgentOS session is present.{_c('r')}")
    if manual:
        print()
        print(f" {_c('b')}Run these as root to finish:{_c('r')}")
        for cmd in manual:
            print(f"   {cmd}")
    print()
    print(f" {_c('dim')}`agentos doctor` checks the whole environment. "
          f"Re-run `agentos installer` any time.{_c('r')}")
    print()


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def run(session_only: bool = False, assume_yes: bool = False,
        groups: tuple = ()) -> int:
    """The installer. Returns a process exit code.

    `session_only` narrows the list to what the login session needs.
    `assume_yes` installs everything offered without asking — for unattended
    use only, and it still prints every package and licence first, because
    "unattended" must not mean "invisible".
    """
    d = _header()
    rows = components.catalog(session_only=session_only)

    # A component for a session this OS cannot host is not "missing" — it is not a
    # thing here at all. Listed anyway, macOS showed eleven of them, each repeating
    # the same sentence, two of them under "Required — without these there is no
    # session". That reads as a broken install on a machine that is working
    # perfectly, and it buries Ollama and the WhatsApp bridge, which ARE installable.
    #
    # The header has already said why, once, in `d["why"]` — which is the honest
    # shape: name the gap in a sentence, not eleven times in a list of things
    # nobody can act on. `--session` is left alone: somebody who asked for the
    # session list deserves to see it, empty or not.
    if not session_only and not d.get("session_capable"):
        rows = [r for r in rows if not r.get("for_session")]

    # The same argument, one step further. What is left can still include entries
    # with no route on this OS at all — ffmpeg and the rest are Linux package names
    # with no macOS spelling in the catalogue — and each printed the session's
    # "Wayland is Linux-only" sentence, which is not even the reason it is missing.
    # A list of things nobody can act on, explained wrongly, is worse than a count.
    absent = []
    if not session_only:
        actionable = [r for r in rows if r["available"] or r["installed"]]
        absent = [r for r in rows if r not in actionable]
        rows = actionable

    if not groups:
        groups = components.GROUPS

    what = "the AgentOS session" if session_only else "this machine"
    print(f"{_c('dim')}"
          + _wrap(f"Components for {what}. Nothing below is bundled with AgentOS — "
                  f"each is your distribution's own package, with its licence shown, "
                  f"and installs only if you say so.", 1)
          + f"{_c('r')}")
    print()

    selectable = _show(rows, groups)

    # Counted, never silently dropped: the difference between "this OS does not
    # have these" and "AgentOS forgot about them" is one line, and it is the line
    # that stops somebody hunting for a component that was never coming.
    if absent:
        # Grouped BY REASON, not summarised in words of my own. On macOS that is one
        # sentence covering all of them; on a distro missing a single package name it
        # is that component's own explanation, which is the useful one. Writing a
        # blanket "packages for other systems" here would have been false in the
        # second case — the component is not for another system, it just has no name
        # for this family yet.
        by_reason: dict = {}
        for r in absent:
            by_reason.setdefault(r["reason"] or "no install route on this system", []) \
                     .append(r["title"])
        for reason, titles in by_reason.items():
            print(f" {_c('dim')}"
                  + _wrap(f"Not available here — {', '.join(sorted(titles))}: {reason}", 1)
                  + f"{_c('r')}")
        print()

    if not selectable:
        print(f" {_c('ok')}Nothing left to install.{_c('r')}")
        _offer_session(d)
        _summary(d, [])
        return 0

    if assume_yes:
        chosen = list(selectable)
        print(f" {_c('dim')}--yes: installing all {len(chosen)} offered component(s).{_c('r')}")
    else:
        # Default to "all" only when something required is missing: that is the
        # case where the machine does not work yet, so the safe default is the
        # one that fixes it. Otherwise default to installing nothing.
        needed = any(r["group"] == "required" for r in selectable)
        chosen = _pick(selectable, default_all=needed)

    done, manual = asyncio.run(_install_all(chosen))
    if done:
        # A new binary changes what the catalogue reports.
        osdetect.detect(refresh=True)
    _offer_session(d)
    _summary(d, manual)
    return 0

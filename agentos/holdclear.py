"""Clearing a security hold without a terminal: a clear picture, then an admin's yes.

The owner's call (2026-11): "the users should be allowed to reset and get a clear picture or
accept it at admin's telegram or whatsapp ... it is then difficult to login to the machine to do
this". `bento integrity accept` at a terminal stays, and is still the only door on a machine whose
record is signed with a key (a phone can't hold the key). Everywhere else an admin may accept from
their paired phone or from Settings → Permissions → Security. Five rules keep it a person's act:

- **While held, every agent is stopped.** The gate refuses every step, so no agent can press this.
  What is left is somebody holding the admin's phone, or the admin's session.
- **The picture decides how much proof is asked for** (`picture`). "Back to normal" (the files match
  the record again) and "matches GitHub" (a clean checkout of a commit on the branch it tracks) are
  a tap. "Unknown" (content git can't vouch for, a locked home file, a record that doesn't check)
  needs the 6-digit code from an authenticator app (`code_ok`). Never a password in a chat: chat
  history keeps it.
- **The phone's words are caught before any agent** (`from_phone`), like a sign-in code, and only
  from the paired chat of an admin. A code is never logged or saved in the conversation.
- **Wrong answers are counted** (`TRIES` per `TRY_WINDOW_S`), and a code can be used once.
- **Every accept is said everywhere**: a `integrity.accepted` security alert (every admin's screens
  and phones) and an `integrity.accept` ledger row written by the caller.

Stdlib only and free of HTTP and asyncio, like integrity.py: the TOTP is RFC 6238 by hand."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import struct
import threading
import time
import urllib.parse
from pathlib import Path

from . import constcmp, integrity, secevents

CODE_NAME = "integrity.totp"        # the authenticator's secret, in the machine's vault
STEP_S = 30
DIGITS = 6
TRIES = 5                           # wrong codes or passwords before a pause
TRY_WINDOW_S = 900
ASK_S = 300                         # how long a phone's Accept waits for its code
DIFF_CHARS = 3500                   # a phone message is small; the screen gets the same text

SETTLED, KNOWN, UNKNOWN = "settled", "known", "unknown"

_lock = threading.Lock()
_misses: list[float] = []
_used: set[int] = set()             # TOTP counters already spent
_asking: dict[str, float] = {}      # "tg:<chat>" -> when its Accept started waiting for a code


def forget_for_tests() -> None:
    with _lock:
        _misses.clear()
        _used.clear()
        _asking.clear()


# ------------------------------------------------------------------------------ the picture

def _changed_code(root: Path) -> tuple[list[str], dict]:
    verdict = integrity.judge(integrity.record_for(root), integrity.hash_tree(root))
    return verdict["changed"], verdict


def picture(root: Path | None = None) -> dict:
    """What the hold is about, in one of three words, with the files and a sentence.

    settled: the code and the locked files are what was recorded again (a change that was undone),
             or the only change is a vault key file Bento retired itself (integrity.retired_key).
    known:   the code is a clean checkout of a commit on a branch the remote has.
    unknown: anything git can't vouch for, a locked home file, or a record that doesn't check."""
    root = Path(root or integrity.code_root()).resolve()
    hold = integrity.held()
    out = {"held": bool(hold), "files": list((hold or {}).get("files") or []),
           "reason": (hold or {}).get("reason", ""), "at": (hold or {}).get("at", 0), "root": str(root),
           "kind": "", "words": "", "commit": "", "now_changed": [], "home": []}
    if not hold:
        out["words"] = "Nothing is held."
        return out
    changed, verdict = _changed_code(root)
    # A locked home file is noted as seen once it trips (one alert per change), so check_home() no
    # longer reports it: the hold's own list is what says one changed. The record, the same.
    held_home = [f for f in out["files"] if f.startswith("~") or f == "integrity.json"]
    home = list(dict.fromkeys(held_home + integrity.check_home()))
    out["now_changed"], out["home"] = changed[:50], home[:20]
    if verdict["state"] in ("forged", "unsigned"):
        out["kind"] = UNKNOWN
        out["words"] = f"The integrity record itself can't be believed: {verdict.get('why') or verdict['state']}."
        return out
    # Vault key files Bento removed itself when the vault moved to another key. 0.99.0's two
    # migrations did that without telling the watcher, and every machine that updated held with
    # "Unknown change". A key nothing uses any more is not an identity replaced.
    retired = [f for f in home if integrity.retired_key(f)]
    home = [f for f in home if f not in retired]
    out["retired"] = retired
    if retired and not home and not changed:
        out["kind"] = SETTLED
        out["words"] = ("Bento's own upgrade removed " + ", ".join(retired[:3]) + ": the vault moved to "
                        "another key and no longer uses that file. Nothing else changed.")
        return out
    if home:
        out["kind"] = UNKNOWN
        out["words"] = ("A locked file in Bento's home changed outside Bento: " + ", ".join(home[:3])
                        + ". Bento can't tell who did it.")
        return out
    if not changed:
        out["kind"] = SETTLED
        out["words"] = ("The files are back to what was recorded. Whatever changed them was undone, "
                        "so only the stop is left.")
        return out
    dirty = integrity.dirty_in_scope(root)
    ok, head = integrity._git(root, "log", "-1", "--format=%h %s")
    ok2, remotes = integrity._git(root, "branch", "-r", "--contains", "HEAD")
    if ok and ok2 and not dirty and remotes.strip():
        out["kind"] = KNOWN
        out["commit"] = head.strip()[:200]
        out["words"] = (f"{len(changed)} file(s) now match commit {out['commit']}, which is on "
                        f"{remotes.split()[0]}. It wasn't installed through bento update.")
        return out
    out["kind"] = UNKNOWN
    new = set(_untracked(root, [c for c in changed if not c.startswith("~")]))
    def named(xs):
        return ", ".join(xs[:3]) + (f" and {len(xs) - 3} more" if len(xs) > 3 else "")
    parts = []
    if [c for c in changed if c not in new]:
        parts.append(named([c for c in changed if c not in new]) + " changed")
    if new:
        parts.append(named(sorted(new)) + (" is new" if len(new) == 1 else " are new"))
    out["words"] = (" and ".join(parts) + ". Git can't vouch for it"
                    + (": it isn't in any commit." if dirty else "."))
    return out


def _lines(text: str, limit: int) -> str:
    """secevents.plain line by line: a diff keeps its lines, and loses every control and bidi mark."""
    return "\n".join(secevents.plain(ln, 400) for ln in str(text)[:limit].splitlines())


def _untracked(root: Path, rels: list[str]) -> list[str]:
    ok, out = integrity._git(root, "ls-files", "--others", "--exclude-standard", "--", *rels) if rels else (False, "")
    return [ln.strip() for ln in out.splitlines() if ln.strip()] if ok else []


def changes(pic: dict | None = None, root: Path | None = None, head: bool = True) -> str:
    """The detail behind the picture, as plain text: a diff for code, names only for home files.
    `head` puts the picture's sentence first (a phone); the card shows it above already."""
    pic = pic or picture(root)
    root = Path(pic.get("root") or root or integrity.code_root())
    if not pic.get("held"):
        return "Nothing is held."
    lines = [pic["words"], ""] if head else []
    if pic["home"]:
        lines.append("Locked files (their content is never shown):")
        lines += [f"  {f}" for f in pic["home"]]
    if pic["kind"] == SETTLED:
        lines.append("Files that changed earlier: " + ", ".join(pic["files"][:12]))
    elif pic["now_changed"]:
        rels = [r for r in pic["now_changed"] if not r.startswith("~")][:20]
        ok, stat = integrity._git(root, "diff", "HEAD", "--stat", "--", *rels) if rels else (False, "")
        ok2, body = integrity._git(root, "diff", "HEAD", "--no-color", "--", *rels) if rels else (False, "")
        if pic["kind"] == KNOWN:
            lines.append(f"Commit: {pic['commit']}")
            lines.append("Files: " + ", ".join(rels))
        else:
            if ok and stat.strip():
                lines.append(stat.rstrip())
                if ok2:
                    lines += ["", _lines(body, DIFF_CHARS) + ("\n…" if len(body) > DIFF_CHARS else "")]
            # A file git has never seen is not in any diff, and a planted module is the case that
            # matters most: show what it says.
            for rel in _untracked(root, rels)[:5]:
                try:
                    text = (root / rel).read_text(errors="replace")
                except OSError:
                    lines += ["", f"New file {rel} (it can't be read)"]
                    continue
                lines += ["", f"New file {rel}:", _lines(text, DIFF_CHARS // 2)
                          + ("\n…" if len(text) > DIFF_CHARS // 2 else "")]
            if not (ok and stat.strip()) and not _untracked(root, rels):
                lines.append("Files: " + ", ".join(rels))
    return "\n".join(lines).strip()


# ------------------------------------------------------------------------------ the code

def _vault():
    from . import users as usersmod
    from . import vault
    return usersmod, vault


def code_set() -> bool:
    usersmod, vault = _vault()
    with usersmod.as_user(""):
        return vault.has(CODE_NAME)


def new_code(label: str = "Bento") -> dict:
    """Make the authenticator's secret and keep it in the machine's vault. Shown once."""
    usersmod, vault = _vault()
    secret = base64.b32encode(os.urandom(20)).decode().rstrip("=")
    with usersmod.as_user(""):
        vault.put(CODE_NAME, secret)
    with _lock:
        _used.clear()
    name = urllib.parse.quote(f"Bento security ({label})")
    uri = f"otpauth://totp/{name}?secret={secret}&issuer=Bento&digits={DIGITS}&period={STEP_S}"
    from . import qr
    return {"secret": secret, "uri": uri, "qr": qr.path(uri)}


def _hotp(secret: str, counter: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    n = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(n).zfill(DIGITS)


def _secret() -> str:
    usersmod, vault = _vault()
    with usersmod.as_user(""):
        return vault.get(CODE_NAME, actor="integrity accept")


def paused() -> bool:
    now = time.time()
    with _lock:
        _misses[:] = [t for t in _misses if now - t < TRY_WINDOW_S]
        return len(_misses) >= TRIES


def missed() -> None:
    with _lock:
        _misses.append(time.time())
    secevents.flag("integrity.accept_refused", "a wrong code or password")


def code_ok(code: str, now: float | None = None, spend: bool = True) -> bool:
    """The authenticator's code for now (one step either side), never twice. `spend=False` is
    the setup's "check it works": the same code must still accept a change a minute later."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    secret = _secret()
    if not secret or len(code) != DIGITS:
        return False
    t = int((now or time.time()) // STEP_S)
    for c in (t - 1, t, t + 1):
        if constcmp.same(_hotp(secret, c), code):
            with _lock:
                if c in _used:
                    return False
                if spend:
                    _used.add(c)
            return True
    return False


# ------------------------------------------------------------------------------ accepting

def why_not(pic: dict, code: str = "") -> str:
    """Why this accept can't go ahead, or ''. Checks everything except who is asking."""
    if not pic.get("held"):
        return "Nothing is held."
    if integrity.needs_key():
        return ("This machine signs its record with a key, so the change has to be accepted at its "
                "terminal with the key: bento integrity accept --key <path>.")
    if paused():
        return "Too many wrong answers. Wait 15 minutes and try again."
    if pic["kind"] == UNKNOWN:
        if not code_set():
            return ("Bento can't vouch for this change, so accepting it needs a code from an "
                    "authenticator app, and none is set up. Set one up in Settings → Permissions → "
                    "Security, or accept at the machine's terminal.")
        if not code:
            return "This change needs the 6-digit code from your authenticator app."
        if not code_ok(code):
            missed()
            return "That code isn't right."
    return ""


def accept(by: str, via: str, pic: dict | None = None, root: Path | None = None, say: bool = True) -> dict:
    """Take the code and the locked files as they are now, and let the agents run again.
    The caller has checked who is asking and `why_not`."""
    root = Path(root or integrity.code_root()).resolve()
    pic = pic or picture(root)
    entry = integrity.seal(root, by="accept", via=f"{via}:{by}"[:120])
    w = integrity.WATCHER
    if w is not None and w.root == root:
        with contextlib.suppress(Exception):
            w._try_release()
    if say:   # an undo says its own words: one act, one alert
        secevents.flag("integrity.accepted", f"{pic.get('kind') or 'held'} change accepted by {by} via {via}")
    return {"ok": True, "kind": pic.get("kind"), "files": pic.get("files") or [],
            "released": integrity.held() is None, "at": entry.get("at")}


# ------------------------------------------------------------------------------ undoing

ASIDE = "integrity-undone"           # <home>/integrity-undone/<time>/<path>: what an undo set aside


def undo_plan(root: Path | None = None, pic: dict | None = None) -> dict:
    """What `undo` would do, and why it can't, worked out without touching anything.

    It puts the watched code back to the commit the checkout is on: a changed file is checked out
    again, a new file is moved aside. Nothing is deleted: both are copied to `ASIDE` first. It only
    goes in the safe direction (towards a commit), so it needs no authenticator code. A locked home
    file can't be undone by git, and a checkout whose commit moved (somebody committed) isn't put
    back to an older one: those stay for accept, in words."""
    root = Path(root or integrity.code_root()).resolve()
    pic = pic or picture(root)
    out = {"root": str(root), "restore": [], "set_aside": [], "left": [], "why": ""}
    if not pic.get("held"):
        out["why"] = "Nothing is held."
        return out
    if pic.get("home"):
        out["why"] = ("A locked file in Bento's home changed (" + ", ".join(pic["home"][:3])
                      + "). Undo only puts code back, so check it and accept it instead.")
        return out
    ok, _ = integrity._git(root, "rev-parse", "--verify", "HEAD")
    if not ok:
        out["why"] = "This copy of the code isn't a git checkout, so there's no commit to go back to."
        return out
    dirty = [d for d in integrity.dirty_in_scope(root) if d != "(git could not say)"]
    new = set(_untracked(root, dirty))
    out["restore"] = sorted(d for d in dirty if d not in new)
    out["set_aside"] = sorted(new)
    ok, other = integrity._git(root, "status", "--porcelain", "--no-renames")
    watched = set(dirty)
    out["left"] = sorted({ln[3:].strip().strip('"') for ln in other.splitlines() if len(ln) > 3} - watched) if ok else []
    if not dirty and pic.get("kind") != SETTLED:
        out["why"] = ("Every file matches its commit already, but not the record: the commit itself moved. "
                      "Check it with bento integrity changes, then accept it.")
    return out


def undo(by: str, via: str, root: Path | None = None) -> dict:
    """Put the watched code back to its commit (`undo_plan`), then let the agents run if that left
    the files as recorded. The caller has checked who is asking. Returns the plan with `done`,
    `aside` (the folder) and `released`."""
    root = Path(root or integrity.code_root()).resolve()
    plan = undo_plan(root)
    if plan["why"]:
        return {**plan, "done": False, "released": False}
    aside = integrity._home() / ASIDE / time.strftime("%Y%m%d-%H%M%S")
    import shutil
    aside.mkdir(parents=True, exist_ok=True)
    os.chmod(aside, 0o700)
    for rel in plan["restore"] + plan["set_aside"]:
        src = root / rel
        if src.is_file() and not src.is_symlink():
            dest = aside / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    if plan["restore"]:
        ok, err = integrity._git(root, "checkout", "HEAD", "--", *plan["restore"])
        if not ok:
            return {**plan, "done": False, "released": False, "aside": str(aside),
                    "why": "git couldn't put the files back: " + secevents.plain(err, 300)}
    for rel in plan["set_aside"]:
        with contextlib.suppress(OSError):
            (root / rel).unlink()
    pic = picture(root)
    released = False
    if pic.get("kind") == SETTLED and not integrity.needs_key():
        accept(by, via, pic, root, say=False)
        released = integrity.held() is None
    secevents.flag("integrity.undone", f"{len(plan['restore']) + len(plan['set_aside'])} file(s) put back by {by} via {via}")
    out = {**plan, "done": True, "released": released, "aside": str(aside), "kind": pic.get("kind")}
    if not released:
        out["why"] = ("The files are back, and this machine signs its record, so accept it with your key: "
                      "bento integrity accept --key <path>" if integrity.needs_key() else
                      "The files are back but something else still differs: " + pic.get("words", ""))
    return out


# ------------------------------------------------------------------------------ a phone

PHONE_HELP = "Reply show to see what changed, accept to let the agents run again, or keep to leave them stopped."


def phone_message(pic: dict | None = None) -> str:
    pic = pic or picture()
    return (f"⚠ Bento stopped its agents: a security file changed.\n{pic['words']}\n\n"
            + ("Accepting needs the code from your authenticator app.\n" if pic["kind"] == UNKNOWN else "")
            + PHONE_HELP)


def from_phone(chat: str, text: str, is_admin_owner: bool, who: str, via: str) -> str | None:
    """A message from a phone while the agents are held. Returns the reply, or None when this
    isn't for us (nothing held, or not the paired chat of an admin). Never logs `text`."""
    if not integrity.held() or not is_admin_owner:
        return None
    word = (text or "").strip().lower().lstrip("/")
    now = time.time()
    with _lock:
        waiting = now - _asking.get(chat, 0) < ASK_S
    digits = "".join(ch for ch in word if ch.isdigit())
    if word in ("show", "changes", "details", "ig:show"):
        return changes()[:3900]
    if word in ("keep", "keep stopped", "ig:keep"):
        with _lock:
            _asking.pop(chat, None)
        return "The agents stay stopped. Reply accept when you're ready."
    if word in ("accept", "ig:accept") or (waiting and len(digits) == DIGITS and digits == word.replace(" ", "")):
        pic = picture()
        code = digits if word not in ("accept", "ig:accept") else ""
        if pic["kind"] == UNKNOWN and not code and code_set() and not integrity.needs_key() and not paused():
            with _lock:
                _asking[chat] = now
            return "Send the 6-digit code from your authenticator app."
        why = why_not(pic, code)
        if why:
            return why
        with _lock:
            _asking.pop(chat, None)
        accept(who, via, pic)
        return "✓ Accepted. The agents can run again."
    return phone_message()

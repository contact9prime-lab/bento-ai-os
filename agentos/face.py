"""How this machine's own screen looks: one agent (buddy) and the kiosk face.

Asked for as "a single buddy / agent ui interface option for Light mode so that shows
just one agent in the office and desktop face for raspi interface, there will be a kiosk
mode as well where mic would be on and agents would be working in the office".

  * BUDDY: the Office and the desktop's Crew stage draw only your lead agent. Specialists
    still exist and still work; their work lights the lead's desk, because on a 7-inch
    screen a room of eight figures is a wall of names. `auto` follows Light mode
    (profile.resolve == "lite"), so a Pi gets it without being told.
  * KIOSK: the machine's own screen becomes the Office, full screen, with the mic
    listening for the agent's name (or for everything) and the answer spoken. It is a
    FACE, not a run mode: `runmode.KIOSK` is how the session is launched (an X11 app
    window), this is what that window shows. A phone looking at the same machine never
    gets the kiosk face; only the screen attached to it does, or a browser opened with
    `#kiosk`.

Both are the MACHINE's (a screen belongs to the box it is plugged into), so neither is a
USER_KEY. Kept free of HTTP and asyncio: `bento face` reads and writes the same settings
with the server down.
"""
from __future__ import annotations

import re
import time
import unicodedata

BUDDY = ("auto", "on", "off")
WAKE = ("name", "always")
WAKE_WORD_MAX = 32          # "Hey Bento" is a wake word; a sentence is not


def _face(cfg: dict) -> dict:
    f = (cfg or {}).get("face")
    return f if isinstance(f, dict) else {}


def buddy_setting(cfg: dict) -> str:
    v = str(_face(cfg).get("buddy") or "auto").lower()
    return v if v in BUDDY else "auto"


def buddy(cfg: dict) -> bool:
    """Is only the lead drawn? `auto` means: in Light mode."""
    v = buddy_setting(cfg)
    if v != "auto":
        return v == "on"
    from . import profile
    return profile.resolve(cfg) == "lite"


def kiosk(cfg: dict) -> bool:
    return bool(_face(cfg).get("kiosk"))


def wake(cfg: dict) -> str:
    v = str(_face(cfg).get("wake") or "name").lower()
    return v if v in WAKE else "name"


def wake_word(cfg: dict) -> str:
    """A wake word of the person's own ("Hey Bento"), or '' for the agent's name alone."""
    return str(_face(cfg).get("wake_word") or "").strip()


def wake_words(cfg: dict) -> list[str]:
    """Everything the kiosk answers to: the person's own wake word, then the agent's name.
    The name always works, so renaming the agent never leaves a screen nobody can wake."""
    out = []
    for w in (wake_word(cfg), str((cfg or {}).get("agent_name") or "Aria")):
        if w and w.lower() not in (x.lower() for x in out):
            out.append(w)
    return out


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def addressed(text: str, words: list[str]) -> tuple[str, str] | None:
    """(the wake word heard, the words after it), or None when none was said. Whole words,
    so "Ariadne" is not "Aria", and the first one said wins. The page's kioskAddressed
    is the same rule; tests/test_face.py holds the two to the same cases."""
    t = _norm(text)
    best = None
    for w in words:
        n = _norm(w).strip()
        if not n:
            continue
        m = re.search(r"(^|[^\w])" + re.escape(n) + r"(?=$|[^\w])", t)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), w, m.end())
    if not best:
        return None
    # the original text, cut where the normalised match ended (NFKD keeps positions for
    # the scripts a wake word is said in; a mismatch only trims a little more or less)
    after = str(text)[best[2]:] if len(_norm(text)) == len(str(text)) else t[best[2]:]
    return best[1], after.lstrip(" \t,.:;!?-").strip()


def heard(cfg: dict) -> dict:
    """When this machine last heard its wake word, understood: the voice step's evidence."""
    h = _face(cfg).get("heard")
    return h if isinstance(h, dict) and h.get("at") else {}


def mark_heard(cfg: dict, text: str, word: str, engine: str) -> dict:
    """Record a wake word that was really heard. Mutates `cfg`; the caller saves."""
    f = dict(_face(cfg))
    f["heard"] = {"at": time.time(), "text": str(text)[:200], "word": str(word)[:WAKE_WORD_MAX],
                  "engine": str(engine)[:20]}
    cfg["face"] = f
    return f["heard"]


def state(cfg: dict) -> dict:
    """What the page and the CLI read: one answer for both."""
    from . import hearing
    return {"buddy": buddy(cfg), "buddy_setting": buddy_setting(cfg),
            "kiosk": kiosk(cfg), "kiosk_chosen": "kiosk" in _face(cfg), "wake": wake(cfg),
            "wake_word": wake_word(cfg), "wake_words": wake_words(cfg), "heard": heard(cfg),
            "hear": hearing.status(cfg)}


def wake_word_problem(w: str) -> str:
    """'' when `w` can be a wake word. Letters, digits, spaces and an apostrophe, at most
    four words: a wake word somebody says in one breath."""
    w = str(w or "").strip()
    if not w:
        return ""
    if len(w) > WAKE_WORD_MAX or len(w.split()) > 4:
        return f"a wake word is a few words, at most {WAKE_WORD_MAX} letters"
    if not re.fullmatch(r"[\w' ]+", w) or w.replace("'", "").replace(" ", "").isdigit():
        return "a wake word is made of letters"
    return ""


def set_face(cfg: dict, buddy: str | None = None, kiosk: bool | None = None,
             wake: str | None = None, wake_word: str | None = None) -> tuple[bool, str]:
    """Change the face. Mutates `cfg`; the caller saves. Refuses an unknown value by
    naming the choices, so a typo is a sentence and not a silently ignored setting."""
    f = dict(_face(cfg))
    if buddy is not None:
        b = str(buddy).strip().lower()
        if b not in BUDDY:
            return False, f"one agent on screen is one of {', '.join(BUDDY)}"
        f["buddy"] = b
    if kiosk is not None:
        f["kiosk"] = bool(kiosk)
    if wake is not None:
        w = str(wake).strip().lower()
        if w not in WAKE:
            return False, f"the kiosk listens for one of {', '.join(WAKE)}"
        f["wake"] = w
    if wake_word is not None:
        problem = wake_word_problem(wake_word)
        if problem:
            return False, problem
        f["wake_word"] = " ".join(str(wake_word).split())
    cfg["face"] = f
    return True, describe(cfg)


def describe(cfg: dict) -> str:
    """One sentence per setting, for the CLI and the doctor."""
    s = buddy_setting(cfg)
    one = ("Only your agent is drawn in the Office and on the desktop"
           if buddy(cfg) else "Every agent is drawn in the Office and on the desktop")
    why = " (Light mode)" if s == "auto" and buddy(cfg) else ""
    names = " or ".join(f"“{w}”" for w in wake_words(cfg))
    kio = ("The kiosk face is on: this machine's screen shows the Office and listens "
           + ("for everything." if wake(cfg) == "always" else f"for {names}.")
           if kiosk(cfg) else "The kiosk face is off.")
    return f"{one}{why}. {kio}"


def record(store, detail: str) -> None:
    """A person's change to the screen is a ledger row, like every change to the machine."""
    try:
        from . import users as _users
        uid = _users.current() or ""
    except Exception:
        uid = ""
    try:
        store.audit_add(uid=uid, principal_kind="user", principal_id="", action="face.write",
                        resource="face:screen", effect="allow", rule="person", outcome="ok",
                        detail=str(detail)[:1000])
    except Exception:
        pass

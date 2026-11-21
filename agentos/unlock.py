"""Typing your Bento password from your phone, after a restart, through remote access only.

Asked for as "when Bento has restarted and I'm away, my phone chat should offer a link to type my
password, like the GitHub sign-in hand-off. The link opens the remote sign-in page on my phone; I
sign in there and type my password. That opens my 'only while I'm signed in' secrets for my
missions. The password must never be typed into the chat itself, because chat history keeps it.
It must only work through remote access, with no second door, and the chat must be the one
paired to my account."

How it works, and the rule each part keeps:

  * **Asked for by a step, sent to your own chat.** A step that needs a secret set to "only while
    I'm signed in", with nobody signed in, calls `closed(uid, name)` (vault.py does, as it
    refuses). That account's OWN paired Telegram or WhatsApp chat (the owner chat of its own
    bridges, never the machine's or another account's) gets one message with the link, at most
    once every `EVERY_S`.
  * **The link is an address, never a key.** It is `<remote address>/unlock`: the remote gate
    serves the sign-in page there to a phone with no session, and the page comes back to the
    link once signed in (login.html's LINK). Signing in IS typing the password: it opens the
    seal for that session (server `_seal_sign_in`). A phone still signed in from before a
    restart types it into the page (`/api/seal/open`). Nothing about it is in the chat.
  * **Only through remote access.** With remote access off, the chat is told what would turn it
    on, and no link is sent. There is no route, listener or ticket of its own.
  * **Then you choose for how long.** The page lists the secrets that are closed and opens them
    for the next run (`once`), for today, or until revoked, through the same `PUT /api/seal/away`
    as Settings. The step that asked waits up to `WAIT_S` for that and carries on.

Kept free of HTTP; the server wires the phones, the config, the port and the ledger.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
import time

PATH = "/unlock"
EVERY_S = 1800.0          # one message per account per half hour, however many steps ask
WAIT_S = 300.0            # how long a waiting step gives the person to open it from their phone
POLL_S = 2.0

_HOOKS: dict = {"phones": None, "cfg": None, "ledger": None, "loop": None, "port": None}
_SENT: dict[str, float] = {}
_LINKED: dict[str, float] = {}      # when a LINK (not only words) last went to that account
_LOCK = threading.Lock()


def bind(phones=None, cfg=None, ledger=None, loop=None, port=None) -> None:
    for k, v in (("phones", phones), ("cfg", cfg), ("ledger", ledger), ("loop", loop), ("port", port)):
        if v is not None:
            _HOOKS[k] = v


def _due(uid: str) -> bool:
    with _LOCK:
        if time.time() - _SENT.get(uid, 0) < EVERY_S:
            return False
        _SENT[uid] = time.time()
        return True


def words(label: str, link: str = "", road: str = "", why: str = "") -> str:
    """The one message, in the chat's words. Never asks for the password here."""
    head = (f"🔐 Bento restarted, and your {label} works only while you're signed in, so a "
            "mission of yours is waiting for it.")
    if not link:
        return f"{head}\n{why}"
    return (f"{head}\nSign in on this phone to open it: {link}\n{road}\n"
            "Type your password on that page, never in this chat. The mission waits a few minutes.")


def closed(uid: str, name: str) -> bool:
    """A step was refused a signed-in-only secret with nobody signed in. Tell this account's own
    chat, once per `EVERY_S`. Safe from a worker thread or the loop. True when a message went."""
    if not uid or _HOOKS["phones"] is None or _HOOKS["loop"] is None:
        return False
    loop = _HOOKS["loop"]
    if not loop.is_running():
        return False
    from . import remote, users as usersmod
    with contextlib.suppress(Exception):
        with usersmod.as_user(uid):
            if not _HOOKS["phones"](uid):
                return False          # no paired chat of their own: nobody to tell, nothing to wait for
    cfg = None
    with contextlib.suppress(Exception):
        cfg = _HOOKS["cfg"]()
    linked = bool(cfg) and remote.enabled(cfg)
    if not _due(uid):
        return False
    coro = _tell(uid, name)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        loop.create_task(coro)
    else:
        asyncio.run_coroutine_threadsafe(coro, loop)
    if not linked:
        _LINKED.pop(uid, None)
        return False              # told why there is no link; a step waiting would wait for nothing
    _LINKED[uid] = time.time()
    return True


async def _tell(uid: str, name: str) -> None:
    from . import handoff, users as usersmod, vault
    cfg = None
    with contextlib.suppress(Exception):
        cfg = _HOOKS["cfg"]()
    with usersmod.as_user(uid):
        label = vault.label(name)
        phones = list(_HOOKS["phones"](uid) or [])
    if not phones:
        return
    from . import remote
    link = road = ""
    why = "This machine has no address a phone could reach."
    if cfg is None or not remote.enabled(cfg):
        why = handoff.REMOTE_OFF          # remote access is the only way in: no second door
    else:
        port = int((_HOOKS["port"] or (lambda: 0))() or os.environ.get("AGENTOS_BOUND_PORT")
                   or cfg.get("port") or 8321)
        roads = await handoff.addresses(cfg, port)
        if roads:
            link, road = roads[0]["base"] + PATH, handoff.ROAD_WORDS[roads[0]["kind"]]
    text = words(label, link, road, why)
    buttons = [("Sign in", f"url:{link}")] if link else None
    for _key, _ask, say in phones:
        with contextlib.suppress(Exception):
            await say(text, buttons)
    fn = _HOOKS["ledger"]
    if fn:
        with contextlib.suppress(Exception):
            fn(uid, "seal.unlock_link", f"vault:{name}",
               ("a link to sign in sent to your own phone chat, through remote access" if link
                else "your phone chat told why no link could be sent"))


def sent_lately(uid: str) -> bool:
    """A link already went to this person within `EVERY_S`: a second step waits for it too."""
    return time.time() - _LINKED.get(uid, 0) < EVERY_S


def wait(uid: str, ready) -> bool:
    """Hold a step (in a worker thread) until `ready()` is true or `WAIT_S` passes. Never on the
    event loop's own thread: that would stop the server answering the very page that opens it."""
    loop = _HOOKS["loop"]
    if loop is None:
        return False
    try:
        if asyncio.get_running_loop() is loop:
            return False
    except RuntimeError:
        pass
    end = time.time() + WAIT_S
    while time.time() < end:
        with contextlib.suppress(Exception):
            if ready():
                return True
        time.sleep(POLL_S)
    return False


def forget() -> None:
    _SENT.clear()
    _LINKED.clear()

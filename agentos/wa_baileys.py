"""WhatsApp without Meta: the Baileys transport.

The Cloud API path (`whatsapp.py`) is the official one and it is expensive to reach:
a Meta developer app, business verification, a publicly reachable HTTPS webhook, and
a 24-hour window that silently refuses free-form messages. On a laptop behind NAT
that is a lot of ceremony before the first "hello".

This is the other route. Baileys (MIT) speaks the WhatsApp **Web** multi-device
protocol, so pairing is a QR code scanned from the phone that already has WhatsApp
on it: no Meta account, no webhook, no tunnel, and no 24-hour window — the session
is a linked device, and a linked device may message whenever it likes.

## What this module is, and is not

It supervises a Node child process (`wa_bridge/bridge.js`) and translates between it
and `WhatsAppBridge`. It makes no decisions: inbound messages are reshaped into the
**same dict shape the Cloud API webhook produces** and handed to `WhatsAppBridge._one`,
so owner pairing, the allow-list, `/clear`, flow triggers, approvals, taint and the
audit ledger are the exact code that already runs — one agent path, two transports.

Reshaping to Meta's shape rather than refactoring both onto a neutral one is
deliberate: it keeps the diff on the existing, tested path at nearly zero.

## Two things that are honestly worse than the official API

- **It is unofficial.** It emulates a linked device. WhatsApp does not support this,
  and accounts have been banned for automating on it. That sentence belongs on the
  screen before anybody scans, not in a doc — `components.py` carries it.
- **There are no interactive reply buttons.** The Cloud API's three-button approval
  card has no equivalent here, so approvals fall back to numbered replies. See
  `approval_prompt()`.

## Why a subprocess and not a library

There is no Python implementation of the multi-device protocol worth depending on.
Node is therefore a real runtime dependency — which is why this is an *offered*
component (`components.CATALOG["whatsapp-bridge"]`) rather than something the
installer drags in. Nothing here is installed until somebody says yes.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent / "wa_bridge"
NODE_MODULES = BRIDGE_DIR / "node_modules"


def session_dir() -> Path:
    """Where this ACCOUNT's linked device lives — resolved, never a constant.

    It was `cfgmod.AGENTOS_HOME / "whatsapp" / "session"`, evaluated once at import,
    and that is wrong twice on a machine with accounts. `whatsapp` is in
    `users.USER_KEYS`, so the settings are per-user while the credentials were not:
    every account shared one linked device, and `paired()` answered for the machine
    rather than for the person asking. The second account to open the panel would
    have found itself already linked to the first one's phone.

    `home_for('')` is the machine home, so an install with no accounts keeps using
    the exact directory it always used.
    """
    from . import users as usersmod
    return usersmod.home_for(usersmod.current()) / "whatsapp" / "session"


#: How long to wait for the first QR (or a restored session) before saying so.
PAIR_TIMEOUT = 90.0


def node_path() -> str:
    """Node, over the extended PATH — a GUI-launched process does not inherit nvm."""
    from .mcp_client import _extended_path
    return shutil.which("node", path=_extended_path()) or ""


def npm_path() -> str:
    from .mcp_client import _extended_path
    return shutil.which("npm", path=_extended_path()) or ""


def installed() -> bool:
    """Is the bridge ready to run? Node present AND its dependencies fetched."""
    return bool(node_path()) and (NODE_MODULES / "baileys").exists()


def paired() -> bool:
    """A multi-file auth state exists, so a previous scan is still valid."""
    try:
        return any(session_dir().glob("creds.json"))
    except OSError:
        return False


def why_not() -> str:
    """One sentence naming what is missing, and never a dead control."""
    if not node_path():
        return ("Node.js is not installed — the WhatsApp Web bridge is a Node "
                "library, so it needs a Node runtime on this machine.")
    if not (NODE_MODULES / "baileys").exists():
        return ("The WhatsApp bridge has not been downloaded yet — install the "
                "'whatsapp-bridge' component to fetch it (MIT, ~60 MB).")
    return ""


def forget_session() -> bool:
    """Unlink: drop the stored device credentials so the next start asks for a scan."""
    import shutil as _sh
    d = session_dir()
    if not d.exists():
        return False
    _sh.rmtree(d, ignore_errors=True)
    return True


def approval_prompt(name: str, reason: str) -> str:
    """The approval card, as text.

    The Cloud API path sends three reply buttons. A linked device cannot, so this is
    the fallback — spelled out rather than degraded silently, because an approval
    nobody can answer is a run that hangs until it times out.
    """
    return (f"⚠ Approval needed: {name}\n{reason}\n\n"
            f"Reply 1 to deny · 2 to allow once · 3 to allow and remember")


#: A linked device has no reply buttons, so an approval is answered by typing a
#: digit. These map onto the Cloud API's button VALUES (`ap:<id>:<val>`); the id
#: itself belongs to whichever approval is pending and is filled in by
#: `WhatsAppBridge.pending_button()` — this module has no business knowing it.
REPLY_TO_VALUE = {"1": "0", "2": "1", "3": "2"}


class BaileysTransport:
    """The Node child process, its lifecycle, and the two directions of traffic."""

    def __init__(self, on_message, on_event=None, store=None, pending_button=None):
        self.on_message = on_message      # async fn(msg: dict, val: dict) -> None
        #: fn(value) -> "ap:<aid>:<value>" for the approval currently waiting, or "".
        #: Supplied by WhatsAppBridge, which owns the pending table.
        self.pending_button = pending_button or (lambda _v: "")
        self.on_event = on_event          # async fn(dict) -> None — QR, ready, errors
        self.store = store
        self.proc: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task | None = None
        self.qr = ""                      # latest unscanned pairing payload
        self.qr_svg = ""                  # the same code, drawn for a browser
        self.qr_ascii = ""                # and for a terminal
        self.state = "stopped"            # stopped|starting|qr|ready|error|logged_out
        self.error = ""
        self.me = ""
        self._pending: dict[str, asyncio.Future] = {}
        #: wa_id -> the full jid it really arrived from (`…@s.whatsapp.net` or
        #: `…@lid`). See `send()`: the domain cannot be guessed from the id.
        self._jids: dict[str, str] = {}
        self._stopping = False

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> str:
        if self.proc and self.proc.returncode is None:
            return ""
        gap = why_not()
        if gap:
            self.state, self.error = "error", gap
            return gap
        self._stopping = False
        self.state, self.error, self.qr = "starting", "", ""
        sess = session_dir()
        sess.mkdir(parents=True, exist_ok=True)
        try:
            sess.chmod(0o700)      # a linked-device credential is a credential
        except OSError:
            pass
        from .mcp_client import _extended_path
        env = {**os.environ, "PATH": _extended_path(),
               "WA_SESSION_DIR": str(sess)}
        self.proc = await asyncio.create_subprocess_exec(
            node_path(), str(BRIDGE_DIR / "bridge.js"),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=env, cwd=str(BRIDGE_DIR))
        self.task = asyncio.create_task(self._pump())
        return ""

    async def stop(self):
        self._stopping = True
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), timeout=8)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self.proc.kill()
                except ProcessLookupError:
                    pass
        self.state = "stopped"

    async def logout(self):
        """Unlink from the phone, then forget the credentials locally."""
        await self._write({"type": "logout"})
        await asyncio.sleep(1.0)
        await self.stop()
        forget_session()
        self.state = "logged_out"

    # -- the protocol -------------------------------------------------------

    async def _write(self, obj: dict) -> bool:
        if not (self.proc and self.proc.stdin and self.proc.returncode is None):
            return False
        try:
            self.proc.stdin.write((json.dumps(obj) + "\n").encode())
            await self.proc.stdin.drain()
            return True
        except Exception:
            return False

    async def _pump(self):
        """Read the bridge's stdout forever, one JSON frame per line."""
        assert self.proc and self.proc.stdout
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                try:
                    ev = json.loads(line.decode(errors="replace"))
                except Exception:
                    continue          # a corrupt frame is not worth killing the link
                await self._on_frame(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.state, self.error = "error", f"{type(e).__name__}: {e}"
        finally:
            if not self._stopping and self.state not in ("logged_out", "stopped"):
                # stderr is where Baileys' own diagnostics went; surface the tail so a
                # crash says something more useful than "the process ended".
                tail = ""
                try:
                    if self.proc and self.proc.stderr:
                        tail = (await self.proc.stderr.read())[-400:].decode(errors="replace")
                except Exception:
                    pass
                self.state = "error"
                self.error = self.error or (tail.strip() or "the WhatsApp bridge stopped")

    async def _on_frame(self, ev: dict):
        kind = ev.get("type") or ""
        if kind == "qr":
            self.qr, self.state = ev.get("qr") or "", "qr"
            self.qr_svg = ev.get("svg") or ""
            self.qr_ascii = ev.get("ascii") or ""
        elif kind == "ready":
            self.qr = self.qr_svg = self.qr_ascii = ""
            self.state, self.me = "ready", ev.get("me") or ""
            if self.store:
                self.store.log("whatsapp", f"linked device ready ({self.me})")
        elif kind == "status":
            st = ev.get("state") or ""
            if st == "logged_out":
                self.state, self.qr = "logged_out", ""
                forget_session()
            elif st == "closed" and ev.get("reason") == "logged_out":
                self.state, self.qr = "logged_out", ""
                forget_session()
        elif kind == "error":
            self.error = ev.get("message") or "unknown bridge error"
            if ev.get("fatal"):
                self.state = "error"
            if self.store:
                self.store.log("error", f"whatsapp bridge: {self.error}")
        elif kind == "message":
            await self._inbound(ev)
        if self.on_event:
            try:
                await self.on_event({"type": "whatsapp_link", "state": self.state,
                                     "qr": self.qr, "qr_svg": self.qr_svg,
                                     "error": self.error})
            except Exception:
                pass

    async def _inbound(self, ev: dict):
        """Reshape a Baileys message into the Cloud API's webhook shape.

        The point is that `WhatsAppBridge._one` cannot tell the difference: pairing,
        the allow-list, commands, flow triggers and approvals are the same code on
        both transports.
        """
        wa_id = ev.get("from") or ""
        if not wa_id:
            return
        # Learn the address before anything else can fail: this is the only place the
        # real domain is ever visible, and `send()` cannot reconstruct it. See there.
        if ev.get("jid"):
            self._jids[wa_id] = ev["jid"]
        text = (ev.get("text") or "").strip()
        # A bare "1"/"2"/"3" is a button tap — but ONLY while something is actually
        # waiting to be answered. Without that check, texting "2" to your own agent
        # would silently resolve nothing and be swallowed instead of answered.
        val = REPLY_TO_VALUE.get(text)
        btn = self.pending_button(val) if val is not None else ""
        msg: dict
        if btn:
            msg = {"from": wa_id, "id": ev.get("id") or "", "type": "interactive",
                   "interactive": {"type": "button_reply",
                                   "button_reply": {"id": btn, "title": text}}}
        else:
            msg = {"from": wa_id, "id": ev.get("id") or "",
                   "type": "text" if text else (ev.get("kind") or "unknown"),
                   "text": {"body": text}}
        val = {"contacts": [{"wa_id": wa_id,
                             "profile": {"name": ev.get("name") or ""}}]}
        try:
            await self.on_message(msg, val)
        except Exception as e:
            if self.store:
                self.store.log("error", f"whatsapp inbound: {type(e).__name__}: {e}")

    # -- outbound -----------------------------------------------------------

    async def send(self, text: str, wa_id: str) -> str:
        """Reply to the ADDRESS the message came from, not a reconstruction of it.

        `wa_id` is the bare local part, because that is the shape the Cloud API uses
        and `WhatsAppBridge` keys everything on it — the owner, the allow-list, the
        chat rows. The bridge used to turn it back into a jid by appending
        `@s.whatsapp.net`, which is right only while that guess happens to be the
        right domain.

        It is increasingly not. WhatsApp now addresses many contacts by **LID**
        (`<id>@lid`, a privacy identifier that is not a phone number), and a reply to
        `<lid-number>@s.whatsapp.net` goes to an address nobody holds: accepted by
        the socket, delivered to no one. The channel looked perfect from this side —
        the message arrived, the turn ran, the ledger recorded a reply — and the
        phone stayed silent.

        So remember the real jid per sender and send back to that. It is learned from
        inbound traffic, which is also the only way a linked device ever obtains a
        LID; the append stays as the fallback for a plain number nobody has messaged
        from yet.
        """
        if self.state != "ready":
            return (f"[error] the WhatsApp link is not connected "
                    f"({self.state}{': ' + self.error if self.error else ''})")
        to = self._jids.get(wa_id) or wa_id
        ok = await self._write({"type": "send", "to": to, "text": text or "(empty)"})
        if not ok:
            return "[error] the WhatsApp bridge is not running"
        if self.store:
            self.store.log("whatsapp", f"→ sent: {text[:200]}")
        return "sent via WhatsApp"

    def info(self) -> dict:
        return {"mode": "baileys", "installed": installed(), "paired": paired(),
                "state": self.state, "qr": self.qr, "qr_svg": self.qr_svg,
                "qr_ascii": self.qr_ascii, "error": self.error,
                "me": self.me, "why": why_not(),
                # No 24-hour window on a linked device: that rule belongs to the
                # Business API, and repeating it here would be inventing a limit.
                "window_open": self.state == "ready"}

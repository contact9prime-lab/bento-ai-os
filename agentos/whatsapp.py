"""WhatsApp, natively: the same agent, the same memory, on the app people already use.

This brings a conversation IN to *your* agent, the
way Telegram does: same conversation history, same tools, same approvals, same
`space_id`. Someone who enables "WhatsApp" expecting to reach Aria gets Aria.

It uses Meta's WhatsApp Cloud API, which is free to set up and does not require a
scraped or reverse-engineered client. Setup is four values from
developers.facebook.com: a phone number id, an access token, an app secret, and a
verify token you invent.

Four things about WhatsApp are genuinely different from Telegram, and each one has
bitten a naive port of the Telegram bridge:

- **It is a webhook, not a poll.** Meta POSTs to this machine, so this machine has
  to be reachable from the internet. `webhook_url` reports the address to paste
  into Meta's console and `reachability()` says plainly when there isn't one yet,
  pointing at the tunnel — rather than sitting silently "enabled" and never
  receiving anything.

- **The webhook is public, so the signature is not optional.** Every delivery
  carries `X-Hub-Signature-256`, an HMAC of the RAW body under the app secret.
  It is verified in constant time before the body is even parsed, on the
  bytes as received — re-serialising the JSON changes them and the check would
  then fail on every legitimate message and pass on nothing.

- **The 24-hour window is real.** Outside 24 hours from the user's last inbound
  message, Meta refuses free-form text and only allows a pre-approved template.
  A scheduled 08:00 briefing therefore *cannot* be delivered to a silent chat.
  `send()` says exactly that instead of returning a bare API error, because
  "delivery failed" and "WhatsApp will not let me speak first" are different
  problems with different fixes.

- **Approvals are three buttons, hard-limited.** Reply buttons max out at three
  per message with 20-character titles, which happens to fit Deny / Allow once /
  Always exactly. `_TITLES` is not styling; going over truncates server-side and
  the user is asked to approve something whose label was cut off.

Three faces (per CLAUDE.md):
  GUI  Settings → Channels → WhatsApp: the four fields, the webhook URL to paste,
       the paired chats, and whether the window is open.
  TUI  `bento channels whatsapp --on` configures it; `bento channels` prints the
       same state including the webhook URL and why it is or is not reachable.
  SUI  identical to GUI — a channel is not a window.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import time
from pathlib import Path

import httpx

from . import channels as chanmod
from . import config as cfgmod
from .agent import Agent
from . import users as usersmod
from . import constcmp

GRAPH = "https://graph.facebook.com/v21.0"
CHUNK = 3900              # WhatsApp's body limit is 4096
CAPTION = 1024           # an image caption's limit on both transports
WA_FILE_LIMIT = 100 * 1024 * 1024   # the Cloud API's document limit
WA_VIDEO_LIMIT = 15 * 1024 * 1024   # a video is 16 MB on WhatsApp; a little under, for the container
WINDOW_SECS = 24 * 3600   # Meta's customer-service window

# Reply-button titles. Twenty characters, hard limit — see the module docstring.
_TITLES = {"deny": "Deny", "once": "Allow once", "always": "Allow & remember"}


#: The transports this channel can run on. `channels.save` validates against it,
#: so adding one here is what makes it settable at all.
MODES = ("baileys", "cloud")


def conf(cfg: dict) -> dict:
    """The WhatsApp block, read through the channel registry.

    `channels.whatsapp` is where Settings → Channels writes; the top-level
    `whatsapp` block is where the running bridge's own state (the paired chat)
    lives. One reader, so a value set in either place is seen by both.
    """
    c = dict((cfg.get("channels") or {}).get("whatsapp") or {})
    legacy = cfg.get("whatsapp") or {}
    for k in ("phone_number_id", "access_token", "app_secret", "verify_token",
              "enabled", "owner_wa_id", "display_number"):
        if not c.get(k):
            c[k] = legacy.get(k) or ("" if k != "enabled" else False)
    # Which transport carries this channel. "baileys" pairs by QR against WhatsApp
    # Web; "cloud" is Meta's Business API. Default is cloud so an install that was
    # already working keeps working — the choice is only ever made deliberately.
    # Anything else normalises to the default rather than being carried around as
    # a mode no code branches on: a typo in config must not leave the channel in
    # a state that reads as neither transport.
    m = (c.get("mode") or legacy.get("mode") or "").strip()
    c["mode"] = m if m in MODES else "cloud"
    return c


def mode(cfg: dict) -> str:
    return conf(cfg).get("mode") or "cloud"


def configured(cfg: dict) -> bool:
    """Is this channel able to carry a message at all?

    The two transports need entirely different things, and asking a QR-paired link
    for a phone_number_id would report "not set up" on a channel that is working.
    """
    c = conf(cfg)
    if c.get("mode") == "baileys":
        from . import wa_baileys
        return wa_baileys.installed() and wa_baileys.paired()
    return all(c.get(k) for k in ("phone_number_id", "access_token", "verify_token"))


def webhook_path() -> str:
    return "/api/whatsapp/webhook"


def webhook_url(cfg: dict, base: str = "") -> str:
    """The callback URL to paste into Meta's console.

    `base` is how this server is actually reachable — a tunnel address, usually.
    Handing back `http://localhost:…` would be handing back something that cannot
    possibly work, so when there is no public base the caller gets '' and asks
    `reachability()` what to say about it.
    """
    base = (base or "").rstrip("/")
    return f"{base}{webhook_path()}" if base else ""


async def reachability(cfg: dict) -> dict:
    """Can Meta actually reach this machine, and if not, what would fix it.

    A webhook channel that is "on" but unreachable receives nothing, forever, with
    no error anywhere — the single most confusing state this integration can be in,
    so it is reported rather than left to be discovered.
    """
    if mode(cfg) == "baileys":
        # A linked device dials out to WhatsApp; nothing has to reach this machine.
        return {"reachable": True, "base": "", "via": "linked device",
                "webhook": "", "why": ""}
    from . import tunnel
    try:
        st = await tunnel.status(cfg)
    except Exception:
        st = {}
    url = (st.get("public_url") or st.get("url") or "").strip()
    if url.startswith("https://"):
        return {"reachable": True, "base": url, "via": st.get("provider") or "tunnel",
                "webhook": webhook_url(cfg, url), "why": ""}
    return {"reachable": False, "base": "", "via": "", "webhook": "",
            "why": "Meta has to be able to reach this machine over HTTPS. Turn on a "
                   "public tunnel in Settings → Remote access, then paste the "
                   "webhook URL shown here into the WhatsApp app on "
                   "developers.facebook.com."}


def verify_signature(app_secret: str, raw: bytes, header: str) -> bool:
    """Is this delivery really from Meta?

    Over the RAW bytes, always. Verifying a re-serialised body is the classic way
    to get a check that fails on every real message — key order and whitespace both
    change the digest — and then gets "fixed" by being removed.

    No secret configured means no verification is possible, and an unverifiable
    public endpoint is refused rather than trusted: this is the one route in the OS
    a stranger can POST to.
    """
    if not app_secret or not header:
        return False
    got = header.strip()
    if got.startswith("sha256="):
        got = got[7:]
    want = hmac.new(app_secret.encode(), raw, hashlib.sha256).hexdigest()
    return constcmp.same(want, got)


class WhatsAppBridge(usersmod.Scoped):
    """One paired WhatsApp chat, carried to the same agent as every other channel."""

    def __init__(self, cfg: dict, store, toolbox, broadcast):
        self.cfg = cfg
        self.store = store
        self.toolbox = toolbox
        self.broadcast = broadcast
        self.status = "off"        # off | needs | ready | error
        self.error = ""
        self._busy = False
        self._pending: dict[str, asyncio.Future] = {}
        self._seen: dict[str, float] = {}   # message id -> when, for redelivery
        #: The Baileys child process, when this channel is running in that mode.
        #: None on the Cloud API path, where Meta calls us and there is nothing to
        #: supervise.
        self.link = None

    # -- outbound ------------------------------------------------------------

    def _c(self) -> dict:
        return conf(self.cfg)

    def window_open(self, wa_id: str = "") -> bool:
        """Is Meta's 24-hour customer-service window open for this chat?

        Only the Business API has this rule. A linked device may message whenever it
        likes, so answering "closed" there would invent a restriction and refuse a
        send that would have worked — which is why this asks the mode first.
        """
        if self._c().get("mode") == "baileys":
            return True
        chat = self.store.wa_get_chat(wa_id or self._c().get("owner_wa_id") or "")
        return bool(chat and (time.time() - (chat.get("last_inbound") or 0)) < WINDOW_SECS)

    async def _api(self, path: str, payload: dict) -> dict:
        c = self._c()
        async with httpx.AsyncClient(timeout=45) as client:
            r = await client.post(
                f"{GRAPH}/{path}", json=payload,
                headers={"Authorization": f"Bearer {c.get('access_token', '')}"})
        data = r.json() if r.content else {}
        if r.status_code >= 400:
            err = (data.get("error") or {})
            raise RuntimeError(err.get("message") or f"HTTP {r.status_code}")
        return data

    def _refusal(self, c: dict, wa_id: str) -> str:
        """Why WhatsApp would not carry a message to `wa_id` right now, in one
        sentence — or '' when it would. One answer for text and pictures alike.

        The 24-hour refusal is spelled out rather than passed through as Meta's own
        error, because it is not a failure of this machine and it has a specific fix:
        the user says anything, and the window reopens for a day.
        """
        if c.get("mode") == "baileys":
            if not self.link:
                return ("[error] the WhatsApp Web bridge is not running — pair it in "
                        "Settings → Channels → WhatsApp")
            if not wa_id:
                return ("[error] Not paired yet — message this WhatsApp from your "
                        "phone once, and that chat becomes the owner")
            return ""
        if not configured(self.cfg):
            return ("[error] WhatsApp is not set up — add the phone number id, access "
                    "token and verify token in Settings → Channels → WhatsApp")
        if not wa_id:
            return ("[error] Not paired yet — message the WhatsApp number from your "
                    "phone once, and that chat becomes the owner")
        if not self.window_open(wa_id):
            return ("[error] WhatsApp only allows free-form messages within 24 hours of "
                    "your last message to it. Send anything to the number and it will "
                    "reopen for a day. (Scheduled jobs should deliver to Telegram or "
                    "Reports if you want them to reach a silent chat.)")
        return ""

    async def send(self, text: str, wa_id: str | None = None, quiet: bool = False) -> str:
        """Deliver a message, or say in one sentence why WhatsApp would not carry it.
        `quiet` keeps the words out of the diary (a sign-in link is in them)."""
        c = self._c()
        wa_id = wa_id or c.get("owner_wa_id") or ""
        no = self._refusal(c, wa_id)
        if no:
            return no
        if c.get("mode") == "baileys":
            return await self.link.send(text, wa_id, **({"quiet": True} if quiet else {}))
        text = text or "(empty)"
        try:
            for i in range(0, len(text), CHUNK):
                await self._api(f"{c['phone_number_id']}/messages", {
                    "messaging_product": "whatsapp", "to": wa_id, "type": "text",
                    "text": {"preview_url": False, "body": text[i:i + CHUNK]}})
        except Exception as e:
            return f"[error] whatsapp send failed: {e}"
        self.store.log("whatsapp", "→ said something about a sign-in link" if quiet else f"→ sent: {text[:200]}")
        return "sent via WhatsApp"

    async def say_down(self, reason: str = "", by: str = "") -> None:
        """From the server's shutdown, as Telegram's: why it is going, said to the owner's
        chat. A Cloud API chat outside its 24-hour window refuses it quietly (send)."""
        c = self._c()
        if not (c.get("enabled") and c.get("owner_wa_id") and c.get("status_messages", True) is not False):
            return
        name = self.cfg.get("agent_name") or "Bento"
        await self.send(f"▼ {name} is going offline{(' ' + reason) if reason else ''}"
                        f"{(', asked by ' + by) if by else ''}. It will be back in a minute or two.")

    async def say_wall(self, wa_id: str, text: str, buttons: list) -> None:
        """A line about a sign-in link (handoff.py). No buttons here: an address is in the
        words already, and anything else is answered by replying with its word."""
        asks = [word for _label, word in buttons or [] if not word.startswith("url:")]
        if asks:
            text += "\nReply " + " or ".join(f"“{w}”" for w in asks) + "."
        await self.send(text, wa_id, quiet=True)

    async def send_photo(self, png: bytes, caption: str = "", wa_id: str | None = None) -> str:
        """A picture with its caption — the Office's roll call, a comic strip. The same
        refusals as text (the 24-hour window included: an image is not a template).
        On the Cloud API the bytes are uploaded to Meta first and sent by media id,
        which is the only way that API takes an image that is not at a public URL."""
        c = self._c()
        wa_id = wa_id or c.get("owner_wa_id") or ""
        no = self._refusal(c, wa_id)
        if no:
            return no
        caption = (caption or "")[:CAPTION]
        if c.get("mode") == "baileys":
            return await self.link.send_photo(png, caption, wa_id)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.post(
                    f"{GRAPH}/{c['phone_number_id']}/media",
                    data={"messaging_product": "whatsapp", "type": "image/png"},
                    files={"file": ("office.png", png, "image/png")},
                    headers={"Authorization": f"Bearer {c.get('access_token', '')}"})
            up = r.json() if r.content else {}
            if r.status_code >= 400 or not up.get("id"):
                raise RuntimeError((up.get("error") or {}).get("message") or f"HTTP {r.status_code}")
            await self._api(f"{c['phone_number_id']}/messages", {
                "messaging_product": "whatsapp", "to": wa_id, "type": "image",
                "image": {"id": up["id"], "caption": caption}})
        except Exception as e:
            return f"[error] whatsapp picture failed: {e}"
        self.store.log("whatsapp", f"→ sent a picture: {caption[:120]}")
        return "sent via WhatsApp"

    async def send_video(self, data: bytes, mime: str, caption: str = "", wa_id: str | None = None) -> str:
        """A video that plays in the chat. WhatsApp plays only mp4 and takes 16 MB, so anything
        bigger is made smaller first (stageclip.fit) and what cannot be is said, never cut.
        The same refusals as text: on the Cloud API a video is not a template either."""
        from . import stageclip
        c = self._c()
        wa_id = wa_id or c.get("owner_wa_id") or ""
        no = self._refusal(c, wa_id)
        if no:
            return no
        if "mp4" not in (mime or ""):
            return "[error] this machine recorded a video WhatsApp cannot play (no mp4, and no ffmpeg to make one)"
        got = await stageclip.fit(data, mime, WA_VIDEO_LIMIT)
        if not got:
            return f"[error] the video is over WhatsApp's {WA_VIDEO_LIMIT // (1024 * 1024)} MB and could not be made smaller here"
        data, mime = got
        caption = (caption or "")[:CAPTION]
        if c.get("mode") == "baileys":
            return await self.link.send_video(data, caption, wa_id)
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                r = await client.post(
                    f"{GRAPH}/{c['phone_number_id']}/media",
                    data={"messaging_product": "whatsapp", "type": "video/mp4"},
                    files={"file": ("story.mp4", data, "video/mp4")},
                    headers={"Authorization": f"Bearer {c.get('access_token', '')}"})
            up = r.json() if r.content else {}
            if r.status_code >= 400 or not up.get("id"):
                raise RuntimeError((up.get("error") or {}).get("message") or f"HTTP {r.status_code}")
            await self._api(f"{c['phone_number_id']}/messages", {
                "messaging_product": "whatsapp", "to": wa_id, "type": "video",
                "video": {"id": up["id"], "caption": caption}})
        except Exception as e:
            return f"[error] whatsapp video failed: {e}"
        self.store.log("whatsapp", f"→ sent a video: {caption[:120]}")
        return "sent via WhatsApp"

    async def send_clips(self, scenes: list, wa_id: str, items: list | None = None,
                         pngs: list | None = None) -> int:
        """The story's videos after its pictures, as Telegram sends them: what is built in 3D
        raised and toured, a blueprint with no 3D form walked through, with sound. One plan
        for both channels (stageclip.plan). `/clips off` is `whatsapp.clips: false`. Never
        fatal: the pictures already went, and the diary says why there was no video."""
        from . import stageclip
        if self._c().get("clips") is False or not stageclip.available(self.cfg):
            return 0
        sent = 0
        for job in stageclip.plan(scenes, items, pngs):
            sc = job["scene"]
            got = None
            try:
                got = await stageclip.make(job, self.cfg, voice=self._c().get("narrate") is not False,
                                           agent=self.cfg.get("agent_name") or "",
                                           log=lambda m: self.store.log("whatsapp", m))
            except Exception:
                got = None
            if not got:
                self.store.log("whatsapp", f"no video for '{sc.get('title') or sc.get('kind')}': it could not be recorded here")
                continue
            res = await self.send_video(got[0], got[1], stageclip.caption(job), wa_id)
            if str(res).startswith("[error]"):
                self.store.log("whatsapp", f"could not send the video: {res}")
            else:
                sent += 1
        return sent

    async def send_document(self, path: str, caption: str = "", wa_id: str | None = None) -> str:
        """A file a reply named, as a WhatsApp document. The same refusals as text (the
        24-hour window applies on the Cloud API). Cloud API uploads the bytes first and
        sends by media id; a linked device takes them over its stdio line."""
        import mimetypes
        c = self._c()
        wa_id = wa_id or c.get("owner_wa_id") or ""
        no = self._refusal(c, wa_id)
        if no:
            return no
        p = Path(path)
        caption = (caption or "")[:CAPTION]
        if c.get("mode") == "baileys":
            return await self.link.send_document(str(p), caption, wa_id)
        if p.stat().st_size > WA_FILE_LIMIT:
            return "too big"
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                with p.open("rb") as fh:
                    r = await client.post(
                        f"{GRAPH}/{c['phone_number_id']}/media",
                        data={"messaging_product": "whatsapp", "type": mime},
                        files={"file": (p.name, fh, mime)},
                        headers={"Authorization": f"Bearer {c.get('access_token', '')}"})
            up = r.json() if r.content else {}
            if r.status_code >= 400 or not up.get("id"):
                raise RuntimeError((up.get("error") or {}).get("message") or f"HTTP {r.status_code}")
            await self._api(f"{c['phone_number_id']}/messages", {
                "messaging_product": "whatsapp", "to": wa_id, "type": "document",
                "document": {"id": up["id"], "filename": p.name, "caption": caption}})
        except Exception as e:
            return f"[error] whatsapp file failed: {e}"
        self.store.log("whatsapp", f"→ sent a file: {p.name}")
        return "sent via WhatsApp"

    async def send_blueprint_docs(self, rows: list, ans: str, wa_id) -> None:
        """A blueprint also goes as its document of drawing sheets (bpdoc.py), to keep or print.
        Never fatal, and nothing when this machine has no browser to print it with."""
        from . import bpdoc, executors as _ex, stage as stagemod
        for r in rows:
            if (r.get("scene") or {}).get("kind") != "blueprint":
                continue
            try:
                p = await bpdoc.to_file(self.store, self.cfg, r["id"], _ex.default_workspace(self.cfg),
                                        self.cfg.get("agent_name") or "", stagemod.question_of(self.store, ans))
                if p:
                    await self.send_document(str(p), "⤓ The blueprint as drawing sheets, to keep or print.", wa_id)
            except Exception as e:
                self.store.log("whatsapp", f"could not send the blueprint document: {e}")

    async def send_stage(self, cid: str, reply: str, wa_id: str, ans: str = "") -> str:
        """The answer's story after the reply, as Telegram sends it: a picture per scene
        (stagestill.py), or the page when this machine has no browser to draw them.
        Never fatal: the reply has already gone."""
        try:
            from . import stage as stagemod, stagestill, executors as _ex
            ans = ans or stagemod.last_question(self.store, cid)   # one named story (sent from the desktop), else the last
            scenes = [s["scene"] for s in stagemod.story(self.store, cid, ans)] if ans else []
            n = len(scenes)
            if not n:
                return ""
            # a blueprint fills itself in after the reply (bpfill.py): a phone gets its pictures,
            # so wait a while for the parts to land rather than photograph the outline
            from . import bpfill
            rows = stagemod.story(self.store, cid, ans)
            if bpfill.filling([r["id"] for r in rows]):
                await self.send(bpfill.HOLD_LINE, wa_id)     # or the phone hears nothing for minutes
            await bpfill.settle([r["id"] for r in rows], bpfill.PHONE_WAIT_S)
            scenes = [r["scene"] for r in stagemod.story(self.store, cid, ans)]
            pngs = await stagestill.render(stagemod.report_html(
                self.store, cid, ans, agent=self.cfg.get("agent_name") or "", still=True), self.cfg)
            items = stagemod.still_items(scenes)
            if len(pngs) == len(items):
                ok = True
                caps = [stagemod.still_caption_for(sc, v, i, len(items)) for i, (sc, v) in enumerate(items)]
                q = stagemod.question_of(self.store, ans)
                if q and caps:
                    caps[0] = f"▶ {q}\n\n" + caps[0]      # what the story answers, on top, as on Telegram
                for png, cap in zip(pngs, caps):
                    res = await self.send_photo(png, cap, wa_id)
                    ok = ok and not str(res).startswith("[error]")
                if ok:
                    await self.send_clips(scenes, wa_id, items, pngs)
                    await self.send_blueprint_docs(rows, ans, wa_id)
                    return "sent"
            p = stagemod.write_report(self.store, _ex.default_workspace(self.cfg), cid, ans,
                                      answer=reply, agent=self.cfg.get("agent_name") or "")
            if p:
                res = await self.send_document(str(p), f"▶ The story, {n} scene{'s' if n != 1 else ''}. "
                                                       f"Open it to watch.", wa_id)
                if str(res).startswith("[error]"):
                    self.store.log("whatsapp", f"could not send the story: {res}")
                    return str(res)
                return "sent"
            return "[error] the story could not be drawn or written on this machine"
        except Exception as e:
            self.store.log("whatsapp", f"could not send the story: {e}")
            return f"[error] {e}"

    async def send_files(self, reply: str, wa_id: str) -> None:
        """The files a reply names, after it, as Telegram does (whatsapp.files = false
        switches it off). A file too big to send is named with where it is instead."""
        if self._c().get("files") is False:
            return
        try:
            from . import outputs, users as _u
            for f in outputs.mentioned(reply, outputs.roots(self.cfg, admin=_u.is_admin(_u.current()))):
                res = await self.send_document(f["path"], f["name"], wa_id)
                if res == "too big":
                    await self.send(f"📎 {f['name']} is {outputs.size_words(f['size'])}, too big to "
                                    f"send here. It's on the machine at {f['path']}", wa_id)
                elif res.startswith("[error]"):
                    await self.send(f"📎 I couldn't send {f['name']} ({res[8:]}). "
                                    f"It's on the machine at {f['path']}", wa_id)
        except Exception as e:
            self.store.log("whatsapp", f"could not send the reply's files: {e}")

    async def send_talk(self, lines: list, wa_id: str) -> None:
        """Agents talked during this chat's turn: the exchange as a comic strip, as
        the Telegram bridge sends it (and switched off the same way, whatsapp.comics =
        false). Never fatal — the reply has already been sent."""
        if not lines or self._c().get("comics") is False:
            return
        try:
            from . import comic, playground
            from .telegram import office_name
            first = lines[0]
            title = f"{office_name(self.cfg)} · {first['speaker']}" + (
                f" asks {first['to']}" if first.get("to") and first.get("kind") == "ask" else " talks")
            png = comic.strip(self.store, self.cfg, lines, title)
            await self.send_photo(png, playground.caption(lines, CAPTION), wa_id)
        except Exception as e:
            self.store.log("whatsapp", f"could not draw the comic strip: {e}")

    async def send_office(self, wa_id: str) -> str:
        """/office: who is at work right now, as a picture — Telegram's /office."""
        from . import comic, knowledge, playground
        from .telegram import office_name
        rows = playground.rollcall(self.store, self.cfg, lead_busy=knowledge.active_turns() > 0)
        png = comic.rollcall_image(self.store, self.cfg, rows, office_name(self.cfg))
        return await self.send_photo(png, playground.rollcall_text(rows), wa_id)

    # -- inbound -------------------------------------------------------------

    def verify_challenge(self, mode: str, token: str, challenge: str) -> str | None:
        """Meta's one-time GET handshake. Returns the challenge to echo, or None."""
        want = (self._c().get("verify_token") or "").strip()
        if mode == "subscribe" and want and constcmp.same(want, (token or "").strip()):
            self.store.log("whatsapp", "webhook verified by Meta")
            return challenge or ""
        return None

    async def handle(self, body: dict):
        """One webhook delivery. Meta batches, retries and redelivers, so this walks
        the whole envelope and drops anything already answered — a redelivery must
        not start a second agent turn on the same sentence."""
        for entry in (body.get("entry") or []):
            for change in (entry.get("changes") or []):
                val = change.get("value") or {}
                for msg in (val.get("messages") or []):
                    await self._one(msg, val)

    def _fresh(self, mid: str) -> bool:
        """First time this message id has been seen? Remember it if so.

        This lives BELOW both transports, in `_one`, because both redeliver and only
        one of them used to be guarded. Meta batches and retries; a linked device
        re-emits `messages.upsert` when the socket reconnects. The guard sat in
        `handle()` — the webhook path — so the Baileys transport, which calls `_one`
        directly, had none: one sentence became two agent turns a minute apart, two
        replies on the phone, and two charges for it.
        """
        if not mid:
            return True                      # nothing to key on; let it through
        if mid in self._seen:
            return False
        self._seen[mid] = time.time()
        if len(self._seen) > 500:
            cut = time.time() - 3600
            self._seen = {k: v for k, v in self._seen.items() if v > cut}
        return True

    def _profile_name(self, val: dict, wa_id: str) -> str:
        for c in (val.get("contacts") or []):
            if c.get("wa_id") == wa_id:
                return (c.get("profile") or {}).get("name") or wa_id
        return wa_id

    async def _one(self, msg: dict, val: dict):
        wa_id = msg.get("from") or ""
        if not wa_id:
            return
        # Before anything with a side effect — a redelivered approval tap would
        # otherwise answer the same question twice as surely as a redelivered
        # sentence starts the same turn twice.
        if not self._fresh(msg.get("id") or ""):
            return
        # A button tap answers a pending approval; it is not a new sentence.
        inter = msg.get("interactive") or {}
        if inter.get("type") == "button_reply":
            self._answer(wa_id, (inter.get("button_reply") or {}).get("id") or "")
            return
        text = ((msg.get("text") or {}).get("body") or "").strip()
        kind = msg.get("type") or ""
        if not text:
            # Media, location, contacts, reactions. Saying so is better than silence:
            # a photo sent to an assistant that never answers reads as broken.
            if kind and kind not in ("text", "interactive"):
                await self.send(f"I can only read text here for now — that arrived as "
                                f"a {kind}.", wa_id)
            return

        # A sign-in wall this chat is being asked about (cdpbrowser.reach), as on Telegram:
        # a code goes into the page and is never logged or saved in the conversation. Only
        # a chat whose own turn registered itself can answer.
        from . import cdpbrowser as _cdpb
        said = await _cdpb.from_phone(usersmod.current() or "", f"wa:{wa_id}", text)
        if said:
            self.store.log("whatsapp", f"a reply from {wa_id} answered the browser")
            if _cdpb.reply_of(said):
                await self.send(_cdpb.reply_of(said), wa_id)
            return

        name = self._profile_name(val, wa_id)
        chat = self.store.wa_upsert_chat(wa_id, name)
        self.store.log("whatsapp", f"← {name} ({wa_id}): {text[:160]}")

        c = self.cfg.setdefault("whatsapp", {})
        if not (self._c().get("owner_wa_id") or ""):
            c["owner_wa_id"] = wa_id
            cfgmod.save_config(self.cfg)
            self.store.wa_set_allowed(wa_id, 1, "pairing: the first chat to write")
            chat["allowed"] = 1
            agent = self.cfg.get("agent_name") or "Bento"
            self.store.log("whatsapp", f"paired: owner = {name} ({wa_id})")
            await self.send(f"▲ Linked. I'm {agent}, the agent on your machine — same "
                            f"memory and the same tools as at the desk. Send me "
                            f"anything; /new starts a new session.", wa_id)
            await self.broadcast({"type": "whatsapp_chats"})
            return

        # The standing allow-list, consulted before the refusal. A number the owner
        # wrote down in advance is let in on its first message instead of being told
        # no and waiting for somebody to find its row — see channels.preauthorised.
        if not chat.get("allowed"):
            match = chanmod.preauthorised(conf(self.cfg), wa_id)
            if match:
                self.store.wa_set_allowed(wa_id, 1, f"the allow-list ({match})")
                chat["allowed"] = 1
                self.store.log("whatsapp", f"allowed {name} ({wa_id}) — on the allow-list",
                               {"wa_id": wa_id, "matched": match})

        if not chat.get("allowed"):
            # A stranger reaching your agent is a security event, and it used to
            # leave a log line indistinguishable from a message that was answered.
            # "Has anyone else been trying to talk to it?" has to be answerable from
            # the log alone, so this is recorded EVERY time — not only on the first
            # message, which is all the reply below is rate-limited to.
            self.store.log("whatsapp", f"refused {name} ({wa_id}) — not paired and not on "
                                       f"the allow-list",
                           {"wa_id": wa_id, "name": name,
                            "msg_count": chat.get("msg_count") or 0, "text": text[:160]})
            if (chat.get("msg_count") or 0) <= 1:
                await self.send("▲ I've asked the owner whether you can talk to me. You'll hear "
                                "back here once they say yes.", wa_id)
                await self.ask_owner_about(wa_id, name, text)
            await self.broadcast({"type": "whatsapp_chats"})
            return
        await self.broadcast({"type": "whatsapp_chats"})

        low = text.lower()
        if wa_id == (self._c().get("owner_wa_id") or "") and low.split(" ")[0] in ("/people", "/allow", "/block"):
            await self.send(await self._owner_command(low.split(" ")[0], text.partition(" ")[2].strip()), wa_id)
            return
        if low.startswith("/clear"):
            self.store.clear_messages(self._conversation(chat))
            await self.send("🧹 Session cleared — starting fresh.", wa_id)
            return
        from . import phonesessions
        res = phonesessions.handle(self.store, "whatsapp", wa_id, chat.get("name") or wa_id,
                                   self._conversation(chat), text, self._busy)
        if res is not None:
            # /new, /sessions, /resume: the same answers Telegram gives, without buttons
            # (a reply button is three at most, and a list of sessions is longer)
            if res.get("cid"):
                self.store.wa_set_conversation(wa_id, res["cid"])
                chat["conversation_id"] = res["cid"]
                self.store.log("whatsapp", f"session {'started' if res.get('new') else 'reopened'} "
                                           f"for {chat.get('name') or wa_id}",
                               {"wa_id": wa_id, "conversation_id": res["cid"]})
            await self.send(res["say"], wa_id)
            return
        if low.startswith("/office"):
            out = await self.send_office(wa_id)
            if out.startswith("[error]"):
                await self.send(out, wa_id)
            return
        if low.startswith("/clips"):
            arg = low[6:].strip()
            if arg in ("on", "off"):
                self.cfg.setdefault("whatsapp", {})["clips"] = arg == "on"
                cfgmod.save_config(self.cfg)
            on = self._c().get("clips", True) is not False
            await self.send("▶ When a story builds something in 3D, or is a blueprint, I'll send a video "
                            "of it with sound after the pictures." if on
                            else "▶ Pictures only. /clips on brings the videos back.", wa_id)
            return
        if low.startswith("/status"):
            # what answers, as Telegram's /status says it: an agent CLI and its model when
            # one is the engine, since the saved provider model is not in use then
            from . import executors as execmod
            eng = execmod.resolve_engine(self.cfg)
            what = (self.cfg.get("default_model") or "(none)") if eng == "aria" else \
                eng + (" · " + execmod.executor_model(self.cfg, eng)
                       if execmod.executor_model(self.cfg, eng) else "")
            await self.send(f"▲ online · model {what} · autonomy {self.cfg.get('autonomy')}", wa_id)
            return

        # A message trigger starts a flow, checked before the busy lock — a flow runs
        # in its own task with its own orchestrator, so making it queue behind a
        # conversation would mean "the alert I set up did not fire because I was
        # mid-sentence". Same reasoning, and same seam, as the Telegram bridge.
        try:
            from . import flows as flowsmod
            hit = (flowsmod.match_message(self.store, text, surface="whatsapp")
                   if self.toolbox.fabric else None)
        except Exception:
            hit = None
        if hit:
            trig, flow = hit
            asyncio.create_task(self.toolbox.fabric.run_flow(
                flow, text, origin={"surface": "whatsapp", "chat_id": wa_id,
                                    "ref": trig["id"]},
                conversation_id=self._conversation(chat), trigger_id=trig["id"]))
            await self.send(f"▶ {flow['name']} started — I'll report back here.", wa_id)
            return

        if self._busy:
            await self.send("⏳ Still working on your previous message…", wa_id)
            return
        self._busy = True
        # a sign-in wall met during this turn is asked here, on the phone
        from . import cdpbrowser as _cdpb
        _wall_uid = usersmod.current() or ""
        _cdpb.reach(_wall_uid, f"wa:{wa_id}", lambda att, png: self.ask_wall(wa_id, att, png),
                    say=lambda text, buttons: self.say_wall(wa_id, text, buttons))
        try:
            await self._turn(chat, wa_id, text)
        except Exception as e:
            await self.send(f"[error] {type(e).__name__}: {e}", wa_id)
        finally:
            _cdpb.unreach(_wall_uid, f"wa:{wa_id}")
            self._busy = False

    async def ask_wall(self, wa_id: str, att: dict, png: bytes) -> None:
        """The shared browser met a page only a person can get past during this chat's
        turn: a picture of the page and one question (cdpbrowser.tool_wait). No button: a
        reply of "done" carries on, which works on both transports."""
        from . import cdpbrowser as _cdpb
        text = _cdpb.phone_words(att, self.cfg.get("agent_name") or "Bento", button=False,
                                 offer=_cdpb.phone_offer(att))
        if png:
            out = await self.send_photo(png, text, wa_id)
            if out == "sent via WhatsApp":
                return
        await self.send(text, wa_id)

    async def ask_owner_about(self, wa_id: str, name: str, text: str) -> None:
        """Somebody new wrote: the account that owns this channel decides. Asked on its
        WhatsApp owner chat, on its Telegram owner chat when that is paired (buttons),
        and on its desktop. Before, the newcomer was sent to Settings and the owner
        was told nothing."""
        owner = self._c().get("owner_wa_id") or ""
        agent = self.cfg.get("agent_name") or "Bento"
        who = f"{name} (+{wa_id})" if name and name != wa_id else f"+{wa_id}"
        words = (f"📩 {who} wants to talk to {agent} on WhatsApp. They wrote:\n“{text[:300]}”\n\n"
                 f"Allowing them lets them chat with {agent}, under your settings and permissions.")
        if owner and owner != wa_id:
            with contextlib.suppress(Exception):
                await self.send(words + f"\n\nReply /allow {wa_id} or /block {wa_id}.", owner, quiet=True)
        tg = getattr(self.toolbox, "telegram", None)
        tg_owner = tg is not None and (tg._t().get("owner_chat_id") or 0)
        if tg_owner and getattr(tg, "status", "") == "polling":
            with contextlib.suppress(Exception):
                await tg._api("sendMessage", chat_id=tg_owner, text=words[:4000],
                              reply_markup={"inline_keyboard": [[
                                  {"text": "✓ Allow", "callback_data": f"wan:{wa_id}:1"},
                                  {"text": "✗ Block", "callback_data": f"wan:{wa_id}:0"}]]})
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "whatsapp_request", "wa_id": wa_id, "title": who, "text": text[:160]})

    async def decide_newcomer(self, wa_id: str, allow: bool, by: str = "the owner, on WhatsApp") -> str:
        """The owner's answer, from WhatsApp, Telegram or the desktop: one door."""
        if not self.store.wa_get_chat(wa_id):
            return "nobody by that number has written"
        if not allow and wa_id == (self._c().get("owner_wa_id") or ""):
            return "that's the owner"
        self.store.wa_set_allowed(wa_id, 1 if allow else 0, by)
        self.store.log("whatsapp", f"{'allowed' if allow else 'blocked'} {wa_id} ({by})",
                       {"wa_id": wa_id, "allowed": allow, "by": by})
        if allow:
            agent = self.cfg.get("agent_name") or "Bento"
            with contextlib.suppress(Exception):
                await self.send(f"▲ You're in. I'm {agent}. Send me anything; /new starts a new session.",
                                wa_id, quiet=True)
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "whatsapp_chats"})
        return "allowed" if allow else "blocked"

    async def _owner_command(self, cmd: str, arg: str) -> str:
        """/people, /allow, /block: the owner's, from their own WhatsApp."""
        from .telegram_admin import decided
        owner = self._c().get("owner_wa_id") or ""
        if cmd == "/people":
            ok, waiting = [], []
            for c in self.store.wa_list_chats():
                line = (f"• {c.get('name') or ''} +{c['wa_id']}".replace("  ", " ")
                        + (" · owner" if c["wa_id"] == owner else "")
                        + (f"\n   {'let in' if c['allowed'] else 'blocked'} {decided(c)}" if c.get("decided_at") else ""))
                (ok if c["allowed"] else waiting).append(line)
            out = "▲ Can talk to me\n" + ("\n".join(ok) or "only you")
            if waiting:
                out += "\n\nWrote, not allowed\n" + "\n".join(waiting)
            return out + "\n\n/allow <number> lets somebody in. /block <number> stops them."
        num = "".join(ch for ch in arg.split(" ")[0] if ch.isdigit())
        if not num:
            return f"▲ Who? {cmd} <number>. /people lists them."
        said = await self.decide_newcomer(num, cmd == "/allow")
        return {"allowed": f"▲ +{num} can talk to me now. I've told them.",
                "blocked": f"▲ +{num} can no longer talk to me."}.get(said, f"▲ I can't: {said}.")

    def _conversation(self, chat: dict) -> str:
        cid = chat.get("conversation_id")
        if cid and any(c["id"] == cid for c in self.store.list_conversations(limit=500)):
            return cid
        from . import phonesessions
        cid = phonesessions.start(self.store, "whatsapp", chat["wa_id"],
                                  chat.get("name") or chat["wa_id"])
        self.store.wa_set_conversation(chat["wa_id"], cid)
        chat["conversation_id"] = cid
        return cid

    async def _turn(self, chat: dict, wa_id: str, text: str):
        cid = self._conversation(chat)
        # agents talking inside this turn come back as a comic strip after the reply,
        # as on Telegram (playground.listen; closed in `finally`)
        from . import playground as _pg
        tap = _pg.listen(cid)
        try:
            await self._turn_in(chat, wa_id, text, cid)
            await self.send_talk(list(tap), wa_id)
        finally:
            _pg.close(cid, tap)

    async def _turn_in(self, chat: dict, wa_id: str, text: str, cid: str):
        from . import history as _history
        from . import knowledge as _k
        from . import usage as _usage
        # The same rebuild as the desktop and Telegram: a thread answered from the
        # phone must see what the thread saw at the desk, tool traces included. A
        # bespoke window here is how one conversation ends up with two memories of
        # itself.
        # Saved and shown first; the rebuild (which may compact with a model call) only for
        # the built-in loop, which reads it. Telegram's reason, measured there.
        self.store.add_message(cid, "user", text)
        exec_meta: dict = {}          # the executor session a forwarded reply was given in
        await self.broadcast({"type": "whatsapp_in", "conversation_id": cid,
                              "text": text[:160]})
        note = ("[Message arriving via WhatsApp — the user is away from the "
                "machine. Reply in plain text (no markdown tables). Do the whole "
                "job before you reply; then say it in plain words a phone can show.]\n\n")

        async def emit(ev):
            # the turn is the screen's too (the Office, Chat), as Telegram's is
            if isinstance(ev, dict) and str(ev.get("name") or "").startswith("mcp__bento__"):
                return
            if isinstance(ev, dict) and ev.get("type"):
                with contextlib.suppress(Exception):
                    await self.broadcast({**ev, "conversation_id": cid, "surface": "whatsapp"})

        async def approver(name, args, reason, offer=None) -> bool:
            # full autonomy answers for you — except a step that must be a
            # person's (policy.needs_person): you are right here, so you are asked
            # The channel's own posture counts: "ask over WhatsApp" has to mean it.
            from .policy import effective_autonomy, needs_person
            if effective_autonomy(self.cfg, "whatsapp") == "full" and not needs_person():
                return True
            return await self.ask_approval(wa_id, name, args, reason, offer=offer)

        model = self.cfg.get("default_model") or ""
        from . import executors as execmod
        from . import fabric as fabricmod
        engine = execmod.resolve_engine(self.cfg)
        await emit({"type": "turn_start", "model": engine if engine != "aria" else model})
        try:
            return await self._turn_body(chat, wa_id, text, cid, emit, approver, note)
        finally:
            await emit({"type": "turn_end"})

    async def _turn_body(self, chat, wa_id, text, cid, emit, approver, note):
        # one function for both phones (phoneturn.py): who is addressed, which brain, and
        # the next brain when that one isn't available
        from . import phoneturn

        async def tell(line):
            await self.send("↪ " + line, wa_id)
        out = await phoneturn.answer(
            self.store, self.cfg, self.toolbox, cid=cid, text=text, surface="whatsapp",
            emit=emit, approver=approver, note=note, tell=tell)
        reply = out["reply"]
        self.store.add_message(cid, "assistant", reply, {"steps": out["steps"], **out["meta"]})
        self.store.touch_conversation(cid)
        await self.send(reply, wa_id)
        await self.send_files(reply, wa_id)
        await self.send_stage(cid, reply, wa_id)
        await self.broadcast({"type": "whatsapp_out", "conversation_id": cid,
                              "text": reply[:160]})
        from . import knowledge
        knowledge.schedule_extraction(self.cfg, self.store, cid, text, reply, self.broadcast)

    # -- approvals -----------------------------------------------------------

    async def ask_approval(self, wa_id: str, name: str, args: dict, reason: str,
                           offer: dict | None = None, timeout: float = 300) -> bool:
        """Three reply buttons and a wait. Same three answers as everywhere else:
        deny, allow once, allow and remember.

        "Always" is written as a USER grant, never a definition one — a definition
        grant would be revoked by the next save of whatever asked for it, which is
        precisely the permission somebody just said they wanted to keep.
        """
        import uuid
        aid = uuid.uuid4().hex[:8]
        # what it is for and the start of what it does (approvalcard): the Cloud API's
        # button body is 1024 characters, and slicing the whole text cut the reason off
        from . import approvalcard
        from .policy import said
        card = approvalcard.card(name, args, said())
        rows = [{"type": "reply", "reply": {"id": f"ap:{aid}:0", "title": _TITLES["deny"]}},
                {"type": "reply", "reply": {"id": f"ap:{aid}:1", "title": _TITLES["once"]}}]
        if offer:
            rows.append({"type": "reply",
                         "reply": {"id": f"ap:{aid}:2", "title": _TITLES["always"]}})
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[aid] = fut
        try:
            if self._c().get("mode") == "baileys":
                # No interactive buttons on a linked device. Numbered replies are
                # the fallback, and they are spelled out — an approval nobody can
                # see how to answer is a run that hangs until it times out.
                from . import wa_baileys
                opts = "1 to deny · 2 to allow once"
                if offer:
                    opts += " · 3 to allow and remember"
                sent = await self.link.send(
                    approvalcard.message(card, reason, limit=3500) + f"\n\nReply {opts}",
                    wa_id) if self.link else "[error] no link"
                if str(sent).startswith("[error]"):
                    raise RuntimeError(sent)
            else:
                await self._api(f"{self._c()['phone_number_id']}/messages", {
                    "messaging_product": "whatsapp", "to": wa_id, "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": approvalcard.message(card, reason, limit=1024)},
                        "action": {"buttons": rows}}})
        except Exception as e:
            self._pending.pop(aid, None)
            self.store.log("error", f"whatsapp: could not ask for approval: {e}")
            return False
        try:
            val = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            await self.send("⌛ Approval timed out — action not taken. The run continues "
                            "without it.", wa_id)
            return False
        finally:
            self._pending.pop(aid, None)
        if val == "2" and offer:
            from .policy import write_remembered
            write_remembered(self.store, offer, "always", via="a WhatsApp approval")
            self.store.log("policy",
                           f"grant remembered: {offer['action']} {offer['resource']}",
                           {"principal": f"{offer['principal_kind']}:{offer['principal_id']}",
                            "action": offer["action"], "resource": offer["resource"],
                            "effect": "allow", "via": "whatsapp_approval"})
            try:
                await self.broadcast({"type": "grants"})
            except Exception:
                pass
        return val in ("1", "2")

    def pending_button(self, value: str) -> str:
        """The button id a typed digit should resolve, or '' if nothing is waiting.

        Only meaningful for the linked-device transport, which has no real buttons.
        The newest unanswered approval wins: approvals are asked one at a time and
        answered immediately, so "the one I was just asked" is the only reading a
        person would expect.
        """
        for aid, fut in reversed(list(self._pending.items())):
            if not fut.done():
                return f"ap:{aid}:{value}"
        return ""

    def _answer(self, wa_id: str, button_id: str):
        """A tap on an approval button. Only the owner's taps count — anybody else
        with the number could otherwise answer a prompt that was not theirs."""
        if wa_id != (self._c().get("owner_wa_id") or ""):
            return
        if not button_id.startswith("ap:"):
            return
        _, aid, val = button_id.split(":", 2)
        fut = self._pending.get(aid)
        if fut and not fut.done():
            fut.set_result(val)

    # -- state ---------------------------------------------------------------

    # -- the linked-device transport -----------------------------------------

    async def start_link(self) -> str:
        """Start (or restart) the WhatsApp Web bridge. Returns '' or why not.

        Inbound is pointed straight at `_one`, the same entry point the Cloud API
        webhook uses, so everything downstream — pairing, the allow-list, commands,
        flow triggers, approvals, taint, the ledger — is one implementation.
        """
        from . import wa_baileys
        if mode(self.cfg) != "baileys":
            return "WhatsApp is not set to the linked-device transport"
        if self.link is None:
            self.link = wa_baileys.BaileysTransport(
                on_message=self._one, on_event=self.broadcast, store=self.store,
                pending_button=self.pending_button)
        return await self.link.start()

    async def stop_link(self):
        if self.link:
            await self.link.stop()

    async def unlink(self) -> str:
        """Unlink this device and forget who was paired.

        The owner is cleared too. Keeping it would mean the next person to scan
        inherits the previous owner's chat — an authorisation nobody granted.
        """
        from . import wa_baileys
        if self.link:
            await self.link.logout()
        else:
            wa_baileys.forget_session()
        c = self.cfg.setdefault("whatsapp", {})
        c["owner_wa_id"] = ""
        ch = (self.cfg.setdefault("channels", {}).setdefault("whatsapp", {}))
        ch["owner_wa_id"] = ""
        cfgmod.save_config(self.cfg)
        self.store.log("whatsapp", "unlinked — device credentials and owner cleared")
        await self.broadcast({"type": "whatsapp_chats"})
        return "unlinked"

    def info(self) -> dict:
        c = self._c()
        ok = configured(self.cfg)
        if not c.get("enabled"):
            self.status = "off"
        elif not ok:
            self.status = "needs"
        else:
            self.status = "ready"
        owner = c.get("owner_wa_id") or ""
        return {"enabled": bool(c.get("enabled")), "configured": ok,
                "status": self.status, "error": self.error,
                "has_token": bool(c.get("access_token")),
                "has_secret": bool(c.get("app_secret")),
                "phone_number_id": c.get("phone_number_id") or "",
                "display_number": c.get("display_number") or "",
                "owner_wa_id": owner,
                "window_open": self.window_open(owner) if owner else False,
                "window_hours": WINDOW_SECS // 3600,
                "webhook_path": webhook_path(),
                "mode": c.get("mode") or "cloud",
                # The linked-device half of the story. Present in both modes so a
                # surface can render one card that knows which transport it is
                # looking at, rather than two that disagree.
                "link": (self.link.info() if self.link else _link_info_idle()),
                "chats": self.store.wa_list_chats()}


def _link_info_idle() -> dict:
    """What the linked-device transport looks like before it has been started."""
    from . import wa_baileys
    return {"mode": "baileys", "installed": wa_baileys.installed(),
            "paired": wa_baileys.paired(), "state": "stopped", "qr": "",
            "qr_svg": "", "qr_ascii": "", "error": "", "me": "",
            "why": wa_baileys.why_not(), "window_open": False}

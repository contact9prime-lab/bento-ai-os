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
  It is verified with `hmac.compare_digest` before the body is even parsed, on the
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
import hashlib
import hmac
import json
import time

import httpx

from . import config as cfgmod
from .agent import Agent
from . import users as usersmod

GRAPH = "https://graph.facebook.com/v21.0"
CHUNK = 3900              # WhatsApp's body limit is 4096
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
    return hmac.compare_digest(want, got)


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
        self._exec_sessions: dict[str, str] = {}

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

    async def send(self, text: str, wa_id: str | None = None) -> str:
        """Deliver a message, or say in one sentence why WhatsApp would not carry it.

        The 24-hour refusal is spelled out rather than passed through as Meta's own
        error, because it is not a failure of this machine and it has a specific fix:
        the user says anything, and the window reopens for a day.
        """
        c = self._c()
        wa_id = wa_id or c.get("owner_wa_id") or ""
        if c.get("mode") == "baileys":
            if not self.link:
                return ("[error] the WhatsApp Web bridge is not running — pair it in "
                        "Settings → Channels → WhatsApp")
            if not wa_id:
                return ("[error] Not paired yet — message this WhatsApp from your "
                        "phone once, and that chat becomes the owner")
            return await self.link.send(text, wa_id)
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
        text = text or "(empty)"
        try:
            for i in range(0, len(text), CHUNK):
                await self._api(f"{c['phone_number_id']}/messages", {
                    "messaging_product": "whatsapp", "to": wa_id, "type": "text",
                    "text": {"preview_url": False, "body": text[i:i + CHUNK]}})
        except Exception as e:
            return f"[error] whatsapp send failed: {e}"
        self.store.log("whatsapp", f"→ sent: {text[:200]}")
        return "sent via WhatsApp"

    # -- inbound -------------------------------------------------------------

    def verify_challenge(self, mode: str, token: str, challenge: str) -> str | None:
        """Meta's one-time GET handshake. Returns the challenge to echo, or None."""
        want = (self._c().get("verify_token") or "").strip()
        if mode == "subscribe" and want and hmac.compare_digest(want, (token or "").strip()):
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

        name = self._profile_name(val, wa_id)
        chat = self.store.wa_upsert_chat(wa_id, name)
        self.store.log("whatsapp", f"← {name} ({wa_id}): {text[:160]}")

        c = self.cfg.setdefault("whatsapp", {})
        if not (self._c().get("owner_wa_id") or ""):
            c["owner_wa_id"] = wa_id
            cfgmod.save_config(self.cfg)
            self.store.wa_set_allowed(wa_id, 1)
            chat["allowed"] = 1
            agent = self.cfg.get("agent_name") or "Aria"
            self.store.log("whatsapp", f"paired: owner = {name} ({wa_id})")
            await self.send(f"▲ Linked. I'm {agent}, the agent on your machine — same "
                            f"memory and the same tools as at the desk. Send me "
                            f"anything; /clear starts a fresh session.", wa_id)
            await self.broadcast({"type": "whatsapp_chats"})
            return

        if not chat.get("allowed"):
            if (chat.get("msg_count") or 0) <= 1:
                await self.send("▲ This number reached an AgentOS machine, but it is not "
                                "enabled. Its owner can allow it in Settings → Channels.",
                                wa_id)
            await self.broadcast({"type": "whatsapp_chats"})
            return
        await self.broadcast({"type": "whatsapp_chats"})

        low = text.lower()
        if low.startswith("/clear"):
            self.store.clear_messages(self._conversation(chat))
            await self.send("🧹 Session cleared — starting fresh.", wa_id)
            return
        if low.startswith("/status"):
            await self.send(f"▲ online · model {self.cfg.get('default_model') or '(none)'} "
                            f"· autonomy {self.cfg.get('autonomy')}", wa_id)
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
        try:
            await self._turn(chat, wa_id, text)
        except Exception as e:
            await self.send(f"[error] {type(e).__name__}: {e}", wa_id)
        finally:
            self._busy = False

    def _conversation(self, chat: dict) -> str:
        cid = chat.get("conversation_id")
        if cid and any(c["id"] == cid for c in self.store.list_conversations(limit=500)):
            return cid
        cid = self.store.create_conversation(f"WhatsApp · {chat.get('name') or chat['wa_id']}")
        self.store.wa_set_conversation(chat["wa_id"], cid)
        return cid

    async def _turn(self, chat: dict, wa_id: str, text: str):
        from . import history as _history
        from . import knowledge as _k
        from . import usage as _usage

        cid = self._conversation(chat)
        # The same rebuild as the desktop and Telegram: a thread answered from the
        # phone must see what the thread saw at the desk, tool traces included. A
        # bespoke window here is how one conversation ends up with two memories of
        # itself.
        history, _info = await _history.build(self.store, cid, self.cfg,
                                              self.cfg.get("default_model", ""))
        self.store.add_message(cid, "user", text)
        await self.broadcast({"type": "whatsapp_in", "conversation_id": cid,
                              "text": text[:160]})
        history.append({"role": "user", "content":
                        "[Message arriving via WhatsApp — the user is away from the "
                        "machine. Reply in plain text (no markdown tables). Keep it "
                        "short enough to read on a phone.]\n\n" + text})

        async def emit(_ev):
            pass

        async def approver(name, args, reason, offer=None) -> bool:
            if self.cfg.get("autonomy") == "full":
                return True
            return await self.ask_approval(wa_id, name, args, reason, offer=offer)

        model = self.cfg.get("default_model") or ""
        from . import executors as execmod
        engine = execmod.resolve_engine(self.cfg)
        if engine != "aria":
            _k.turn_started()
            try:
                reply, run = await execmod.forward(
                    engine, text, self.cfg, str(cfgmod.AGENTOS_HOME / "workspace"),
                    session_id=self._exec_sessions.get(cid, ""))
                if run and run.session_id:
                    self._exec_sessions[cid] = run.session_id
            finally:
                _k.turn_ended()
            reply = reply or "(done — no text output)"
            result = {"steps": [{"type": "executor", "name": engine}]}
        else:
            agent = Agent(self.cfg, self.toolbox, model, emit, approver,
                          conversation_id=cid, surface="whatsapp")
            _k.turn_started()
            try:
                result = await agent.run(history)
            finally:
                _k.turn_ended()
            reply = result["content"] or "(done — no text output)"

        self.store.add_message(cid, "assistant", reply, {"steps": result["steps"]})
        self.store.touch_conversation(cid)
        _usage.record(self.store, self.cfg, model, result.get("tokens") or {},
                      surface="whatsapp", conversation_id=cid)
        await self.send(reply, wa_id)
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
        detail = args.get("command", "") if name == "run_command" else json.dumps(args)[:200]
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
                    f"⚠ Approval needed\n\n{name}  {detail}\n\n{reason}\n\n"
                    f"Reply {opts}", wa_id) if self.link else "[error] no link"
                if str(sent).startswith("[error]"):
                    raise RuntimeError(sent)
            else:
                await self._api(f"{self._c()['phone_number_id']}/messages", {
                    "messaging_product": "whatsapp", "to": wa_id, "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": f"⚠ Approval needed\n\n{name}  {detail}\n\n{reason}"[:1024]},
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
            self.store.add_grant(offer["principal_kind"], offer["principal_id"],
                                 offer["action"], offer["resource"], source="user",
                                 note="allowed & remembered from a WhatsApp approval")
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

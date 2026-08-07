"""Telegram bridge: chat with your AgentOS from anywhere via a bot from @BotFather.

Setup: message @BotFather on Telegram → /newbot → paste the token into the
Telegram app in the UI. The first person to /start the bot becomes its owner;
everyone else is ignored.

Commands: /start pairs, /clear wipes the Telegram session, /status pings.
"""

import asyncio
import json
import time

import httpx

from . import config as cfgmod
from .agent import Agent

API = "https://api.telegram.org/bot{token}/{method}"
CHUNK = 3900  # Telegram hard limit is 4096


class TelegramBridge:
    def __init__(self, cfg: dict, store, toolbox, broadcast):
        self.cfg = cfg
        self.store = store
        self.toolbox = toolbox
        self.broadcast = broadcast
        self._stop = asyncio.Event()
        self._offset = 0
        self.status = "off"          # off | polling | error
        self.error = ""
        self.bot_username = ""
        self._busy = False
        self._pending: dict[str, asyncio.Future] = {}   # approval id -> future
        # When forwarding, keep the executor's own session per conversation so a
        # follow-up over Telegram continues rather than starting from nothing.
        self._exec_sessions: dict[str, str] = {}

    def _t(self) -> dict:
        return self.cfg.get("telegram") or {}

    async def _api(self, method: str, **params):
        token = self._t().get("bot_token", "")
        async with httpx.AsyncClient(timeout=70) as client:
            r = await client.post(API.format(token=token, method=method), json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        return data["result"]

    async def send(self, text: str, chat_id: int | None = None) -> str:
        chat_id = chat_id or self._t().get("owner_chat_id")
        if not self._t().get("bot_token"):
            return "[error] No bot token set — add one in the Telegram app (from @BotFather)"
        if not chat_id:
            bot = ("@" + self.bot_username) if self.bot_username else "your bot"
            return f"[error] Not paired yet — send any message to {bot} on Telegram first"
        text = text or "(empty)"
        try:
            for i in range(0, len(text), CHUNK):
                await self._api("sendMessage", chat_id=chat_id, text=text[i:i + CHUNK])
        except Exception as e:
            return f"[error] telegram send failed: {e}"
        self.store.log("telegram", f"→ sent: {text[:200]}")
        return "sent via Telegram"

    def _conversation(self, chat: dict) -> str:
        """One persistent conversation per Telegram chat."""
        cid = chat.get("conversation_id")
        if cid and any(c["id"] == cid for c in self.store.list_conversations(limit=500)):
            return cid
        cid = self.store.create_conversation(f"Telegram · {chat.get('title') or chat['chat_id']}")
        self.store.tg_set_conversation(chat["chat_id"], cid)
        return cid

    async def _handle(self, msg: dict):
        chat_info = msg.get("chat", {})
        chat_id = chat_info.get("id")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return
        frm = msg.get("from", {})
        title = (chat_info.get("title")
                 or " ".join(filter(None, [frm.get("first_name", ""), frm.get("last_name", "")])).strip()
                 or str(chat_id))
        username = chat_info.get("username") or frm.get("username") or ""
        ctype = chat_info.get("type", "private")
        chat = self.store.tg_upsert_chat(chat_id, title, username, ctype)
        self.store.log("telegram", f"← {title} ({chat_id}): {text[:160]}")

        t = self._t()
        # first private chat to say anything becomes the owner
        if not (t.get("owner_chat_id") or 0) and ctype == "private":
            t["owner_chat_id"] = chat_id
            cfgmod.save_config(self.cfg)
            self.store.tg_set_allowed(chat_id, 1)
            chat["allowed"] = 1
            name = self.cfg.get("agent_name") or "Aria"
            self.store.log("telegram", f"paired: owner = {title} ({chat_id})")
            await self.send(f"▲ Linked! Hi {frm.get('first_name', 'there')} — I'm {name}, "
                            f"the agent on your machine. This chat is now the owner. "
                            f"Send me anything; /clear resets our session.", chat_id)
            if text.startswith("/start"):
                return  # welcome is enough for /start

        if not chat["allowed"]:
            if chat["msg_count"] <= 1:
                await self.send("▲ This chat is registered with AgentOS but not enabled yet. "
                                "The owner can enable it in the Telegram app on the desktop.", chat_id)
            await self.broadcast({"type": "telegram_chats"})
            return
        await self.broadcast({"type": "telegram_chats"})

        if text.startswith("/start"):
            await self.send("▲ Already linked. Send me anything; /clear resets the session.", chat_id)
            return
        if text.startswith("/clear"):
            cid = self._conversation(chat)
            self.store.clear_messages(cid)
            self.store.log("telegram", f"session cleared for {title}")
            await self.send("🧹 Session cleared — starting fresh.", chat_id)
            return
        if text.startswith("/status"):
            await self.send(f"▲ online · model {self.cfg.get('default_model') or '(none)'} · "
                            f"autonomy {self.cfg.get('autonomy')}", chat_id)
            return

        # A message trigger starts a flow. Checked before the busy lock on purpose: a flow
        # runs in its own task with its own orchestrator, so it is not the conversation
        # this chat is holding, and making it queue behind one would mean "the alert I set
        # up did not fire because I was mid-sentence".
        try:
            from . import flows as flowsmod
            hit = flowsmod.match_message(self.store, text, surface="telegram") \
                if self.toolbox.fabric else None
        except Exception:
            hit = None
        if hit:
            trig, flow = hit
            asyncio.create_task(self.toolbox.fabric.run_flow(
                flow, text, origin={"surface": "telegram", "chat_id": chat_id,
                                    "ref": trig["id"]},
                conversation_id=self._conversation(chat), trigger_id=trig["id"]))
            await self.send(f"▶ {flow['name']} started — I'll report back here.", chat_id)
            return

        if self._busy:
            await self.send("⏳ Still working on your previous message…", chat_id)
            return
        self._busy = True
        try:
            await self._api("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass
        try:
            cid = self._conversation(chat)
            # The same rebuild as the desktop: a thread answered from the phone
            # must see what the thread saw at the desk, tool traces included. A
            # bespoke last-30 window here is how one conversation ends up with
            # two different memories of itself.
            from . import history as _history
            history, _hinfo = await _history.build(
                self.store, cid, self.cfg, self.cfg.get("default_model", ""))
            self.store.add_message(cid, "user", text)
            await self.broadcast({"type": "telegram_in", "conversation_id": cid, "text": text[:160]})
            history.append({"role": "user", "content":
                            "[Message arriving via Telegram — the user is away from the machine. "
                            "Reply in plain text (no markdown tables). No one can click approval "
                            "dialogs, so risky actions only run in full autonomy.]\n\n" + text})

            async def emit(_ev):
                pass

            async def approver(name, args, reason, offer=None) -> bool:
                if self.cfg.get("autonomy") == "full":
                    return True
                return await self.ask_approval(chat_id, name, args, reason, offer=offer)

            model = self.cfg.get("default_model") or ""
            from . import fabric as fabricmod
            from . import knowledge as _k
            mention = fabricmod.parse_mention(self.store, text) if self.toolbox.fabric else None
            if mention:  # '@researcher …' from the phone goes straight to that subagent
                defn, task = mention
                res = await self.toolbox.fabric.run_subagent(defn, task, conversation_id=cid,
                                                             approver=approver)
                reply = (f"@{defn['name']} · {res['status']}\n\n"
                         + (res["content"] or res["fault"] or "(no output)"))
                result = {"steps": res["steps"]}
            else:
                from . import executors as execmod
                engine = execmod.resolve_engine(self.cfg)
                if engine != "aria":
                    # A machine set to forward forwards what arrives from OUTSIDE
                    # too — a Telegram message is exactly the case the setting is
                    # for. There is no event stream here, so take the text back.
                    from . import config as _cfgmod
                    _k.turn_started()
                    try:
                        reply, _run = await execmod.forward(
                            engine, text, self.cfg,
                            str(_cfgmod.AGENTOS_HOME / "workspace"),
                            session_id=self._exec_sessions.get(cid, ""))
                        if _run and _run.session_id:
                            self._exec_sessions[cid] = _run.session_id
                    finally:
                        _k.turn_ended()
                    reply = reply or "(done — no text output)"
                    result = {"steps": [{"type": "executor", "name": engine}]}
                else:
                    agent = Agent(self.cfg, self.toolbox, model, emit, approver,
                                  conversation_id=cid, surface="telegram")
                    _k.turn_started()
                    try:
                        result = await agent.run(history)
                    finally:
                        _k.turn_ended()
                    reply = result["content"] or "(done — no text output)"
            self.store.add_message(cid, "assistant", reply, {"steps": result["steps"]})
            self.store.touch_conversation(cid)
            from . import usage as _usage
            _usage.record(self.store, self.cfg, model, result.get("tokens") or {},
                          surface="telegram", conversation_id=cid)
            await self.send(reply, chat_id)
            await self.broadcast({"type": "telegram_out", "conversation_id": cid, "text": reply[:160]})
            from . import knowledge
            knowledge.schedule_extraction(self.cfg, self.store, cid, text, reply, self.broadcast)
        except Exception as e:
            await self.send(f"[error] {type(e).__name__}: {e}", chat_id)
        finally:
            self._busy = False

    async def _ask_approval(self, chat_id: int, name: str, args: dict, reason: str) -> bool:
        return await self.ask_approval(chat_id, name, args, reason)

    async def ask_approval(self, chat_id: int, name: str, args: dict, reason: str,
                           offer: dict | None = None, timeout: float = 300) -> bool:
        """Send an inline keyboard and wait for the user's tap.

        Three buttons rather than two when the decision carries a grant offer: an
        unattended flow that has to be re-approved every night is one somebody will
        eventually put on full autonomy to make it stop asking, which is worse than the
        grant they actually meant. "Always" is written as a USER grant — never a
        definition one, or the next save of that flow would silently revoke it.
        """
        import uuid
        aid = uuid.uuid4().hex[:8]
        detail = args.get("command", "") if name == "run_command" else json.dumps(args)[:300]
        text = f"⚠ Approval needed\n\n{name}  {detail}\n\n{reason}"
        row = [{"text": "✅ Allow once", "callback_data": f"ap:{aid}:1"},
               {"text": "⛔ Deny", "callback_data": f"ap:{aid}:0"}]
        if offer:
            row.insert(1, {"text": "♾ Always", "callback_data": f"ap:{aid}:2"})
        fut = asyncio.get_event_loop().create_future()
        self._pending[aid] = fut
        try:
            await self._api("sendMessage", chat_id=chat_id, text=text,
                            reply_markup={"inline_keyboard": [row]})
        except Exception:
            self._pending.pop(aid, None)
            return False
        try:
            val = await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            await self.send("⌛ Approval timed out — action not taken. The run continues "
                            "without it.", chat_id)
            return False
        finally:
            self._pending.pop(aid, None)
        if val == "2" and offer:
            self.store.add_grant(offer["principal_kind"], offer["principal_id"],
                                 offer["action"], offer["resource"], source="user",
                                 note="allowed & remembered from a Telegram approval")
            self.store.log("policy", f"grant remembered: {offer['action']} {offer['resource']}",
                           {"principal": f"{offer['principal_kind']}:{offer['principal_id']}",
                            "action": offer["action"], "resource": offer["resource"],
                            "effect": "allow", "via": "telegram_approval"})
            try:
                await self.broadcast({"type": "grants"})
            except Exception:
                pass
        return val in ("1", "2")

    async def _handle_callback(self, cq: dict):
        if cq.get("from", {}).get("id") != (self._t().get("owner_chat_id") or 0):
            return
        data = cq.get("data", "")
        try:
            await self._api("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception:
            pass
        if not data.startswith("ap:"):
            return
        _, aid, val = data.split(":", 2)
        fut = self._pending.get(aid)
        if fut and not fut.done():
            fut.set_result(val)          # "0" deny | "1" allow once | "2" always
        # reflect the decision on the message
        msg = cq.get("message", {})
        if msg:
            said = {"1": "✅ Allowed", "2": "♾ Allowed & remembered"}.get(val, "⛔ Denied")
            try:
                await self._api("editMessageText", chat_id=msg["chat"]["id"],
                                message_id=msg["message_id"],
                                text=(msg.get("text", "") + f"\n\n{said}"))
            except Exception:
                pass

    async def run_forever(self):
        while not self._stop.is_set():
            t = self._t()
            if not (t.get("enabled") and t.get("bot_token")):
                self.status = "off"
                await self._sleep(5)
                continue
            try:
                if not self.bot_username:
                    me = await self._api("getMe")
                    self.bot_username = me.get("username", "")
                    try:
                        # a leftover webhook blocks getUpdates polling — clear it
                        await self._api("deleteWebhook")
                    except Exception:
                        pass
                    self.store.log("telegram", f"polling as @{self.bot_username}")
                self.status = "polling"
                self.error = ""
                updates = await self._api("getUpdates", offset=self._offset, timeout=50,
                                          allowed_updates=["message", "channel_post",
                                                           "callback_query"])
                for u in updates:
                    self._offset = max(self._offset, u["update_id"] + 1)
                    if "message" in u:
                        asyncio.create_task(self._handle(u["message"]))
                    elif "channel_post" in u:
                        # channels the bot was added to register like chats/groups: they
                        # appear in the Telegram app, blocked until the owner permits them
                        asyncio.create_task(self._handle(u["channel_post"]))
                    elif "callback_query" in u:
                        asyncio.create_task(self._handle_callback(u["callback_query"]))
            except Exception as e:
                self.status = "error"
                self.error = str(e)[:300]
                self.bot_username = ""
                self.store.log("error", f"telegram: {self.error}")
                await self._sleep(10)

    async def _sleep(self, secs: float):
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=secs)
        except asyncio.TimeoutError:
            pass

    def stop(self):
        self._stop.set()

    def info(self) -> dict:
        t = self._t()
        return {"enabled": bool(t.get("enabled")), "has_token": bool(t.get("bot_token")),
                "owner_chat_id": t.get("owner_chat_id") or 0,
                "status": self.status, "error": self.error, "bot_username": self.bot_username,
                "chats": self.store.tg_list_chats()}

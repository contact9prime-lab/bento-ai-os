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
            history = [{"role": m["role"], "content": m["content"]}
                       for m in self.store.get_messages(cid)
                       if m["role"] in ("user", "assistant") and (m["content"] or "").strip()][-30:]
            self.store.add_message(cid, "user", text)
            await self.broadcast({"type": "telegram_in", "conversation_id": cid, "text": text[:160]})
            history.append({"role": "user", "content":
                            "[Message arriving via Telegram — the user is away from the machine. "
                            "Reply in plain text (no markdown tables). No one can click approval "
                            "dialogs, so risky actions only run in full autonomy.]\n\n" + text})

            async def emit(_ev):
                pass

            async def approver(name, args, reason, offer=None) -> bool:
                # offer (grant-&-remember) is a web-UI affordance; Telegram answers yes/no
                if self.cfg.get("autonomy") == "full":
                    return True
                return await self._ask_approval(chat_id, name, args, reason)

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
                agent = Agent(self.cfg, self.toolbox, model, emit, approver, conversation_id=cid)
                _k.turn_started()
                try:
                    result = await agent.run(history)
                finally:
                    _k.turn_ended()
                reply = result["content"] or "(done — no text output)"
            self.store.add_message(cid, "assistant", reply, {"steps": result["steps"]})
            self.store.touch_conversation(cid)
            await self.send(reply, chat_id)
            await self.broadcast({"type": "telegram_out", "conversation_id": cid, "text": reply[:160]})
            from . import knowledge
            knowledge.schedule_extraction(self.cfg, self.store, cid, text, reply, self.broadcast)
        except Exception as e:
            await self.send(f"[error] {type(e).__name__}: {e}", chat_id)
        finally:
            self._busy = False

    async def _ask_approval(self, chat_id: int, name: str, args: dict, reason: str) -> bool:
        """Send an inline Allow/Deny keyboard and wait for the user's tap."""
        import uuid
        aid = uuid.uuid4().hex[:8]
        detail = args.get("command", "") if name == "run_command" else json.dumps(args)[:300]
        text = f"⚠ Approval needed\n\n{name}  {detail}\n\n{reason}"
        kb = {"inline_keyboard": [[{"text": "✅ Allow", "callback_data": f"ap:{aid}:1"},
                                   {"text": "⛔ Deny", "callback_data": f"ap:{aid}:0"}]]}
        fut = asyncio.get_event_loop().create_future()
        self._pending[aid] = fut
        try:
            await self._api("sendMessage", chat_id=chat_id, text=text, reply_markup=kb)
        except Exception:
            self._pending.pop(aid, None)
            return False
        try:
            return await asyncio.wait_for(fut, timeout=300)
        except asyncio.TimeoutError:
            await self.send("⌛ Approval timed out — action not taken.", chat_id)
            return False
        finally:
            self._pending.pop(aid, None)

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
            fut.set_result(val == "1")
        # reflect the decision on the message
        msg = cq.get("message", {})
        if msg:
            try:
                await self._api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                text=(msg.get("text", "") + f"\n\n{'✅ Allowed' if val=='1' else '⛔ Denied'}"))
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
                                          allowed_updates=["message", "callback_query"])
                for u in updates:
                    self._offset = max(self._offset, u["update_id"] + 1)
                    if "message" in u:
                        asyncio.create_task(self._handle(u["message"]))
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

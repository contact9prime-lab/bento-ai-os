"""Telegram bridge: chat with your AgentOS from anywhere via a bot from @BotFather.

Setup: message @BotFather on Telegram → /newbot → paste the token into the
Telegram app in the UI. The first person to /start the bot becomes its owner;
everyone else is ignored.

Commands: /start pairs, /clear wipes the Telegram session, /status pings.
"""

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

import httpx

from . import channels as chanmod
from . import config as cfgmod
from . import telegram_admin
from .agent import Agent
from . import users as usersmod

API = "https://api.telegram.org/bot{token}/{method}"


def api_url(token: str, method: str) -> str:
    """Telegram's Bot API — or, with AGENTOS_TELEGRAM_API=http://127.0.0.1:8429, a
    stand-in at that address with the same paths, so a whole Telegram turn (the reply,
    the comic strip, /office) can be walked through without a real bot. The same idea
    as AGENTOS_SIGNIN_BASE for the sign-in doors."""
    base = os.environ.get("AGENTOS_TELEGRAM_API", "").rstrip("/")
    return f"{base}/bot{token}/{method}" if base else API.format(token=token, method=method)


def office_name(cfg: dict) -> str:
    from . import office
    return office.current(cfg)["name"]
CHUNK = 3900  # Telegram hard limit is 4096
TG_FILE_LIMIT = 50 * 1024 * 1024  # what the Bot API lets a bot upload


class TelegramBridge(usersmod.Scoped):
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
        self._busy = False             # kept for callers that read it: any chat working
        # Per chat, so two people (or two chats) work at once; and within a chat, what is
        # said while it works reaches the running turn or waits for the next one.
        self._busy_chats: set = set()
        self._runs: dict = {}
        self._waiting: dict = {}
        self._pending: dict[str, asyncio.Future] = {}   # approval id -> future
        # Operating the machine from the phone — owner-only, and every command
        # that DOES something goes through the same PDP the desktop uses.
        self._console = telegram_admin.Console(self)

    def _t(self) -> dict:
        return self.cfg.get("telegram") or {}

    async def _api(self, method: str, **params):
        token = self._t().get("bot_token", "")
        async with httpx.AsyncClient(timeout=70) as client:
            r = await client.post(api_url(token, method), json=params)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        return data["result"]

    # -- going down and coming back ------------------------------------------------
    # Asked for as "when the agent is coming up or going down, that message needs to be
    # sent". A clean stop says goodbye (the server's shutdown calls say_down); a start says
    # hello once per process, with the version and, if the last stop was not clean (a
    # crash, the power), when it was last seen. The record is a small file in the person's
    # own home, refreshed while polling.
    ALIVE_EVERY = 60

    def _alive_path(self):
        from pathlib import Path
        return Path(getattr(self.store, "path", "") or ".").parent / ".telegram-alive.json"

    def _alive(self) -> dict:
        import json as _j
        try:
            return _j.loads(self._alive_path().read_text())
        except Exception:
            return {}

    def _alive_write(self, **kw) -> None:
        import json as _j
        try:
            self._alive_path().write_text(_j.dumps({**self._alive(), **kw}))
        except Exception:
            pass

    def _says_status(self) -> bool:
        t = self._t()
        return bool(t.get("enabled") and t.get("bot_token") and t.get("owner_chat_id")
                    and t.get("status_messages", True) is not False)

    async def say_up(self) -> None:
        """Once per process, on the first successful poll."""
        if getattr(self, "_said_up", False):
            return
        self._said_up = True
        try:
            from . import updates
            version = updates.current()
        except Exception:
            version = ""
        before = self._alive()
        self._alive_write(up_at=time.time(), seen=time.time(), version=version, clean=False)
        if not self._says_status():
            return
        name = self.cfg.get("agent_name") or "Bento"
        msg = f"▲ {name} is back online"
        if before.get("version") and version and before["version"] != version:
            msg += f", updated {before['version']} → {version}"
        elif version:
            msg += f" (Bento {version})"
        msg += "."
        if before and before.get("clean") is False and before.get("seen"):
            msg += (" I wasn't shut down cleanly: I was last seen at "
                    + time.strftime("%H:%M on %d %b", time.localtime(before["seen"])) + ".")
        with contextlib.suppress(Exception):
            await self.send(msg)

    async def say_down(self, reason: str = "") -> None:
        """From the server's shutdown, before the poller stops."""
        if not getattr(self, "_said_up", False):
            return                        # it never came up in this process: nothing to say
        self._alive_write(seen=time.time(), clean=True)
        if not self._says_status():
            return
        name = self.cfg.get("agent_name") or "Bento"
        with contextlib.suppress(Exception):
            await self.send(f"▼ {name} is going offline{(' ' + reason) if reason else ''}. "
                            f"I'll message you when I'm back.")

    async def publish_commands(self) -> None:
        """Register the command menu with Telegram (the blue Menu button and the
        `/` autocomplete).

        Done here rather than asked of the user in BotFather: a menu typed by hand
        is a copy that goes stale the first time a command is added, and "why does
        my bot not show the menu" is a support question nobody should have.

        Scoped in two: the console for the owner's chat, the conversational three
        for the default scope. Offering `/logs` to somebody who will be refused it
        is a worse experience than not offering it.
        """
        if not self._t().get("bot_token"):
            return
        try:
            await self._api("setMyCommands", commands=telegram_admin.menu(False),
                            scope={"type": "default"})
            owner = self._t().get("owner_chat_id") or 0
            if owner:
                await self._api("setMyCommands", commands=telegram_admin.menu(True),
                                scope={"type": "chat", "chat_id": owner})
        except Exception as e:
            # Never fatal: the commands all still work by typing them. A bot that
            # refused to poll because a cosmetic menu failed would be worse.
            self.store.log("telegram", f"could not publish the command menu: {e}")

    async def send(self, text: str, chat_id: int | None = None) -> str:
        chat_id = chat_id or self._t().get("owner_chat_id")
        if not self._t().get("bot_token"):
            return "[error] No bot token set — add one in the Telegram app (from @BotFather)"
        if not chat_id:
            bot = ("@" + self.bot_username) if self.bot_username else "your bot"
            return f"[error] Not paired yet — send any message to {bot} on Telegram first"
        text = text or "(empty)"
        from . import tgformat
        try:
            # The agent writes markdown; Telegram shows a small HTML set. A piece Telegram
            # cannot parse goes again as the plain text it was, never lost.
            for piece in tgformat.chunks(text, CHUNK - 900):
                try:
                    await self._api("sendMessage", chat_id=chat_id, text=tgformat.to_html(piece),
                                    parse_mode="HTML", link_preview_options={"is_disabled": True})
                except RuntimeError as e:
                    if "parse" not in str(e).lower() and "entit" not in str(e).lower():
                        raise
                    await self._api("sendMessage", chat_id=chat_id, text=piece)
        except Exception as e:
            return f"[error] telegram send failed: {e}"
        self.store.log("telegram", f"→ sent: {text[:200]}")
        return "sent via Telegram"

    async def send_photo(self, png: bytes, caption: str = "", chat_id: int | None = None) -> str:
        """A picture into the chat — the playground's comic strips and roll call
        (agentos/comic.py). The caption carries every word the picture could not."""
        chat_id = chat_id or self._t().get("owner_chat_id")
        token = self._t().get("bot_token", "")
        if not token or not chat_id:
            return "[error] Telegram is not set up"
        try:
            async with httpx.AsyncClient(timeout=70) as client:
                r = await client.post(api_url(token, "sendPhoto"),
                                      data={"chat_id": str(chat_id), "caption": (caption or "")[:1024]},
                                      files={"photo": ("office.png", png, "image/png")})
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        except Exception as e:
            return f"[error] telegram photo failed: {e}"
        self.store.log("telegram", f"→ sent a picture: {(caption or '')[:120]}")
        return "sent via Telegram"

    async def send_document(self, path: str, caption: str = "", chat_id: int | None = None) -> str:
        """A file into the chat as a document (a deck, a report). Bots may send up to
        50 MB; past that the chat is told where the file is instead."""
        chat_id = chat_id or self._t().get("owner_chat_id")
        token = self._t().get("bot_token", "")
        if not token or not chat_id:
            return "[error] Telegram is not set up"
        p = Path(path)
        size = p.stat().st_size
        if size > TG_FILE_LIMIT:
            from .outputs import size_words
            await self.send(f"📎 {p.name} is {size_words(size)}, more than Telegram lets a bot "
                            f"send. It's on the machine at {p}", chat_id)
            return "too big"
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                with p.open("rb") as fh:
                    r = await client.post(api_url(token, "sendDocument"),
                                          data={"chat_id": str(chat_id), "caption": (caption or "")[:1024]},
                                          files={"document": (p.name, fh)})
            data = r.json()
            if not data.get("ok"):
                raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        except Exception as e:
            return f"[error] telegram file failed: {e}"
        self.store.log("telegram", f"→ sent a file: {p.name}")
        return "sent via Telegram"

    async def send_files(self, reply: str, chat_id: int) -> None:
        """The files a reply names, sent after it, so "the deck is ready" arrives with the
        deck. Only files in this person's folders (outputs.roots); switched off with
        telegram.files = false. Never fatal: the reply has already been sent."""
        if self._t().get("files") is False:
            return
        try:
            from . import outputs, users as _u
            files = outputs.mentioned(reply, outputs.roots(self.cfg, admin=_u.is_admin(_u.current())))
            for f in files:
                res = await self.send_document(f["path"], f["name"], chat_id)
                if res.startswith("[error]"):
                    await self.send(f"📎 I couldn't send {f['name']} ({res[8:]}). "
                                    f"It's on the machine at {f['path']}", chat_id)
        except Exception as e:
            self.store.log("telegram", f"could not send the reply's files: {e}")

    async def send_blueprint_docs(self, rows: list, ans: str, chat_id) -> None:
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
                    await self.send_document(str(p), "⤓ The blueprint as drawing sheets, to keep or print.", chat_id)
            except Exception as e:
                self.store.log("telegram", f"could not send the blueprint document: {e}")

    async def send_stage(self, cid: str, reply: str, chat_id: int, ans: str = "") -> str:
        """The answer's story, when it showed one (stage.py), as pictures in the chat.

        Reported as "the stage experience in Telegram is really bad": it was one .html file
        to download and open elsewhere, and a phone's viewer that runs no script showed no
        scene at all. Now each scene is photographed (stagestill.py, the Stage's own drawing)
        and sent as an album with its title, caption and source under each picture; a video
        scene follows as its YouTube link, which Telegram plays in place. With no browser on
        this machine to draw them, the page goes as before. Never fatal."""
        try:
            from . import stage as stagemod, stagestill, executors as _ex
            ans = ans or stagemod.last_question(self.store, cid)   # one named story (sent from the desktop), else the last
            scenes = [s["scene"] for s in stagemod.story(self.store, cid, ans)] if ans else []
            if not scenes:
                return ""
            agent = self.cfg.get("agent_name") or ""
            # a blueprint fills itself in after the reply (bpfill.py): a phone gets its pictures,
            # so wait a while for the parts to land rather than photograph the outline
            from . import bpfill
            rows = stagemod.story(self.store, cid, ans)
            await self._settle_with_word(rows, chat_id)
            scenes = [r["scene"] for r in stagemod.story(self.store, cid, ans)]
            pngs = await stagestill.render(
                stagemod.report_html(self.store, cid, ans, agent=agent, still=True), self.cfg)
            # a blueprint is several pictures (its drawing, parts, how it works, each part opened)
            items = stagemod.still_items(scenes)
            if len(pngs) == len(items):
                caps = [stagemod.still_caption_for(sc, v, i, len(items)) for i, (sc, v) in enumerate(items)]
                q = stagemod.question_of(self.store, ans)
                if q:
                    caps[0] = (f"▶ {q}\n\n" + caps[0])[:1024]   # what the story answers, on top
                res = await self.send_album(pngs, caps, chat_id)
                if not res.startswith("[error]"):
                    for sc in scenes:
                        if sc.get("kind") == "video" and sc.get("video"):
                            await self._api("sendMessage", chat_id=chat_id,
                                            text=f"▶ {sc.get('title') or 'Video'}\n"
                                                 f"https://www.youtube.com/watch?v={sc['video']}"
                                                 + (f"&t={int(sc['start'])}" if sc.get("start") else ""))
                    await self.send_clips(scenes, chat_id, items, pngs)
                    await self.send_narration(scenes, chat_id)
                    await self.send_blueprint_docs(rows, ans, chat_id)
                    return "sent"
                self.store.log("telegram", f"could not send the story as pictures: {res}")
            p = stagemod.write_report(self.store, _ex.default_workspace(self.cfg), cid, ans,
                                      answer=reply, agent=agent)
            if p:
                n = len(scenes)
                res = await self.send_document(str(p), f"▶ The story, {n} scene{'s' if n != 1 else ''}. "
                                                       f"Open it in your browser to watch.", chat_id)
                if res.startswith("[error]"):
                    self.store.log("telegram", f"could not send the story: {res}")
                    return str(res)
                return "sent"
            return "[error] the story could not be drawn or written on this machine"
        except Exception as e:
            self.store.log("telegram", f"could not send the story: {e}")
            return f"[error] {e}"

    async def _settle_with_word(self, rows: list, chat_id: int) -> None:
        """Wait for a blueprint to fill in, saying so on the phone. Reported as "it shows the
        stage on the desktop but not on Telegram": the desktop drew the outline at once, while
        the phone heard nothing, not even the reply, for the three minutes the parts took to
        look up. So one line goes at once, and the chat shows "sending a photo" while it waits."""
        from . import bpfill
        ids = [r["id"] for r in rows]
        if not bpfill.filling(ids):
            return
        await self.send(bpfill.HOLD_LINE_FIRST, chat_id)
        wait = asyncio.ensure_future(bpfill.settle(ids, bpfill.PHONE_WAIT_S))
        while not wait.done():
            with contextlib.suppress(Exception):
                await self._api("sendChatAction", chat_id=chat_id, action="upload_photo")
            await asyncio.wait([wait], timeout=4.5)   # Telegram's indicator lasts five seconds

    async def send_clips(self, scenes: list, chat_id: int, items: list | None = None,
                         pngs: list | None = None) -> int:
        """What is built in 3D goes as a video with sound, after the pictures (stageclip.py): the
        plan inked, the thing raised and brought to life, a turn round its named things with
        their notes, and the story read over it when this machine has a voice. Asked for as "it
        should not just send a diagram … a working feed with audio". A blueprint with no 3D form
        (a process) is walked through picture by picture instead: reported as "the blueprint is
        just coming as a PDF", when a blueprint that came without a model got no video at all.
        A clip is made in real time, so the chat shows "sending a video" meanwhile and a story
        gets `stageclip.CLIPS` at most. `/clips off` is `telegram.clips: false`. Never fatal:
        the pictures already went."""
        from . import stageclip
        if self._t().get("clips") is False or not stageclip.available(self.cfg):
            return 0
        sent = 0
        for job in stageclip.plan(scenes, items, pngs):
            sc = job["scene"]
            task = asyncio.ensure_future(stageclip.make(
                job, self.cfg, voice=self._t().get("narrate") is not False,
                agent=self.cfg.get("agent_name") or "", log=lambda m: self.store.log("telegram", m)))
            while not task.done():
                with contextlib.suppress(Exception):
                    await self._api("sendChatAction", chat_id=chat_id, action="upload_video")
                await asyncio.wait([task], timeout=4.5)
            got = None
            with contextlib.suppress(Exception):
                got = task.result()
            if not got:
                self.store.log("telegram", f"no video for '{sc.get('title') or sc.get('kind')}': it could not be recorded here")
                continue
            data, mime, secs = got
            res = await self.send_video(data, mime, stageclip.caption(job), chat_id, secs)
            if res.startswith("[error]"):
                self.store.log("telegram", f"could not send the video: {res}")
            else:
                sent += 1
                self.store.log("telegram", f"→ sent a video: {stageclip.caption(job)[:120]}")
        return sent

    async def send_video(self, data: bytes, mime: str, caption: str = "", chat_id: int | None = None,
                         seconds: float = 0) -> str:
        """A video that plays in the chat (mp4); anything else goes as a file, which is all
        Telegram does with it."""
        chat_id = chat_id or self._t().get("owner_chat_id")
        token = self._t().get("bot_token", "")
        if not token or not chat_id or not data:
            return "[error] Telegram is not set up"
        mp4 = "mp4" in (mime or "")
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                if mp4:
                    from . import stageclip
                    r = await client.post(api_url(token, "sendVideo"),
                                          data={"chat_id": str(chat_id), "caption": caption, "supports_streaming": "true",
                                                "width": str(stageclip.WIDTH), "height": str(stageclip.HEIGHT),
                                                **({"duration": str(int(seconds))} if seconds else {})},
                                          files={"video": ("story.mp4", data, "video/mp4")})
                else:
                    r = await client.post(api_url(token, "sendDocument"), data={"chat_id": str(chat_id), "caption": caption},
                                          files={"document": ("story.webm", data, mime or "video/webm")})
            if not r.json().get("ok"):
                raise RuntimeError(r.json().get("description", f"HTTP {r.status_code}"))
        except Exception as e:
            return f"[error] {e}"
        return "sent"

    async def send_narration(self, scenes: list, chat_id: int) -> str:
        """The story told aloud, as one audio message after the pictures: each scene's line,
        in the agent's voice. Only with a speech engine on the server (Settings → Voice): the
        browser voice lives in a browser. Never fatal, and silent when there is none."""
        from . import speech
        if speech.conf(self.cfg).get("engine") in ("", "browser") or self._t().get("narrate") is False:
            return ""
        lines = [str(sc.get("say") or sc.get("caption") or sc.get("title") or "").strip() for sc in scenes]
        text = " ".join(x if x.endswith((".", "!", "?")) else x + "." for x in lines if x)
        if not text:
            return ""
        try:
            audio, mime, _info = await speech.speak(self.cfg, text, agent=self.cfg.get("agent_name") or "",
                                                    lead=True)
        except Exception as e:
            self.store.log("telegram", f"no narration: {e}")
            return ""
        token = self._t().get("bot_token", "")
        ext = "mp3" if "mpeg" in (mime or "") or "mp3" in (mime or "") else "wav" if "wav" in (mime or "") else "ogg"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(api_url(token, "sendAudio"),
                                      data={"chat_id": str(chat_id), "title": "The story, told",
                                            "performer": self.cfg.get("agent_name") or "Bento"},
                                      files={"audio": (f"story.{ext}", audio, mime or "audio/mpeg")})
            if not r.json().get("ok"):
                raise RuntimeError(r.json().get("description", f"HTTP {r.status_code}"))
        except Exception as e:
            self.store.log("telegram", f"could not send the narration: {e}")
            return ""
        return "sent"

    async def send_album(self, pngs: list, captions: list, chat_id: int | None = None) -> str:
        """Pictures as one album (sendMediaGroup, ten at most each), a caption under each.
        A single picture is an ordinary photo."""
        chat_id = chat_id or self._t().get("owner_chat_id")
        token = self._t().get("bot_token", "")
        if not token or not chat_id or not pngs:
            return "[error] Telegram is not set up"
        if len(pngs) == 1:
            return await self.send_photo(pngs[0], captions[0] if captions else "", chat_id)
        import json as _j
        try:
            for at in range(0, len(pngs), 10):
                part = pngs[at:at + 10]
                if len(part) == 1:
                    await self.send_photo(part[0], captions[at], chat_id)
                    continue
                media = [{"type": "photo", "media": f"attach://p{i}",
                          "caption": (captions[at + i] if at + i < len(captions) else "")[:1024]}
                         for i in range(len(part))]
                async with httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(api_url(token, "sendMediaGroup"),
                                          data={"chat_id": str(chat_id), "media": _j.dumps(media)},
                                          files={f"p{i}": (f"scene{at + i + 1}.png", b, "image/png")
                                                 for i, b in enumerate(part)})
                data = r.json()
                if not data.get("ok"):
                    raise RuntimeError(data.get("description", f"HTTP {r.status_code}"))
        except Exception as e:
            return f"[error] telegram album failed: {e}"
        self.store.log("telegram", f"→ sent {len(pngs)} pictures: {(captions[0] if captions else '')[:100]}")
        return "sent via Telegram"

    async def send_talk(self, lines: list, chat_id: int) -> None:
        """Agents talked during this chat's turn: the exchange as a comic strip, the
        way the Office shows it on the desk. Only when they really talked (a turn
        with no agent-to-agent lines sends nothing extra), and switched off with
        telegram.comics = false. Never fatal — the reply has already been sent."""
        if not lines or self._t().get("comics") is False:
            return
        try:
            from . import comic, playground
            first = lines[0]
            title = f"{office_name(self.cfg)} · {first['speaker']}" + (
                f" asks {first['to']}" if first.get("to") and first.get("kind") == "ask" else " talks")
            png = comic.strip(self.store, self.cfg, lines, title)
            await self.send_photo(png, playground.caption(lines), chat_id)
        except Exception as e:
            self.store.log("telegram", f"could not draw the comic strip: {e}")

    def _conversation(self, chat: dict) -> str:
        """One persistent conversation per Telegram chat."""
        cid = chat.get("conversation_id")
        if cid and any(c["id"] == cid for c in self.store.list_conversations(limit=500)):
            return cid
        from . import phonesessions
        cid = phonesessions.start(self.store, "telegram", chat["chat_id"],
                                  chat.get("title") or chat["chat_id"])
        self.store.tg_set_conversation(chat["chat_id"], cid)
        chat["conversation_id"] = cid
        return cid

    async def _sessions(self, chat: dict, text: str = "", tapped: str = "") -> bool:
        """/new, /sessions, /resume and the buttons under the list (phonesessions.py).
        True when it was one of them and has been answered."""
        from . import phonesessions
        chat_id = chat["chat_id"]
        title = chat.get("title") or chat_id
        cur, busy = self._conversation(chat), chat_id in self._busy_chats
        res = (phonesessions.tapped(self.store, "telegram", chat_id, title, cur, tapped, busy) if tapped
               else phonesessions.handle(self.store, "telegram", chat_id, title, cur, text, busy))
        if res is None:
            return False
        if res.get("cid"):
            self.store.tg_set_conversation(chat_id, res["cid"])
            chat["conversation_id"] = res["cid"]
            self.store.log("telegram", f"session {'started' if res.get('new') else 'reopened'} "
                                       f"for {title}", {"chat_id": chat_id, "conversation_id": res["cid"]})
        rows = res.get("rows") or []
        if rows:
            # one tap per session, and one for a new one; typing the number works too
            kb = [[{"text": f"{r['n']}. {r['label']}"[:40], "callback_data": f"ss:{r['id']}"}]
                  for r in rows if not r["current"]]
            kb.append([{"text": "＋ New session", "callback_data": "ss:new"}])
            try:
                await self._api("sendMessage", chat_id=chat_id, text=res["say"][:4000],
                                reply_markup={"inline_keyboard": kb})
                return True
            except Exception:
                pass
        await self.send(res["say"], chat_id)
        return True

    def _conversation_for_chat(self, chat_id: int) -> str:
        """Same persistent conversation, reached by id — the admin console has the
        chat_id in hand but not the row `_handle` looked up."""
        chat = self.store.tg_upsert_chat(chat_id, "", "", "private")
        return self._conversation(chat)

    async def _handle(self, msg: dict):
        chat_info = msg.get("chat", {})
        chat_id = chat_info.get("id")
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if not text and msg.get("photo"):
            text = "(a picture, with no words)"
        if not chat_id or not text:
            return
        # A sign-in wall this chat is being asked about (cdpbrowser.reach): a code goes into
        # the page, and is never logged or saved in the conversation. Only a chat whose own
        # turn registered itself can answer, so a stranger cannot type into the page.
        from . import cdpbrowser as _cdpb
        said = await _cdpb.from_phone(usersmod.current() or "", f"tg:{chat_id}", text)
        if said:
            self.store.log("telegram", f"a reply from {chat_id} answered the browser")
            if _cdpb.reply_of(said):
                await self.send(_cdpb.reply_of(said), chat_id)
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
            self.store.tg_set_allowed(chat_id, 1, "pairing: the first chat to write")
            chat["allowed"] = 1
            name = self.cfg.get("agent_name") or "Bento"
            self.store.log("telegram", f"paired: owner = {title} ({chat_id})")
            await self.publish_commands()   # the console menu is owner-scoped
            await self.send(f"▲ Linked! Hi {frm.get('first_name', 'there')} — I'm {name}, "
                            f"the agent on your machine. This chat is now the owner. "
                            f"Send me anything; /new starts a new session.", chat_id)
            if text.startswith("/start"):
                return  # welcome is enough for /start

        # A group or channel is answered only when the owner switched group chats on, and
        # then only the ones they picked. Off, nothing is said in the group: the bot may sit
        # in groups whose members never asked for an agent. The owner hears of each group once.
        if ctype != "private" and not self.groups_on():
            self.store.log("telegram", f"refused the group {title} ({chat_id}) — group chats are off",
                           {"chat_id": chat_id, "title": title, "type": ctype,
                            "msg_count": chat["msg_count"], "text": text[:160]})
            if chat["msg_count"] <= 1:
                await self.ask_owner_about(chat_id, title, username, text, group=True)
            await self.broadcast({"type": "telegram_chats"})
            return

        # The standing allow-list, consulted before the refusal. Somebody the owner
        # named in advance is let in on their first message rather than being told
        # no and waiting for a human to find their row — see channels.preauthorised.
        if not chat["allowed"]:
            match = chanmod.preauthorised(chanmod.conf_of(self.cfg, "telegram"),
                                          username, str(chat_id))
            if match:
                self.store.tg_set_allowed(chat_id, 1, f"the allow-list ({match})")
                chat["allowed"] = 1
                self.store.log("telegram", f"allowed {title} ({chat_id}) — on the allow-list as "
                                           f"{match}", {"chat_id": chat_id, "matched": match})

        if not chat["allowed"]:
            # A stranger reaching your agent is a security event, and until now it
            # left a log line identical to a message that was answered. Whoever asks
            # "has anyone else been trying to talk to it?" has to be able to answer
            # from the log alone, so the refusal is recorded EVERY time — not only
            # on the first message, which is all the reply below is rate-limited to.
            self.store.log("telegram", f"refused {title} ({chat_id}) — not paired and not on "
                                       f"the allow-list",
                           {"chat_id": chat_id, "title": title, "username": username,
                            "type": ctype, "msg_count": chat["msg_count"],
                            "text": text[:160]})
            if chat["msg_count"] <= 1:
                await self.send("▲ I've asked the owner whether you can talk to me. You'll hear "
                                "back here once they say yes.", chat_id)
                await self.ask_owner_about(chat_id, title, username, text, group=ctype != "private")
            await self.broadcast({"type": "telegram_chats"})
            return
        await self.broadcast({"type": "telegram_chats"})

        if ctype != "private" and not await self._member_ok(chat, frm, text):
            return

        if text.startswith("/start"):
            await self.send("▲ Already linked. Send me anything; /new starts a new session.", chat_id)
            return
        if text.startswith("/clear"):
            cid = self._conversation(chat)
            self.store.clear_messages(cid)
            self.store.log("telegram", f"session cleared for {title}")
            await self.send("🧹 Session cleared — starting fresh.", chat_id)
            return
        if await self._sessions(chat, text):
            return
        # The admin console. Placed after the allow-list (only known chats reach it)
        # and before the busy lock (reading the logs must work WHILE a turn runs —
        # "what is it doing" is exactly the question you ask when it is busy).
        if telegram_admin.is_command(text) and await self._console.handle(chat_id, text):
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

        if chat_id in self._busy_chats:
            # Reported as "different tasks at the same time … in Telegram mode the backend
            # should handle it": a second message was refused with "still working". It goes
            # into the running Claude Code turn when it can (Run.steer, as on the desktop),
            # and otherwise waits and runs right after, in order.
            run = self._runs.get(chat_id)
            if run is not None and run.steer(text):
                with contextlib.suppress(Exception):
                    self.store.add_message(self._conversation(chat), "user", text, {"steered": True})
                await self.send("↪ Taken into what I'm working on.", chat_id)
            else:
                self._waiting.setdefault(chat_id, []).append(msg)
                n = len(self._waiting[chat_id])
                await self.send(f"⏳ Got it. I'll do this right after the current one"
                                + (f" ({n} waiting)." if n > 1 else "."), chat_id)
            return
        self._busy_chats.add(chat_id)
        self._busy = True
        # a sign-in wall met during this turn is asked here, on the phone
        from . import cdpbrowser as _cdpb
        _wall_uid = usersmod.current() or ""
        _cdpb.reach(_wall_uid, f"tg:{chat_id}", lambda att, png: self.ask_wall(chat_id, att, png),
                    say=lambda text, buttons: self.say_wall(chat_id, text, buttons))
        try:
            await self._api("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass
        try:
            cid = self._conversation(chat)
            # agents talking inside this turn are collected here and sent back as a
            # comic strip after the reply (playground.listen; closed in `finally`)
            from . import playground as _pg
            tap = _pg.listen(cid)
            # The same rebuild as the desktop: a thread answered from the phone
            # must see what the thread saw at the desk, tool traces included. A
            # bespoke last-30 window here is how one conversation ends up with
            # two different memories of itself.
            # Saved and shown FIRST. The history rebuild below can compact a long thread with
            # a model call; it ran before the message was saved, so a long thread sat for
            # minutes looking queued while a newer chat was answered (measured on the owner's
            # machine: 2 min 45 s). And it runs only for the built-in loop, which reads it: a
            # forwarded brain resumes its own session.
            # A photo comes with the message: fetched only now, for a chat that is let in,
            # and handed to whichever brain answers. It was ignored without a word.
            images = await self._photos(msg)
            self.store.add_message(cid, "user", text, {"images": images} if images else None)
            await self.broadcast({"type": "telegram_in", "conversation_id": cid, "text": text[:160]})
            note = ("[Message arriving via Telegram — the user is away from the machine. "
                    "Reply in plain text (no markdown tables). No one can click approval "
                    "dialogs, so risky actions only run in full autonomy.]\n\n")

            # The turn is the screen's too: the Office lights the lead's desk, a step shows
            # as a burst and a hand-over as a walk, and Chat streams it when this thread is
            # open. Reported as "when I'm sending the message with Telegram the office is
            # generally quiet": every event of a phone turn was dropped here.
            async def emit(ev):
                # the CLI's own copy of a tool this OS ran is dropped: the gate sent one
                if isinstance(ev, dict) and str(ev.get("name") or "").startswith("mcp__bento__"):
                    return
                if isinstance(ev, dict) and ev.get("type"):
                    with contextlib.suppress(Exception):
                        await self.broadcast({**ev, "conversation_id": cid, "surface": "telegram"})
            ended = False

            async def end_turn():
                nonlocal ended
                if not ended:
                    ended = True
                    with contextlib.suppress(Exception):
                        await self.broadcast({"type": "turn_end", "conversation_id": cid})

            async def approver(name, args, reason, offer=None) -> bool:
                # full autonomy answers for you — except a step that must be a
                # person's (policy.needs_person): you are right here, so you are asked
                # The channel's own posture counts: "ask over Telegram" has to mean it.
                from .policy import effective_autonomy, needs_person
                if effective_autonomy(self.cfg, "telegram") == "full" and not needs_person():
                    return True
                return await self.ask_approval(chat_id, name, args, reason, offer=offer)

            model = self.cfg.get("default_model") or ""
            from . import fabric as fabricmod
            from . import knowledge as _k
            from . import executors as _ex
            _engine = _ex.resolve_engine(self.cfg)
            await emit({"type": "turn_start", "model": _engine if _engine != "aria" else model})
            # Who answers is one function for both phones (phoneturn.py): a department, a
            # huddle or a specialist addressed by name, else the lead on this machine's
            # brain, and the next brain on the person's list when that one isn't available.
            from . import phoneturn

            async def tell(line):
                await self.send("↪ " + line, chat_id)
            out = await phoneturn.answer(
                self.store, self.cfg, self.toolbox, cid=cid, text=text, surface="telegram",
                emit=emit, approver=approver, note=note, images=tuple(images),
                on_run=lambda run: self._runs.__setitem__(chat_id, run), steerable=True, tell=tell)
            reply = out["reply"]
            self.store.add_message(cid, "assistant", reply, {"steps": out["steps"], **out["meta"]})
            self.store.touch_conversation(cid)
            # The story first, then the words: the Stage is what the answer looks like, and
            # a long text above it pushed the pictures off the screen ("it is not giving an
            # impression of the Stage")
            await self.send_stage(cid, reply, chat_id)
            await self.send(reply, chat_id)
            await self.send_files(reply, chat_id)
            await self.send_talk(_pg.close(cid, tap), chat_id)
            await end_turn()
            await self.broadcast({"type": "telegram_out", "conversation_id": cid, "text": reply[:160]})
            from . import knowledge
            knowledge.schedule_extraction(self.cfg, self.store, cid, text, reply, self.broadcast)
        except Exception as e:
            await self.send(f"[error] {type(e).__name__}: {e}", chat_id)
        finally:
            with contextlib.suppress(Exception):
                await end_turn()
            _cdpb.unreach(_wall_uid, f"tg:{chat_id}")
            self._busy_chats.discard(chat_id)
            self._runs.pop(chat_id, None)
            self._busy = bool(self._busy_chats)
            # what waited for this turn runs next, one at a time, in the order it came
            queue = self._waiting.get(chat_id) or []
            if queue:
                nxt = queue.pop(0)
                if not queue:
                    self._waiting.pop(chat_id, None)
                asyncio.create_task(self._handle(nxt))
            if "tap" in locals():
                _pg.close(cid, tap)          # idempotent: a failed turn must not leak a tap

    PHOTO_MAX = 5_000_000      # under the chat's own cap for one picture, as base64

    async def _photos(self, msg: dict) -> list:
        """The photo on a message, as the data URL the chat's own pictures are. Telegram
        sends several sizes; the largest that fits is taken. [] when there is none or it
        could not be fetched: the turn still runs on the words."""
        sizes = [p for p in (msg.get("photo") or []) if isinstance(p, dict) and p.get("file_id")]
        if not sizes:
            return []
        import base64
        try:
            fits = [p for p in sizes if int(p.get("file_size") or 0) <= self.PHOTO_MAX] or sizes[:1]
            info = await self._api("getFile", file_id=fits[-1]["file_id"])
            path = str(info.get("file_path") or "")
            if not path or ".." in path:
                return []
            token = self._t().get("bot_token", "")
            base = os.environ.get("AGENTOS_TELEGRAM_API", "").rstrip("/") or "https://api.telegram.org"
            async with httpx.AsyncClient(timeout=40) as client:
                r = await client.get(f"{base}/file/bot{token}/{path}")
            if r.status_code != 200 or len(r.content) > self.PHOTO_MAX:
                return []
            kind = "image/png" if r.content[:4] == b"\x89PNG" else "image/webp" if r.content[8:12] == b"WEBP" \
                else "image/jpeg"
            return [f"data:{kind};base64," + base64.b64encode(r.content).decode()]
        except Exception as e:
            self.store.log("telegram", f"a photo could not be fetched: {type(e).__name__}")
            return []

    async def ask_wall(self, chat_id: int, att: dict, png: bytes) -> None:
        """The shared browser met a page only a person can get past, during this chat's turn:
        a picture of the page and one question, with Done under it (cdpbrowser.tool_wait)."""
        from . import cdpbrowser as _cdpb
        offer = _cdpb.phone_offer(att)
        text = _cdpb.phone_words(att, self.cfg.get("agent_name") or "Bento", offer=offer)
        rows = [[{"text": "Done, carry on", "callback_data": "bw:done"}]]
        if offer.get("ok"):
            # the page itself, on this phone, through remote access (handoff.py): the tap
            # is the permission
            rows.insert(0, [{"text": "Open on this phone", "callback_data": "bw:open"}])
        kb = {"inline_keyboard": rows}
        token = self._t().get("bot_token", "")
        if png and token:
            try:
                async with httpx.AsyncClient(timeout=70) as client:
                    r = await client.post(api_url(token, "sendPhoto"),
                                          data={"chat_id": str(chat_id), "caption": text[:1024],
                                                "reply_markup": json.dumps(kb)},
                                          files={"photo": ("page.png", png, "image/png")})
                if (r.json() or {}).get("ok"):
                    self.store.log("telegram", f"→ asked about a page: {att.get('site') or ''}")
                    return
            except Exception:
                pass
        with contextlib.suppress(Exception):
            await self._api("sendMessage", chat_id=chat_id, text=text, reply_markup=kb)

    async def say_wall(self, chat_id: int, text: str, buttons: list) -> None:
        """A line about a sign-in link (handoff.py), with its buttons under it. Sent as plain
        text and never written to the diary: the words may hold the link. A button whose
        word starts `url:` opens that address; any other answers through `bw:<word>`."""
        rows = [[({"text": label, "url": word[4:]} if word.startswith("url:")
                  else {"text": label, "callback_data": "bw:" + word})] for label, word in buttons or []]
        kw = {"link_preview_options": {"is_disabled": True}}
        try:
            await self._api("sendMessage", chat_id=chat_id, text=text,
                            **kw, **({"reply_markup": {"inline_keyboard": rows}} if rows else {}))
        except Exception:
            # Telegram refuses a button for some addresses (a bare IP on a home network):
            # the address is in the words too, so the line goes again without the button
            rows = [r for r in rows if "url" not in r[0]]
            with contextlib.suppress(Exception):
                await self._api("sendMessage", chat_id=chat_id, text=text,
                                **kw, **({"reply_markup": {"inline_keyboard": rows}} if rows else {}))
        self.store.log("telegram", "→ said something about a sign-in link")

    async def send_brief(self, text: str, rows: list, chat_id: int | None = None) -> str:
        """The Brief's digest with Done / Later / decision buttons under it — the
        message a mission ends in. Buttons carry `br:<id>:<action>[:<choice>]`."""
        chat_id = chat_id or self._t().get("owner_chat_id")
        if not self._t().get("bot_token") or not chat_id:
            return await self.send(text, chat_id)
        try:
            kw = {"reply_markup": {"inline_keyboard": rows}} if rows else {}
            await self._api("sendMessage", chat_id=chat_id, text=text[:4000], **kw)
        except Exception as e:
            return f"[error] telegram send failed: {e}"
        return "sent"

    async def _ask_approval(self, chat_id: int, name: str, args: dict, reason: str) -> bool:
        return await self.ask_approval(chat_id, name, args, reason)

    async def ask_approval(self, chat_id: int, name: str, args: dict, reason: str,
                           offer: dict | None = None, timeout: float = 300,
                           unanswered=None) -> bool:
        """Send an inline keyboard and wait for the user's tap.

        Three buttons rather than two when the decision carries a grant offer: an
        unattended flow that has to be re-approved every night is one somebody will
        eventually put on full autonomy to make it stop asking, which is worse than the
        grant they actually meant. "Always" is written as a USER grant — never a
        definition one, or the next save of that flow would silently revoke it.
        """
        import uuid
        aid = uuid.uuid4().hex[:8]
        # what it is for and the start of what it does; a message is capped at 4096
        from . import approvalcard
        from .policy import said
        text = approvalcard.message(approvalcard.card(name, args, said()), reason, limit=4000)
        row = [{"text": "✅ Allow once", "callback_data": f"ap:{aid}:1"},
               {"text": "⛔ Deny", "callback_data": f"ap:{aid}:0"}]
        if offer:
            row.insert(1, {"text": "⏱ 1 hour", "callback_data": f"ap:{aid}:3"})
            row.insert(2, {"text": "♾ Always", "callback_data": f"ap:{aid}:2"})
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
            # Nobody tapped. Same rule as the desktop's broker: silence is not a
            # refusal, so the question is filed where it will be seen rather than
            # disappearing with the message nobody opened.
            note = ""
            if unanswered:
                try:
                    await unanswered()
                    note = " It is on your Brief."
                except Exception:
                    pass
            await self.send("⌛ Approval timed out — action not taken. The run continues "
                            "without it." + note, chat_id)
            return False
        finally:
            self._pending.pop(aid, None)
        if val in ("2", "3") and offer:
            from .policy import write_remembered
            write_remembered(self.store, offer, "always" if val == "2" else "hour",
                             via="a Telegram approval")
            self.store.log("policy", f"grant remembered: {offer['action']} {offer['resource']}",
                           {"principal": f"{offer['principal_kind']}:{offer['principal_id']}",
                            "action": offer["action"], "resource": offer["resource"],
                            "effect": "allow", "via": "telegram_approval"})
            try:
                await self.broadcast({"type": "grants"})
            except Exception:
                pass
        return val in ("1", "2", "3")

    def member_rule(self, chat: dict, member: dict, member_id) -> bool:
        """May this person talk to the agent in this group? The owner always; a blocked
        person never; otherwise everybody, or only the picked ones when the group is
        set to `members_only`."""
        if str(member_id) == str(self._t().get("owner_chat_id") or 0):
            return True
        state = (member or {}).get("state") or ""
        if state == "blocked":
            return False
        return state == "allowed" or not chat.get("members_only")

    async def _member_ok(self, chat: dict, frm: dict, text: str = "") -> bool:
        """The person inside an enabled group. Everyone who writes there is recorded, so
        the owner can see who talks to the agent and stop one of them."""
        mid = frm.get("id")
        if not mid:
            return not chat.get("members_only")      # a post with no sender (a channel)
        name = " ".join(filter(None, [frm.get("first_name", ""), frm.get("last_name", "")])).strip() or str(mid)
        m = self.store.member_seen("telegram", chat["chat_id"], mid, name, frm.get("username") or "")
        if self.member_rule(chat, m, mid):
            return True
        title = chat.get("title") or chat["chat_id"]
        self.store.log("telegram", f"refused {name} in the group {title} — "
                       + ("blocked there" if m.get("state") == "blocked" else "not one of the people picked there"),
                       {"chat_id": chat["chat_id"], "member": str(mid), "text": text[:160]})
        if m.get("state") != "blocked" and m["msg_count"] <= 1:
            # asked once: the owner picks who talks to the agent in this group
            await self.send(f"▲ In this group I answer only the people the owner picked. "
                            f"I've asked about you, {name}.", chat["chat_id"])
            owner = self._t().get("owner_chat_id") or 0
            agent = self.cfg.get("agent_name") or "Bento"
            if owner:
                with contextlib.suppress(Exception):
                    await self._api("sendMessage", chat_id=owner,
                                    text=(f"📩 {name} wrote to {agent} in the group {title}:\n“{text[:300]}”\n\n"
                                          f"Only people you pick are answered there.")[:4000],
                                    reply_markup={"inline_keyboard": [[
                                        {"text": "✓ Allow them there", "callback_data": f"mem:{chat['chat_id']}:{mid}:1"},
                                        {"text": "✗ Block", "callback_data": f"mem:{chat['chat_id']}:{mid}:0"}]]})
            with contextlib.suppress(Exception):
                await self.broadcast({"type": "telegram_request", "chat_id": chat["chat_id"], "member": str(mid),
                                      "title": f"{name}, in the group {title}", "text": text[:160]})
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "telegram_chats"})
        return False

    def decide_member(self, chat_id, member_id, state: str, by: str = "the owner, on Telegram") -> str:
        """Allow or block one person inside a group, or hand them back to the group's rule."""
        if str(member_id) == str(self._t().get("owner_chat_id") or 0) and state == "blocked":
            return "That's the owner. The owner is always answered."
        if not self.store.member_set("telegram", chat_id, member_id, state, by):
            return "Nobody by that id wrote in that group."
        self.store.log("telegram", f"member {member_id} of chat {chat_id}: {state or 'the group rule'} ({by})",
                       {"chat_id": chat_id, "member": str(member_id), "state": state, "by": by})
        return {"allowed": "allowed there", "blocked": "blocked there"}.get(state, "back to the group's rule")

    def set_members_only(self, chat_id, on: bool, by: str = "the owner, on Telegram") -> None:
        self.store.tg_set_members_only(chat_id, on)
        self.store.log("telegram", f"chat {chat_id} answers {'only picked people' if on else 'everybody in it'} ({by})")

    def table(self) -> dict:
        """People and groups as the tables draw them: who, since when, decided by whom,
        and for a group the people who wrote there."""
        owner = self._t().get("owner_chat_id") or 0
        people, groups = [], []
        for c in self.store.tg_list_chats():
            row = {**c, "owner": c["chat_id"] == owner}
            if (c.get("type") or "private") == "private":
                people.append(row)
                continue
            ms = self.store.members("telegram", c["chat_id"])
            for m in ms:
                m["owner"] = str(m["member_id"]) == str(owner)
                m["talks"] = self.member_rule(c, m, m["member_id"])
            row["members"], row["answered"] = ms, bool(c.get("allowed")) and self.groups_on()
            groups.append(row)
        return {"people": people, "group_rows": groups, "groups_on": self.groups_on()}

    def groups_on(self) -> bool:
        """Whether groups and channels are answered at all. The owner's switch
        (`telegram.groups`); a machine that never set it keeps answering the groups it
        already enabled, and answers no group otherwise."""
        v = self._t().get("groups")
        if v is None:
            return any(c.get("allowed") and (c.get("type") or "private") != "private"
                       for c in self.store.tg_list_chats())
        return bool(v)

    def set_groups(self, on: bool, by: str = "") -> None:
        self._t()["groups"] = bool(on)
        cfgmod.save_config(self.cfg)
        self.store.log("telegram", f"group chats switched {'on' if on else 'off'}" + (f" ({by})" if by else ""))

    def groups(self) -> list[dict]:
        """The groups and channels a message has come in from, newest first."""
        return [c for c in self.store.tg_list_chats() if (c.get("type") or "private") != "private"]

    async def ask_owner_about(self, chat_id: int, title: str, username: str, text: str,
                              group: bool = False) -> None:
        """Somebody new wrote: the owner decides, with Allow / Block on their phone and an
        Allow on the desktop. Reported as "I am not getting an option to authorize other
        people on Telegram": the newcomer was told "the owner can enable it in the Telegram
        app", and the owner was told nothing."""
        owner = self._t().get("owner_chat_id") or 0
        who = f"{title}" + (f" (@{username})" if username else "")
        name = self.cfg.get("agent_name") or "Bento"
        if owner and owner != chat_id:
            if group:
                off = not self.groups_on()
                words = (f"📩 A message came in from the group {who}:\n“{text[:300]}”\n\n"
                         + ("Group chats are off, so I said nothing there. " if off else "")
                         + f"Allowing this group lets everybody in it talk to {name}, under your "
                           f"settings and permissions." + (" It also turns group chats on." if off else ""))
                yes = "✓ Allow this group"
            else:
                words = (f"📩 {who} wants to talk to {name}. They wrote:\n“{text[:300]}”\n\n"
                         f"Allowing them lets them chat with {name} here, under your "
                         f"settings and permissions.")
                yes = "✓ Allow"
            try:
                await self._api("sendMessage", chat_id=owner, text=words[:4000],
                                reply_markup={"inline_keyboard": [[
                                    {"text": yes, "callback_data": f"who:{chat_id}:1"},
                                    {"text": "✗ Block", "callback_data": f"who:{chat_id}:0"}]]})
            except Exception as e:
                self.store.log("telegram", f"could not ask the owner about {who}: {e}")
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "telegram_request", "chat_id": chat_id, "title": who,
                                  "text": text[:160]})

    async def decide_newcomer(self, chat_id: int, allow: bool, by: str = "the owner, on Telegram") -> str:
        """The owner's answer, from a button or the desktop: one door for both."""
        row = next((c for c in self.store.tg_list_chats() if c["chat_id"] == chat_id), None) or {}
        if allow and (row.get("type") or "private") != "private" and not self.groups_on():
            # picking a group is the owner saying yes to groups: the two go together,
            # or the group would read "enabled" and never be answered
            self.set_groups(True, f"allowing {row.get('title') or chat_id}")
        self.store.tg_set_allowed(chat_id, 1 if allow else 0, by)
        self.store.log("telegram", f"{'allowed' if allow else 'blocked'} chat {chat_id} ({by})",
                       {"chat_id": chat_id, "allowed": allow, "by": by})
        if allow:
            name = self.cfg.get("agent_name") or "Bento"
            await self.send(f"▲ You're in. I'm {name}. Send me anything; /new starts a new session.", chat_id)
        with contextlib.suppress(Exception):
            await self.broadcast({"type": "telegram_chats"})
        return "allowed" if allow else "blocked"

    async def _handle_callback(self, cq: dict):
        if (cq.get("data") or "").startswith("ss:"):
            # A session button (/sessions). Any enabled chat has sessions, so this is
            # decided by the chat the button sits in, before the owner-only buttons.
            with contextlib.suppress(Exception):
                await self._api("answerCallbackQuery", callback_query_id=cq["id"])
            chat_id = ((cq.get("message") or {}).get("chat") or {}).get("id")
            chat = next((c for c in self.store.tg_list_chats() if c["chat_id"] == chat_id), None)
            owner = chat_id == (self._t().get("owner_chat_id") or 0)
            if chat and (chat.get("type") or "private") != "private" and not self.groups_on():
                return
            if chat and (chat.get("type") or "private") != "private":
                who = cq.get("from") or {}
                m = next((x for x in self.store.members("telegram", chat_id)
                          if x["member_id"] == str(who.get("id"))), None)
                if not self.member_rule(chat, m, who.get("id")):
                    return
            if chat and (chat.get("allowed") or owner):
                await self._sessions(chat, tapped=cq["data"][3:])
            return
        if cq.get("from", {}).get("id") != (self._t().get("owner_chat_id") or 0):
            return
        data = cq.get("data", "")
        try:
            await self._api("answerCallbackQuery", callback_query_id=cq["id"])
        except Exception:
            pass
        if data == "bw:done":
            # "Done, carry on" under a page the browser was waiting on
            from . import cdpbrowser as _cdpb
            msg = cq.get("message", {})
            chat_id = (msg.get("chat") or {}).get("id") or cq.get("from", {}).get("id")
            said = await _cdpb.from_phone(usersmod.current() or "", f"tg:{chat_id}", "done")
            await self.send("✓ " + (said or "Nothing is waiting on that page now."), chat_id)
            return
        if data.startswith("co:"):
            # a company's Open button (telegram_admin /companies)
            said = await self._console.open_company(data[3:])
            msg = cq.get("message", {})
            await self.send(said, (msg.get("chat") or {}).get("id") or cq.get("from", {}).get("id"))
            return
        if data.startswith("mem:") or data.startswith("gm:"):
            # one person inside a group (mem:<chat>:<member>:<1|0>), or the group's rule
            # (gm:<chat>:<1|0> = only picked people | everybody)
            parts = data.split(":")
            try:
                if parts[0] == "mem":
                    said = self.decide_member(int(parts[1]), parts[2], "allowed" if parts[3] == "1" else "blocked")
                else:
                    self.set_members_only(int(parts[1]), parts[2] == "1")
                    said = "only the people you pick are answered there" if parts[2] == "1" \
                        else "everybody in that group is answered"
            except (ValueError, IndexError):
                return
            msg = cq.get("message", {})
            if msg:
                with contextlib.suppress(Exception):
                    await self._api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                    text=(msg.get("text") or "")[:3900] + f"\n\n→ {said}")
            with contextlib.suppress(Exception):
                await self.broadcast({"type": "telegram_chats"})
            return
        if data.startswith("wan:"):
            # somebody new on WHATSAPP, asked here because this account's Telegram is paired
            parts = data.split(":")
            wa = getattr(self.toolbox, "whatsapp", None)
            if wa is None or len(parts) < 3:
                return
            said = await wa.decide_newcomer(parts[1], parts[2] == "1", "the owner, on Telegram")
            msg = cq.get("message", {})
            if msg:
                with contextlib.suppress(Exception):
                    await self._api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                    text=(msg.get("text") or "")[:3900] + f"\n\n→ {said}")
            return
        if data.startswith("who:"):
            # the owner's answer about somebody new (ask_owner_about)
            parts = data.split(":")
            try:
                said = await self.decide_newcomer(int(parts[1]), parts[2] == "1")
            except (ValueError, IndexError):
                return
            msg = cq.get("message", {})
            if msg:
                with contextlib.suppress(Exception):
                    await self._api("editMessageText", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                                    text=(msg.get("text") or "")[:3900] + f"\n\n→ {said}")
            return
        if data in ("bw:open", "bw:close"):
            # the sign-in link (handoff.py): the tap that asks for it, or closes it
            from . import cdpbrowser as _cdpb
            msg = cq.get("message", {})
            chat_id = (msg.get("chat") or {}).get("id") or cq.get("from", {}).get("id")
            said = await _cdpb.from_phone(usersmod.current() or "", f"tg:{chat_id}", data[3:])
            if not said:
                await self.send("Nothing is waiting on that page now.", chat_id)
            elif _cdpb.reply_of(said):
                await self.send(_cdpb.reply_of(said), chat_id)
            return
        if data.startswith("br:"):
            # a Brief button: Done / Later / a decision — the same act() the
            # desktop and `bento brief` use; a decision starts the agent's turn
            from . import brief as briefmod
            parts = data.split(":", 3)
            bid, action = parts[1], parts[2] if len(parts) > 2 else ""
            choice = parts[3] if len(parts) > 3 else ""
            fab = getattr(self.toolbox, "fabric", None)
            run_id = (briefmod.parked_run(self.store.brief_get(bid) or {})
                      if action == "decide" and fab is not None else "")
            if run_id:
                # a mission waiting for this answer: the same rule as the desktop's
                # route, and the run carries on behind the poll loop
                got = fab.answer_parked(run_id, briefmod.allows(self.store.brief_get(bid), choice))
                if not got["ok"]:
                    self.store.brief_set(bid, state="done")
                    await self.send(f"✗ {got['why']}", cq.get("from", {}).get("id"))
                    return
            try:
                item = briefmod.act(self.store, bid, action, choice)
            except ValueError as e:
                await self.send(f"✗ {e}", cq.get("from", {}).get("id"))
                return
            said = {"done": "✓ done", "later": "⏸ later"}.get(action, f"→ {choice}")
            msg = cq.get("message", {})
            if msg:
                try:
                    await self._api("editMessageText", chat_id=msg["chat"]["id"],
                                    message_id=msg["message_id"],
                                    text=(msg.get("text") or "")[:3900] + f"\n\n{said}: {item.get('title', '')}")
                except Exception:
                    pass
            # the bridge has no scheduler of its own: the toolbox carries the one the
            # server wired, and a bridge built without one (tests, CLI) just records
            scheduler = getattr(self.toolbox, "scheduler", None)
            if run_id:
                who = cq.get("from", {}).get("id")

                async def _carry_on():
                    res = await fab.resume_parked(run_id)
                    st = res.get("status", "")
                    await self.send({"parked": "It carried on and stopped at another question. "
                                               "It is in the Brief.",
                                     "ok": "It carried on and finished."}.get(
                                         st, f"It carried on and ended: {st}."), who)
                    try:
                        await self.broadcast({"type": "brief", "action": "resumed", "run_id": run_id})
                    except Exception:
                        pass
                self._answer_task = asyncio.create_task(_carry_on())
            elif action == "decide" and scheduler is not None:
                # behind the poll loop, not in it: the answer is a whole turn, and a
                # bot that ignores every tap for a minute reads as broken
                who = cq.get("from", {}).get("id")

                async def _answer():
                    try:
                        cid, text = await scheduler.run_prompt(
                            briefmod.decide_prompt(item, choice), origin="brief",
                            title=f"Brief · {item.get('title', '')[:40]}")
                    except Exception as e:
                        cid, text = "", f"could not run the answer: {e}"
                    self.store.brief_set(bid, answer_cid=cid or "")
                    await self.send(text or "(done)", who)
                    try:
                        await self.broadcast({"type": "brief", "id": bid, "action": "answered"})
                    except Exception:
                        pass
                self._answer_task = asyncio.create_task(_answer())
            try:
                await self.broadcast({"type": "brief", "id": bid, "action": action})
            except Exception:
                pass
            return
        if not data.startswith("ap:"):
            return
        _, aid, val = data.split(":", 2)
        fut = self._pending.get(aid)
        if fut and not fut.done():
            fut.set_result(val)          # "0" deny | "1" allow once | "2" always
        # reflect the decision on the message
        msg = cq.get("message", {})
        if msg:
            said = {"1": "✅ Allowed", "2": "♾ Allowed & remembered",
                    "3": "⏱ Allowed for an hour"}.get(val, "⛔ Denied")
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
                    await self.publish_commands()
                    await self.say_up()
                self.status = "polling"
                self.error = ""
                if time.time() - getattr(self, "_seen_at", 0) > self.ALIVE_EVERY:
                    self._seen_at = time.time()
                    self._alive_write(seen=self._seen_at)
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
                "groups": self.groups_on(), "chats": self.store.tg_list_chats(), **self.table()}

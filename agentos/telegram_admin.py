"""The admin console: running this machine from the phone.

Telegram was a way to *talk to* the agent. This makes it a way to *operate the
OS* — see what agents and flows exist, start one, switch the model, read the
ledger. The machine is often in another room and the phone is the only thing to
hand, so "open Settings on the desktop" is not an answer.

Two rules hold the whole thing up, and neither is optional:

- **Owner only.** An allow-listed chat may converse; only the paired owner may
  operate. Those are different permissions and conflating them would make every
  allow-listed colleague an administrator.
- **A command is never a way around the gate.** Every command that *does*
  something asks the PDP exactly as the equivalent tool call would, with
  `surface="telegram"`, so the same grants, the same approval buttons and the
  same audit rows apply. `/model` is `configure_agentos`; `/run` is
  `agent.invoke`. A console that bypassed policy would be a second, unaudited
  way to use this machine — which is the thing the ledger exists to prevent.

Read-only commands (`/agents`, `/tools`, `/flows`, `/logs`, `/perms`) do not ask,
because listing what exists is not an action. They are still owner-only: the
ledger and the permission table say a great deal about the person who owns this
machine.

Not applicable to the GUI or the TUI — both already have these as apps and
panels. This is the surface that had no way in.
"""

from __future__ import annotations

import time

# One line each, and this IS /help — a list that lives apart from the dispatcher
# is a list that ends up describing commands that no longer exist.
COMMANDS = [
    ("/help", "", "this list"),
    ("/status", "", "model, autonomy, what is running"),
    ("/model", "[id]", "show what can answer; with an id, switch this machine to it"),
    ("/agents", "", "the specialists this machine has"),
    ("/run", "<agent> <task>", "hand a task to one of them"),
    ("/flows", "", "standing missions, and whether they are armed"),
    ("/flow", "<name> [input]", "run one now"),
    ("/tools", "[search]", "what the agent can do"),
    ("/logs", "[n|search]", "the operator diary, newest last"),
    ("/perms", "", "who has been granted what"),
    ("/clear", "", "wipe this conversation and start fresh"),
]


# What every enabled chat may use. Administration is not in here: a command the
# client offers and the bot then refuses is worse than one that was never shown.
_EVERYONE = {"/help", "/status", "/clear"}


def is_command(text: str) -> bool:
    return (text or "").strip().startswith("/")


def menu(owner: bool) -> list[dict]:
    """The command list Telegram's blue Menu button and `/` autocomplete render.

    Registered with `setMyCommands` by the bridge rather than typed into
    BotFather by hand: this list and the dispatcher are the same list, so the
    menu cannot drift into offering a command that no longer exists.

    Scoped, because the menu is a promise. The owner's chat gets the console;
    everyone else gets the three that work for them. Telegram wants lowercase
    names without the slash, and descriptions of at most 256 characters.
    """
    out = [{"command": "start", "description": "link this chat / say hello"}]
    for cmd, arg, desc in COMMANDS:
        if not owner and cmd not in _EVERYONE:
            continue
        out.append({"command": cmd[1:],
                    "description": (f"{arg} — {desc}" if arg else desc)[:256]})
    return out


def _fmt_age(ts: float) -> str:
    d = max(0, time.time() - (ts or 0))
    if d < 60:
        return f"{int(d)}s ago"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


def _lines(head: str, rows: list[str], empty: str) -> str:
    if not rows:
        return f"{head}\n{empty}"
    return head + "\n" + "\n".join(rows)


class Console:
    """Owner-only commands over a chat. `tg` is the TelegramBridge."""

    def __init__(self, tg):
        self.tg = tg

    # ------------------------------------------------------------------ gate

    def _is_owner(self, chat_id: int) -> bool:
        return chat_id == (self.tg._t().get("owner_chat_id") or 0)

    async def _gated(self, chat_id: int, tool: str, args: dict, reason: str) -> tuple[bool, str]:
        """Ask the PDP the same question the tool call would, and honour the answer.

        Returns (allowed, refusal). An "ask" becomes the channel's own approval
        buttons, so operating from the phone feels like the desktop rather than
        like a back door with no lock on it.
        """
        pdp = getattr(self.tg.toolbox, "pdp", None)
        if pdp is None:                     # policy off: the console is off with it
            return False, "policy is not available on this machine right now"
        from .policy import MAIN
        risk, why = self.tg.toolbox.risk_of(tool, args)
        dec = pdp.decide_tool(MAIN, tool, args, risk, reason=reason or why,
                              surface="telegram")
        if dec.effect == "allow":
            return True, ""
        if dec.effect == "deny":
            return False, f"refused: {dec.reason or 'policy'}"
        ok = await self.tg.ask_approval(chat_id, tool, args, dec.reason or reason or why,
                                        offer=dec.grant_offer)
        return (True, "") if ok else (False, "not approved")

    # ------------------------------------------------------------- dispatch

    async def handle(self, chat_id: int, text: str) -> bool:
        """Returns True if this text was a console command and has been answered."""
        raw = (text or "").strip()
        if not raw.startswith("/"):
            return False
        head, _, arg = raw.partition(" ")
        cmd = head.split("@", 1)[0].lower()       # /logs@mybot in a group
        arg = arg.strip()
        fn = getattr(self, "_cmd_" + cmd[1:], None) if len(cmd) > 1 else None
        if fn is None:
            return False                          # not ours — /start, /clear, or a real message
        if not self._is_owner(chat_id):
            # Said plainly rather than silently ignored: a colleague typing /logs
            # should learn this is not theirs to run, not think it is broken.
            await self.tg.send("▲ That one is for the owner of this machine only. "
                               "You can still just talk to me.", chat_id)
            return True
        try:
            out = await fn(chat_id, arg)
        except Exception as e:                    # a broken command must not kill the poller
            out = f"[error] {type(e).__name__}: {e}"
        if out:
            await self.tg.send(out, chat_id)
        return True

    # --------------------------------------------------------- read-only

    async def _cmd_help(self, chat_id: int, arg: str) -> str:
        rows = [f"{c}{' ' + a if a else ''} — {d}" for c, a, d in COMMANDS]
        return _lines("▲ Admin console", rows, "")

    async def _cmd_status(self, chat_id: int, arg: str) -> str:
        cfg = self.tg.cfg
        from . import executors as execmod
        eng = execmod.resolve_engine(cfg)
        running = "idle" if not self.tg._busy else "a turn is running"
        return (f"▲ online · {running}\n"
                f"model: {cfg.get('default_model') or '(none)'}"
                + (f" · forwarding to {eng}" if eng != "aria" else "") + "\n"
                f"autonomy: {cfg.get('autonomy')}")

    async def _cmd_agents(self, chat_id: int, arg: str) -> str:
        rows = []
        for a in self.tg.store.list_subagents():
            tools = a.get("tools") or []
            rows.append(f"• {a['name']} — {(a.get('soul') or '').strip()[:70]}"
                        + (f"\n   {len(tools)} tools · {a.get('model') or 'default model'}"
                           if tools else f"\n   read-only · {a.get('model') or 'default model'}"))
        return _lines("▲ Agents  (/run <agent> <task>)", rows,
                      "none yet — ask me to build one and I will")

    async def _cmd_flows(self, chat_id: int, arg: str) -> str:
        rows = []
        for f in self.tg.store.list_flows():
            roster = ", ".join(r.get("subagent", "") for r in (f.get("roster") or []))
            rows.append(f"• {f['name']} — {'armed' if f.get('enabled') else 'off (holds nothing)'}"
                        + (f"\n   roster: {roster}" if roster else ""))
        return _lines("▲ Flows  (/flow <name> [input])", rows, "none defined")

    async def _cmd_tools(self, chat_id: int, arg: str) -> str:
        from .tools import TOOL_SCHEMAS
        q = arg.lower()
        hits = [t for t in TOOL_SCHEMAS
                if not q or q in t["name"].lower() or q in t.get("description", "").lower()]
        if not hits:
            return f"▲ nothing matches “{arg}”"
        # A phone is not the place for ninety descriptions: names, and the
        # description only when the list is already short enough to read.
        if len(hits) <= 8:
            rows = [f"• {t['name']} — {t.get('description', '')[:110]}" for t in hits]
        else:
            rows = ["  ".join(t["name"] for t in hits[i:i + 3]) for i in range(0, len(hits), 3)]
        return _lines(f"▲ Tools · {len(hits)}" + (f" matching “{arg}”" if arg else ""), rows, "")

    async def _cmd_logs(self, chat_id: int, arg: str) -> str:
        """The operator diary and the decision ledger, together.

        Two different questions get asked from a phone — "what has it been doing"
        and "what did it decide it was allowed to do" — and answering only the
        first is how a permission problem becomes invisible from the road.
        """
        n, q = 12, ""
        if arg.isdigit():
            n = max(1, min(40, int(arg)))
        elif arg:
            q = arg
        rows = [f"{_fmt_age(r['created_at'])} · {r['kind']}: {(r.get('message') or '')[:150]}"
                for r in reversed(self.tg.store.list_logs(limit=n, q=q))]
        out = _lines(f"▲ Logs · last {n}" + (f" matching “{q}”" if q else ""), rows, "nothing yet")
        gated = [r for r in self.tg.store.audit_list(limit=60, q=q)
                 if r["effect"] in ("deny", "ask")][:6]
        if gated:
            out += "\n\n▲ Gated recently\n" + "\n".join(
                f"{_fmt_age(r['ts'])} · {r['effect']} {r['action']} {r['resource'][:60]}"
                f" ({r['principal_kind']}{':' + r['principal_id'] if r['principal_id'] else ''})"
                for r in gated)
        return out

    async def _cmd_perms(self, chat_id: int, arg: str) -> str:
        rows = []
        for g in self.tg.store.list_grants()[:25]:
            who = g["principal_kind"] + (f":{g['principal_id']}" if g["principal_id"] else "")
            rows.append(f"• {'deny ' if g.get('effect') == 'deny' else ''}{who} → "
                        f"{g['action']} {g['resource'][:50]}")
        return _lines("▲ Granted  (revoke in Permissions on the desktop)", rows,
                      "nothing granted — everything still asks")

    # ------------------------------------------------------------ actions

    async def _cmd_model(self, chat_id: int, arg: str) -> str:
        from . import providers
        cfg = self.tg.cfg
        if not arg:
            models = await providers.available_models(cfg)
            cur = cfg.get("default_model") or ""
            rows = [("→ " if m.get("id") == cur else "  ") + m.get("id", "") for m in models[:30]]
            return _lines(f"▲ Models  (/model <id> to switch · now: {cur or 'none'})",
                          rows, "no models available — add a provider key on the desktop")
        models = await providers.available_models(cfg)
        ids = [m.get("id", "") for m in models]
        want = arg.strip()
        if want not in ids:
            near = [i for i in ids if want.lower() in i.lower()]
            if len(near) != 1:
                return (f"▲ “{want}” is not one of this machine's models"
                        + (f" — did you mean: {', '.join(near[:5])}?" if near else "")
                        + "\nSend /model to see the list.")
            want = near[0]
        # Switching the machine's model is a configuration change, so it goes
        # through the same gate `configure_agentos` would — including the buttons.
        ok, why = await self._gated(chat_id, "configure_agentos", {"default_model": want},
                                    f"Switch this machine's model to {want}.")
        if not ok:
            return f"▲ {why}"
        cfg["default_model"] = want
        from . import config as cfgmod
        cfgmod.save_config(cfg)
        self.tg.store.log("policy", f"default model set to {want} from telegram")
        await self.tg.broadcast({"type": "config"})
        return f"▲ model is now {want}"

    async def _cmd_run(self, chat_id: int, arg: str) -> str:
        name, _, task = arg.partition(" ")
        name, task = name.strip(), task.strip()
        if not name or not task:
            return "▲ /run <agent> <task> — send /agents to see them"
        defn = self.tg.store.get_subagent(name)
        if not defn:
            return f"▲ no agent called “{name}” — /agents lists them"
        if not self.tg.toolbox.fabric:
            return "▲ the team is not available on this machine"
        # The same first-use consent the desktop asks, reaching the phone: this is
        # `delegate` by another door, and it must not be a cheaper one.
        ok, why = await self._gated(chat_id, "delegate", {"subagent": name, "task": task},
                                    "")
        if not ok:
            return f"▲ {why}"
        await self.tg.send(f"▶ {name} is on it…", chat_id)
        res = await self.tg.toolbox.fabric.run_subagent(
            defn, task, conversation_id=self.tg._conversation_for_chat(chat_id),
            approver=lambda n, a, r, offer=None: self.tg.ask_approval(chat_id, n, a, r, offer=offer))
        return (f"@{name} · {res['status']}\n\n"
                + (res.get("content") or res.get("fault") or "(no output)"))

    async def _cmd_flow(self, chat_id: int, arg: str) -> str:
        name, _, inp = arg.partition(" ")
        name = name.strip()
        if not name:
            return "▲ /flow <name> [input] — send /flows to see them"
        flow = self.tg.store.get_flow(name) if hasattr(self.tg.store, "get_flow") else None
        if not flow:
            return f"▲ no flow called “{name}” — /flows lists them"
        if not self.tg.toolbox.fabric:
            return "▲ flows are not available on this machine"
        ok, why = await self._gated(chat_id, "run_flow", {"flow": name, "input": inp}, "")
        if not ok:
            return f"▲ {why}"
        import asyncio
        asyncio.create_task(self.tg.toolbox.fabric.run_flow(
            flow, inp or f"Run {name}.",
            origin={"surface": "telegram", "chat_id": chat_id},
            conversation_id=self.tg._conversation_for_chat(chat_id)))
        return f"▶ {name} started — I'll report back here."

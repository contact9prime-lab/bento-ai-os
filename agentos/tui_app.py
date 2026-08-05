"""AgentOS TUI — a full terminal management interface (for SSH / headless use).

A navigable, full-screen text UI over the running AgentOS server: chat with the agent, watch
the system live, switch models, launch installed apps, view tasks and logs, and edit config.

    agentos tui
"""

import asyncio
import json
import time

import httpx
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input, Label,
                             ListItem, ListView, RichLog, Select, Static, TabbedContent, TabPane)

from . import config as cfgmod


def _base(port):
    return f"http://127.0.0.1:{port}"


class ApprovalScreen(ModalScreen):
    """A yes/no modal for a risky action the agent wants to run."""
    def __init__(self, name, detail, reason):
        super().__init__()
        self._name, self._detail, self._reason = name, detail, reason

    def compose(self) -> ComposeResult:
        with Vertical(id="ap-box"):
            yield Label("⚠  Approval needed", id="ap-title")
            yield Static(f"[b]{self._name}[/b]  {self._detail}", id="ap-cmd")
            yield Static(self._reason or "", id="ap-reason")
            with Horizontal(id="ap-btns"):
                yield Button("Allow", variant="success", id="ap-allow")
                yield Button("Deny", variant="error", id="ap-deny")

    def on_button_pressed(self, e: Button.Pressed):
        self.dismiss(e.button.id == "ap-allow")


class AgentTUI(App):
    CSS = """
    Screen { background: $surface; }
    #ap-box { width: 70; height: auto; padding: 1 2; border: round $accent; background: $panel; }
    #ap-title { color: $warning; text-style: bold; }
    #ap-cmd { margin: 1 0; }
    #ap-reason { color: $text-muted; }
    #ap-btns { height: auto; align-horizontal: center; margin-top: 1; }
    #ap-btns Button { margin: 0 1; }
    #chatlog, #logslog { border: round $primary; padding: 0 1; }
    #chatinput { dock: bottom; }
    DataTable { height: 1fr; }
    #sysbars { height: auto; padding: 1 1; }
    .barlabel { color: $text-muted; }
    #cfg-box { padding: 1 2; }
    #cfg-box Label { margin-top: 1; color: $text-muted; }
    #cfg-box .section { margin: 1 0; color: $accent; text-style: bold; }
    #cfg-box Checkbox { margin-top: 1; }
    #cfg-save { margin-top: 1; }
    #modellist, #applist { height: 1fr; border: round $primary; }
    #appfilter { dock: top; }
    #doclist { width: 38; border: round $primary; }
    #docbody-wrap { border: round $primary; }
    #docbody { padding: 0 2; }
    #team-box { border: round $primary; padding: 1 2; }
    """
    BINDINGS = [
        Binding("ctrl+c,ctrl+q", "quit", "Quit"),
        Binding("1", "tab('chat')", "Chat"),
        Binding("2", "tab('system')", "System"),
        Binding("3", "tab('models')", "Models"),
        Binding("4", "tab('apps')", "Apps"),
        Binding("5", "tab('tasks')", "Tasks"),
        Binding("6", "tab('logs')", "Logs"),
        Binding("7", "tab('config')", "Config"),
        Binding("8", "tab('docs')", "Docs"),
        Binding("9", "tab('team')", "Team"),
        Binding("0", "tab('spaces')", "Spaces"),
        Binding("a", "tab('audit')", "Audit"),
    ]

    def __init__(self, port: int, cfg: dict):
        super().__init__()
        self.port = port
        self.cfg = cfg
        self.model = cfg.get("default_model", "")
        self.agent_name = cfg.get("agent_name", "Aria")
        self.cid = None
        self.title = "AgentOS"

    # ---- layout ----
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="chat", id="tabs"):
            with TabPane("💬 Chat", id="chat"):
                yield RichLog(id="chatlog", wrap=True, markup=True, highlight=True)
                yield Input(placeholder=f"Ask {self.agent_name}…  (Enter to send)", id="chatinput")
            with TabPane("📊 System", id="system"):
                yield Static(id="sysbars")
                yield DataTable(id="systable")
            with TabPane("🧠 Models", id="models"):
                yield Static(id="gpuinfo")
                yield ListView(id="modellist")
            with TabPane("🗔 Apps", id="apps"):
                yield Input(placeholder="Filter installed apps…  (Enter on a row to launch)", id="appfilter")
                yield ListView(id="applist")
            with TabPane("⏱ Tasks", id="tasks"):
                yield DataTable(id="taskstable")
            with TabPane("📜 Logs", id="logs"):
                yield RichLog(id="logslog", wrap=True, markup=True)
            with TabPane("📖 Docs", id="docs"):
                with Horizontal():
                    yield ListView(id="doclist")
                    with VerticalScroll(id="docbody-wrap"):
                        yield Static("Pick a guide on the left.", id="docbody")
            with TabPane("👥 Team", id="team"):
                with VerticalScroll(id="team-box"):
                    yield Static("", id="team-body")
            # Spaces and the timeline are a chronological list and a short menu —
            # both native to a terminal, so this is a face where the TUI is not a
            # lesser version of the GUI. The Gallery is the opposite case and is
            # deliberately an inventory here, not a viewer: a terminal cannot show
            # a video, and pretending otherwise would be the dead-control failure.
            with TabPane("▣ Spaces", id="spaces"):
                with VerticalScroll(id="spaces-box"):
                    yield Static("", id="spaces-body")
            with TabPane("⚖ Audit", id="audit"):
                with VerticalScroll(id="audit-box"):
                    yield Static("", id="audit-body")
            with TabPane("⚙ Config", id="config"):
                with VerticalScroll(id="cfg-box"):
                    yield Label("Agent name")
                    yield Input(value=self.agent_name, id="cfg-name")
                    yield Label("Autonomy")
                    yield Select([("Paranoid", "paranoid"), ("Balanced", "balanced"), ("Full", "full")],
                                 value=self.cfg.get("autonomy", "balanced"), id="cfg-autonomy", allow_blank=False)
                    # Autonomy says how much the agent may do on your say-so; this
                    # says how much a fetched page may do on its own (policy.py).
                    yield Label("After reading untrusted content (a web page, an MCP reply)")
                    yield Select([("Ask before changing anything", "ask"),
                                  ("Refuse to change anything", "strict"),
                                  ("No extra caution", "off")],
                                 value=(self.cfg.get("security") or {}).get("taint", "ask"),
                                 id="cfg-taint", allow_blank=False)
                    yield Label("Default model")
                    yield Select([], id="cfg-model", allow_blank=True)
                    yield Static("── Providers ──", classes="section")
                    yield Label("Ollama base URL")
                    yield Input(id="cfg-ollama")
                    yield Checkbox("Anthropic (Claude)", id="cfg-ant-on")
                    yield Input(placeholder="sk-ant-… API key", id="cfg-ant-key")
                    yield Input(placeholder="models, comma-separated (e.g. claude-sonnet-4.5)", id="cfg-ant-models")
                    yield Checkbox("OpenAI", id="cfg-oai-on")
                    yield Input(placeholder="sk-… API key", id="cfg-oai-key")
                    yield Input(placeholder="models (e.g. gpt-4o, gpt-4o-mini)", id="cfg-oai-models")
                    yield Checkbox("OpenRouter", id="cfg-or-on")
                    yield Input(placeholder="sk-or-… API key", id="cfg-or-key")
                    yield Input(placeholder="models (e.g. anthropic/claude-sonnet-4.5)", id="cfg-or-models")
                    yield Button("Save", variant="primary", id="cfg-save")
                    yield Static("", id="cfg-status")
        yield Footer()

    # ---- lifecycle ----
    def on_mount(self):
        self.sub_title = f"{self.agent_name} · {self.model or 'no model'}"
        self.query_one("#systable", DataTable).add_columns("PID", "Process", "CPU%", "MEM%")
        self.query_one("#taskstable", DataTable).add_columns("Prompt", "Schedule", "Next / last")
        self.query_one("#chatlog", RichLog).write(
            f"[b cyan]{self.agent_name}[/]  ready. Type below. Use number keys to switch tabs, Ctrl-Q to quit.\n")
        self.refresh_system()
        self.refresh_models()
        self.refresh_apps()
        self.refresh_tasks()
        self.refresh_logs()
        self.refresh_docs()
        self.refresh_team()
        self.refresh_spaces()
        self.refresh_audit()
        self.load_cfg_form()
        self.set_interval(2.0, self.refresh_system)
        self.set_interval(6.0, self.refresh_logs)
        self.set_interval(8.0, self.refresh_team)
        self.set_interval(10.0, self.refresh_spaces)
        self.set_interval(10.0, self.refresh_audit)

    @work(group="cfgload")
    async def load_cfg_form(self):
        d = await self.api_get("/api/config")
        p = d.get("providers", {})
        try:
            self.query_one("#cfg-ollama", Input).value = p.get("ollama", {}).get("base_url", "")
            for prov, pre in (("anthropic", "ant"), ("openai", "oai"), ("openrouter", "or")):
                pr = p.get(prov, {})
                self.query_one(f"#cfg-{pre}-on", Checkbox).value = bool(pr.get("enabled"))
                self.query_one(f"#cfg-{pre}-key", Input).value = pr.get("api_key", "")  # masked from server
                self.query_one(f"#cfg-{pre}-models", Input).value = ", ".join(pr.get("models", []))
        except Exception:
            pass

    async def api_get(self, path):
        try:
            async with httpx.AsyncClient(timeout=6) as c:
                return (await c.get(_base(self.port) + path)).json()
        except Exception:
            return {}

    async def api(self, method, path, body=None):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.request(method, _base(self.port) + path, json=body)
                return r.json() if r.content else {}
        except Exception as e:
            return {"error": str(e)}

    # ---- tabs ----
    def action_tab(self, tab: str):
        self.query_one("#tabs", TabbedContent).active = tab

    # ---- system ----
    @work(exclusive=True, group="sys")
    async def refresh_system(self):
        d = await self.api_get("/api/system")
        if not d:
            return
        mem = d.get("mem", {}); du = d.get("disk", {})
        memp = 100 * mem.get("used_kb", 0) / max(mem.get("total_kb", 1), 1)
        dskp = 100 * du.get("used", 0) / max(du.get("total", 1), 1)
        def bar(p):
            n = int(p / 5)
            col = "red" if p > 85 else "cyan"
            return f"[{col}]{'█'*n}[/][grey37]{'░'*(20-n)}[/]"
        self.query_one("#sysbars", Static).update(
            f"[b]CPU[/]  {bar(d.get('cpu',0))} {d.get('cpu',0):4.0f}%\n"
            f"[b]MEM[/]  {bar(memp)} {memp:4.0f}%   {mem.get('used_kb',0)/1e6:.1f}/{mem.get('total_kb',1)/1e6:.0f} GB\n"
            f"[b]DISK[/] {bar(dskp)} {dskp:4.0f}%   {du.get('used',0)/1e9:.0f}/{du.get('total',0)/1e9:.0f} GB\n"
            f"[grey58]{d.get('cores','?')} cores · load {' '.join(f'{x:.2f}' for x in d.get('load',[]))}[/]")
        t = self.query_one("#systable", DataTable)
        t.clear()
        for p in d.get("procs", [])[:14]:
            t.add_row(str(p["pid"]), p["name"][:28], f"{p['cpu']:.1f}", f"{p['mem']:.1f}")

    # ---- models ----
    @work(exclusive=True, group="models")
    async def refresh_models(self):
        d = await self.api_get("/api/models")
        mgr = await self.api_get("/api/models/manage")
        gpus = mgr.get("gpu", [])
        if gpus:
            g = gpus[0]
            self.query_one("#gpuinfo", Static).update(
                f"[b]GPU[/] {g['name']} · {g['mem_used_mb']/1024:.1f}/{g['mem_total_mb']/1024:.0f} GB · {g['util']}%")
        lv = self.query_one("#modellist", ListView)
        lv.clear()
        opts = []
        for m in d.get("models", []):
            mark = "● " if m["id"] == self.model else "  "
            lv.append(ListItem(Label(f"{mark}{m['id']}"), id="m_" + m["id"].replace("/", "__").replace(".", "_").replace(":", "_")))
            opts.append((m["id"], m["id"]))
        try:
            sel = self.query_one("#cfg-model", Select)
            sel.set_options(opts)
            if self.model:
                sel.value = self.model
        except Exception:
            pass
        self._model_ids = [m["id"] for m in d.get("models", [])]

    async def on_list_view_selected(self, e: ListView.Selected):
        if e.list_view.id == "modellist":
            idx = list(e.list_view.children).index(e.item)
            ids = getattr(self, "_model_ids", [])
            if idx < len(ids):
                self.model = ids[idx]
                await self.api("PUT", "/api/config", {"default_model": self.model})
                self.sub_title = f"{self.agent_name} · {self.model}"
                self.refresh_models()
                self.notify(f"model → {self.model}")
        elif e.list_view.id == "applist":
            app = getattr(e.item, "_appid", None)
            if app:
                r = await self.api("POST", "/api/native/launch", {"id": app})
                self.notify("launched" if r.get("ok") else f"failed: {r.get('message','')}")
        elif e.list_view.id == "doclist":
            f = getattr(e.item, "_docfile", None)
            if f:
                self.show_doc(f)

    # ---- apps ----
    @work(exclusive=True, group="apps")
    async def refresh_apps(self, flt: str = ""):
        d = await self.api_get("/api/native/apps")
        self._apps = d.get("apps", [])
        self._render_apps(flt)

    def _render_apps(self, flt=""):
        lv = self.query_one("#applist", ListView)
        lv.clear()
        q = flt.lower()
        for a in getattr(self, "_apps", []):
            if q and q not in a["name"].lower():
                continue
            it = ListItem(Label(a["name"]))
            it._appid = a["id"]
            lv.append(it)

    # ---- docs ----
    @work(exclusive=True, group="docs")
    async def refresh_docs(self):
        d = await self.api_get("/api/docs")
        self._docs = d.get("docs", [])
        lv = self.query_one("#doclist", ListView)
        lv.clear()
        for doc in self._docs:
            it = ListItem(Label(f"📖 {doc['title'][:32]}"))
            it._docfile = doc["file"]
            lv.append(it)

    @work(group="docs")
    async def show_doc(self, file: str):
        from rich.markdown import Markdown
        d = await self.api_get("/api/docs/" + file)
        body = self.query_one("#docbody", Static)
        body.update(Markdown(d.get("content", "(not found)")))
        self.query_one("#docbody-wrap", VerticalScroll).scroll_home(animate=False)

    # ---- team: subagents + data-plane observability ----
    @work(exclusive=True, group="team")
    async def refresh_team(self):
        sa = await self.api_get("/api/subagents")
        obs = await self.api_get("/api/fabric/observability")
        lines = ["[b]Subagents[/b] — address one in Chat with [b cyan]@name your task[/b cyan]\n"]
        for s in sa.get("subagents", []):
            tools = f"{len(s['tools'])} tools" if s.get("tools") else "safe read-only set"
            lines.append(f"  [b]{s['name']:<14}[/b] {s.get('model') or 'inherits OS model':<28} "
                         f"{tools} · ≤ {s.get('autonomy_cap','balanced')}")
            if s.get("soul"):
                lines.append(f"      [grey58]{s['soul'][:88]}[/]")
        lines.append("\n[b]Data planes — faults · performance · usage[/b]\n")
        m = obs.get("main_agent", {})
        lines.append(f"  {'main agent (L0)':<26} runs {m.get('runs',0):<5} "
                     f"faults {m.get('faults',0):<5} tok {m.get('tokens_in',0)+m.get('tokens_out',0)}")
        for name, p in (obs.get("per_plane") or {}).items():
            avg = round(p["secs"] / p["runs"]) if p.get("runs") else 0
            lines.append(f"  {name:<26} runs {p['runs']:<5} faults {p['faults']:<5} "
                         f"avg {avg}s · tok {p['tokens_in']+p['tokens_out']}")
        live = obs.get("live") or []
        if live:
            lines.append("\n[b]Live now[/b]")
            for i in live:
                lines.append(f"  {i['ref']} — heartbeat {round(__import__('time').time()-i['last_beat'])}s ago"
                             + ("  [red]STALE[/red]" if i.get("stale") else ""))
        for f in (obs.get("recent_faults") or [])[:5]:
            lines.append(f"  [red]fault[/red] {f['ref']}: {str(f.get('fault',''))[:70]}")
        try:
            self.query_one("#team-body", Static).update("\n".join(lines))
        except Exception:
            pass

    # ---- spaces, timeline and the gallery inventory ----
    @work(exclusive=True, group="spaces")
    async def refresh_spaces(self):
        sp = await self.api_get("/api/spaces")
        active = (sp.get("active") or {}).get("tui", "")
        spaces = sp.get("spaces") or []
        by_id = {s["id"]: s for s in spaces}
        here = by_id.get(active, {}).get("name", "Everywhere")
        lines = [f"[b]Working in:[/b] [cyan]{here}[/cyan]"
                 "   [grey58]agentos space <name>  ·  agentos space --none[/]\n",
                 "[b]Spaces[/b] — a space sees its own memory AND what is true everywhere\n"]
        if not spaces:
            lines.append("  [grey58](none yet — everything is shared. "
                         "Make one when a project starts accumulating its own context.)[/]")
        for s in spaces:
            mark = "[cyan]●[/cyan]" if s["id"] == active else " "
            lines.append(f"  {mark} [b]{s['name'][:22]:<22}[/b] {(s.get('description') or '')[:60]}")

        qs = f"?space={active}" if active else ""
        tl = await self.api_get("/api/timeline" + qs + ("&" if qs else "?") + "limit=15")
        lines.append("\n[b]Timeline[/b] — milestones, not messages\n")
        events = tl.get("events") or []
        if not events:
            lines.append("  [grey58](nothing recorded yet)[/]")
        for e in events:
            when = time.strftime("%d %b %H:%M", time.localtime(e.get("ts", 0)))
            lines.append(f"  [grey58]{when}[/]  [{e.get('kind','')}] {str(e.get('title',''))[:64]}")

        assets = await self.api_get("/api/assets" + qs + ("&" if qs else "?") + "limit=10")
        cap = assets.get("capability") or {}
        lines.append("\n[b]Gallery[/b] — a terminal cannot show a picture, so this is the "
                     "inventory; [b cyan]agentos assets[/b cyan] opens or exports one\n")
        for a in (assets.get("assets") or []):
            size = f"{(a.get('bytes') or 0)//1024} KB"
            extra = (f" · {a['duration']:.0f}s" if a.get("duration") else "")
            lines.append(f"  [grey58]{a['id']}[/]  {a.get('kind',''):<6} {size:>8}{extra}  "
                         f"{str(a.get('title',''))[:40]}")
        if not (assets.get("assets") or []):
            lines.append("  [grey58](empty)[/]")
        if not cap.get("ffmpeg", True):
            lines.append(f"\n  [yellow]{cap.get('why','')}[/yellow]")
            lines.append(f"  [grey58]install the '{cap.get('component','ffmpeg')}' component to "
                         f"measure and thumbnail media here[/]")
        try:
            self.query_one("#spaces-body", Static).update("\n".join(lines))
        except Exception:
            pass

    # ---- audit: the access ledger ----
    @work(exclusive=True, group="audit")
    async def refresh_audit(self):
        since = time.time() - 24 * 3600
        d = await self.api_get(f"/api/audit?limit=60&since={since:.0f}")
        s = await self.api_get(f"/api/audit/summary?since={since:.0f}")
        eff = s.get("effects") or {}
        lines = ["[b]Access ledger[/b] — last 24h: "
                 f"[green]{eff.get('allow',0)} allowed[/green] · "
                 f"[red]{eff.get('deny',0)} denied[/red] · "
                 f"[yellow]{eff.get('ask',0)} asked[/yellow]\n"]
        top = s.get("top_denied") or []
        if top:
            lines.append("[b]Most refused[/b]")
            for t in top[:5]:
                lines.append(f"  [red]{t['n']}×[/red] {t['action']} {str(t['resource'])[:56]}")
            lines.append("")
        lines.append("[b]Decisions[/b]")
        for a in (d.get("entries") or []):
            colour = {"allow": "green", "deny": "red", "ask": "yellow"}.get(a.get("effect"), "white")
            who = f"{a['principal_kind']}:{a['principal_id']}" if a.get("principal_id") else a.get("principal_kind", "")
            when = time.strftime("%H:%M:%S", time.localtime(a.get("ts", 0)))
            lines.append(f"  [grey58]{when}[/] [{colour}]{a.get('effect',''):<5}[/{colour}] "
                         f"{a.get('action',''):<14} {str(a.get('resource',''))[:44]}")
            lines.append(f"          [grey58]{who} via {a.get('surface') or 'unknown'} "
                         f"· rule {a.get('rule','')}[/]")
        if not (d.get("entries") or []):
            lines.append("  [grey58](nothing in the last 24 hours)[/]")
        try:
            self.query_one("#audit-body", Static).update("\n".join(lines))
        except Exception:
            pass

    # ---- tasks ----
    @work(exclusive=True, group="tasks")
    async def refresh_tasks(self):
        d = await self.api_get("/api/tasks")
        t = self.query_one("#taskstable", DataTable)
        t.clear()
        for tk in d.get("tasks", []):
            sch = (tk.get("schedule_type") or "")
            when = tk.get("last_result", "") or ("enabled" if tk.get("enabled") else "disabled")
            t.add_row(tk.get("prompt", "")[:44], sch, str(when)[:30])

    # ---- logs ----
    @work(exclusive=True, group="logs")
    async def refresh_logs(self):
        d = await self.api_get("/api/logs?limit=40")
        rl = self.query_one("#logslog", RichLog)
        rl.clear()
        col = {"error": "red", "tool": "cyan", "turn": "green", "telegram": "blue",
               "mcp": "magenta", "system": "grey58"}
        for L in reversed(d.get("logs", [])):
            c = col.get(L["kind"], "white")
            rl.write(f"[grey37]{L['kind']:>8}[/] [{c}]{L['message'][:90]}[/]")

    # ---- input / chat ----
    def on_input_submitted(self, e: Input.Submitted):
        if e.input.id == "appfilter":
            self._render_apps(e.value.strip())
        elif e.input.id == "chatinput":
            text = e.value.strip()
            if text:
                e.input.value = ""
                self.query_one("#chatlog", RichLog).write(f"\n[b]you[/]  {text}")
                self.send_chat(text)

    def on_button_pressed(self, e: Button.Pressed):
        if e.button.id == "cfg-save":
            self.save_config()

    @work(group="cfg")
    async def save_config(self):
        name = self.query_one("#cfg-name", Input).value.strip() or "Aria"
        model = self.query_one("#cfg-model", Select).value
        auton = self.query_one("#cfg-autonomy", Select).value
        taint = self.query_one("#cfg-taint", Select).value
        patch = {"agent_name": name, "autonomy": auton, "security": {"taint": taint}}
        if model and model != Select.BLANK:
            patch["default_model"] = model
            self.model = model
        # providers — a masked key ("•••…") is treated as "unchanged" by the server
        def models(pre):
            return [m.strip() for m in self.query_one(f"#cfg-{pre}-models", Input).value.split(",") if m.strip()]
        providers = {"ollama": {"base_url": self.query_one("#cfg-ollama", Input).value.strip()}}
        for prov, pre in (("anthropic", "ant"), ("openai", "oai"), ("openrouter", "or")):
            providers[prov] = {
                "enabled": self.query_one(f"#cfg-{pre}-on", Checkbox).value,
                "api_key": self.query_one(f"#cfg-{pre}-key", Input).value.strip(),
                "models": models(pre),
            }
        patch["providers"] = providers
        await self.api("PUT", "/api/config", patch)
        self.agent_name = name
        self.sub_title = f"{self.agent_name} · {self.model}"
        self.query_one("#cfg-status", Static).update("[green]saved ✓  (switch models in the Models tab)[/]")
        self.refresh_models()

    @work(group="chat")
    async def send_chat(self, text: str):
        import websockets
        log = self.query_one("#chatlog", RichLog)
        ws_url = f"ws://127.0.0.1:{self.port}/ws"
        try:
            async with websockets.connect(ws_url, max_size=None) as ws:
                await ws.send(json.dumps({"type": "chat", "text": text, "surface": "tui",
                                          "conversation_id": self.cid, "model": self.model}))
                log.write(f"[b cyan]{self.agent_name}[/]  ")
                buf = ""
                while True:
                    ev = json.loads(await ws.recv())
                    t = ev.get("type")
                    # events are broadcast to every client — only render this chat's
                    ecid = ev.get("conversation_id")
                    if ecid and self.cid and ecid != self.cid:
                        continue
                    if t == "conversation":
                        self.cid = ev["id"]
                    elif t == "text_delta":
                        buf += ev["text"]
                        while "\n" in buf:  # stream complete lines as they arrive
                            line, buf = buf.split("\n", 1)
                            log.write(line)
                    elif t == "status":
                        if ev.get("message"):
                            log.write(f"[grey58]{ev['message']}[/]")
                    elif t == "tool_start":
                        arg = ev["args"].get("command", "") if ev["name"] == "run_command" else ""
                        log.write(f"[grey58]▸ {ev['name']} {arg[:80]}[/]")
                    elif t == "tool_end":
                        if not ev.get("ok", True):
                            log.write(f"[red]✗ {ev.get('name','')} — {(ev.get('output') or '')[:120]}[/]")
                    elif t == "approval_request":
                        detail = ev["args"].get("command", "") if ev["name"] == "run_command" else json.dumps(ev["args"])[:120]
                        ok = await self.push_screen_wait(ApprovalScreen(ev["name"], detail, ev.get("reason", "")))
                        await ws.send(json.dumps({"type": "approval", "id": ev["id"], "approved": bool(ok)}))
                    elif t == "error":
                        log.write(f"[red]error: {ev.get('message','')}[/]")
                    elif t == "turn_end":
                        break
                if buf.strip():
                    log.write(buf.strip())
        except Exception as ex:
            log.write(f"[red]connection error: {ex}[/]")


def run():
    import socket
    cfg = cfgmod.load_config()
    port = cfg.get("port", 8321)
    # start the server if it isn't already up
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except OSError:
        from . import desktop
        desktop._start_server_thread(port)
    AgentTUI(port, cfg).run()

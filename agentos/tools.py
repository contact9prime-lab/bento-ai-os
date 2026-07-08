"""The hands of the OS: tools the agent can call, plus risk classification.

Every tool returns a string (what the model sees). Risk levels:
    safe   — auto-run always
    risky  — auto-run only in 'full' autonomy; otherwise needs user approval
"""

import asyncio
import html.parser
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

import httpx

MAX_OUTPUT = 12_000  # chars of tool output fed back to the model

# Read-only commands that are always safe to run.
SAFE_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "sort", "uniq", "cut",
    "echo", "pwd", "whoami", "id", "date", "cal", "uptime", "uname", "hostname",
    "df", "du", "free", "ps", "top", "lscpu", "lsblk", "lsusb", "lspci", "ip",
    "which", "whereis", "type", "file", "stat", "env", "printenv", "history",
    "git", "diff", "md5sum", "sha256sum", "basename", "dirname", "realpath",
    "xrandr", "sensors", "nvidia-smi", "acpi", "ping", "dig", "nslookup", "host",
    "curl", "wget", "tree", "less", "more", "awk", "sed", "jq", "column", "nl",
}
# Commands never run even with approval.
BLOCKED_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*/(\s|$)",   # rm on filesystem root
    r"\bmkfs\b", r"\bdd\s+.*of=/dev/", r":\(\)\s*\{.*\};:",  # mkfs, raw disk writes, forkbomb
    r"\bshutdown\b", r"\breboot\b", r"\binit\s+0\b",
]
DANGEROUS_META = re.compile(r"[><`$\n]")  # redirects, substitution, multiline
CONNECTORS = re.compile(r"\s*(?:\|\||&&|;|\|)\s*")


def classify_command(command: str) -> str:
    """Return 'safe', 'risky', or 'blocked' for a shell command.

    Safe = every segment of a pipe/&&/; chain is a known read-only command,
    with no redirects or command substitution anywhere.
    """
    for pat in BLOCKED_PATTERNS:
        if re.search(pat, command):
            return "blocked"
    if DANGEROUS_META.search(command):
        return "risky"
    segments = [s for s in CONNECTORS.split(command.strip()) if s.strip()]
    if not segments:
        return "risky"
    for seg in segments:
        parts = seg.strip().split()
        base = os.path.basename(parts[0]) if parts else ""
        if base not in SAFE_COMMANDS:
            return "risky"
        if base in ("sed", "awk", "find") and re.search(r"(^|\s)-i\b|\s-delete\b|\s-exec\b", seg):
            return "risky"  # in-place edits / find -delete / find -exec can write
    return "safe"


class _TextExtractor(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "head"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def sandbox_conf(cfg: dict) -> tuple[bool, str]:
    """(enabled, absolute root). Root defaults to the workspace."""
    sb = cfg.get("sandbox") or {}
    root = os.path.realpath(os.path.expanduser(sb.get("root") or cfg["workspace"]))
    return bool(sb.get("enabled")) and shutil.which("bwrap") is not None, root


def bwrap_argv(root: str, tail: list[str], chdir: str | None = None) -> list[str]:
    """Jail: whole FS read-only, /home hidden, only `root` writable & visible in /home."""
    return ["bwrap",
            "--ro-bind", "/", "/",
            "--tmpfs", "/home",
            "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
            "--bind", root, root,
            "--chdir", chdir or root,
            "--setenv", "HOME", root,
            "--setenv", "AGENTOS_SANDBOX", "1",
            "--die-with-parent",
            *tail]


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


class Toolbox:
    """Executes tools. `store` is a memory.Store; `scheduler` is set by the app."""

    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.scheduler = None  # wired up in server startup
        self.mcp = None        # MCPManager, wired up in server startup
        self.telegram = None   # TelegramBridge, wired up in server startup
        self.broadcast = None  # UI event broadcaster, wired up in server startup

    def schemas(self) -> list[dict]:
        """Built-in tool schemas plus tools from connected MCP servers."""
        out = [dict(t) for t in TOOL_SCHEMAS]
        if self.mcp:
            for t in self.mcp.tool_schemas():
                out.append({k: v for k, v in t.items() if not k.startswith("_")})
        return out

    # -- tool implementations ----------------------------------------------

    def _sandbox_deny(self, path) -> str | None:
        enabled, root = sandbox_conf(self.cfg)
        if not enabled:
            return None
        rp = os.path.realpath(str(path))
        if rp == root or rp.startswith(root + os.sep):
            return None
        return f"[denied] sandbox mode: only paths inside {root} are accessible (see Settings → Sandbox)"

    async def run_command(self, command: str, cwd: str = "") -> str:
        enabled, root = sandbox_conf(self.cfg)
        if enabled:
            workdir = os.path.realpath(os.path.expanduser(cwd)) if cwd else root
            if not (workdir == root or workdir.startswith(root + os.sep)) or not os.path.isdir(workdir):
                workdir = root
            os.makedirs(root, exist_ok=True)
            proc = await asyncio.create_subprocess_exec(
                *bwrap_argv(root, ["/bin/bash", "-lc", command], chdir=workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        else:
            workdir = os.path.expanduser(cwd) if cwd else os.path.expanduser(self.cfg["workspace"])
            if not os.path.isdir(workdir):
                workdir = os.path.expanduser("~")
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
            )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            proc.kill()
            return "[error] command timed out after 120s"
        text = out.decode(errors="replace")
        code = proc.returncode
        result = _truncate(text) if text.strip() else "(no output)"
        return result if code == 0 else f"[exit code {code}]\n{result}"

    async def read_file(self, path: str) -> str:
        p = Path(os.path.expanduser(path))
        if (deny := self._sandbox_deny(p)):
            return deny
        if not p.exists():
            return f"[error] file not found: {p}"
        if p.stat().st_size > 2_000_000:
            return f"[error] file too large ({p.stat().st_size} bytes)"
        try:
            return _truncate(p.read_text(errors="replace"))
        except IsADirectoryError:
            return f"[error] {p} is a directory — use list_dir"

    async def write_file(self, path: str, content: str) -> str:
        p = Path(os.path.expanduser(path))
        if (deny := self._sandbox_deny(p)):
            return deny
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return f"wrote {len(content)} chars to {p}"

    async def list_dir(self, path: str = "") -> str:
        p = Path(os.path.expanduser(path or self.cfg["workspace"]))
        if (deny := self._sandbox_deny(p)):
            return deny
        if not p.is_dir():
            return f"[error] not a directory: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries[:300]]
        return f"{p}\n" + ("\n".join(lines) if lines else "(empty)")

    async def fetch_url(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                     headers={"User-Agent": "AgentOS/0.1"}) as client:
            r = await client.get(url)
        ctype = r.headers.get("content-type", "")
        if "html" in ctype:
            ex = _TextExtractor()
            ex.feed(r.text)
            return _truncate(f"[{r.status_code}] {url}\n" + "\n".join(ex.parts))
        return _truncate(f"[{r.status_code}] {url}\n{r.text}")

    async def system_info(self) -> str:
        info = {
            "os": f"{platform.system()} {platform.release()}",
            "hostname": platform.node(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        try:
            la = os.getloadavg()
            info["load_avg"] = f"{la[0]:.2f} {la[1]:.2f} {la[2]:.2f}"
        except OSError:
            pass
        try:
            mem = {}
            for line in Path("/proc/meminfo").read_text().splitlines()[:3]:
                k, v = line.split(":", 1)
                mem[k.strip()] = v.strip()
            info["memory"] = mem
        except OSError:
            pass
        du = shutil.disk_usage(os.path.expanduser("~"))
        info["disk_home"] = f"{du.used / 1e9:.1f}GB used / {du.total / 1e9:.1f}GB total"
        return json.dumps(info, indent=2)

    async def open_app(self, target: str) -> str:
        subprocess.Popen(
            ["xdg-open", target],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return f"opened: {target}"

    async def notify(self, title: str, message: str = "") -> str:
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, message],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "notification sent"
        return "[error] notify-send not available"

    async def remember(self, content: str) -> str:
        mid = self.store.add_memory(content)
        return f"remembered (id {mid})"

    async def recall(self, query: str = "") -> str:
        mems = self.store.search_memories(query, limit=15)
        if not mems:
            return "(no memories found)"
        return "\n".join(
            f"- [{m['id']}] {time.strftime('%Y-%m-%d', time.localtime(m['created_at']))}: {m['content']}"
            for m in mems
        )

    async def generate_wallpaper(self, prompt: str) -> str:
        """AI-generate a high-res desktop wallpaper from a text prompt (pollinations.ai flux, free, no key).
        Saves to the local gallery and applies it as the current wallpaper."""
        import time as _t
        import urllib.parse
        from . import config as cfgmod
        # flux model for the best detail this free service offers (it caps output at ~1024x576;
        # CSS scales it to fill the screen). For true-HD wallpaper use set_wallpaper with a file/URL.
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:400])
               + "?width=1280&height=720&model=flux&nologo=true&enhance=true&nofeed=true")
        async with httpx.AsyncClient(timeout=240.0, follow_redirects=True,
                                     headers={"User-Agent": "AgentOS/0.1"}) as client:
            r = await client.get(url)
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
            return f"[error] image generation failed (HTTP {r.status_code}) — is the machine online?"
        gallery = cfgmod.AGENTOS_HOME / "wallpapers"
        gallery.mkdir(parents=True, exist_ok=True)
        (gallery / f"{int(_t.time())}.png").write_bytes(r.content)       # keep in the gallery
        (cfgmod.AGENTOS_HOME / "wallpaper.png").write_bytes(r.content)   # apply as current
        self.store.log("system", f"wallpaper generated: {prompt[:120]}")
        if self.broadcast:
            await self.broadcast({"type": "wallpaper"})
        return (f"wallpaper generated ({len(r.content) // 1024} KB), saved to the gallery, and applied. "
                f"(The free image service caps resolution; for a true-HD background, use set_wallpaper "
                f"with a photo file or an image URL.)")

    async def set_wallpaper(self, source: str = "") -> str:
        """Set the desktop wallpaper from a local file or URL; empty source resets to the default."""
        from . import config as cfgmod
        dest = cfgmod.AGENTOS_HOME / "wallpaper.png"
        if not source.strip():
            dest.unlink(missing_ok=True)
            if self.broadcast:
                await self.broadcast({"type": "wallpaper"})
            return "wallpaper reset to the default"
        if source.startswith(("http://", "https://")):
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                r = await client.get(source)
            if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image"):
                return f"[error] not an image (HTTP {r.status_code})"
            dest.write_bytes(r.content)
        else:
            p = Path(os.path.expanduser(source))
            if not p.is_file():
                return f"[error] file not found: {p}"
            dest.write_bytes(p.read_bytes())
        if self.broadcast:
            await self.broadcast({"type": "wallpaper"})
        return f"wallpaper set from {source}"

    async def kg_add(self, subject: str, relation: str, object: str,
                     subject_type: str = "", object_type: str = "") -> str:
        eid = self.store.kg_add(subject, relation, object, subject_type, object_type)
        return f"added to knowledge graph: {subject} —{relation}→ {object} (edge {eid})"

    async def kg_query(self, query: str = "") -> str:
        lines = self.store.kg_query(query)
        if not lines:
            return "(knowledge graph has no matching facts)"
        return "\n".join(lines)

    async def update_soul(self, content: str) -> str:
        from . import config as cfgmod
        if len(content.strip()) < 40:
            return "[error] refusing to overwrite the soul with something that short — pass the full new soul text"
        cfgmod.save_soul(content)
        return f"soul updated ({len(content)} chars)"

    async def configure_agentos(self, changes: str) -> str:
        """Apply a JSON config patch to AgentOS itself (autonomy, model, name, policies, MCP, telegram)."""
        from . import config as cfgmod
        try:
            patch = json.loads(changes) if isinstance(changes, str) else dict(changes)
        except Exception as e:
            return f"[error] changes must be a valid JSON object: {e}"
        if not isinstance(patch, dict):
            return "[error] changes must be a JSON object"
        allowed = {"agent_name", "default_model", "autonomy", "max_steps", "workspace",
                   "policies", "telegram", "mcp_servers", "sandbox"}
        applied, skipped = [], []
        for k, v in patch.items():
            if k not in allowed:
                skipped.append(k)
                continue
            if k in ("telegram", "mcp_servers") and isinstance(v, dict):
                target = self.cfg.setdefault(k, {})
                for kk, vv in v.items():
                    if vv is None:
                        target.pop(kk, None)   # null deletes an entry (e.g. remove an MCP server)
                    else:
                        target[kk] = vv
            else:
                self.cfg[k] = v
            applied.append(k)
        if not applied:
            return f"[error] nothing applied; allowed keys: {sorted(allowed)}"
        cfgmod.save_config(self.cfg)
        self.store.log("system", f"config changed by agent: {', '.join(applied)}")
        if "mcp_servers" in applied and self.mcp:
            await self.mcp.reload()
        if self.broadcast:
            await self.broadcast({"type": "config"})
        note = f" (ignored unknown keys: {', '.join(skipped)})" if skipped else ""
        return "updated: " + ", ".join(applied) + note

    async def create_app(self, name: str, icon: str, description: str, html: str) -> str:
        """Create/update a UI app that appears on the AgentOS desktop (rendered in a window)."""
        if len(html.strip()) < 20:
            return "[error] html too short — pass the full app markup (HTML/CSS/JS)"
        aid = self.store.save_app(name, icon or "🧰", description, html)
        self.store.log("system", f"app created by agent: {name}")
        if self.broadcast:
            await self.broadcast({"type": "apps"})
        return (f"app '{name}' ({icon}) saved with id {aid} — it now has a desktop icon and opens in a window. "
                f"It can call the AgentOS REST API (e.g. GET /api/tasks, /api/system, POST /api/chat).")

    def _repo_root(self):
        return Path(__file__).resolve().parent.parent   # the AgentOS source checkout

    def _repo_path(self, rel: str):
        root = self._repo_root()
        p = (root / rel).resolve()
        if not (p == root or str(p).startswith(str(root) + os.sep)):
            return None
        return p

    async def read_source(self, path: str) -> str:
        """Read a file from AgentOS's OWN source tree (to understand/extend the OS itself)."""
        p = self._repo_path(path)
        if p is None:
            return "[error] path escapes the AgentOS source tree"
        if not p.exists():
            # help the model discover the layout
            root = self._repo_root()
            listing = "\n".join(sorted(str(x.relative_to(root)) for x in root.rglob("*.py")
                                       if ".venv" not in str(x) and "__pycache__" not in str(x))[:60])
            return f"[error] not found: {path}\n\nAgentOS source files:\n{listing}"
        return _truncate(p.read_text(errors="replace"))

    def _make_snapshot(self, label: str = "") -> str:
        import json as _j
        import shutil
        import time as _t
        from . import config as cfgmod
        sid = str(int(_t.time()))
        d = cfgmod.AGENTOS_HOME / "snapshots" / sid
        d.mkdir(parents=True, exist_ok=True)
        for f in ("config.json", "soul.md", "agentos.db"):
            if (cfgmod.AGENTOS_HOME / f).exists():
                shutil.copy2(cfgmod.AGENTOS_HOME / f, d / f)
        src = Path(__file__).resolve().parent
        shutil.copytree(src, d / "agentos", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                        dirs_exist_ok=True)
        (d / "meta.json").write_text(_j.dumps({"label": label, "created_at": _t.time()}))
        return sid

    async def snapshot_os(self, label: str = "") -> str:
        """Save a restore point of the whole OS (config, data, and source) you can roll back to."""
        sid = self._make_snapshot(label)
        self.store.log("system", f"snapshot created by agent: {sid} {label}")
        if self.broadcast:
            await self.broadcast({"type": "snapshots"})
        return f"snapshot '{label or sid}' saved (id {sid}) — restore it from the Snapshots app if needed"

    async def develop_agentos(self, path: str, content: str, restart: bool = False) -> str:
        """Write a file into AgentOS's OWN source tree — modify or extend the operating system itself
        (e.g. add a new integration like WhatsApp). Set restart=true to reload the service after."""
        p = self._repo_path(path)
        if p is None:
            return "[error] path escapes the AgentOS source tree"
        p.parent.mkdir(parents=True, exist_ok=True)
        # always snapshot before touching our own source — corruption insurance
        snap = self._make_snapshot(f"auto before editing {path}")
        # syntax-check python before writing so we never brick the OS with a parse error
        if p.suffix == ".py":
            import ast
            try:
                ast.parse(content)
            except SyntaxError as e:
                return f"[error] refused: Python syntax error (line {e.lineno}): {e.msg}"
        prev = p.read_text(errors="replace") if p.exists() else ""
        (p.parent / (p.name + ".bak")).write_text(prev) if prev else None  # keep a backup
        p.write_text(content)
        self.store.log("system", f"AgentOS source modified: {path}"
                       + (" (restarting)" if restart else ""))
        msg = f"wrote {len(content)} chars to AgentOS source at {path} (snapshot {snap} saved first)"
        if restart:
            subprocess.Popen(["systemctl", "--user", "restart", "agentos.service"],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            msg += " — restarting AgentOS now (reconnect in a few seconds)"
        else:
            msg += ". Call again with restart=true (or use restart_agentos) to load the change."
        return msg

    async def restart_agentos(self) -> str:
        """Restart the AgentOS service to load code changes."""
        subprocess.Popen(["systemctl", "--user", "restart", "agentos.service"],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.store.log("system", "AgentOS restart requested by agent")
        return "restarting AgentOS — the UI will reconnect in a few seconds"

    async def add_mcp_server(self, name: str, command: str = "", url: str = "",
                             args: str = "", env: str = "", action: str = "add") -> str:
        """Add/remove an MCP server ('channel') the agent can then use. stdio: give `command` (+ optional
        `args`); http: give `url`. `env` is optional 'KEY=val,KEY2=val2' for API keys."""
        from . import config as cfgmod
        servers = self.cfg.setdefault("mcp_servers", {})
        key = name.strip().replace(" ", "-")
        if action == "remove":
            servers.pop(key, None)
            msg = f"removed MCP server '{key}'"
        else:
            if url.strip():
                conf = {"transport": "http", "url": url.strip(), "enabled": True}
            elif command.strip():
                conf = {"transport": "stdio", "command": command.strip(),
                        "args": args.strip(), "enabled": True}
            else:
                return "[error] provide either a command (stdio) or a url (http)"
            if env.strip():
                conf["env"] = {}
                for pair in env.split(","):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        conf["env"][k.strip()] = v.strip()
            servers[key] = conf
            msg = f"added MCP server '{key}' — connecting now; its tools appear as mcp_{key}_*"
        cfgmod.save_config(self.cfg)
        if self.mcp:
            await self.mcp.reload()
        if self.broadcast:
            await self.broadcast({"type": "config"})
        return msg

    async def delete_skill(self, name: str) -> str:
        """Remove a saved skill by name."""
        s = self.store.get_skill(name)
        if not s:
            return f"[error] no skill named '{name}'"
        self.store.delete_skill(s["id"])
        return f"deleted skill '{s['name']}'"

    async def pin_widget(self, name: str, action: str = "pin") -> str:
        """Pin/unpin a user app as a live desktop widget (persists and restores on startup)."""
        from . import config as cfgmod
        app = next((a for a in self.store.list_apps() if a["name"].lower() == name.strip().lower()), None)
        if not app:
            names = ", ".join(a["name"] for a in self.store.list_apps()) or "(none)"
            return f"[error] no app named '{name}'. Apps: {names}"
        widgets = self.cfg.get("widgets") or []
        if action == "unpin":
            widgets = [w for w in widgets if w.get("app_id") != app["id"]]
            msg = f"unpinned '{app['name']}' from the desktop"
        else:
            if not any(w.get("app_id") == app["id"] for w in widgets):
                n = len(widgets)
                widgets.append({"app_id": app["id"], "x": 40 + (n % 3) * 320,
                                "y": 40 + (n // 3) * 220, "w": 300, "h": 200})
            msg = f"pinned '{app['name']}' to the desktop as a live widget"
        self.cfg["widgets"] = widgets
        cfgmod.save_config(self.cfg)
        if self.broadcast:
            await self.broadcast({"type": "widgets"})
        return msg

    async def save_report(self, title: str, content: str, to_telegram: bool = False) -> str:
        """Save a report as an HTML file in the workspace 'reports' folder (visible in the File Manager,
        opens in the Browser). `content` may be HTML or plain text. Set to_telegram to also send a summary."""
        import re as _re
        import time as _t
        root = os.path.expanduser(self.cfg["workspace"])
        reports = Path(root) / "reports"
        reports.mkdir(parents=True, exist_ok=True)
        slug = _re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "report"
        stamp = _t.strftime("%Y-%m-%d")
        fname = f"{stamp}-{slug}.html"
        body = content if "<" in content and ">" in content else f"<pre>{content}</pre>"
        html = (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
                "<style>body{background:#0e1116;color:#e6ebf2;font-family:-apple-system,Segoe UI,Roboto,sans-serif;"
                "line-height:1.6;max-width:820px;margin:0 auto;padding:34px}h1,h2,h3{color:#5eead4}"
                "a{color:#22d3ee}code,pre{background:#171b22;border:1px solid #232a35;border-radius:6px;padding:2px 6px}"
                "pre{padding:12px;overflow:auto;white-space:pre-wrap}table{border-collapse:collapse;width:100%}"
                "td,th{border:1px solid #232a35;padding:6px 9px;text-align:left}"
                f".meta{{color:#5c6577;font-size:12px;margin-bottom:18px}}</style></head><body>"
                f"<h1>{title}</h1><div class='meta'>Generated {_t.strftime('%Y-%m-%d %H:%M')}</div>{body}</body></html>")
        (reports / fname).write_text(html)
        self.store.log("system", f"report saved: reports/{fname}")
        if self.broadcast:
            await self.broadcast({"type": "files"})
        msg = f"report saved to reports/{fname} (open it in the File Manager or Browser)"
        if to_telegram and self.telegram:
            import html as _h
            plain = _re.sub(r"<[^>]+>", "", content)[:1500]
            r = await self.telegram.send(f"📊 {title}\n\n{_h.unescape(plain)}")
            msg += f" · telegram: {r}"
        return msg

    async def use_skill(self, name: str) -> str:
        s = self.store.get_skill(name)
        if not s:
            names = ", ".join(x["name"] for x in self.store.list_skills()) or "(none)"
            return f"[error] no skill named '{name}'. Available: {names}"
        return f"# Skill: {s['name']}\n{s['content']}"

    async def save_skill(self, name: str, description: str, content: str) -> str:
        sid = self.store.save_skill(name, description, content)
        return f"skill '{name}' saved (id {sid})"

    async def telegram_send(self, message: str) -> str:
        if self.telegram is None:
            return "[error] Telegram bridge not running"
        return await self.telegram.send(message)

    async def schedule_task(self, prompt: str, schedule_type: str,
                            interval_minutes: int = 0, at_time: str = "",
                            delay_minutes: int = 0) -> str:
        if self.scheduler is None:
            return "[error] scheduler not running"
        return self.scheduler.create_task(prompt, schedule_type, interval_minutes, at_time, delay_minutes)

    # -- registry ------------------------------------------------------------

    def _policy(self, name: str, args: dict) -> str | None:
        """Match user policies against '<tool> <command-or-args>'. Deny wins. Returns action or None."""
        import fnmatch
        policies = self.cfg.get("policies") or []
        desc = name + " " + (args.get("command", "") if name == "run_command" else json.dumps(args))
        matched = None
        for p in policies:
            pat = (p.get("match") or "").strip()
            if not pat:
                continue
            if "*" not in pat:
                pat = "*" + pat + "*"
            if fnmatch.fnmatchcase(desc, pat):
                if p.get("action") == "deny":
                    return "deny"
                matched = p.get("action")
        return matched

    def risk_of(self, name: str, args: dict) -> tuple[str, str]:
        """Return (level, reason). level: safe | risky | blocked."""
        # hard blocks are checked before user policies and cannot be overridden
        if name == "run_command":
            level = classify_command(args.get("command", ""))
            if level == "blocked":
                return "blocked", "This command is blocked (destructive to the system)."
        action = self._policy(name, args)
        if action == "deny":
            return "blocked", "Blocked by one of your deny policies (see the Policies app)."
        if action == "allow":
            return "safe", ""
        if name == "run_command":
            if classify_command(args.get("command", "")) == "risky":
                return "risky", "Shell command that may modify the system."
            return "safe", ""
        if name == "write_file":
            return "risky", f"Writes to {args.get('path', '?')}."
        if name == "open_app":
            return "risky", "Launches an application or URL on your desktop."
        if name == "schedule_task":
            return "risky", "Creates a recurring background task."
        if name == "update_soul":
            return "risky", "Rewrites the agent's soul (its persistent identity and behavior)."
        if name == "configure_agentos":
            return "risky", "Changes AgentOS configuration (autonomy, policies, integrations)."
        if name == "create_app":
            return "risky", "Installs a UI app (HTML/JS) onto the AgentOS desktop."
        if name in ("develop_agentos", "restart_agentos"):
            return "risky", "Modifies/restarts AgentOS's own source code (self-modification)."
        if name == "pin_widget":
            return "safe", ""
        if name == "add_mcp_server":
            return "risky", "Connects/removes an external MCP tool server."
        if name.startswith("mcp_"):
            return "risky", "Calls a tool on an external MCP server."
        return "safe", ""

    async def execute(self, name: str, args: dict) -> str:
        if name.startswith("mcp_") and self.mcp:
            target = self.mcp.resolve(name)
            if not target:
                return f"[error] unknown MCP tool: {name}"
            out = await self.mcp.call(target[0], target[1], args)
            self.store.log("mcp", f"{target[0]}/{target[1]}", {"args": args, "ok": not out.startswith("[error]")})
            return _truncate(out)
        fn = getattr(self, name, None)
        if fn is None or name not in {t["name"] for t in TOOL_SCHEMAS}:
            return f"[error] unknown tool: {name}"
        try:
            return await fn(**{k: v for k, v in args.items() if not k.startswith("_")})
        except TypeError as e:
            return f"[error] bad arguments for {name}: {e}"
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"


TOOL_SCHEMAS = [
    {
        "name": "run_command",
        "description": "Run a shell command on the user's Linux machine and return its output. "
                       "Use for anything the OS can do: inspect files, manage processes, install things, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "cwd": {"type": "string", "description": "Working directory (optional)."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path (~ allowed)."}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file, creating parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_dir",
        "description": "List the entries of a directory.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path; defaults to the workspace."}},
        },
    },
    {
        "name": "fetch_url",
        "description": "Fetch a web page or API URL and return its text content.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "system_info",
        "description": "Get a snapshot of the machine: OS, CPU, memory, disk, load, current time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "open_app",
        "description": "Open an application, file, or URL on the user's desktop (via xdg-open).",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "App name, file path, or URL."}},
            "required": ["target"],
        },
    },
    {
        "name": "notify",
        "description": "Show a desktop notification to the user.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "message": {"type": "string"}},
            "required": ["title"],
        },
    },
    {
        "name": "remember",
        "description": "Save a fact to long-term memory so future conversations can use it.",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "The fact to remember."}},
            "required": ["content"],
        },
    },
    {
        "name": "recall",
        "description": "Search long-term memory. Empty query returns the most recent memories.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
    {
        "name": "generate_wallpaper",
        "description": "Generate a desktop wallpaper with AI from a text prompt and apply it to the "
                       "AgentOS desktop. Describe the scene richly (style, colors, mood).",
        "parameters": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "Image description, e.g. 'dark cyberpunk city at dusk, teal neon, cinematic'"}},
            "required": ["prompt"],
        },
    },
    {
        "name": "set_wallpaper",
        "description": "Set the AgentOS desktop wallpaper from a local image file or image URL. "
                       "Empty source resets to the default background.",
        "parameters": {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "Image path or URL; empty to reset."}},
        },
    },
    {
        "name": "kg_add",
        "description": "Add a fact to the knowledge graph as a (subject, relation, object) triple. "
                       "Use for structured knowledge about people, projects, tools, and how they relate — "
                       "e.g. (Piyush, works_at, Accacia). Types are optional labels like person/org/project/tool.",
        "parameters": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "relation": {"type": "string", "description": "snake_case verb, e.g. works_at, uses, depends_on"},
                "object": {"type": "string"},
                "subject_type": {"type": "string"},
                "object_type": {"type": "string"},
            },
            "required": ["subject", "relation", "object"],
        },
    },
    {
        "name": "kg_query",
        "description": "Search the knowledge graph. Returns matching 'subject —relation→ object' facts; "
                       "empty query returns everything (up to 40).",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    },
    {
        "name": "update_soul",
        "description": "Rewrite your soul file — your persistent identity, personality, and values, injected "
                       "into every future conversation. Pass the COMPLETE new markdown (it replaces the old one).",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    },
    {
        "name": "configure_agentos",
        "description": "Reconfigure AgentOS itself. Pass a JSON object with any of: agent_name, "
                       "default_model, autonomy ('paranoid'|'balanced'|'full'), max_steps, workspace, "
                       "policies (list of {action:'allow'|'deny', match:'pattern *'}), "
                       "telegram ({enabled, bot_token}), mcp_servers ({name:{transport:'stdio', command, args, "
                       "env, enabled} or name:null to remove}). Use when the user asks to change settings, "
                       "add MCP servers, set policies, etc.",
        "parameters": {
            "type": "object",
            "properties": {"changes": {"type": "string", "description": "JSON object of config changes."}},
            "required": ["changes"],
        },
    },
    {
        "name": "create_app",
        "description": "Create or update a UI tool/app inside AgentOS itself: it gets a desktop icon and opens "
                       "in a window. Pass self-contained HTML/CSS/JS (a fragment is fine; it is wrapped in a "
                       "dark-themed page). The app runs in an iframe on the same origin, so its JS can call the "
                       "AgentOS REST API: GET /api/system (cpu/mem/disk), /api/tasks, /api/memories, /api/kg, "
                       "/api/logs, and POST /api/chat {text} for one-shot agent calls. Use this when the user asks "
                       "for a new tool, widget, dashboard, or UI enhancement.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "icon": {"type": "string", "description": "single emoji"},
                "description": {"type": "string"},
                "html": {"type": "string"},
            },
            "required": ["name", "icon", "description", "html"],
        },
    },
    {
        "name": "snapshot_os",
        "description": "Save a restore point of the entire OS (config, data, and source code) that can be "
                       "rolled back to later. Do this before risky changes.",
        "parameters": {"type": "object", "properties": {"label": {"type": "string"}}},
    },
    {
        "name": "read_source",
        "description": "Read a file from AgentOS's OWN source code (the operating system you run on). "
                       "Pass a path relative to the repo root, e.g. 'agentos/server.py'. A wrong path "
                       "returns the list of source files so you can find your way.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
    },
    {
        "name": "develop_agentos",
        "description": "Modify or EXTEND AgentOS itself by writing a file into its own source tree "
                       "(e.g. add a WhatsApp integration module, a new API endpoint, or a new tool). "
                       "Python files are syntax-checked before writing and the previous version is backed up. "
                       "Set restart=true to reload the service and apply the change. Read the relevant source "
                       "with read_source first so your edit fits the existing code.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "repo-relative path, e.g. agentos/whatsapp.py"},
                "content": {"type": "string", "description": "the full new file contents"},
                "restart": {"type": "boolean"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "restart_agentos",
        "description": "Restart the AgentOS service to load source changes made with develop_agentos.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "add_mcp_server",
        "description": "Add or remove an MCP server (an external tool 'channel') so you gain new tools. "
                       "For a stdio server pass `command` (e.g. 'npx') and `args` (e.g. '-y @playwright/mcp@latest'); "
                       "for an HTTP server pass `url`. Optional `env` = 'KEY=value,KEY2=value2' for API keys. "
                       "Set action='remove' to delete one. Common: playwright (browser), filesystem, git, github.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "command": {"type": "string"}, "args": {"type": "string"},
                "url": {"type": "string"}, "env": {"type": "string"},
                "action": {"type": "string", "enum": ["add", "remove"]},
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_skill",
        "description": "Delete a saved skill by name.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
    },
    {
        "name": "pin_widget",
        "description": "Pin (or unpin) a user app as a live tile on the desktop. Pinned widgets persist "
                       "and restore on startup. Use after create_app when the user wants it on the desktop.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "app name"},
                           "action": {"type": "string", "enum": ["pin", "unpin"]}},
            "required": ["name"],
        },
    },
    {
        "name": "save_report",
        "description": "Save a finished report as an HTML file in the workspace 'reports' folder — it shows in "
                       "the File Manager and opens in the Browser. content can be HTML (headings, tables, lists) "
                       "or plain text. Set to_telegram=true to also deliver a summary to the user's Telegram. "
                       "Use this to DELIVER results after research/analysis — don't just describe them.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string", "description": "the report body (HTML or text)"},
                "to_telegram": {"type": "boolean"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "use_skill",
        "description": "Load a skill (a stored procedure/runbook) by name and follow it. "
                       "The list of available skills with descriptions is in your system prompt.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "save_skill",
        "description": "Save or update a reusable skill — a named procedure in markdown that you (or the user) "
                       "can reuse later. Use when the user teaches you a repeatable process.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string", "description": "One line: when is this skill relevant?"},
                "content": {"type": "string", "description": "The full procedure in markdown."},
            },
            "required": ["name", "description", "content"],
        },
    },
    {
        "name": "telegram_send",
        "description": "Send a message to the user's paired Telegram chat. Works even when they are away "
                       "from this machine (unlike desktop notify).",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "schedule_task",
        "description": "Schedule a prompt to run automatically in the background. "
                       "schedule_type: 'once' (with delay_minutes), 'interval' (with interval_minutes), "
                       "or 'daily' (with at_time 'HH:MM' 24h).",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What the agent should do when the task fires."},
                "schedule_type": {"type": "string", "enum": ["once", "interval", "daily"]},
                "interval_minutes": {"type": "integer"},
                "at_time": {"type": "string"},
                "delay_minutes": {"type": "integer"},
            },
            "required": ["prompt", "schedule_type"],
        },
    },
]

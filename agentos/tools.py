"""The hands of the OS: tools the agent can call, plus risk classification.

Every tool returns a string (what the model sees). Risk levels:
    safe   — auto-run always
    risky  — auto-run only in 'full' autonomy; otherwise needs user approval
"""

import asyncio
import contextlib
import html.parser
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

MAX_OUTPUT = 12_000  # chars of tool output fed back to the model

# Read-only commands that are always safe to run.
SAFE_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc", "sort", "uniq", "cut",
    "echo", "pwd", "whoami", "id", "date", "cal", "uptime", "uname", "hostname",
    "df", "du", "free", "ps", "top", "lscpu", "lsblk", "lsusb", "lspci", "ip",
    "which", "whereis", "type", "file", "stat", "env", "printenv", "history",
    "diff", "md5sum", "sha256sum", "basename", "dirname", "realpath",
    "xrandr", "sensors", "nvidia-smi", "acpi", "ping", "dig", "nslookup", "host",
    "curl", "wget", "tree", "less", "more", "awk", "sed", "jq", "column", "nl",
}
# git is NOT blanket-safe: `git push`/`reset --hard`/`clean -fdx` mutate and publish.
# Only these read-only subcommands auto-run; everything else asks (or use the
# structured git_* tools, which carry their own risk levels).
GIT_SAFE_SUBCOMMANDS = {
    "status", "log", "diff", "show", "branch", "remote", "tag", "describe",
    "rev-parse", "ls-files", "ls-remote", "shortlog", "blame", "reflog", "config",
}
# Commands never run even with approval.
BLOCKED_PATTERNS = [
    r"\brm\s+(-[a-zA-Z]*\s+)*/(\s|$)",   # rm on filesystem root
    r"\bmkfs\b", r"\bdd\s+.*of=/dev/", r":\(\)\s*\{.*\};:",  # mkfs, raw disk writes, forkbomb
    r"\bshutdown\b", r"\breboot\b", r"\binit\s+0\b",
]
DANGEROUS_META = re.compile(r"[><`$\n]")  # redirects, substitution, multiline
CONNECTORS = re.compile(r"\s*(?:\|\||&&|;|\|)\s*")

# Stock theme ids the desktop ships (keys of THEMES in ui/src/js/02-themes-shells.js);
# custom themes from the Themes store merge in at call time (list_themes).
BUILTIN_THEMES = ["agentos", "ubuntu", "ubuntu-light", "dracula", "nord",
                  "aero", "field", "shell",
                  "bento", "liquid", "spatial", "clay", "minimal", "jarvis"]

# Tools that confirm with the user EVERY time — even for the main agent at full
# autonomy. The PDP's default-allow is downgraded to ask at the enforcement sites
# (agent loop, /api/tool); only an explicit user-written grant (rule != "default")
# skips the prompt, because that grant IS persisted consent.
ALWAYS_ASK = {"power_action"}


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
        if base == "git":
            sub = next((p for p in parts[1:] if not p.startswith("-")), "")
            if sub not in GIT_SAFE_SUBCOMMANDS:
                return "risky"
            if sub == "config":
                # `git config <key>` reads; `git config <key> <value>` writes
                args = [p for p in parts[2:] if not p.startswith("-")]
                if len(args) > 1:
                    return "risky"
            if sub == "branch" and any(p in parts for p in ("-d", "-D", "-m", "-M", "--delete")):
                return "risky"
            if sub == "tag" and any(not p.startswith("-") for p in parts[2:]):
                return "risky"  # creating/deleting a tag; bare `git tag` lists
            if sub == "remote" and any(p in parts for p in ("add", "remove", "rm", "set-url", "rename")):
                return "risky"
            continue
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


def sandbox_mechanism() -> str:
    """Which OS jail is available: 'bwrap' (Linux), 'sandbox-exec' (macOS), or ''."""
    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    if shutil.which("bwrap"):
        return "bwrap"
    return ""


def sandbox_conf(cfg: dict) -> tuple[bool, str]:
    """(enabled, absolute root). Root defaults to the workspace. Enabled only when a
    jail mechanism exists for this OS (bubblewrap on Linux, sandbox-exec on macOS)."""
    sb = cfg.get("sandbox") or {}
    root = os.path.realpath(os.path.expanduser(sb.get("root") or cfg["workspace"]))
    return bool(sb.get("enabled")) and bool(sandbox_mechanism()), root


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


def _sandbox_exec_profile(root: str) -> str:
    """macOS SBPL: everything readable, but writes confined to `root` (+ tmp/dev/caches).
    Matches bubblewrap's security-relevant guarantee — the agent's shell cannot modify
    files outside the workspace — without hiding the rest of the FS (which would break
    Homebrew/node tooling the command may legitimately read)."""
    def esc(p):
        return p.replace("\\", "\\\\").replace('"', '\\"')
    writable = [root, "/tmp", "/private/tmp", "/private/var/tmp", "/dev/null",
                "/dev/dtracehelper", os.path.expanduser("~/Library/Caches")]
    subpaths = "\n  ".join(f'(subpath "{esc(p)}")' for p in writable)
    return ("(version 1)\n"
            "(allow default)\n"
            "(deny file-write*)\n"
            f"(allow file-write*\n  {subpaths})\n"
            "(allow file-write-data (literal \"/dev/stdout\") (literal \"/dev/stderr\"))\n")


def sandbox_exec_argv(root: str, command: str, chdir: str | None = None) -> list[str]:
    """Wrap a shell command in macOS sandbox-exec with a workspace write-jail."""
    prof = _sandbox_exec_profile(root)
    inner = f'cd {shlex.quote(chdir or root)} && {command}'
    return ["sandbox-exec", "-p", prof, "/bin/bash", "-lc", inner]


def jail_argv(root: str, command: str, chdir: str | None = None) -> list[str] | None:
    """The right jail wrapper for this OS, or None if no mechanism is available."""
    mech = sandbox_mechanism()
    if mech == "bwrap":
        return bwrap_argv(root, ["/bin/bash", "-lc", command], chdir=chdir)
    if mech == "sandbox-exec":
        return sandbox_exec_argv(root, command, chdir=chdir)
    return None


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated, {len(text) - limit} more chars]"


def _truncate_envelope(out: str, limit: int = MAX_OUTPUT) -> str:
    """Truncate a tool result without shredding a media envelope.

    An MCP result carrying assets is JSON. Cutting it at a byte count would
    produce invalid JSON, and the agent would lose the asset ids entirely — the
    one part of the result that must survive. So the envelope's *text* is
    truncated in place and the structure is left whole.
    """
    if len(out) <= limit:
        return out
    if '"__media__"' in out or '"__image__"' in out:
        try:
            d = json.loads(out)
            if isinstance(d, dict):
                d["text"] = _truncate(d.get("text") or "", limit)
                return json.dumps(d)
        except Exception:
            pass
    return _truncate(out, limit)


def _automation_step_label(s: dict) -> str:
    """One step as a short phrase — what list_automations shows the model."""
    k = s.get("kind")
    if k == "app":
        return f"open {s.get('app')}"
    if k == "action":
        return str(s.get("action"))
    if k == "theme":
        return f"theme {s.get('theme')}"
    if k == "wallpaper":
        return f"wallpaper {s.get('wallpaper')}"
    if k == "desktop":
        return f"desktop {s.get('desk')}"
    if k == "wait":
        return f"wait {s.get('ms')}ms"
    if k == "agent":
        return "ask: " + str(s.get("prompt", ""))[:60]
    if k == "tool":
        return f"call {s.get('tool')}"
    if k == "python":
        return "python: " + " ".join(str(s.get("code", "")).split())[:60]
    return str(k)


class Toolbox:
    """Executes tools. `store` is a memory.Store; `scheduler` is set by the app."""

    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.scheduler = None  # wired up in server startup
        self.mcp = None        # MCPManager, wired up in server startup
        self.telegram = None   # TelegramBridge, wired up in server startup
        self.broadcast = None  # UI event broadcaster, wired up in server startup
        self.fabric = None     # ControlPlane, wired up in server startup
        self.pdp = None        # policy.PDP — the permission gate, wired up in server startup
        self.shell = None      # server.shell_command — reaches the browser shell, wired up in server startup
        self.notifd = None     # NotificationDaemon (DE mode only), wired up in server startup

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
        argv = None
        if enabled:
            workdir = os.path.realpath(os.path.expanduser(cwd)) if cwd else root
            if not (workdir == root or workdir.startswith(root + os.sep)) or not os.path.isdir(workdir):
                workdir = root
            os.makedirs(root, exist_ok=True)
            argv = jail_argv(root, command, chdir=workdir)  # bwrap on Linux, sandbox-exec on macOS
        if argv:
            proc = await asyncio.create_subprocess_exec(
                *argv,
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

    async def llm_generate(self, prompt: str, system: str = "", model: str = "") -> str:
        from . import providers
        model = (model or self.cfg.get("default_model", "")).strip()
        if not model:
            return "[error] no model configured"
        try:
            out = await providers.complete(self.cfg, model, prompt, system)
        except Exception as e:
            return f"[error] llm: {type(e).__name__}: {e}"
        return _truncate(out or "(empty response)")

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
            if sys.platform == "darwin":  # no /proc on macOS
                out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                     capture_output=True, text=True).stdout.strip()
                if out.isdigit():
                    info["memory"] = {"MemTotal": f"{int(out) / 1e9:.1f}GB"}
        du = shutil.disk_usage(os.path.expanduser("~"))
        info["disk_home"] = f"{du.used / 1e9:.1f}GB used / {du.total / 1e9:.1f}GB total"
        return json.dumps(info, indent=2)

    async def open_app(self, target: str) -> str:
        from . import desktop as desktopmod
        err = desktopmod.open_path(target)
        return f"[error] {err}" if err else f"opened: {target}"

    async def notify(self, title: str, message: str = "") -> str:
        from . import desktop as desktopmod
        if desktopmod.send_notification(title, message):
            return "notification sent"
        return "[error] no desktop notification mechanism available"

    async def remember(self, content: str, scope: str = "user",
                       conversation_id: str = "", space_id: str = "",
                       everywhere: bool = False) -> str:
        """Save a durable fact. It lands in the current space unless `everywhere`
        is set — which is how the agent says "this is true about the user, not
        about this project"."""
        if scope == "session" and not conversation_id:
            scope = "user"  # headless contexts have no session to attach to
        target_space = "" if everywhere else (space_id or "")
        mid = self.store.add_memory(content, scope=scope,
                                    conversation_id=conversation_id or None, source="agent",
                                    space_id=target_space)
        if self.broadcast:
            await self.broadcast({"type": "knowledge_update"})
        where = "everywhere" if not target_space else "this space"
        return f"remembered ({scope} memory, {where}, id {mid})"

    async def search_files(self, query: str, limit: int = 8) -> str:
        """Semantic search over the user's workspace files and generated docs."""
        from . import search as searchmod
        try:
            res = await searchmod.query(self.cfg, self.store, query, limit=int(limit))
        except Exception as e:
            return f"[error] search failed: {e}"
        if not res:
            return ("no matches — the index refreshes lazily, so brand-new files may "
                    "take a query or two to appear")
        return "\n".join(f"{r['path']}  (score {r['score']}, {r['kind']})\n  …{r['snippet'][:160]}"
                         for r in res)

    async def recall(self, query: str = "", space_id: str = "") -> str:
        mems = self.store.search_memories(query, limit=15, space=space_id)
        if query:
            # semantic recall finds what keyword LIKE misses ("job" → "works at Accacia").
            # The scoping happened in search_memories above; semantic_rank only orders
            # the list it is handed, which is the right layer for it.
            try:
                from . import knowledge
                ranked = await knowledge.semantic_rank(
                    self.cfg, self.store.search_memories("", limit=500, space=space_id), query)
                if ranked:
                    seen = {m["id"] for m in mems}
                    mems += [m for m in ranked[:10] if m["id"] not in seen]
                    mems = mems[:15]
            except Exception:
                pass
        if not mems:
            return "(no memories found)"
        return "\n".join(
            f"- [{m['id']}|{m.get('scope', 'user')}] "
            f"{time.strftime('%Y-%m-%d', time.localtime(m['created_at']))}: {m['content']}"
            for m in mems
        )

    async def delegate(self, subagent: str, task: str, conversation_id: str = "") -> str:
        """Hand a task to a specialist subagent; its steps run in a separate data plane
        with its own model, tool allow-list, and budget (see the Team app)."""
        if not self.fabric:
            return "[error] fabric not available"
        defn = self.store.get_subagent(subagent)
        if not defn:
            names = ", ".join(s["name"] for s in self.store.list_subagents()) or "(none)"
            return f"[error] no subagent named '{subagent}'. Available: {names}"
        res = await self.fabric.run_subagent(defn, task, conversation_id=conversation_id)
        head = f"[subagent {defn['name']} · {res['status']} · model {res['model']}]"
        body = res["content"] or res["fault"] or "(no output)"
        return f"{head}\n{body[:3500]}"

    async def run_workflow(self, workflow: str, input: str, conversation_id: str = "") -> str:
        """Run a stored multi-subagent workflow (a DAG of steps) and return its result."""
        if not self.fabric:
            return "[error] fabric not available"
        wf = self.store.get_workflow(workflow)
        if not wf:
            names = ", ".join(w["name"] for w in self.store.list_workflows()) or "(none)"
            return f"[error] no workflow named '{workflow}'. Available: {names}"
        res = await self.fabric.run_workflow(wf, input, conversation_id=conversation_id)
        head = f"[workflow {wf['name']} · {res['status']}]"
        if res["status"] != "ok":
            return f"{head}\n{res['fault']}"
        return f"{head}\n{res['content'][:3500]}"

    async def forget(self, memory_id: str) -> str:
        mems = {m["id"] for m in self.store.search_memories("", limit=10**6)}
        if memory_id not in mems:
            return f"[error] no memory with id {memory_id} — use recall to find the right id"
        self.store.delete_memory(memory_id)
        if self.broadcast:
            await self.broadcast({"type": "knowledge_update"})
        return f"forgotten (id {memory_id})"

    async def _generate_image(self, prompt: str, width: int = 1280,
                              height: int = 720) -> tuple[bytes | None, str]:
        """Generate an image with the configured provider. Returns (bytes, provider label)
        on success or (None, error). cfg['image']: provider auto|google|openai|pollinations
        (auto = google → openai → pollinations, by which keys are set), model optional.

        A PINNED provider is tried first and honoured — but a rate limit or an
        outage is not a reason to leave the user without an image, so a retryable
        failure falls through to the others (free pollinations last) and the
        returned label says which one actually drew it.
        """
        import asyncio as _aio
        import base64
        import urllib.parse
        icfg = self.cfg.get("image") or {}
        choice = (icfg.get("provider") or "auto").lower()
        google = self.cfg["providers"].get("google") or {}
        openai = self.cfg["providers"].get("openai") or {}
        keyed = ((["google"] if google.get("api_key") else [])
                 + (["openai"] if openai.get("api_key") else []) + ["pollinations"])
        if choice == "auto":
            order = keyed
        else:
            order = [choice] + [p for p in keyed if p != choice]   # pinned first, then a safety net
        errors: list[str] = []

        def _msg(resp) -> str:
            """The API's own explanation, not just a status code."""
            try:
                j = resp.json()
                e = j.get("error") or j
                return str(e.get("message") or e)[:180]
            except Exception:
                return (resp.text or "")[:180]

        for pos, prov in enumerate(order):
            try:
                if prov == "google":
                    if not google.get("api_key"):
                        errors.append("google: API key not set (Settings → AI providers → Google)")
                        continue
                    model = icfg.get("model") or "gemini-2.5-flash-image"
                    base = (google.get("base_url") or "https://generativelanguage.googleapis.com").rstrip("/")
                    headers = {"x-goog-api-key": google["api_key"]}
                    # Imagen models speak :predict; Gemini image models speak
                    # :generateContent and must be told to answer with an image.
                    if model.startswith("imagen"):
                        url = f"{base}/v1beta/models/{model}:predict"
                        body = {"instances": [{"prompt": prompt}],
                                "parameters": {"sampleCount": 1,
                                               "aspectRatio": "16:9" if width >= height else "9:16"}}
                    else:
                        url = f"{base}/v1beta/models/{model}:generateContent"
                        body = {"contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
                    data = None
                    for attempt in (0, 1):        # one retry: 429s are often a burst limit
                        async with httpx.AsyncClient(timeout=240.0) as c:
                            r = await c.post(url, headers=headers, json=body)
                        if r.status_code == 200:
                            j = r.json()
                            for pred in (j.get("predictions") or []):
                                data = pred.get("bytesBase64Encoded")
                                if data:
                                    break
                            if not data:
                                cands = j.get("candidates") or [{}]
                                for part in (cands[0].get("content") or {}).get("parts", []):
                                    d = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
                                    if d:
                                        data = d
                                        break
                            if data:
                                return base64.b64decode(data), f"google/{model}"
                            errors.append(f"google/{model}: the response carried no image")
                            break
                        if r.status_code == 429 and attempt == 0:
                            await _aio.sleep(3)
                            continue
                        detail = _msg(r)
                        if r.status_code == 429:
                            errors.append(f"google/{model}: rate-limited / out of quota (HTTP 429). {detail}")
                        elif r.status_code in (400, 404):
                            errors.append(f"google/{model}: HTTP {r.status_code} — is that a real image model? {detail}")
                        else:
                            errors.append(f"google/{model}: HTTP {r.status_code}. {detail}")
                        break
                elif prov == "openai":
                    if not openai.get("api_key"):
                        errors.append("openai: API key not set (Settings → AI providers → OpenAI)")
                        continue
                    model = icfg.get("model") if choice == "openai" else ""
                    model = model or "gpt-image-1"
                    body = {"model": model, "prompt": prompt}
                    if model.startswith("dall-e"):
                        body["size"] = "1792x1024" if width >= height else "1024x1792"
                        body["response_format"] = "b64_json"
                    else:
                        body["size"] = "1536x1024" if width >= height else "1024x1536"
                    base = (openai.get("base_url") or "https://api.openai.com/v1").rstrip("/")
                    async with httpx.AsyncClient(timeout=240.0) as c:
                        r = await c.post(f"{base}/images/generations",
                                         headers={"Authorization": f"Bearer {openai['api_key']}"},
                                         json=body)
                    if r.status_code == 200:
                        item = (r.json().get("data") or [{}])[0]
                        if item.get("b64_json"):
                            return base64.b64decode(item["b64_json"]), f"openai/{model}"
                        if item.get("url"):
                            async with httpx.AsyncClient(timeout=120.0) as c:
                                img = await c.get(item["url"])
                            if img.status_code == 200:
                                return img.content, f"openai/{model}"
                        errors.append("openai: response had no image")
                    else:
                        errors.append(f"openai/{model}: HTTP {r.status_code}. {_msg(r)}")
                else:
                    q = urllib.parse.quote(prompt[:400])
                    url = (f"https://image.pollinations.ai/prompt/{q}"
                           f"?width={width}&height={height}&nologo=true")
                    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as c:
                        r = await c.get(url)
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
                        label = "pollinations/flux"
                        if pos > 0:
                            label += " (fallback)"
                        return r.content, label
                    errors.append(f"pollinations: HTTP {r.status_code}")
            except Exception as e:
                errors.append(f"{prov}: {type(e).__name__}: {e}")
        return None, "; ".join(errors) or "no image provider available"

    async def generate_wallpaper(self, prompt: str) -> str:
        """AI-generate a desktop wallpaper from a text prompt using the configured image
        provider (Gemini / OpenAI / free pollinations.ai fallback).
        Saves to the local gallery and applies it as the current wallpaper."""
        import time as _t
        from . import config as cfgmod
        data, src = await self._generate_image(prompt, 1280, 720)
        if data is None:
            return f"[error] image generation failed — {src}"
        gallery = cfgmod.AGENTOS_HOME / "wallpapers"
        gallery.mkdir(parents=True, exist_ok=True)
        (gallery / f"{int(_t.time())}.png").write_bytes(data)       # keep in the gallery
        (cfgmod.AGENTOS_HOME / "wallpaper.png").write_bytes(data)   # apply as current
        self.store.log("system", f"wallpaper generated via {src}: {prompt[:120]}")
        if self.broadcast:
            await self.broadcast({"type": "wallpaper"})
        note = (" (The free service caps resolution; add a Google or OpenAI key in Settings "
                "for sharper images, or use set_wallpaper with a photo file/URL.)"
                if src.startswith("pollinations") else "")
        if "(fallback)" in src:
            note = (" Your pinned provider was unavailable (rate limit or outage), so this "
                    "came from the free service — try again later for the pinned one." + note)
        return f"wallpaper generated with {src} ({len(data) // 1024} KB), saved to the gallery, and applied.{note}"

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
                     subject_type: str = "", object_type: str = "",
                     space_id: str = "", everywhere: bool = False) -> str:
        """Record an assertion. It belongs to the current space unless `everywhere`
        marks it as true regardless of what the user is working on. Entities are
        shared across spaces — only the assertion is scoped."""
        target_space = "" if everywhere else (space_id or "")
        eid = self.store.kg_add(subject, relation, object, subject_type, object_type,
                                space_id=target_space)
        where = "everywhere" if not target_space else "in this space"
        return f"added to knowledge graph {where}: {subject} —{relation}→ {object} (edge {eid})"

    async def kg_query(self, query: str = "", space_id: str = "") -> str:
        lines = self.store.kg_query(query, space=space_id)
        if not lines:
            return "(knowledge graph has no matching facts)"
        return "\n".join(lines)

    # -- assets & spaces ----------------------------------------------------

    async def list_assets(self, kind: str = "", query: str = "", limit: int = 20,
                          space_id: str = "") -> str:
        """What is in the gallery. Asset ids are what every other media tool takes."""
        rows = self.store.asset_list(kind=kind, q=query, space=space_id, limit=int(limit))
        if not rows:
            return "(no assets yet)" if not (kind or query) else "(no assets match)"
        out = []
        for r in rows:
            bits = [f"[{r['id']}] {r['kind']}", r.get("title") or ""]
            if r.get("duration"):
                bits.append(f"{r['duration']:.1f}s")
            if r.get("width"):
                bits.append(f"{r['width']}x{r['height']}")
            bits.append(f"{(r.get('bytes') or 0) // 1024} KB")
            if r.get("source"):
                bits.append(f"from {r['source']}")
            out.append(" · ".join(b for b in bits if b))
        return "\n".join(out)

    async def get_asset(self, asset_id: str) -> str:
        """Details of one asset. For images this also SHOWS it to vision-capable
        models, using the same result shape take_screenshot uses."""
        from . import assets as assetmod
        row = self.store.asset_get(asset_id)
        if not row:
            return f"[error] no asset with id {asset_id}"
        info = assetmod.public(row)
        text = (f"{info['kind']} · {info['mime']} · {info['bytes'] // 1024} KB"
                + (f" · {info['width']}x{info['height']}" if info["width"] else "")
                + (f" · {info['duration']:.1f}s" if info["duration"] else "")
                + (f"\ntitle: {info['title']}" if info["title"] else "")
                + (f"\nprompt: {info['prompt']}" if info["prompt"] else "")
                + (f"\nsource: {info['source']}" if info["source"] else ""))
        path = assetmod.path_of(row)
        if row["kind"] == "image" and path:
            return json.dumps({"__image__": str(path), "text": text})
        if not path:
            return text + "\n[the file behind this asset is missing from disk]"
        return text

    async def save_asset(self, source: str, title: str = "", space_id: str = "",
                         conversation_id: str = "") -> str:
        """Put a file or a URL into the gallery so it can be used, shown and kept.
        `source` is a local path or an http(s) URL."""
        from . import assets as assetmod
        src = (source or "").strip()
        if not src:
            return "[error] source is required (a local path or an http(s) URL)"
        try:
            if src.startswith(("http://", "https://")):
                async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                    r = await client.get(src)
                    r.raise_for_status()
                    data, mime = r.content, r.headers.get("content-type", "").split(";")[0]
                name = os.path.basename(src.split("?")[0]) or ""
                row = await assetmod.put_bytes(
                    self.store, data, name=name, mime=mime, title=title, source="url",
                    origin_url=src, space_id=space_id, conversation_id=conversation_id)
            else:
                p = Path(os.path.expanduser(src))
                deny = self._sandbox_deny(p)
                if deny:
                    return deny
                if not p.is_file():
                    return f"[error] file not found: {p}"
                row = await assetmod.put_bytes(
                    self.store, p.read_bytes(), name=p.name, title=title or p.name,
                    source="tool:save_asset", space_id=space_id,
                    conversation_id=conversation_id)
        except Exception as e:
            return f"[error] could not save asset: {type(e).__name__}: {e}"
        if not row:
            return "[error] nothing to save (empty file, or larger than the inline limit)"
        if self.broadcast:
            await self.broadcast({"type": "assets_update"})
        return f"saved as asset {row['id']} ({row['kind']}, {(row.get('bytes') or 0)//1024} KB)"

    async def delete_asset(self, asset_id: str) -> str:
        from . import assets as assetmod
        if not assetmod.delete(self.store, asset_id):
            return f"[error] no asset with id {asset_id}"
        if self.broadcast:
            await self.broadcast({"type": "assets_update"})
        return f"deleted asset {asset_id}"

    async def generate_image(self, prompt: str, width: int = 1280, height: int = 720,
                             title: str = "", space_id: str = "",
                             conversation_id: str = "") -> str:
        """Draw a picture and keep it in the gallery.

        The provider fan-out (google → openai → free pollinations, with fallback)
        has existed since the first release but could only ever produce a
        wallpaper. This is the same engine, writing into the asset store, so what
        it makes can be used for anything.
        """
        data, label = await self._generate_image(prompt, int(width), int(height))
        if not data:
            return f"[error] {label}"
        from . import assets as assetmod
        row = await assetmod.put_bytes(
            self.store, data, name="generated.png", mime="image/png",
            title=title or prompt[:80], prompt=prompt, source=f"tool:generate_image ({label})",
            space_id=space_id, conversation_id=conversation_id)
        if not row:
            return "[error] the image was generated but could not be stored"
        if self.broadcast:
            await self.broadcast({"type": "assets_update"})
        return (f"generated asset {row['id']} with {label} "
                f"({row.get('width') or width}x{row.get('height') or height})")

    async def list_spaces(self) -> str:
        """The things the user is working on."""
        rows = self.store.list_spaces()
        if not rows:
            return ("(no spaces yet — everything is global. Create one with "
                    "create_space when the user starts a distinct project.)")
        return "\n".join(
            f"- {r['name']}" + (f" — {r['description']}" if r.get("description") else "")
            for r in rows)

    async def create_space(self, name: str, description: str = "", icon: str = "") -> str:
        sid = self.store.create_space(name, description=description, icon=icon)
        if not sid:
            return "[error] a space needs a name"
        if self.broadcast:
            await self.broadcast({"type": "spaces_update"})
        return (f"created space '{name}' (id {sid}). Memory and facts saved while it is "
                f"active belong to it; things true about the user regardless stay global.")

    async def timeline(self, since_hours: float = 168, kind: str = "",
                       limit: int = 40, space_id: str = "") -> str:
        """What has happened — milestones, not messages."""
        since = time.time() - float(since_hours) * 3600 if since_hours else 0.0
        rows = self.store.timeline(space=space_id, kind=kind, since=since, limit=int(limit))
        if not rows:
            return "(nothing on the timeline for that period)"
        return "\n".join(
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(r['ts']))}  [{r['kind']}] {r['title']}"
            for r in rows)

    async def update_soul(self, content: str) -> str:
        from . import config as cfgmod
        if len(content.strip()) < 40:
            return "[error] refusing to overwrite the soul with something that short — pass the full new soul text"
        cfgmod.save_soul(content)
        return f"soul updated ({len(content)} chars)"

    async def create_theme(self, name: str, mode: str = "", vars: str = "",
                           css: str = None, font_url: str = "", font_family: str = "",
                           shell_html: str = None) -> str:
        """Design a full OS theme and apply it live — or REFINE an existing one. If a theme with
        this `name` already exists, the call is a refinement: pass ONLY the fields to change and
        everything else is kept (vars merge key-by-key; css/font/shell stay unless given). When
        the user is iterating on a theme in this session, keep calling with the SAME name —
        never fork a new theme for a tweak. `vars` is a JSON object of CSS variables (bg, bg2,
        bg3, bg4, line, txt, dim, dim2, acc, acc2, warn, err, ok, glass — hex/rgba). `css` is
        extra CSS to restyle the desktop chrome (#menubar, #taskbar, .win, .aicon, .widget,
        #desktop). Optional web font via font_url + font_family. `shell_html` (optional) is a
        COMPLETE replacement interface — full HTML+CSS+JS that takes over the whole screen
        instead of the stock desktop; it can call every endpoint in GET /api/registry (fetch +
        /ws websocket). Pass shell_html="" to remove an existing shell."""
        import json as _j
        try:
            v = _j.loads(vars) if isinstance(vars, str) and vars.strip() else (vars or {})
        except Exception as e:
            return f"[error] vars must be a JSON object of CSS variables: {e}"
        name = name.strip()
        existing = next((t for t in self.store.list_themes()
                         if t.get("name", "").lower() == name.lower()), None)
        refining = existing is not None
        theme = existing or {"mode": "dark", "v": {}, "css": ""}
        if mode in ("dark", "light"):
            theme["mode"] = mode
        theme["v"] = {**(theme.get("v") or theme.pop("vars", None) or {}), **v}
        if css is not None:
            theme["css"] = css
        if font_url:
            theme["font"] = {"url": font_url,
                             "family": font_family or (theme.get("font") or {}).get("family", "")}
        elif font_family and theme.get("font"):
            theme["font"]["family"] = font_family
        if shell_html is not None:
            if shell_html.strip():
                theme["shell"] = shell_html
            else:
                theme.pop("shell", None)   # explicit empty string removes the shell
        theme.update(name=name, custom=True, apply=True)
        self.store.save_theme(name, _j.dumps(theme))
        if self.broadcast:
            await self.broadcast({"type": "themes"})
            await self.broadcast({"type": "theme_apply", "theme": theme})
        self.store.log("system", f"theme {'refined' if refining else 'created'} by agent: {name}")
        extras = (" + custom CSS" if theme.get("css") else "") + (" + a full replacement shell" if theme.get("shell") else "")
        changed = ", ".join(sorted(v)) if v else "no color changes"
        return (f"theme '{name}' {'refined in place (changed: ' + changed + ')' if refining else 'created'} "
                f"and applied live — {len(theme.get('v') or {})} color variables{extras}. "
                f"To iterate further, call create_theme again with the SAME name and only the fields to change.")

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
                   "policies", "telegram", "mcp_servers", "sandbox", "memory"}
        applied, skipped = [], []
        for k, v in patch.items():
            if k not in allowed:
                skipped.append(k)
                continue
            if k in ("telegram", "mcp_servers", "memory") and isinstance(v, dict):
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

    async def create_app(self, name: str, icon: str, description: str, html: str,
                         permissions: str = "") -> str:
        """Create/update a UI app that appears on the AgentOS desktop (rendered in a window).
        `permissions` (JSON list of {action, resource, reason, required}) declares what the
        app needs at runtime — it becomes the manifest the user consents to."""
        if len(html.strip()) < 20:
            return "[error] html too short — pass the full app markup (HTML/CSS/JS)"
        aid = self.store.save_app(name, icon or "", description, html, note="agent build")
        perms = []
        if permissions:
            try:
                perms = json.loads(permissions)
            except Exception:
                perms = []
        perms = [p for p in perms if isinstance(p, dict) and p.get("action")] \
            if isinstance(perms, list) else []
        if perms:
            man = {"format": 1, "name": name, "description": description,
                   "permissions": perms, "prerequisites": {}}
            self.store.set_app_manifest(aid, json.dumps(man), "proposed")
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
            # test gate: a self-modification that breaks the suite must not go live —
            # the AST check above only catches parse errors, not broken behavior
            tests = await self.run_tests()
            if tests.startswith("[exit code"):
                return (msg + "\n[error] NOT restarting: the change breaks the test suite. "
                        "Fix it (or restore the snapshot) before restarting.\n" + tests[:1500])
            from . import desktop as desktopmod
            desktopmod.restart_service()
            msg += " — tests passed; restarting AgentOS now (reconnect in a few seconds)"
        else:
            msg += ". Call again with restart=true (or use restart_agentos) to load the change."
        return msg

    async def run_tests(self, path: str = "") -> str:
        """Run the AgentOS test suite (or a project's tests). The Test pillar's
        workhorse: self-modification calls this before restarting."""
        import agentos
        src_root = Path(agentos.__file__).resolve().parent.parent
        workdir = os.path.realpath(os.path.expanduser(path)) if path else str(src_root)
        if not os.path.isdir(workdir):
            return f"[error] not a directory: {workdir}"
        py = sys.executable
        proc = await asyncio.create_subprocess_exec(
            py, "-m", "pytest", "-q", "--no-header", cwd=workdir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            return "[error] tests timed out after 600s"
        text = out.decode(errors="replace")
        tail = "\n".join(text.strip().splitlines()[-25:])
        summary = next((ln for ln in reversed(text.strip().splitlines())
                        if "passed" in ln or "failed" in ln or "error" in ln), "")
        if proc.returncode == 0:
            self.store.log("test", f"passed: {summary}"[:200], {"dir": workdir, "ok": True})
            return f"tests PASSED\n{tail}"
        if "no tests ran" in text or "collected 0 items" in text:
            return f"[error] no tests found in {workdir}"
        self.store.log("test", f"failed: {summary}"[:200], {"dir": workdir, "ok": False})
        return f"[exit code {proc.returncode}] tests FAILED\n{_truncate(tail)}"

    async def restart_agentos(self) -> str:
        """Restart the AgentOS service to load code changes — gated on the test
        suite: a self-modification that breaks the tests must not go live."""
        tests = await self.run_tests()
        if tests.startswith("[exit code"):
            return ("[error] refusing to restart: the test suite fails against the current "
                    "source. Fix the failures (or revert via snapshot) first.\n" + tests[:1500])
        from . import desktop as desktopmod
        desktopmod.restart_service()
        self.store.log("system", "AgentOS restart requested by agent (tests passed)")
        return "tests passed — restarting AgentOS; the UI will reconnect in a few seconds"

    async def manage_models(self, action: str = "list", name: str = "") -> str:
        """Manage local Ollama models. action: 'list' (installed + GPU), 'pull' (download `name`),
        'remove' (delete `name`). Pulling can take minutes; it runs in the background."""
        base = self.cfg["providers"]["ollama"]["base_url"]
        async with httpx.AsyncClient(timeout=None) as c:
            if action == "list":
                tags = (await c.get(f"{base}/api/tags", timeout=8)).json()
                names = [m["name"] for m in tags.get("models", [])]
                gpu = ""
                if shutil.which("nvidia-smi"):
                    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
                                          "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
                return f"installed models: {', '.join(names) or '(none)'}" + (f"\nGPU: {gpu}" if gpu else "")
            if action == "remove":
                await c.request("DELETE", f"{base}/api/delete", json={"model": name}, timeout=15)
                if self.broadcast:
                    await self.broadcast({"type": "models"})
                return f"removed model {name}"
            if action == "pull":
                async def bg():
                    try:
                        await c.post(f"{base}/api/pull", json={"model": name, "stream": False}, timeout=None)
                    except Exception:
                        pass
                    if self.broadcast:
                        await self.broadcast({"type": "models"})
                asyncio.create_task(bg())
                return f"started downloading {name} in the background — check the Model Manager for progress"
        return "[error] action must be list | pull | remove"

    async def launch_native_app(self, name: str) -> str:
        """Launch an installed native desktop app by name, e.g. 'Firefox', 'Files', 'Settings'."""
        from . import host
        apps = host.list_apps()
        q = name.strip().lower()
        app = (next((a for a in apps if a["name"].lower() == q), None)
               or next((a for a in apps if q in a["name"].lower()), None))
        if not app:
            return f"[error] no installed app matching '{name}'"
        ok, msg = host.launch_app(app["id"])
        return f"launched {app['name']}" if ok else f"[error] {msg}"

    async def list_windows(self) -> str:
        """List the native app windows open on the desktop (their titles), if window control is available."""
        from . import host
        w = host.list_windows()
        if not w.get("available"):
            return f"[error] {w.get('reason', 'window control unavailable')}"
        if not w["windows"]:
            return "no native windows open"
        return "\n".join(f"- {x['title']} ({x['app']}) [{x['id']}]" for x in w["windows"])

    async def focus_window(self, title: str) -> str:
        """Bring a native app window to the front by (part of) its title — like alt-tabbing to it."""
        from . import host
        w = host.list_windows()
        if not w.get("available"):
            return f"[error] {w.get('reason', 'window control unavailable')}"
        q = title.strip().lower()
        win = next((x for x in w["windows"] if q in x["title"].lower() or q in x["app"].lower()), None)
        if not win:
            return f"[error] no open window matching '{title}'"
        ok, msg = host.focus_window(win["id"])
        return f"switched to {win['title']}" if ok else f"[error] {msg}"

    async def system_control(self, action: str, value: str = "") -> str:
        """Control the host: action = 'volume' (value 0-100), 'mute'/'unmute', or 'settings'
        (value = panel: sound|network|bluetooth|display|power)."""
        from . import host
        a = action.strip().lower()
        if a == "volume":
            try:
                host.set_volume(percent=int(value))
            except ValueError:
                return "[error] volume needs a number 0-100"
            return f"volume set to {value}%"
        if a in ("mute", "unmute"):
            host.set_volume(mute=(a == "mute"))
            return a + "d"
        if a == "settings":
            ok, msg = host.open_settings(value)
            return msg if ok else f"[error] {msg}"
        return "[error] action must be volume | mute | unmute | settings"

    async def add_mcp_server(self, name: str, command: str = "", url: str = "",
                             args: str = "", env: str = "", bearer_token: str = "",
                             action: str = "add") -> str:
        """Add/remove an MCP server ('channel') the agent can then use. stdio: give `command` (+ optional
        `args`); http: give `url` (+ optional `bearer_token`). `env` is optional 'KEY=val,KEY2=val2' for API keys."""
        from . import config as cfgmod
        servers = self.cfg.setdefault("mcp_servers", {})
        key = name.strip().replace(" ", "-")
        if action == "remove":
            servers.pop(key, None)
            msg = f"removed MCP server '{key}'"
        else:
            if url.strip():
                conf = {"transport": "http", "url": url.strip(), "enabled": True}
                if bearer_token.strip():
                    conf["headers"] = {"Authorization": f"Bearer {bearer_token.strip()}"}
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
        if action == "remove":
            from . import mcp_store
            reg = self.store.mcp_reg_get(key)
            if reg:
                mcp_store.delete_doc(reg.get("doc_file") or "")
                self.store.mcp_reg_delete(key)
        else:
            # every install lands in the MCP Registry and gets a generated manual page
            from . import mcp_store
            mcp_store.record_install(self.store, key, source="manual", conf=conf)
        if self.mcp:
            await self.mcp.reload()
        if self.broadcast:
            await self.broadcast({"type": "config"})
        return msg

    async def discover_mcp_servers(self, query: str) -> str:
        """Search the public MCP registry for servers matching a capability the user needs.
        Pure discovery: present the results and ASK the user which (if any) to install."""
        from . import mcp_store
        try:
            cands = await mcp_store.search_any(query, limit=10, store=self.store)
        except Exception as e:
            return f"[error] MCP registry search failed: {e}"
        deep = []
        if len(cands) < 3:
            # the registry isn't enough — widen the net (npm + GitHub) agentically
            exclude = {x for c in cands
                       for x in (c["registry_name"], c.get("identifier") or "",
                                 (c.get("homepage") or "").rstrip("/")) if x}
            try:
                deep = await mcp_store.search_deep(query, limit=8, exclude=exclude)
            except Exception:
                deep = []
        if not cands and not deep:
            st = mcp_store.index_status()
            if st["syncing"] and not st["count"]:
                return ("the local registry index is still syncing (the public API is "
                        "slow) — try again in a minute")
            return (f"no MCP servers found for '{query}' in the public registry, npm, or "
                    "GitHub — try a broader term")
        have = set((self.cfg.get("mcp_servers") or {}).keys())
        lines = [f"Found {len(cands) + len(deep)} MCP server(s) for '{query}' — ask the "
                 "user which to install, and whether to build an app around it:"]
        for c in cands:
            req = [e["name"] for e in c["env"] if e.get("required")]
            lines.append(
                f"- {c['registry_name']}"
                + (" [already installed]" if c["key"] in have else "")
                + f"\n    {c['description'][:180]}"
                + (f"\n    runs: {c['registry_type']}:{c['identifier']}" if c["identifier"]
                   else (f"\n    remote: {c['remote_url']}" if c["remote_url"] else ""))
                + (f"\n    needs keys: {', '.join(req)}" if req else ""))
        for c in deep:
            if c.get("agentic"):
                lines.append(
                    f"- {c['registry_name']} [GitHub repo — not directly installable]"
                    + f"\n    {c['description'][:180]}"
                    + f"\n    to install: fetch_url the repo README ({c['homepage']}), work "
                      "out the run command (npx/uvx/docker) and required keys, then "
                      "add_mcp_server — ask the user before doing so")
            else:
                lines.append(
                    f"- {c['registry_name']} [found on npm, not in the registry]"
                    + (" [already installed]" if c["key"] in have else "")
                    + f"\n    {c['description'][:180]}"
                    + f"\n    install with install_mcp_server registry_name='{c['registry_name']}'")
        return "\n".join(lines)

    async def install_mcp_server(self, registry_name: str, name: str = "",
                                 env: str = "") -> str:
        """Install a server discovered with discover_mcp_servers (exact registry_name).
        Adds it to the MCP Registry, generates its documentation into Docs, and connects
        it. `env` is optional 'KEY=val,KEY2=val2'; required keys left unset keep the
        server disabled until the user fills them in the MCP app."""
        from . import config as cfgmod
        from . import mcp_store
        try:
            cand = await mcp_store.lookup(registry_name.strip(), store=self.store)
        except Exception as e:
            return f"[error] MCP registry lookup failed: {e}"
        if not cand:
            return (f"[error] '{registry_name}' not found in the public registry — use "
                    "discover_mcp_servers first and pass the exact registry name")
        env_values = {}
        for pair in (env or "").split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                env_values[k.strip()] = v.strip()
        key = (name or cand["key"]).strip().replace(" ", "-")
        conf, missing = mcp_store.to_conf(cand, env_values=env_values)
        self.cfg.setdefault("mcp_servers", {})[key] = conf
        cfgmod.save_config(self.cfg)
        mcp_store.record_install(
            self.store, key, title=cand["registry_name"].split("/")[-1],
            description=cand["description"], source="discovery",
            origin=cand["registry_name"], package=mcp_store.package_info(cand),
            homepage=cand["homepage"], conf=conf)
        self.store.log("system", f"MCP '{key}' installed from the public registry "
                                 f"({cand['registry_name']})")
        if self.mcp:
            await self.mcp.reload()
        if self.broadcast:
            await self.broadcast({"type": "config"})
        msg = (f"installed MCP server '{key}' from {cand['registry_name']} — added to the "
               f"MCP Registry with a generated manual (Docs → mcp/{key}.md)")
        if missing:
            msg += (f". It is DISABLED until these keys are set in the MCP app: "
                    f"{', '.join(missing)}")
        else:
            msg += f". Connecting now; tools will appear as mcp_{key}_*"
        return msg + (". Offer to build a desktop app around it with create_app "
                      "(declare mcp.use on mcp:" + key + "/* in its permissions).")

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

    async def read_app_data(self, name: str) -> str:
        """Read the data an app stores (its own data store) — e.g. a notes app's notes, a tracker's
        entries. Every built app persists to this; use it to answer questions about an app's contents."""
        app = next((a for a in self.store.list_apps() if a["name"].lower() == name.strip().lower()), None)
        if not app:
            return f"[error] no app named '{name}'"
        data = self.store.get_app_data(app["id"])
        return f"data for '{app['name']}':\n{data}" if data and data != "{}" else f"'{app['name']}' has no stored data yet"

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

    async def create_trigger(self, kind: str, match_or_path: str = "", prompt: str = "",
                             cooldown_secs: int = 300, minutes: float = 30) -> str:
        if self.scheduler is None:
            return "[error] scheduler not running"
        kw = {"match": match_or_path} if kind == "notification" else \
             {"path": match_or_path} if kind == "file_change" else {}
        return self.scheduler.create_trigger(kind, prompt, minutes=minutes,
                                             cooldown_secs=cooldown_secs, **kw)

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
        if name in ("git_status", "git_log", "git_diff"):
            return "safe", ""
        if name in ("git_init", "git_commit", "git_branch"):
            # local, reversible history inside the workspace runs free; outside it, ask
            ws = os.path.realpath(os.path.expanduser(self.cfg["workspace"]))
            p = os.path.realpath(os.path.expanduser(args.get("path") or ws))
            if p == ws or p.startswith(ws + os.sep):
                return "safe", ""
            return "risky", f"Writes git history outside the workspace ({p})."
        if name == "git_push":
            return "risky", "Publishes commits to a remote repository (visible outside this machine)."
        if name in ("git_remote_set", "git_pull", "git_clone"):
            return "risky", "Changes git remotes or fetches external code."
        if name == "export_app_to_git":
            if args.get("push"):
                return "risky", "Exports an app to a project folder and pushes it to GitHub."
            return "safe", ""
        if name == "train_autopilot":
            return "risky", "Starts an autonomous dataset-import + training run (long GPU work)."
        if name == "train_job":
            if args.get("action") == "create":
                return "risky", "Launches a model training job (long GPU work)."
            return "safe", ""
        if name == "train_model":
            if args.get("action") == "publish":
                return "risky", "Uploads a trained model to the Hugging Face Hub (leaves this machine)."
            return "safe", ""
        if name == "train_datasets":
            if args.get("action") in ("import_hub", "import_url"):
                return "risky", "Downloads an external dataset onto this machine."
            return "safe", ""
        if name == "trainforge_service":
            return "safe", ""
        if name == "hermes_status":
            return "safe", ""
        if name == "hermes_ask":
            return "risky", "Delegates a task to the Hermes agent — it acts with its own tools and permissions."
        if name == "hermes_send":
            return "risky", f"Sends a message via Hermes to {args.get('target', '?')} (leaves this machine)."
        if name == "run_tests":
            # running a test suite executes that project's code
            p = args.get("path") or ""
            if not p:
                return "safe", ""  # AgentOS's own suite
            ws = os.path.realpath(os.path.expanduser(self.cfg["workspace"]))
            rp = os.path.realpath(os.path.expanduser(p))
            if rp == ws or rp.startswith(ws + os.sep):
                return "safe", ""
            return "risky", f"Runs the test suite (arbitrary code) in {rp}."
        if name == "open_app":
            return "risky", "Launches an application or URL on your desktop."
        if name in ("schedule_task", "create_trigger"):
            return "risky", "Creates a recurring background task."
        if name == "update_soul":
            return "risky", "Rewrites the agent's soul (its persistent identity and behavior)."
        if name == "configure_agentos":
            return "risky", "Changes AgentOS configuration (autonomy, policies, integrations)."
        if name == "create_theme":
            return "safe", ""
        if name == "create_app":
            return "risky", "Installs a UI app (HTML/JS) onto the AgentOS desktop."
        if name in ("develop_agentos", "restart_agentos"):
            return "risky", "Modifies/restarts AgentOS's own source code (self-modification)."
        if name == "pin_widget":
            return "safe", ""
        if name == "add_mcp_server":
            return "risky", "Connects/removes an external MCP tool server."
        if name == "discover_mcp_servers":
            return "safe", ""
        if name == "install_mcp_server":
            return "risky", ("Installs an MCP server discovered in the public registry "
                             "(downloads and runs external code when it connects).")
        if name == "launch_native_app":
            return "risky", "Launches a native application on your desktop."
        if name == "manage_models":
            return "risky" if args.get("action") in ("pull", "remove") else "safe", "Downloads or removes an AI model."
        if name == "system_control":
            return "risky", "Changes system settings (volume, opens settings panels)."
        if name == "focus_window":
            return "safe", ""
        if name == "list_windows":
            return "safe", ""
        if name in ("desktop_state", "list_themes", "list_notifications",
                    "set_brightness", "audio", "power_profile"):
            return "safe", ""
        if name == "control_desktop":
            if args.get("action") == "close_app":
                return "risky", "Closes an app on the desktop (unsaved state may be lost)."
            return "safe", ""
        if name == "manage_window":
            if args.get("action") == "focus":
                return "safe", ""
            return "risky", f"Rearranges or closes a native window ({args.get('action', '?')})."
        if name == "wifi":
            if args.get("action") in ("connect", "forget", "enable", "disable"):
                return "risky", "Changes the machine's wifi connections."
            return "safe", ""
        if name == "bluetooth":
            if args.get("action") in ("pair", "connect", "disconnect", "forget"):
                return "risky", "Changes the machine's bluetooth pairings."
            return "safe", ""
        if name == "lock_screen":
            return "risky", "Locks the screen (interrupts whatever the user is doing)."
        if name == "power_action":
            return "risky", (f"Session power control ({args.get('action', '?')}) — "
                             "confirmed with the user every time.")
        if name == "take_screenshot":
            return "risky", "Captures the screen (it may show sensitive content)."
        if name.startswith("mcp_"):
            return "risky", "Calls a tool on an external MCP server."
        return "safe", ""

    # ---- git (Ship pillar) -------------------------------------------------
    # Structured tools instead of shell strings: each carries its own risk level
    # (reads auto-run; local writes are safe inside the workspace; push/remote/clone
    # ask for approval) and pushes authenticate via the GitHub token from Settings
    # without the token ever appearing in a command line or tool output.

    async def _git(self, repo: str, *argv: str, env: dict | None = None,
                   timeout: int = 120) -> tuple[int, str]:
        e = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
        proc = await asyncio.create_subprocess_exec(
            "git", "-C", repo, *argv,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=e)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return 1, f"[error] git timed out after {timeout}s"
        return proc.returncode or 0, out.decode(errors="replace")

    def _git_repo(self, path: str) -> tuple[str | None, str]:
        p = os.path.realpath(os.path.expanduser(path or self.cfg["workspace"]))
        if (deny := self._sandbox_deny(Path(p))):
            return None, deny
        if not os.path.isdir(p):
            return None, f"[error] not a directory: {p}"
        return p, ""

    def _git_auth_env(self) -> dict:
        """GIT_ASKPASS-based credentials: the token comes from config (Settings →
        github.token) via the environment — never argv, never remotes, never output."""
        token = (self.cfg.get("github") or {}).get("token", "")
        if not token:
            return {}
        from . import config as cfgmod
        askpass = cfgmod.AGENTOS_HOME / "git-askpass.sh"
        if not askpass.exists() or "AGENTOS_GIT" not in askpass.read_text():
            askpass.write_text("#!/bin/sh\n# AGENTOS_GIT askpass helper\n"
                               "case \"$1\" in\n"
                               "  *sername*) echo \"${AGENTOS_GIT_USER:-x-access-token}\";;\n"
                               "  *) echo \"$AGENTOS_GIT_TOKEN\";;\n"
                               "esac\n")
            askpass.chmod(0o700)
        return {"GIT_ASKPASS": str(askpass), "AGENTOS_GIT_TOKEN": token,
                "AGENTOS_GIT_USER": (self.cfg.get("github") or {}).get("username") or "x-access-token"}

    async def git_status(self, path: str = "") -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        code, out = await self._git(repo, "status", "--short", "--branch")
        if code != 0:
            return f"[error] {out.strip()[:800]}"
        _, remotes = await self._git(repo, "remote", "-v")
        return f"{out.strip() or '(clean)'}\n\nremotes:\n{remotes.strip() or '(none)'}"

    async def git_log(self, path: str = "", limit: int = 10) -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        code, out = await self._git(repo, "log", "--oneline", "--decorate",
                                    f"-{max(1, min(int(limit), 100))}")
        return _truncate(out) if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_diff(self, path: str = "", staged: bool = False, ref: str = "") -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        argv = ["diff", "--stat", "-p"]
        if staged:
            argv.append("--staged")
        if ref:
            argv.append(ref)
        code, out = await self._git(repo, *argv)
        return _truncate(out or "(no changes)") if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_init(self, path: str) -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        code, out = await self._git(repo, "init", "-b", "main")
        return out.strip() if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_commit(self, path: str, message: str, add_all: bool = True) -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        if not message.strip():
            return "[error] a commit message is required"
        if add_all:
            code, out = await self._git(repo, "add", "-A")
            if code != 0:
                return f"[error] git add: {out.strip()[:800]}"
        # per-invocation identity fallback so a fresh machine can still commit
        idargs = []
        code, _ = await self._git(repo, "config", "user.email")
        if code != 0:
            idargs = ["-c", "user.name=AgentOS", "-c", "user.email=agentos@localhost"]
        code, out = await self._git(repo, *idargs, "commit", "-m", message)
        if code != 0 and "nothing to commit" in out:
            return "nothing to commit — working tree clean"
        return out.strip()[:800] if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_branch(self, path: str, name: str = "", checkout: bool = True) -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        if not name:
            code, out = await self._git(repo, "branch", "-a", "-v")
            return _truncate(out) if code == 0 else f"[error] {out.strip()[:800]}"
        argv = ["checkout", "-b", name] if checkout else ["branch", name]
        code, out = await self._git(repo, *argv)
        return out.strip()[:400] if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_remote_set(self, path: str, url: str, name: str = "origin") -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        code, out = await self._git(repo, "remote", "get-url", name)
        if code == 0:
            code, out = await self._git(repo, "remote", "set-url", name, url)
        else:
            code, out = await self._git(repo, "remote", "add", name, url)
        return f"remote {name} -> {url}" if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_pull(self, path: str = "", remote: str = "origin", branch: str = "") -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        argv = ["pull", remote] + ([branch] if branch else [])
        code, out = await self._git(repo, *argv, env=self._git_auth_env(), timeout=300)
        return _truncate(out) if code == 0 else f"[error] {out.strip()[:800]}"

    async def git_clone(self, url: str, path: str) -> str:
        parent, err = self._git_repo(os.path.dirname(os.path.expanduser(path)) or self.cfg["workspace"])
        if err:
            return err
        dest = os.path.realpath(os.path.expanduser(path))
        proc_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **self._git_auth_env()}
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", url, dest,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=proc_env)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        except asyncio.TimeoutError:
            proc.kill()
            return "[error] git clone timed out after 600s"
        text = out.decode(errors="replace")
        return _truncate(text) if proc.returncode == 0 else f"[error] {text.strip()[:800]}"

    async def _github_api(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        token = (self.cfg.get("github") or {}).get("token", "")
        if not token:
            return 0, {"message": "no GitHub token configured (Settings → Integrations → GitHub)"}
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.request(method, f"https://api.github.com{path}", json=body,
                                     headers={"Authorization": f"token {token}",
                                              "Accept": "application/vnd.github+json"})
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, {}

    async def git_push(self, path: str = "", remote: str = "origin", branch: str = "",
                       create_github_repo: bool = False, private: bool = True) -> str:
        repo, err = self._git_repo(path)
        if err:
            return err
        if not branch:
            code, out = await self._git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            branch = out.strip() if code == 0 else "main"
        code, _ = await self._git(repo, "remote", "get-url", remote)
        created_url = ""
        if code != 0:  # no remote yet
            if not create_github_repo:
                return (f"[error] no remote '{remote}' configured — call git_remote_set, or "
                        f"re-call git_push with create_github_repo=true to create one on GitHub")
            name = os.path.basename(repo)
            status, data = await self._github_api("POST", "/user/repos",
                                                  {"name": name, "private": bool(private),
                                                   "description": f"Shipped from AgentOS"})
            if status == 0:
                return f"[error] {data['message']}"
            if status not in (200, 201):
                return f"[error] GitHub repo creation failed (HTTP {status}): {str(data.get('message', data))[:300]}"
            clone_url = data.get("clone_url", "")
            created_url = data.get("html_url", "")
            add_code, add_out = await self._git(repo, "remote", "add", remote, clone_url)
            if add_code != 0:
                return f"[error] {add_out.strip()[:400]}"
        env = self._git_auth_env()
        if not env:
            hint = " (no GitHub token configured — add one in Settings → Integrations for private/auth pushes)"
        else:
            hint = ""
        code, out = await self._git(repo, "push", "-u", remote, branch, env=env, timeout=300)
        if code != 0:
            return f"[error] git push failed{hint}: {out.strip()[:600]}"
        done = f"pushed {branch} -> {remote}"
        if created_url:
            done += f"\ncreated GitHub repo: {created_url}"
        return done + ("\n" + out.strip()[:400] if out.strip() else "")

    async def export_app_to_git(self, app: str, push: bool = False, private: bool = True) -> str:
        """Write an AgentOS app out of the SQLite store into a real project folder
        (workspace/projects/<slug>) with README + manifest, commit it, optionally
        create a GitHub repo and push."""
        rec = self.store.get_app(app)
        if not rec:
            match = [a for a in self.store.list_apps()
                     if a["name"].lower() == app.lower() or a["id"] == app]
            rec = self.store.get_app(match[0]["id"]) if match else None
        if not rec:
            return f"[error] no app named or id'd '{app}' — see list in the Apps/Studio UI"
        slug = re.sub(r"[^a-z0-9]+", "-", rec["name"].lower()).strip("-") or "agentos-app"
        proj = Path(os.path.expanduser(self.cfg["workspace"])) / "projects" / slug
        if (deny := self._sandbox_deny(proj)):
            return deny
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "index.html").write_text(rec["html"])
        manifest = {"name": rec["name"], "icon": rec.get("icon", ""),
                    "description": rec.get("description", ""),
                    "permissions": rec.get("manifest") or "",
                    "exported_from": "AgentOS", "app_id": rec["id"]}
        (proj / "manifest.json").write_text(json.dumps(manifest, indent=2))
        (proj / "README.md").write_text(
            f"# {rec['name']}\n\n{rec.get('description', '')}\n\n"
            f"Built with the AgentOS App Studio. `index.html` is a self-contained app;\n"
            f"open it in a browser, or import it into an AgentOS desktop via the Store.\n")
        code, out = await self._git(str(proj), "rev-parse", "--git-dir")
        if code != 0:
            init_out = await self.git_init(str(proj))
            if init_out.startswith("[error]"):
                return init_out
        commit_out = await self.git_commit(str(proj), f"Export {rec['name']} from AgentOS")
        result = f"exported to {proj}\n{commit_out}"
        if push:
            push_out = await self.git_push(str(proj), create_github_repo=True, private=private)
            result += "\n" + push_out
        return result

    # ---- TrainForge (Train pillar) ------------------------------------------
    # Fine-tune and evaluate your own models locally. TrainForge runs as a
    # supervised loopback service (see agentos/trainforge.py); these tools call
    # its REST API server-side. Watch runs live in the Train desktop app.

    def _tf(self):
        tf = getattr(self, "trainforge", None)
        if tf is None:
            return None, "[error] TrainForge integration not initialised (server startup)"
        return tf, ""

    @staticmethod
    def _tf_out(code: int, data) -> str:
        if code == 0:
            return f"[error] {data}"
        body = json.dumps(data, indent=1, default=str) if isinstance(data, (dict, list)) else str(data)
        return _truncate(body if code < 400 else f"[error] HTTP {code}: {body[:800]}")

    async def trainforge_service(self, action: str = "status") -> str:
        tf, err = self._tf()
        if err:
            return err
        if action == "start":
            return await tf.start()
        if action == "stop":
            return await tf.stop()
        return json.dumps(await tf.health())

    async def train_autopilot(self, goal: str, max_rows: int = 5000) -> str:
        tf, err = self._tf()
        if err:
            return err
        code, data = await tf.api("POST", "/api/agent/runs",
                                  {"goal": goal, "max_rows": int(max_rows)})
        return self._tf_out(code, data)

    async def train_datasets(self, action: str = "list", query: str = "", repo_id: str = "",
                             url: str = "", name: str = "", dataset_id: int = 0,
                             max_rows: int = 5000) -> str:
        tf, err = self._tf()
        if err:
            return err
        if action == "list":
            code, data = await tf.api("GET", "/api/datasets")
        elif action == "search":
            code, data = await tf.api("GET", "/api/datasets/search-hub",
                                      params={"q": query, "limit": 25})
        elif action == "import_hub":
            body = {"repo_id": repo_id, "max_rows": int(max_rows)}
            if name:
                body["name"] = name
            code, data = await tf.api("POST", "/api/datasets/import-hub", body)
        elif action == "import_url":
            code, data = await tf.api("POST", "/api/datasets/import-url",
                                      {"url": url, **({"name": name} if name else {})})
        elif action == "get":
            code, data = await tf.api("GET", f"/api/datasets/{int(dataset_id)}")
        elif action == "preview":
            code, data = await tf.api("GET", f"/api/datasets/{int(dataset_id)}/preview",
                                      params={"rows": 30})
        else:
            return "[error] action must be list|search|import_hub|import_url|get|preview"
        return self._tf_out(code, data)

    async def train_job(self, action: str = "list", job_id: int = 0, name: str = "",
                        dataset_id: int = 0, task: str = "", base_model: str = "",
                        hyperparams: dict | None = None, offset: int = 0) -> str:
        tf, err = self._tf()
        if err:
            return err
        if action == "list":
            code, data = await tf.api("GET", "/api/jobs")
        elif action == "create":
            body = {"name": name or f"{task} on dataset {dataset_id}",
                    "dataset_id": int(dataset_id), "task": task}
            if base_model:
                body["base_model"] = base_model
            if hyperparams:
                body["hyperparams"] = hyperparams
            code, data = await tf.api("POST", "/api/jobs", body)
        elif action == "status":
            code, data = await tf.api("GET", f"/api/jobs/{int(job_id)}")
        elif action == "logs":
            code, data = await tf.api("GET", f"/api/jobs/{int(job_id)}/logs",
                                      params={"offset": int(offset)})
        elif action == "metrics":
            code, data = await tf.api("GET", f"/api/jobs/{int(job_id)}/metrics")
        elif action == "stop":
            code, data = await tf.api("POST", f"/api/jobs/{int(job_id)}/stop")
        else:
            return "[error] action must be list|create|status|logs|metrics|stop"
        return self._tf_out(code, data)

    async def train_model(self, action: str = "list", model_id: int = 0,
                          inputs: list | None = None, prompt: str = "",
                          repo_id: str = "", private: bool = True) -> str:
        tf, err = self._tf()
        if err:
            return err
        if action == "list":
            code, data = await tf.api("GET", "/api/models")
        elif action == "signature":
            code, data = await tf.api("GET", f"/api/models/{int(model_id)}/signature")
        elif action == "predict":
            body = {"prompt": prompt, "max_new_tokens": 200} if prompt else {"inputs": inputs or []}
            code, data = await tf.api("POST", f"/api/models/{int(model_id)}/predict",
                                      body, timeout=180)
        elif action == "publish":
            code, data = await tf.api("POST", f"/api/models/{int(model_id)}/publish",
                                      {"repo_id": repo_id, "private": bool(private)}, timeout=600)
        else:
            return "[error] action must be list|signature|predict|publish"
        return self._tf_out(code, data)

    # ---- Hermes (companion agent) -------------------------------------------

    async def hermes_status(self) -> str:
        from . import hermes
        return json.dumps(await hermes.status(self.cfg))

    async def hermes_ask(self, task: str) -> str:
        from . import hermes
        return _truncate(await hermes.ask(task))

    async def hermes_send(self, target: str, message: str) -> str:
        from . import hermes
        return await hermes.send(target, message)

    # ---- Desktop parity (the parity law) ------------------------------------
    # Every capability the desktop UI has is also an agent tool through the same
    # PDP gate. Each degrades gracefully: on machines without the capability
    # (hosted mode, macOS, no D-Bus) the tool returns a sentence, never raises.
    # Shell actions go through server.shell_command (the browser UI answers);
    # native windows through the host facade; radios/power through hostctl.

    _NO_SHELL = ("[error] not supported on this platform: no desktop shell channel — "
                 "the browser UI is the shell and it isn't connected")

    async def desktop_state(self) -> str:
        """One live snapshot of the desktop: shell apps, native windows + focus,
        workspace, battery, power profile, network, volume, brightness, and unread
        notifications. Every section is best-effort; unavailable ones are omitted."""
        from . import host
        out: dict = {}
        if self.shell is not None:
            try:
                ok, data = await self.shell("list_open_apps", {}, timeout=3)
                if ok:
                    out["shell_apps"] = data
            except Exception:
                pass
        try:
            w = host.list_windows()
            if w.get("available"):
                out["windows"] = [{k: x.get(k) for k in
                                   ("id", "app", "title", "workspace", "focused") if k in x}
                                  for x in w["windows"]]
                foc = next((x for x in w["windows"] if x.get("focused")), None)
                if foc:
                    out["focused"] = f"{foc.get('title', '')} ({foc.get('app', '')})"
        except Exception:
            pass
        try:
            ws = host.workspaces()
            if ws.get("available"):
                out["workspace"] = next(
                    (x["name"] for x in ws["workspaces"] if x.get("focused")), "")
        except Exception:
            pass
        try:
            if (bat := host.get_battery()):
                out["battery"] = bat
        except Exception:
            pass
        try:
            from .hostctl import upower
            out["power_profile"] = (await upower.get_profile())["active"]
        except Exception:
            pass
        try:
            if (net := host.get_network()):
                out["network"] = net
        except Exception:
            pass
        try:
            out["audio"] = host.get_volume()
        except Exception:
            pass
        try:
            from .hostctl import brightness
            if (bl := brightness.backlights()):
                out["brightness"] = {d["name"]: d["percent"] for d in bl}
        except Exception:
            pass
        if self.notifd is not None:
            try:
                st = self.notifd.state()
                out["notifications"] = {"unread": st["unread"], "dnd": st["dnd"]}
            except Exception:
                pass
        if not out:
            return "(no desktop state available on this platform)"
        return json.dumps(out, indent=1)

    async def control_desktop(self, action: str, target: str = "") -> str:
        """Drive the AgentOS desktop shell (the browser UI): open/close/focus its app
        windows, switch virtual desktops, apply a theme, list what's open."""
        actions = ("open_app", "close_app", "focus_app", "switch_desktop",
                   "apply_theme", "list_open_apps")
        if action not in actions:
            return f"[error] action must be one of: {' | '.join(actions)}"
        if self.shell is None:
            return self._NO_SHELL
        if action == "apply_theme":
            known = BUILTIN_THEMES + [t["name"] for t in self.store.list_themes()]
            if target not in known:
                return f"[error] no theme named '{target}'. Available: {', '.join(known)}"
        ok, data = await self.shell(action, {"target": target})
        if not ok:
            return f"[error] {data}"
        body = data if isinstance(data, str) else json.dumps(data)
        return body or f"{action} done" + (f": {target}" if target else "")

    async def manage_window(self, window_id: str, action: str, workspace: str = "") -> str:
        """Manage a NATIVE window by id or title fragment: focus | close | float |
        tile | move_to_workspace. Find ids with list_windows / desktop_state."""
        from . import host
        w = host.list_windows()
        if not w.get("available"):
            return ("[error] not supported on this platform: "
                    f"{w.get('reason', 'window control unavailable')}")
        q = str(window_id).strip().lower()
        win = (next((x for x in w["windows"] if str(x.get("id", "")).lower() == q), None)
               or next((x for x in w["windows"]
                        if q in str(x.get("title", "")).lower()
                        or q in str(x.get("app", "")).lower()), None))
        if not win:
            return f"[error] no open window matching '{window_id}' — see list_windows"
        wid = str(win["id"])
        if action == "focus":
            ok, msg = host.focus_window(wid)
        elif action == "close":
            ok, msg = host.close_window(wid)
        elif action in ("float", "tile"):
            ok, msg = host.set_window_floating(wid, action == "float")
        elif action == "move_to_workspace":
            if not workspace:
                return "[error] move_to_workspace needs `workspace`"
            ok, msg = host.move_window_to_workspace(wid, workspace)
        else:
            return "[error] action must be focus | close | float | tile | move_to_workspace"
        return f"{action}: {win.get('title') or wid}" if ok else f"[error] {msg}"

    async def list_themes(self) -> str:
        """The theme ids control_desktop(action='apply_theme') accepts."""
        custom = [t["name"] for t in self.store.list_themes()]
        lines = ["built-in: " + ", ".join(BUILTIN_THEMES)]
        if custom:
            lines.append("custom: " + ", ".join(custom))
        return "\n".join(lines)

    async def run_python(self, code: str, timeout: int = 120) -> str:
        """Run a Python snippet and return its output.

        Goes through run_command rather than around it, so the sandbox jail, the
        risk classification and the permission gate all apply exactly as they do
        to any other command — a Python escape hatch that skipped those would
        quietly become the widest hole in the system.
        """
        if not (code or "").strip():
            return "[error] nothing to run"
        enabled, root = sandbox_conf(self.cfg)
        base = root if enabled else os.path.expanduser(self.cfg["workspace"])
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, f".agentos-run-{uuid.uuid4().hex[:8]}.py")
        try:
            with open(path, "w") as fh:
                fh.write(code)
            out = await self.run_command(f"{shlex.quote(sys.executable)} {shlex.quote(path)}")
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)
        return out or "(no output)"

    # -- automations: named desktop sequences the user can replay -------------

    async def list_automations(self) -> str:
        """Every saved automation, with its steps — so you can run one by name."""
        rows = self.store.list_automations()
        if not rows:
            return ("no automations saved yet. Create one with save_automation, or the user can "
                    "build one in the Automations app.")
        out = []
        for a in rows:
            steps = ", ".join(_automation_step_label(s) for s in a["steps"])
            out.append(f"- {a['name']}  ({len(a['steps'])} steps: {steps})")
        return "\n".join(out)

    async def run_automation(self, name: str) -> str:
        """Fire a saved automation on the desktop, exactly as the user set it up."""
        a = self.store.get_automation(name)
        if not a:
            known = ", ".join(r["name"] for r in self.store.list_automations()) or "none saved"
            return f"[error] no automation named {name!r}. Saved: {known}"
        self.store.mark_automation_run(a["id"])
        if self.broadcast:
            await self.broadcast({"type": "automation.run", "automation": a})
        self.store.log("automation", f"ran {a['name']}", {"via": "agent"})
        return f"ran automation '{a['name']}' ({len(a['steps'])} steps)"

    async def save_automation(self, name: str, steps: str, icon: str = "") -> str:
        """Create or edit an automation. Saving an existing name edits it in place."""
        try:
            parsed = json.loads(steps) if isinstance(steps, str) else steps
        except Exception as e:
            return f"[error] steps must be a JSON array: {e}"
        if not isinstance(parsed, list):
            return "[error] steps must be a JSON array of step objects"
        from .server import _clean_steps
        clean = _clean_steps(parsed)
        if not clean:
            return ("[error] no valid steps. Each step needs a kind: app | action | theme | "
                    "wallpaper | desktop | agent | wait")
        existed = self.store.get_automation(name) is not None
        self.store.save_automation(name.strip(), json.dumps(clean), icon)
        if self.broadcast:
            await self.broadcast({"type": "automations"})
        verb = "updated" if existed else "created"
        return (f"{verb} automation '{name.strip()}' with {len(clean)} steps — "
                f"run it any time from the prompt bar, a hot corner, or by asking me.")

    async def wifi(self, action: str = "status", ssid: str = "", password: str = "") -> str:
        """Wifi via NetworkManager: status | list | connect | forget | enable | disable."""
        try:
            from .hostctl import HostCtlError, network
        except Exception as e:
            return f"[error] not supported on this platform: {e}"
        try:
            if action in ("status", ""):
                st = await network.status()
                from . import host
                st["connections"] = (host.get_network() or {}).get("connections", [])
                return json.dumps(st)
            if action == "list":
                nets = await network.wifi_scan()
                if not nets:
                    return "no wifi networks in range"
                return "\n".join(
                    f"- {n['ssid']}  {n['signal']}%  {n['security']}"
                    + ("  [connected]" if n["connected"] else "")
                    + ("  [saved]" if n.get("saved") else "") for n in nets[:25])
            if action == "connect":
                if not ssid:
                    return "[error] connect needs `ssid`"
                await network.wifi_join(ssid, password or None)
                self.store.log("system", f"wifi: joined '{ssid}' (agent)")
                return f"joined wifi network '{ssid}'"
            if action == "forget":
                if not await network.wifi_forget(ssid):
                    return f"[error] no saved network named '{ssid}'"
                self.store.log("system", f"wifi: forgot '{ssid}' (agent)")
                return f"forgot wifi network '{ssid}'"
            if action in ("enable", "disable"):
                await network.set_wifi_enabled(action == "enable")
                return f"wifi {action}d"
            return "[error] action must be status | list | connect | forget | enable | disable"
        except HostCtlError as e:
            return f"[error] {e}"

    async def bluetooth(self, action: str = "status", device: str = "") -> str:
        """Bluetooth via BlueZ: status | scan | pair | connect | disconnect | forget."""
        try:
            from .hostctl import HostCtlError
            from .hostctl import bluetooth as bt
        except Exception as e:
            return f"[error] not supported on this platform: {e}"

        def fmt(t: dict) -> str:
            lines = [f"adapter {a['name']}: {'on' if a['powered'] else 'off'}"
                     + (" (discovering)" if a.get("discovering") else "")
                     for a in t["adapters"]]
            for d in t["devices"][:25]:
                tags = [k for k in ("connected", "paired", "trusted") if d.get(k)]
                lines.append(f"- {d['name']} [{d['address']}]"
                             + (f"  ({', '.join(tags)})" if tags else ""))
            return "\n".join(lines) or "no bluetooth adapters"

        try:
            if action in ("status", ""):
                return fmt(await bt.tree())
            if action == "scan":
                t = await bt.tree()
                if not t["adapters"]:
                    return "[error] no bluetooth adapter found on this machine"
                ad = t["adapters"][0]["path"]
                await bt.set_discovering(ad, True)
                await asyncio.sleep(4)     # give nearby devices a beat to answer
                t = await bt.tree()
                await bt.set_discovering(ad, False)
                return fmt(t)
            if action in ("pair", "connect", "disconnect", "forget"):
                if not device:
                    return f"[error] {action} needs `device` (a name or address from status/scan)"
                t = await bt.tree()
                q = device.strip().lower()
                dev = (next((d for d in t["devices"] if d["address"].lower() == q), None)
                       or next((d for d in t["devices"] if q in d["name"].lower()), None))
                if not dev:
                    return f"[error] no bluetooth device matching '{device}'"
                await bt.device_action(dev["path"], "remove" if action == "forget" else action)
                self.store.log("system", f"bluetooth: {action} {dev['name']} (agent)")
                return f"{action}: {dev['name']} [{dev['address']}]"
            return "[error] action must be status | scan | pair | connect | disconnect | forget"
        except HostCtlError as e:
            return f"[error] {e}"

    async def set_brightness(self, percent: int, name: str = "") -> str:
        """Set screen brightness 0-100 (internal backlight by default; a DDC display
        number for external monitors)."""
        try:
            from .hostctl import HostCtlError, brightness
        except Exception as e:
            return f"[error] not supported on this platform: {e}"
        try:
            pct = max(0, min(100, int(percent)))
            if not name:
                st = await brightness.state()
                if not st["displays"]:
                    return ("[error] not supported on this platform: "
                            f"{st.get('reason') or 'no adjustable display'}")
                name = str(st["displays"][0]["name"])
            await brightness.set_level(name, pct)
            return f"brightness set to {pct}%"
        except (HostCtlError, ValueError) as e:
            return f"[error] {e}"

    async def audio(self, action: str = "status", value: int = 50, device: str = "") -> str:
        """Audio: status (volume + devices) | volume (value 0-100) | mute | unmute |
        route (make `device` the default output — e.g. switch to headphones)."""
        from . import host
        a = action.strip().lower()
        if a in ("status", ""):
            out = {"volume": host.get_volume()}
            try:
                from .hostctl import audio as hw
                out["devices"] = hw.devices()
            except Exception:
                pass          # pipewire routing is optional; volume still answers
            return json.dumps(out)
        if a == "volume":
            pct = max(0, min(100, int(value)))
            if not host.set_volume(percent=pct):
                return "[error] not supported on this platform: no volume control (wpctl/amixer)"
            return f"volume set to {pct}%"
        if a in ("mute", "unmute"):
            if not host.set_volume(mute=(a == "mute")):
                return "[error] not supported on this platform: no volume control (wpctl/amixer)"
            return a + "d"
        if a == "route":
            try:
                from .hostctl import HostCtlError
                from .hostctl import audio as hw
            except Exception as e:
                return f"[error] not supported on this platform: {e}"
            try:
                devs = hw.devices()
                q = device.strip().lower()
                sink = (next((s for s in devs["sinks"] if str(s["id"]) == q), None)
                        or next((s for s in devs["sinks"]
                                 if q and q in s["description"].lower()), None))
                if not sink:
                    names = ", ".join(f"{s['id']}: {s['description']}"
                                      for s in devs["sinks"]) or "(none)"
                    return f"[error] no output device matching '{device}'. Sinks: {names}"
                hw.set_default(int(sink["id"]))
                return f"audio output routed to {sink['description']}"
            except HostCtlError as e:
                return f"[error] {e}"
        return "[error] action must be status | volume | mute | unmute | route"

    async def power_profile(self, profile: str = "") -> str:
        """Read (no arguments) or set the machine's power profile
        (power-saver | balanced | performance)."""
        try:
            from .hostctl import HostCtlError, upower
        except Exception as e:
            return f"[error] not supported on this platform: {e}"
        try:
            if not profile:
                p = await upower.get_profile()
                return f"active: {p['active']} (available: {', '.join(p['profiles'])})"
            await upower.set_profile(profile)
            return f"power profile set to {profile}"
        except HostCtlError as e:
            return f"[error] {e}"

    async def lock_screen(self) -> str:
        """Lock the session immediately (the user unlocks with their password)."""
        from . import server as srv
        ok, msg = await srv.power_exec("lock")
        return "screen locked" if ok else f"[error] {msg}"

    async def power_action(self, action: str) -> str:
        """Session power control: suspend | reboot | poweroff | logout. The user
        confirms every call (ALWAYS_ASK); run_command keeps shutdown/reboot blocked —
        this tool is the sanctioned path."""
        aliases = {"suspend": "suspend", "sleep": "suspend",
                   "reboot": "restart", "restart": "restart",
                   "poweroff": "poweroff", "shutdown": "poweroff", "logout": "logout"}
        act = aliases.get(action.strip().lower())
        if not act:
            return "[error] action must be suspend | reboot | poweroff | logout"
        from . import server as srv
        self.store.log("system", f"power: {act} requested by the agent (user approved)")
        ok, msg = await srv.power_exec(act)
        return f"{act} initiated" if ok else f"[error] {msg}"

    async def list_notifications(self, limit: int = 20, unread_only: bool = False) -> str:
        """Read the desktop notification center (DE mode): what apps notified the user."""
        if self.notifd is None:
            return ("[error] not supported on this platform: AgentOS is not the "
                    "notification daemon here (hosted mode — the host desktop shows them)")
        items = self.notifd.recent(limit=int(limit), unread_only=bool(unread_only))
        if not items:
            return "no notifications" + (" (unread)" if unread_only else "")
        lines = []
        for n in items:
            stamp = time.strftime("%H:%M", time.localtime(n["time"]))
            lines.append(f"- [{stamp}] {n['app'] or 'system'}: {n['summary']}"
                         + (f" — {n['body']}" if n["body"] else "")
                         + ("" if n["read"] else "  (unread)"))
        st = self.notifd.state()
        return "\n".join(lines) + (f"\n({st['unread']} unread · "
                                   f"DND {'on' if st['dnd'] else 'off'})")

    async def take_screenshot(self, target: str = "screen") -> str:
        """Capture the screen to <workspace>/Screenshots and SEE it — the agent loop
        attaches the image for vision-capable models (via the {"__image__": path}
        result shape); others get the saved path."""
        from . import server as srv
        ok, res = await srv.capture_screen(
            area="select" if target == "select" else "full",
            workspace=self.cfg.get("workspace", ""))
        if not ok:
            return f"[error] {res}"
        self.store.log("system", f"screenshot by agent: {Path(res).name}")
        return json.dumps({"__image__": res, "text": f"screenshot saved to {res}"})

    async def execute(self, name: str, args: dict) -> str:
        if name.startswith("mcp_") and self.mcp:
            target = self.mcp.resolve(name)
            if not target:
                return f"[error] unknown MCP tool: {name}"
            ctx = args.get("_ctx") or {}
            call_args = {k: v for k, v in args.items() if not k.startswith("_")}
            out = await self.mcp.call(target[0], target[1], call_args, context=ctx)
            self.store.log("mcp", f"{target[0]}/{target[1]}",
                           {"args": call_args, "ok": not out.startswith("[error]")},
                           conversation_id=str(ctx.get("conversation_id") or ""),
                           space_id=str(ctx.get("space_id") or ""))
            return _truncate_envelope(out)
        fn = getattr(self, name, None)
        if fn is None or name not in {t["name"] for t in TOOL_SCHEMAS}:
            return f"[error] unknown tool: {name}"
        if set(args.keys()) == {"_raw"}:
            # the streamed tool-call JSON was cut off mid-argument (output token limit)
            return (f"[error] your {name} tool call was cut off at the output token limit — "
                    f"the arguments arrived as truncated JSON. If you were passing a large "
                    f"payload (e.g. a whole app's html), emit it as a ```html code block in "
                    f"plain text instead of a tool call, or produce a smaller version.")
        try:
            return await fn(**{k: v for k, v in args.items() if not k.startswith("_")})
        except TypeError as e:
            return f"[error] bad arguments for {name}: {e}"
        except Exception as e:
            return f"[error] {type(e).__name__}: {e}"


GIT_TOOL_SCHEMAS = [
    {
        "name": "git_status",
        "description": "Git: working-tree status + configured remotes for a repository.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory (default: the workspace)."}},
            "required": []},
    },
    {
        "name": "git_log",
        "description": "Git: recent commit history (one line per commit).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory (default: the workspace)."},
            "limit": {"type": "integer", "description": "Number of commits (default 10)."}},
            "required": []},
    },
    {
        "name": "git_diff",
        "description": "Git: diff of working tree (or staged changes, or against a ref).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory (default: the workspace)."},
            "staged": {"type": "boolean", "description": "Diff staged changes instead."},
            "ref": {"type": "string", "description": "Diff against this ref (e.g. main, HEAD~2)."}},
            "required": []},
    },
    {
        "name": "git_init",
        "description": "Git: initialise a new repository (branch 'main') in a directory.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Directory to initialise."}},
            "required": ["path"]},
    },
    {
        "name": "git_commit",
        "description": "Git: stage (all changes by default) and commit with a message.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory."},
            "message": {"type": "string", "description": "Commit message."},
            "add_all": {"type": "boolean", "description": "git add -A first (default true)."}},
            "required": ["path", "message"]},
    },
    {
        "name": "git_branch",
        "description": "Git: list branches (no name), or create one (and check it out by default).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory."},
            "name": {"type": "string", "description": "New branch name (omit to list)."},
            "checkout": {"type": "boolean", "description": "Switch to the new branch (default true)."}},
            "required": ["path"]},
    },
    {
        "name": "git_remote_set",
        "description": "Git: add or update a remote URL (default remote name: origin).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory."},
            "url": {"type": "string", "description": "Remote URL (https://github.com/user/repo.git)."},
            "name": {"type": "string", "description": "Remote name (default origin)."}},
            "required": ["path", "url"]},
    },
    {
        "name": "git_push",
        "description": "Git: push the current (or named) branch to a remote. With "
                       "create_github_repo=true and no remote configured, creates the GitHub repo "
                       "first (uses the GitHub token from Settings) and pushes to it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory (default: the workspace)."},
            "remote": {"type": "string", "description": "Remote name (default origin)."},
            "branch": {"type": "string", "description": "Branch (default: current)."},
            "create_github_repo": {"type": "boolean", "description": "Create the GitHub repo if no remote exists."},
            "private": {"type": "boolean", "description": "Created repo visibility (default private)."}},
            "required": []},
    },
    {
        "name": "git_pull",
        "description": "Git: pull from a remote.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Repo directory (default: the workspace)."},
            "remote": {"type": "string", "description": "Remote name (default origin)."},
            "branch": {"type": "string", "description": "Branch (optional)."}},
            "required": []},
    },
    {
        "name": "git_clone",
        "description": "Git: clone a repository into a directory (authenticates with the GitHub "
                       "token from Settings for private repos).",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "Repository URL."},
            "path": {"type": "string", "description": "Destination directory."}},
            "required": ["url", "path"]},
    },
    {
        "name": "export_app_to_git",
        "description": "Ship an AgentOS app: write its source to workspace/projects/<name> with "
                       "README + manifest, commit it, and optionally create a GitHub repo and push. "
                       "Use when the user wants to publish/export/version an app they built.",
        "parameters": {"type": "object", "properties": {
            "app": {"type": "string", "description": "App name or id."},
            "push": {"type": "boolean", "description": "Also create a GitHub repo and push (default false)."},
            "private": {"type": "boolean", "description": "GitHub repo visibility (default private)."}},
            "required": ["app"]},
    },
]

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
                "path": {"type": "string", "description": "Destination file path (~ allowed); parent folders are created."},
                "content": {"type": "string", "description": "The full text to write — replaces the file's contents."},
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
            "properties": {"url": {"type": "string", "description": "Full http(s) URL of the page or API endpoint to fetch."}},
            "required": ["url"],
        },
    },
    {
        "name": "llm_generate",
        "description": "Run a raw one-shot LLM completion (no tools, no agent loop) and return the text. "
                       "Use it to summarize, classify, rewrite, or EXTRACT structured data from messy "
                       "text/HTML — e.g. pull a price out of a fetched page regardless of layout. "
                       "Built apps call this through appLLM(prompt, system) to put AI inside their features.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The full prompt, including any input text to work on."},
                "system": {"type": "string", "description": "Optional system instruction, e.g. 'Reply with ONLY a JSON object {price, currency}'."},
                "model": {"type": "string", "description": "Optional model override; defaults to the OS default model."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "system_info",
        "description": "Get a snapshot of the machine: OS, CPU, memory, disk, load, current time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "open_app",
        "description": "Open an application, file, or URL on the user's desktop "
                       "(host OS default handler).",
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
            "properties": {"title": {"type": "string", "description": "Short notification headline."},
                           "message": {"type": "string", "description": "Body text with the detail (optional)."}},
            "required": ["title"],
        },
    },
    {
        "name": "remember",
        "description": "Save a fact to memory. scope='user' (default) is durable and shared across all "
                       "conversations — use it for who the user is, preferences, projects, machine facts. "
                       "scope='session' only lives inside the current conversation — use it for decisions, "
                       "constraints, and working state of the task at hand.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to remember, one self-contained sentence."},
                "scope": {"type": "string", "enum": ["user", "session"],
                          "description": "user = durable across conversations (default); session = this conversation only."},
            },
            "required": ["content"],
        },
    },
    {
        "name": "search_files",
        "description": "Search the user's workspace files and docs BY MEANING (semantic, with "
                       "substring fallback). Use for 'find the file about X' — recall is for "
                       "memories, this is for files.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to find, in natural language."},
                "limit": {"type": "integer", "description": "Max results (default 8)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "recall",
        "description": "Search memory (user + session). Empty query returns the most recent memories. "
                       "Results are tagged [id|scope] — use the id with `forget`.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keywords to search memories for; empty for the most recent."}},
        },
    },
    {
        "name": "forget",
        "description": "Delete a memory by id (find ids with `recall`). Use when the user corrects or "
                       "retracts something you had remembered.",
        "parameters": {
            "type": "object",
            "properties": {"memory_id": {"type": "string", "description": "The id from a `recall` result's [id|scope] tag."}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "delegate",
        "description": "Delegate a task to a specialist subagent (see the Team app: e.g. researcher, "
                       "writer, validator). It runs with its own model, restricted tools, and budget, "
                       "and returns its result. Use for focused subtasks or to get a second model's "
                       "judgement on work.",
        "parameters": {
            "type": "object",
            "properties": {
                "subagent": {"type": "string", "description": "Subagent name, e.g. 'researcher'."},
                "task": {"type": "string", "description": "Self-contained task description — the subagent sees nothing else."},
            },
            "required": ["subagent", "task"],
        },
    },
    {
        "name": "run_workflow",
        "description": "Run a stored multi-subagent workflow (a DAG where each step is executed by a "
                       "subagent, possibly on different models — e.g. draft locally, validate on a "
                       "frontier model). Returns the final step's output.",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow": {"type": "string", "description": "Workflow name, e.g. 'draft-and-validate'."},
                "input": {"type": "string", "description": "The input/request the workflow operates on."},
            },
            "required": ["workflow", "input"],
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
                "subject": {"type": "string", "description": "The entity the fact is about, e.g. 'Piyush'."},
                "relation": {"type": "string", "description": "snake_case verb, e.g. works_at, uses, depends_on"},
                "object": {"type": "string", "description": "The entity the subject relates to, e.g. 'Accacia'."},
                "subject_type": {"type": "string", "description": "Optional label for the subject: person/org/project/tool/…"},
                "object_type": {"type": "string", "description": "Optional label for the object: person/org/project/tool/…"},
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
            "properties": {"query": {"type": "string", "description": "Entity or relation keywords to match; empty for all facts."}},
        },
    },
    {
        "name": "update_soul",
        "description": "Rewrite your soul file — your persistent identity, personality, and values, injected "
                       "into every future conversation. Pass the COMPLETE new markdown (it replaces the old one).",
        "parameters": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "The complete new soul markdown — replaces the previous version."}},
            "required": ["content"],
        },
    },
    {
        "name": "create_theme",
        "description": "Design and apply a complete OS theme — or REFINE one you already made. Calling it with "
                       "an EXISTING theme name updates that theme in place: vars merge key-by-key and css/font/"
                       "shell are kept unless passed, so send only what changes. When the user iterates on a "
                       "theme ('make it warmer', 'bigger radius', 'now add a font'), reuse the SAME name from "
                       "earlier in the conversation — only start a new name for a genuinely new theme. `vars` is "
                       "a JSON object of CSS variables (bg, bg2, bg3, bg4, line, txt, dim, dim2, acc, acc2, warn, "
                       "err, ok, glass). `css` is extra CSS to restyle chrome: windows (.win, .ttl), the top menu "
                       "bar (#menubar), the dock (#taskbar), app icons (.aicon), widgets (.widget), the desktop "
                       "(#desktop). Optional web font (font_url + font_family, e.g. a Google Fonts URL). For a "
                       "TOTAL redesign pass shell_html: complete HTML+CSS+JS that replaces the stock desktop with "
                       "your own interface — it runs same-origin and may use every endpoint listed by GET "
                       "/api/registry (REST + the /ws websocket), so it can do anything the stock UI does. "
                       "Applies live; saved to the Themes app. Use when the user asks to restyle, redesign, "
                       "tweak, or completely reimagine the UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "theme name; reuse the same name to refine instead of forking"},
                "mode": {"type": "string", "enum": ["dark", "light"], "description": "overall brightness the palette is designed for"},
                "vars": {"type": "string", "description": "JSON object of CSS variables — when refining, only the keys to change"},
                "css": {"type": "string", "description": "extra CSS restyling the desktop chrome/widgets; omit when refining to keep the current css"},
                "font_url": {"type": "string", "description": "optional stylesheet URL for a web font, e.g. a Google Fonts CSS link"},
                "font_family": {"type": "string", "description": "the CSS font-family name that font provides, e.g. 'Inter'"},
                "shell_html": {"type": "string", "description": "optional full replacement interface (HTML+CSS+JS) that takes over the screen; omit to keep an existing shell, pass \"\" to remove it; call GET /api/registry for the endpoints it can use"},
            },
            "required": ["name", "vars"],
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
                       "ENTIRE AgentOS REST API — GET /api/registry lists every endpoint, tool and realtime "
                       "event it may use (e.g. /api/system, /api/tasks, /api/memories, POST /api/chat {text}, "
                       "POST /api/tool {name,args}, the /ws websocket). Use this when the user asks for a new "
                       "tool, widget, dashboard, or UI enhancement.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Concise app name shown under the desktop icon; reuse an existing name to update that app."},
                "icon": {"type": "string", "description": "leave empty — the OS renders a clean monogram tile (the user dislikes emoji icons)"},
                "description": {"type": "string", "description": "One line: what the app does (shown in the launcher and Store)."},
                "html": {"type": "string", "description": "The complete self-contained HTML/CSS/JS for the app (fragment or full document)."},
                "permissions": {"type": "string", "description":
                    "JSON list of {action, resource, reason, required} declaring every capability "
                    "the app uses at runtime (appTool/appData/api calls) — e.g. "
                    "[{\"action\":\"tool.use\",\"resource\":\"tool:system_info*\",\"reason\":\"show host stats\",\"required\":false}]. "
                    "The user consents to exactly this list; undeclared calls prompt at runtime."},
            },
            "required": ["name", "icon", "description", "html"],
        },
    },
    {
        "name": "snapshot_os",
        "description": "Save a restore point of the entire OS (config, data, and source code) that can be "
                       "rolled back to later. Do this before risky changes.",
        "parameters": {"type": "object", "properties": {"label": {"type": "string", "description": "Short human-readable label for the restore point, e.g. 'before theme rewrite'."}}},
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
                "restart": {"type": "boolean", "description": "true to restart the service now so the change takes effect."},
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
        "name": "manage_models",
        "description": "Manage local Ollama models. action='list' shows installed models + GPU; "
                       "action='pull' downloads a model by name (e.g. 'llama3.2', 'qwen2.5:14b'); "
                       "action='remove' deletes one. Use when the user wants to add/remove/inspect models.",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["list", "pull", "remove"]},
                           "name": {"type": "string", "description": "Model name for pull/remove, e.g. 'qwen2.5:14b'; not needed for list."}},
        },
    },
    {
        "name": "launch_native_app",
        "description": "Launch an installed native app on the host desktop (e.g. Firefox, "
                       "Files, Settings, Calculator, Terminal, VS Code).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The app's name as the user would say it, e.g. 'firefox' or 'calculator'."}}, "required": ["name"]},
    },
    {
        "name": "list_windows",
        "description": "List the native app windows currently open on the desktop.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "focus_window",
        "description": "Switch to (raise/focus) an open native window by part of its title — like alt-tab.",
        "parameters": {"type": "object", "properties": {"title": {"type": "string", "description": "Any distinctive part of the window title (case-insensitive); find titles with list_windows."}}, "required": ["title"]},
    },
    {
        "name": "system_control",
        "description": "Control the host system: action 'volume' (value 0-100), 'mute'/'unmute', or "
                       "'settings' (value = panel like sound/network/bluetooth/display/power to open the "
                       "native settings).",
        "parameters": {
            "type": "object",
            "properties": {"action": {"type": "string", "enum": ["volume", "mute", "unmute", "settings"],
                                      "description": "What to control on the host."},
                           "value": {"type": "string", "description": "For volume: 0-100. For settings: which panel to open (sound/network/bluetooth/display/power). Unused for mute/unmute."}},
            "required": ["action"],
        },
    },
    {
        "name": "add_mcp_server",
        "description": "Add or remove an MCP server (an external tool 'channel') so you gain new tools. "
                       "For a stdio server pass `command` (e.g. 'npx') and `args` (e.g. '-y @playwright/mcp@latest'); "
                       "for an HTTP server pass `url` and, if it needs auth, `bearer_token` "
                       "(sent as 'Authorization: Bearer …'). Optional `env` = 'KEY=value,KEY2=value2' for stdio API keys. "
                       "OAuth remote servers work via the mcp-remote bridge: command 'npx', args '-y mcp-remote <url>'. "
                       "Set action='remove' to delete one. Common: playwright (browser), filesystem, git, github, notion, linear.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short identifier for the server, e.g. 'playwright' or 'github'."},
                "command": {"type": "string", "description": "stdio servers only: the executable, e.g. 'npx' or 'uvx'."},
                "args": {"type": "string", "description": "stdio servers only: space-separated arguments, e.g. '-y @playwright/mcp@latest'."},
                "url": {"type": "string", "description": "HTTP servers only: the server's endpoint URL."},
                "env": {"type": "string", "description": "stdio servers only: env vars as 'KEY=value,KEY2=value2' (for API keys)."},
                "bearer_token": {"type": "string", "description": "HTTP servers only: token sent as 'Authorization: Bearer …'."},
                "action": {"type": "string", "enum": ["add", "remove"],
                           "description": "add (default) connects the server; remove deletes it by name."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "discover_mcp_servers",
        "description": "Search the public MCP registry (registry.modelcontextprotocol.io) for servers that "
                       "provide a capability — the App Store's discovery engine. Use when the user needs an "
                       "integration you don't have (a service, API, data source). Returns candidates with "
                       "what each needs (API keys etc.). NEVER install from the results without asking: "
                       "present them and ask the user 'discovered X — would you like to build around it and "
                       "add it to your MCP Registry?'.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "The capability or service to search for, e.g. 'github', 'weather', 'postgres'."}},
            "required": ["query"],
        },
    },
    {
        "name": "install_mcp_server",
        "description": "Install an MCP server found via discover_mcp_servers, AFTER the user agrees. Writes "
                       "its config, records it in the local MCP Registry, and generates a manual page in Docs. "
                       "Servers needing API keys stay disabled until the user fills them in the MCP app. "
                       "After installing, offer to build a desktop app on top of it (create_app with a "
                       "manifest declaring mcp.use on mcp:<name>/*).",
        "parameters": {
            "type": "object",
            "properties": {
                "registry_name": {"type": "string", "description": "The EXACT registry name from discover_mcp_servers, e.g. 'io.github.owner/repo' — or 'npm:<package>' for a server discovered on npm."},
                "name": {"type": "string", "description": "Optional short local name (defaults to a slug of the registry name)."},
                "env": {"type": "string", "description": "Optional env vars as 'KEY=value,KEY2=value2' if the user already supplied keys."},
            },
            "required": ["registry_name"],
        },
    },
    {
        "name": "delete_skill",
        "description": "Delete a saved skill by name.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The skill's exact name (listed in your system prompt)."}}, "required": ["name"]},
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
        "name": "read_app_data",
        "description": "Read the data stored by a built app (its own data store), by app name. Use this to "
                       "answer questions about what's inside an app (notes, tasks, tracked entries, etc.).",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "description": "The app's name as shown on the desktop."}}, "required": ["name"]},
    },
    {
        "name": "use_skill",
        "description": "Load a skill (a stored procedure/runbook) by name and follow it. "
                       "The list of available skills with descriptions is in your system prompt.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "The skill's exact name from the skills list."}},
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
            "properties": {"message": {"type": "string", "description": "The message text to deliver (plain text; keep it concise)."}},
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
                "interval_minutes": {"type": "integer", "description": "For 'interval': run every N minutes."},
                "at_time": {"type": "string", "description": "For 'daily': time of day as 'HH:MM' (24h)."},
                "delay_minutes": {"type": "integer", "description": "For 'once': run after N minutes from now."},
            },
            "required": ["prompt", "schedule_type"],
        },
    },
]
TOOL_SCHEMAS.extend(GIT_TOOL_SCHEMAS)

TEST_TOOL_SCHEMAS = [
    {
        "name": "run_tests",
        "description": "Test pillar: run the pytest suite — AgentOS's own tests by default, or a "
                       "project directory's. Returns pass/fail with the failure tail. Run this "
                       "after changing code and ALWAYS before restart_agentos.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "Project directory with tests (default: the AgentOS source)."}},
            "required": []},
    },
]
TOOL_SCHEMAS.extend(TEST_TOOL_SCHEMAS)

HERMES_TOOL_SCHEMAS = [
    {
        "name": "hermes_status",
        "description": "Companion agents: is Hermes (the Nous assistant) installed on this "
                       "machine, is its gateway running, and what model does it use.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "hermes_ask",
        "description": "Delegate a one-shot task to the local Hermes agent — a different "
                       "assistant with its own tools, skills, and messaging platforms. Use when "
                       "the user asks for Hermes specifically, or for capabilities Hermes has "
                       "and you don't. Returns its final answer.",
        "parameters": {"type": "object", "properties": {
            "task": {"type": "string", "description": "The task/question for Hermes."}},
            "required": ["task"]},
    },
    {
        "name": "hermes_send",
        "description": "Send a message through any platform Hermes is paired with — WhatsApp, "
                       "Slack, Discord, Signal, Telegram. Target format: 'platform', "
                       "'platform:chat_id', or 'platform:#channel' (e.g. 'slack:#ops', "
                       "'signal:+15551234567'). Extends delivery beyond AgentOS's own Telegram.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "description": "Delivery target."},
            "message": {"type": "string", "description": "Message text."}},
            "required": ["target", "message"]},
    },
]
TOOL_SCHEMAS.extend(HERMES_TOOL_SCHEMAS)

TRAIN_TOOL_SCHEMAS = [
    {
        "name": "trainforge_service",
        "description": "Train pillar: manage the local TrainForge training service "
                       "(fine-tuning platform). Actions: status | start | stop. Start it before "
                       "using the other train_* tools; the user can watch everything in the "
                       "Train desktop app.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "start", "stop"]}},
            "required": ["action"]},
    },
    {
        "name": "train_autopilot",
        "description": "Train pillar: hand TrainForge a goal in plain language ('train a "
                       "sentiment classifier for movie reviews') — it finds a dataset, imports "
                       "it, configures and launches training, and registers the model. Returns "
                       "the run row; follow progress with train_job / the Train app.",
        "parameters": {"type": "object", "properties": {
            "goal": {"type": "string", "description": "What to train, in plain language."},
            "max_rows": {"type": "integer", "description": "Dataset row cap (default 5000)."}},
            "required": ["goal"]},
    },
    {
        "name": "train_datasets",
        "description": "Train pillar: datasets in TrainForge. Actions: list | search (HF Hub, "
                       "query=) | import_hub (repo_id=) | import_url (url=) | get (dataset_id=) "
                       "| preview (dataset_id=). Imports are async — poll with get until "
                       "status is 'ready'.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["list", "search", "import_hub", "import_url", "get", "preview"]},
            "query": {"type": "string"}, "repo_id": {"type": "string"},
            "url": {"type": "string"}, "name": {"type": "string"},
            "dataset_id": {"type": "integer"}, "max_rows": {"type": "integer"}},
            "required": ["action"]},
    },
    {
        "name": "train_job",
        "description": "Train pillar: training jobs. Actions: list | create (name, dataset_id, "
                       "task [tabular-classification|tabular-regression|text-classification|"
                       "causal-lm], base_model?, hyperparams?) | status | logs (offset= for "
                       "incremental tail) | metrics | stop. causal-lm = LoRA fine-tune of a "
                       "language model on this machine's GPU.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["list", "create", "status", "logs", "metrics", "stop"]},
            "job_id": {"type": "integer"}, "name": {"type": "string"},
            "dataset_id": {"type": "integer"}, "task": {"type": "string"},
            "base_model": {"type": "string"}, "hyperparams": {"type": "object"},
            "offset": {"type": "integer"}},
            "required": ["action"]},
    },
    {
        "name": "train_model",
        "description": "Train pillar: trained models. Actions: list | signature (what inputs it "
                       "expects, with example) | predict (inputs=[...] for tabular/text, prompt= "
                       "for causal-lm) | publish (repo_id= uploads to Hugging Face Hub). Every "
                       "trained model is a live local endpoint — use predict to evaluate it.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["list", "signature", "predict", "publish"]},
            "model_id": {"type": "integer"}, "inputs": {"type": "array"},
            "prompt": {"type": "string"}, "repo_id": {"type": "string"},
            "private": {"type": "boolean"}},
            "required": ["action"]},
    },
]
TOOL_SCHEMAS.extend(TRAIN_TOOL_SCHEMAS)

DESKTOP_TOOL_SCHEMAS = [
    {
        "name": "desktop_state",
        "description": "One live snapshot of the desktop: open shell apps, native windows + focus, "
                       "current workspace, battery, power profile, network, volume, brightness, and "
                       "unread notifications. Sections a platform can't answer are omitted. Call it "
                       "FIRST when the user says 'what am I looking at' or a request depends on the "
                       "machine's current state.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "control_desktop",
        "description": "Drive the AgentOS desktop shell (the browser UI): open_app / close_app / "
                       "focus_app act on an AgentOS app window by name; switch_desktop changes the "
                       "virtual desktop; apply_theme applies a theme by id (see list_themes); "
                       "list_open_apps lists what the shell has open. For NATIVE app windows use "
                       "manage_window instead.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["open_app", "close_app", "focus_app", "switch_desktop",
                                "apply_theme", "list_open_apps"]},
            "target": {"type": "string", "description": "App name, desktop name/number, or theme id — whatever the action addresses."}},
            "required": ["action"]},
    },
    {
        "name": "manage_window",
        "description": "Manage a NATIVE window: focus | close | float | tile | move_to_workspace "
                       "(with workspace=). window_id is the id from list_windows/desktop_state, or "
                       "a distinctive part of the window's title or app name.",
        "parameters": {"type": "object", "properties": {
            "window_id": {"type": "string", "description": "Window id, or part of its title/app name."},
            "action": {"type": "string",
                       "enum": ["focus", "close", "float", "tile", "move_to_workspace"]},
            "workspace": {"type": "string", "description": "For move_to_workspace: the target workspace name/number."}},
            "required": ["window_id", "action"]},
    },
    {
        "name": "list_themes",
        "description": "List the OS theme ids control_desktop(action='apply_theme') accepts: the "
                       "built-in set plus every custom theme saved in the Themes app.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "wifi",
        "description": "Wifi via NetworkManager: 'status' (adapter + connection), 'list' (scan "
                       "nearby networks), 'connect' (ssid= and password= for protected networks), "
                       "'forget' (drop a saved network), 'enable'/'disable' (the wifi radio).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["status", "list", "connect", "forget", "enable", "disable"]},
            "ssid": {"type": "string", "description": "Network name for connect/forget."},
            "password": {"type": "string", "description": "For connect on a protected network."}},
            "required": ["action"]},
    },
    {
        "name": "bluetooth",
        "description": "Bluetooth via BlueZ: 'status' (adapters + known devices), 'scan' (discover "
                       "nearby devices for a few seconds), 'pair' / 'connect' / 'disconnect' / "
                       "'forget' a device by name or address.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["status", "scan", "pair", "connect", "disconnect", "forget"]},
            "device": {"type": "string", "description": "Device name or MAC address from status/scan."}},
            "required": ["action"]},
    },
    {
        "name": "set_brightness",
        "description": "Set screen brightness 0-100. Targets the internal backlight by default; "
                       "pass name= for a specific display (a DDC display number for external "
                       "monitors).",
        "parameters": {"type": "object", "properties": {
            "percent": {"type": "integer", "description": "Brightness 0-100."},
            "name": {"type": "string", "description": "Optional display name (default: the first adjustable one)."}},
            "required": ["percent"]},
    },
    {
        "name": "audio",
        "description": "Audio control: 'status' (volume + output/input devices), 'volume' (value= "
                       "0-100), 'mute'/'unmute', 'route' (device= sink id or name to make the "
                       "default output — e.g. switch sound to headphones).",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["status", "volume", "mute", "unmute", "route"]},
            "value": {"type": "integer", "description": "For volume: 0-100."},
            "device": {"type": "string", "description": "For route: the sink id or (part of) its description."}},
            "required": ["action"]},
    },
    {
        "name": "power_profile",
        "description": "Read (no arguments) or set the machine's power profile: power-saver | "
                       "balanced | performance (power-profiles-daemon).",
        "parameters": {"type": "object", "properties": {
            "profile": {"type": "string", "description": "Omit to read; or power-saver | balanced | performance."}},
        },
    },
    {
        "name": "lock_screen",
        "description": "Lock the session immediately (the user unlocks with their password).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "power_action",
        "description": "Session power control: suspend | reboot | poweroff | logout. The user "
                       "confirms EVERY call — never chain it after other work without asking.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["suspend", "reboot", "poweroff", "logout"]}},
            "required": ["action"]},
    },
    {
        "name": "list_notifications",
        "description": "Read the desktop notification center (AgentOS-as-DE): what apps notified "
                       "the user, newest first, with unread state and DND. Use it to answer 'did "
                       "anything happen?', summarize pings, or decide whether to interrupt.",
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "Max notifications to return (default 20)."},
            "unread_only": {"type": "boolean", "description": "Only ones the user hasn't seen."}},
        },
    },
    {
        "name": "take_screenshot",
        "description": "Capture the screen into the workspace Screenshots folder and LOOK at it — "
                       "vision-capable models receive the image itself, others the saved path. "
                       "target 'screen' grabs everything; 'select' lets the user drag a region.",
        "parameters": {"type": "object", "properties": {
            "target": {"type": "string", "enum": ["screen", "select"]}},
        },
    },
]
TOOL_SCHEMAS.extend(DESKTOP_TOOL_SCHEMAS)

AUTOMATION_TOOL_SCHEMAS = [
    {
        "name": "run_python",
        "description": "Run a Python snippet on this machine and get its stdout/stderr back. Use for "
                       "real computation, data wrangling, file work or API calls where a shell "
                       "one-liner would be awkward. It runs with the same interpreter AgentOS uses, "
                       "inside the same sandbox jail and permission gate as run_command, so treat it "
                       "as a real program on the user's computer. Print what you want to see — the "
                       "return value is the process output.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "the Python source to execute; print() what you need back"},
                "timeout": {"type": "integer", "description": "seconds before it is killed (default 120)"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "list_automations",
        "description": "List the user's saved automations and what each one does. Call this before "
                       "run_automation when you are not sure of the exact name, and before "
                       "save_automation when the user says 'add X to my morning routine' — you edit "
                       "an automation by saving its existing name with the full new step list.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "run_automation",
        "description": "Run a saved automation by name — the desktop performs its steps in order. "
                       "Use when the user says 'run my morning routine', 'do the focus setup', or "
                       "names anything list_automations reports.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "the automation's name, as shown by list_automations"}},
            "required": ["name"],
        },
    },
    {
        "name": "save_automation",
        "description": "Create a named automation, or edit one by reusing its name (steps REPLACE "
                       "the old list, so pass the complete sequence). Use when the user describes a "
                       "routine they want to repeat: 'every time I start work, open chat and the "
                       "terminal, switch to the minimal theme and summarise my day'. `steps` is a "
                       "JSON array run in order, each one of: "
                       "{\"kind\":\"app\",\"app\":\"chat\"} open an app · "
                       "{\"kind\":\"action\",\"action\":\"deck\"} a desktop action (deck, expose, "
                       "windows.arrange, chat.new, voice, fullscreen, terminal, settings) · "
                       "{\"kind\":\"theme\",\"theme\":\"minimal\"} apply a theme · "
                       "{\"kind\":\"wallpaper\",\"wallpaper\":\"spatial\"} a built-in wallpaper · "
                       "{\"kind\":\"desktop\",\"desk\":2} switch virtual desktop · "
                       "{\"kind\":\"agent\",\"prompt\":\"...\"} put me on a task · "
                       "{\"kind\":\"tool\",\"tool\":\"<any tool name>\",\"args\":\"{...}\"} call an agent "
                       "or MCP tool directly with JSON args — deterministic, no model in the loop "
                       "(mcp_* names come from the user's connected MCP servers) · "
                       "{\"kind\":\"python\",\"code\":\"print(...)\"} run Python · "
                       "{\"kind\":\"wait\",\"ms\":500} pause between steps. "
                       "Prefer `tool` and `python` when the work is exact and repeatable, and `agent` "
                       "when it needs judgement — an automation should be as deterministic as the "
                       "task allows.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "what the user will call it; reuse an existing name to edit it"},
                "steps": {"type": "string", "description": "JSON array of step objects, run in order"},
                "icon": {"type": "string", "description": "optional single emoji shown on the automation's tile"},
            },
            "required": ["name", "steps"],
        },
    },
]
TOOL_SCHEMAS.extend(AUTOMATION_TOOL_SCHEMAS)

PROACTIVITY_TOOL_SCHEMAS = [
    {
        "name": "create_trigger",
        "description": "Create an event trigger: run a prompt when something happens instead of at a "
                       "time. kind 'notification' fires when a desktop notification matches "
                       "match_or_path (case-insensitive substring or regex on app/summary/body); "
                       "'file_change' when the file/directory at match_or_path changes; 'login' at "
                       "session start; 'idle' after `minutes` without user chat activity. A trigger "
                       "fires at most once per cooldown_secs.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["notification", "file_change", "login", "idle"]},
                "match_or_path": {"type": "string",
                                  "description": "For 'notification': substring or regex to match. "
                                                 "For 'file_change': the path to watch. "
                                                 "Ignored for 'login'/'idle'."},
                "prompt": {"type": "string", "description": "What the agent should do when it fires."},
                "cooldown_secs": {"type": "integer",
                                  "description": "Minimum seconds between firings (default 300)."},
                "minutes": {"type": "number", "description": "For 'idle': fire after this many "
                                                             "minutes of no chat activity (default 30)."},
            },
            "required": ["kind", "prompt"],
        },
    },
]
TOOL_SCHEMAS.extend(PROACTIVITY_TOOL_SCHEMAS)

# Media & spaces. `space_id` is deliberately NOT declared in any of these schemas:
# the agent loop injects the turn's own space (see SPACE_SCOPED_TOOLS below), so a
# model cannot reach into another project by naming one. `everywhere` is the single
# declared way to write outside the current space, which keeps that choice visible
# to the permission gate instead of hidden inside an id.
MEDIA_TOOL_SCHEMAS = [
    {
        "name": "list_assets",
        "description": "List what is in the gallery — images, video, audio and documents the "
                       "agent generated, received from an MCP server, or was given. Returns "
                       "asset ids, which every other media tool takes.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["", "image", "video", "audio", "doc", "data"],
                         "description": "filter by kind; omit for everything"},
                "query": {"type": "string", "description": "match against title, prompt or source"},
                "limit": {"type": "integer", "description": "default 20"},
            },
            "required": [],
        },
    },
    {
        "name": "get_asset",
        "description": "Details of one asset by id. For an image this also SHOWS it to you if "
                       "the model can see pictures — use it before describing or editing one.",
        "parameters": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
        },
    },
    {
        "name": "save_asset",
        "description": "Put a local file or an http(s) URL into the gallery so it persists and "
                       "can be shown, referenced and used later.",
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "a local path or an http(s) URL"},
                "title": {"type": "string", "description": "what to call it"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "delete_asset",
        "description": "Remove an asset and its file.",
        "parameters": {
            "type": "object",
            "properties": {"asset_id": {"type": "string"}},
            "required": ["asset_id"],
        },
    },
    {
        "name": "generate_image",
        "description": "Draw a picture from a description and keep it in the gallery. Returns "
                       "an asset id. Use this for any image the user wants to KEEP or use; "
                       "generate_wallpaper is only for setting the desktop background.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "what to draw, in detail"},
                "width": {"type": "integer", "description": "default 1280"},
                "height": {"type": "integer", "description": "default 720"},
                "title": {"type": "string", "description": "what to call it in the gallery"},
            },
            "required": ["prompt"],
        },
    },
]
TOOL_SCHEMAS.extend(MEDIA_TOOL_SCHEMAS)

SPACE_TOOL_SCHEMAS = [
    {
        "name": "list_spaces",
        "description": "The things the user is working on. A space groups a project's "
                       "conversations, memory, facts and assets so they do not bleed into "
                       "each other.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_space",
        "description": "Create a space for a distinct piece of work (a launch, a client, a "
                       "channel). Do this when the user starts something that will accumulate "
                       "its own context — not for every passing task.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string",
                                "description": "what this space IS — the memory subsystem reads "
                                               "this to decide what belongs in it"},
                "icon": {"type": "string", "description": "optional single emoji"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "timeline",
        "description": "What has happened recently — runs, assets produced, memory learned, "
                       "apps changed. Milestones, not the message log. Use it to answer "
                       "'what did we do this week?'.",
        "parameters": {
            "type": "object",
            "properties": {
                "since_hours": {"type": "number", "description": "default 168 (a week)"},
                "kind": {"type": "string",
                         "enum": ["", "run", "asset", "memory", "app_version", "conversation",
                                  "task", "space"]},
                "limit": {"type": "integer", "description": "default 40"},
            },
            "required": [],
        },
    },
]
TOOL_SCHEMAS.extend(SPACE_TOOL_SCHEMAS)

#: Tools whose reads and writes belong to the turn's space. The agent loop injects
#: `space_id` for these; nothing else in the OS decides scope on the model's behalf.
SPACE_SCOPED_TOOLS = frozenset({
    "remember", "recall", "kg_add", "kg_query",
    "list_assets", "save_asset", "generate_image", "timeline",
})

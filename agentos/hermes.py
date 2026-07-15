"""Hermes integration — companion agent AND a second engine AgentOS wraps.

Hermes (Nous Research's self-hosted assistant, MIT) is itself an agent. AgentOS
does two things with it:

1. **Interop** — `hermes_status` / `hermes_ask` / `hermes_send`: query it, delegate
   a task, or deliver a message through a platform it's paired with (WhatsApp/Slack/
   Discord/Signal) without AgentOS needing its own bridges.
2. **Wrapper** — the user can pick Hermes as the *chat engine* (instead of Aria),
   download it from inside AgentOS, and edit its config here. AgentOS becomes a
   control surface over Hermes.

Everything shells out to the `hermes` CLI under the user's own account. AgentOS
edits `~/.hermes/config.yaml` (models, providers, toolsets, personalities) but
never touches `~/.hermes/.env` (where API keys live) — Hermes keeps its secrets.
"""

import asyncio
import contextlib
import os
import shutil

from .mcp_client import _extended_path

HOME = os.path.expanduser("~/.hermes")
CONFIG_PATH = os.path.join(HOME, "config.yaml")
DEFAULT_REPO = "https://github.com/NousResearch/hermes-agent.git"
DEFAULT_INSTALL_DIR = os.path.join(HOME, "hermes-agent")


def conf(cfg: dict | None) -> dict:
    h = (cfg or {}).get("hermes") or {}
    return {"repo": h.get("repo") or DEFAULT_REPO,
            "install_dir": os.path.expanduser(h.get("install_dir") or DEFAULT_INSTALL_DIR),
            "engine_enabled": h.get("engine_enabled", True)}


def cli_path() -> str:
    p = shutil.which("hermes", path=_extended_path())
    if p:
        return p
    # a git checkout with its own venv but no ~/.local/bin symlink yet
    venv_bin = os.path.join(DEFAULT_INSTALL_DIR, "venv", "bin", "hermes")
    return venv_bin if os.path.exists(venv_bin) else ""


def gateway_running() -> bool:
    pid_file = os.path.expanduser("~/.hermes/gateway.pid")
    try:
        with open(pid_file) as f:
            raw = f.read().strip()
        try:
            import json
            pid = int(json.loads(raw).get("pid", 0))  # {"pid": 1234, "kind": ...}
        except Exception:
            pid = int(raw.split()[0])
        if pid <= 0:
            return False
        os.kill(pid, 0)
        return True
    except Exception:
        return False


async def _run(argv: list[str], timeout: int) -> tuple[int, str]:
    env = {**os.environ, "PATH": _extended_path()}
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL, env=env)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1, f"[error] hermes timed out after {timeout}s"
    return proc.returncode or 0, out.decode(errors="replace")


_setup_state = {"state": ""}  # "" | "installing" | "error: …" — module-level, one install at a time


async def status(cfg: dict | None = None) -> dict:
    cli = cli_path()
    c = conf(cfg)
    out = {"installed": bool(cli), "cli": cli, "gateway": gateway_running(),
           "model": "", "provider": "", "config_path": CONFIG_PATH,
           "has_config": os.path.exists(CONFIG_PATH),
           "install_dir": c["install_dir"], "setup": _setup_state["state"],
           "engine_enabled": c["engine_enabled"]}
    if not cli:
        return out
    try:
        with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
            text = f.read()
        try:
            import yaml  # not a hard dependency — fall back to a line scan
            parsed = yaml.safe_load(text) or {}
            out["model"] = (parsed.get("model") or {}).get("default", "")
            out["provider"] = (parsed.get("model") or {}).get("provider", "")
        except ImportError:
            in_model = False
            for line in text.splitlines():
                if line.rstrip() == "model:":
                    in_model = True
                    continue
                if in_model:
                    if not line.startswith((" ", "\t")):
                        break
                    k, _, v = line.strip().partition(":")
                    if k == "default":
                        out["model"] = v.strip()
                    elif k == "provider":
                        out["provider"] = v.strip()
    except Exception:
        pass
    return out


async def ask(prompt: str, timeout: int = 600) -> str:
    cli = cli_path()
    if not cli:
        return "[error] hermes is not installed on this machine (https://github.com/NousResearch/hermes-agent)"
    code, out = await _run([cli, "-z", prompt], timeout=timeout)
    text = out.strip()
    return text if code == 0 else f"[exit code {code}]\n{text[:2000]}"


async def send(target: str, message: str) -> str:
    cli = cli_path()
    if not cli:
        return "[error] hermes is not installed on this machine"
    if not target or not message.strip():
        return "[error] target (e.g. 'telegram', 'slack:C0123', 'signal:+1555…') and message are required"
    code, out = await _run([cli, "send", "-t", target, message], timeout=60)
    text = out.strip()
    return (f"sent via hermes to {target}" + (f"\n{text}" if text else "")) if code == 0 \
        else f"[exit code {code}]\n{text[:1000]}"


# ---------------------------------------------------------------------------
# Wrapper controls: install / update, config editing, gateway lifecycle
# ---------------------------------------------------------------------------

async def _stream_proc(argv: list[str], cwd: str, note, timeout: int) -> int:
    """Run a build/install step, forwarding notable output lines to `note`."""
    env = {**os.environ, "PATH": _extended_path()}
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        async def pump():
            assert proc.stdout
            async for raw in proc.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line and note and (len(line) < 200):
                    await note(line[:160])
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 1
    return proc.returncode or 0


async def install(cfg: dict | None = None, note=None, update: bool = False) -> str:
    """Download Hermes (MIT) from git and provision its venv, or update an existing
    checkout. `note(msg)` streams progress. Matches Hermes's own layout: a git
    checkout with an in-tree `venv` and a `hermes` entry point, symlinked into
    ~/.local/bin so AgentOS (and the user's shell) can find it."""
    if _setup_state["state"] == "installing":
        return "[error] a Hermes install/update is already running"
    if not shutil.which("git"):
        return "[error] git is required to download Hermes but isn't installed"

    async def _note(m):
        if note:
            with contextlib.suppress(Exception):
                await note(m)

    c = conf(cfg)
    root = c["install_dir"]
    is_repo = os.path.isdir(os.path.join(root, ".git"))
    _setup_state["state"] = "installing"
    try:
        if is_repo or update:
            if not is_repo:
                return "[error] no Hermes checkout to update at " + root
            await _note("updating Hermes (git pull)…")
            if await _stream_proc(["git", "pull", "--ff-only"], root, _note, 300) != 0:
                _setup_state["state"] = "error: git pull failed"
                return "[error] git pull failed — see the log"
        else:
            os.makedirs(os.path.dirname(root), exist_ok=True)
            await _note(f"cloning {c['repo']} … (one-time)")
            if await _stream_proc(["git", "clone", "--depth", "1", c["repo"], root],
                                  os.path.dirname(root), _note, 600) != 0:
                _setup_state["state"] = "error: clone failed"
                return "[error] git clone failed — check the repo URL (hermes.repo in config)"

        # provision the venv the way Hermes expects (in-tree ./venv)
        venv = os.path.join(root, "venv")
        pybin = os.path.join(venv, "bin", "python")
        if not os.path.exists(pybin):
            await _note("creating Python virtualenv…")
            if await _stream_proc(["python3", "-m", "venv", "venv"], root, _note, 120) != 0:
                _setup_state["state"] = "error: venv failed"
                return "[error] could not create the Hermes virtualenv"
        await _note("installing Hermes dependencies (this can take a few minutes)…")
        if await _stream_proc([pybin, "-m", "pip", "install", "-e", "."], root, _note, 1800) != 0:
            _setup_state["state"] = "error: pip install failed"
            return "[error] pip install failed — see the log; you may need build tools"

        # make the CLI discoverable: symlink the venv entry point into ~/.local/bin
        entry = os.path.join(venv, "bin", "hermes")
        if os.path.exists(entry):
            binhome = os.path.expanduser("~/.local/bin")
            os.makedirs(binhome, exist_ok=True)
            link = os.path.join(binhome, "hermes")
            with contextlib.suppress(Exception):
                if os.path.islink(link) or os.path.exists(link):
                    if os.path.realpath(link) != os.path.realpath(entry):
                        os.remove(link)
                        os.symlink(entry, link)
                else:
                    os.symlink(entry, link)
        await _note("running Hermes postinstall (node / tools)…")
        # best-effort; Hermes still works for chat without every extra
        with contextlib.suppress(Exception):
            await _stream_proc([entry, "postinstall"], root, _note, 600)
        _setup_state["state"] = ""
        return f"Hermes {'updated' if is_repo else 'installed'} at {root}"
    finally:
        if _setup_state["state"] == "installing":
            _setup_state["state"] = ""


async def read_config() -> str:
    if not os.path.exists(CONFIG_PATH):
        return ""
    with open(CONFIG_PATH) as f:
        return f.read()


async def write_config(text: str) -> str:
    """Save Hermes's config.yaml (validated as YAML if PyYAML is present). A
    timestamp-free .bak is kept so a bad edit is one restore away."""
    if not os.path.isdir(HOME):
        return "[error] ~/.hermes does not exist — install Hermes first"
    try:
        import yaml
        yaml.safe_load(text)  # reject syntactically broken YAML before overwriting
    except ImportError:
        # PyYAML is a dependency, but if it's somehow missing don't silently accept
        # a possibly-broken file: require it to at least look like a mapping
        if not text.strip() or not any(":" in ln for ln in text.splitlines()[:50]):
            return "[error] refusing to save — content doesn't look like Hermes config YAML"
    except Exception as e:
        return f"[error] not valid YAML: {e}"
    with contextlib.suppress(Exception):
        if os.path.exists(CONFIG_PATH):
            shutil.copyfile(CONFIG_PATH, CONFIG_PATH + ".agentos.bak")
    with open(CONFIG_PATH, "w") as f:
        f.write(text)
    return "saved Hermes config"


async def gateway(action: str) -> str:
    cli = cli_path()
    if not cli:
        return "[error] hermes is not installed"
    if action == "start":
        if gateway_running():
            return "Hermes gateway already running"
        env = {**os.environ, "PATH": _extended_path()}
        # detached: the gateway is a long-lived service, not tied to this request
        await asyncio.create_subprocess_exec(
            cli, "gateway", "run", env=env, start_new_session=True,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            stdin=asyncio.subprocess.DEVNULL)
        for _ in range(20):
            await asyncio.sleep(0.5)
            if gateway_running():
                return "Hermes gateway started"
        return "Hermes gateway launch requested (still coming up)"
    if action == "stop":
        code, out = await _run([cli, "gateway", "stop"], timeout=30)
        return "Hermes gateway stopped" if code == 0 else f"[exit code {code}]\n{out[:400]}"
    return "[error] action must be start|stop"

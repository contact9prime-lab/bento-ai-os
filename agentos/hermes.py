"""Hermes integration — companion-agent compatibility.

Hermes (Nous Research's self-hosted assistant) often lives on the same machine:
a gateway wired into WhatsApp/Slack/Discord/Signal, its own skills, kanban, and
cron. AgentOS doesn't wrap or replace it — it *interoperates*:

- `hermes_status`  — is it installed / gateway running, which model/provider
- `hermes_ask`     — delegate a one-shot task to Hermes (`hermes -z`), like a
                     subagent that happens to be a different product
- `hermes_send`    — deliver a message through ANY platform Hermes is paired
                     with (`hermes send`) — WhatsApp/Slack/Discord/Signal reach
                     without AgentOS needing its own bridges

Everything shells out to the `hermes` CLI under the user's own account — no
credentials are read or copied, and Hermes's approval/config model stays in
charge of its own side.
"""

import asyncio
import os
import shutil

from .mcp_client import _extended_path


def cli_path() -> str:
    return shutil.which("hermes", path=_extended_path()) or ""


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


async def status() -> dict:
    cli = cli_path()
    out = {"installed": bool(cli), "cli": cli, "gateway": gateway_running(),
           "model": "", "provider": ""}
    if not cli:
        return out
    try:
        with open(os.path.expanduser("~/.hermes/config.yaml")) as f:
            text = f.read()
        try:
            import yaml  # not a hard dependency — fall back to a line scan
            conf = yaml.safe_load(text) or {}
            out["model"] = (conf.get("model") or {}).get("default", "")
            out["provider"] = (conf.get("model") or {}).get("provider", "")
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

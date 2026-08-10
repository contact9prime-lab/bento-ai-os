"""TrainForge integration — the Train pillar.

TrainForge (the `doneitrightai` project) is a self-hosted ML training platform:
datasets (HF Hub / URL / upload), fine-tuning tasks incl. causal-lm LoRA, live
metrics/logs, instant predict endpoints, an agentic Autopilot, and HF publishing.

AgentOS manages it as a supervised local service: started on demand, bound to
127.0.0.1 (TrainForge has no auth — it must never listen beyond loopback), health-
checked over its REST API, and stopped with SIGTERM. The Train desktop app iframes
its UI; the train_* agent tools call its API server-side (no CORS involvement).

TrainForge coordinates GPU memory with Ollama itself (it pauses resident models
before a training run and reloads them after), so no VRAM logic lives here.
"""

import asyncio
import contextlib
import os
import shutil
import signal
import sys
from pathlib import Path

import httpx
from . import users as usersmod

DEFAULT_PORT = 8377   # deliberately not TrainForge's default 8000 (dev-server collisions)
DEFAULT_REPO = "https://github.com/YOUR_ORG/doneitrightai.git"  # override via config trainforge.repo
# where the repo's server entrypoint lives relative to the checkout root
_SERVER_REL = ("server", "main.py")

_KNOWN_LOCATIONS = [
    "~/Documents/scripts/doneitrightai/doneitrightai",
    "~/Documents/scripts/doneitrightai",
    "~/doneitrightai/doneitrightai",
    "~/doneitrightai",
    "~/.agentos/trainforge",           # where auto-fetch installs it
]


def _has_server(p: Path) -> bool:
    return (p / _SERVER_REL[0] / _SERVER_REL[1]).exists()


def conf(cfg: dict) -> dict:
    tf = cfg.get("trainforge") or {}
    path = tf.get("path", "")
    if path and not _has_server(Path(os.path.expanduser(path))):
        path = ""  # configured path is stale/empty → fall through to detection/fetch
    if not path:
        for cand in _KNOWN_LOCATIONS:
            p = Path(os.path.expanduser(cand))
            # the repo nests as doneitrightai/doneitrightai — accept either level
            if _has_server(p):
                path = str(p)
                break
            if _has_server(p / "doneitrightai"):
                path = str(p / "doneitrightai")
                break
    return {"path": path, "port": int(tf.get("port", DEFAULT_PORT)),
            "repo": tf.get("repo") or DEFAULT_REPO,
            "install_dir": os.path.expanduser(tf.get("install_dir") or "~/.agentos/trainforge")}


class TrainForge(usersmod.Scoped):
    """Lifecycle + API access for the local TrainForge instance."""

    def __init__(self, cfg: dict, store, broadcast=None):
        self.cfg = cfg
        self.store = store
        self.broadcast = broadcast
        self.proc: asyncio.subprocess.Process | None = None
        self.setup_proc: asyncio.subprocess.Process | None = None
        self.setup_state = ""   # "" | "fetching" | "installing" | "error: …"

    async def _note(self, msg: str):
        self.store.log("system", f"trainforge: {msg}"[:200])
        if self.broadcast:
            with contextlib.suppress(Exception):
                await self.broadcast({"type": "train_setup", "message": msg})

    # ---- service lifecycle -------------------------------------------------

    def base_url(self) -> str:
        return f"http://127.0.0.1:{conf(self.cfg)['port']}"

    async def health(self) -> dict:
        """{"running": bool, "managed": bool, "url": str, ...api health fields}"""
        c = conf(self.cfg)
        out = {"running": False, "managed": self.proc is not None and self.proc.returncode is None,
               "url": self.base_url(), "path": c["path"], "setup": self.setup_state,
               "fetchable": "YOUR_ORG" not in c["repo"]}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.base_url()}/api/system/health")
                if r.status_code == 200:
                    out["running"] = True
                    out.update(r.json() if isinstance(r.json(), dict) else {})
        except Exception:
            pass
        return out

    async def _fetch(self) -> tuple[str, str]:
        """Clone the TrainForge repo when no checkout exists. Returns (path, error)."""
        c = conf(self.cfg)
        repo = c["repo"]
        dest = Path(c["install_dir"])
        if "YOUR_ORG" in repo:
            return "", ("[error] TrainForge isn't on this machine and no download URL is "
                        "configured — set trainforge.repo in config.json (or trainforge.path "
                        "to an existing checkout).")
        if not shutil.which("git"):
            return "", "[error] git is required to fetch TrainForge but isn't installed"
        self.setup_state = "fetching"
        await self._note(f"downloading TrainForge from {repo} … (one-time)")
        if dest.exists() and not any(dest.iterdir()):
            dest.rmdir()
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", repo, str(dest),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            self.setup_state = "error: clone failed"
            return "", f"[error] git clone failed: {out.decode(errors='replace')[:400]}"
        root = dest / "doneitrightai" if _has_server(dest / "doneitrightai") else dest
        if not _has_server(root):
            self.setup_state = "error: unexpected repo layout"
            return "", f"[error] cloned repo has no {os.sep.join(_SERVER_REL)} — wrong URL?"
        # remember where it landed so we don't re-detect every time
        self.cfg.setdefault("trainforge", {})["path"] = str(root)
        with contextlib.suppress(Exception):
            from . import config as cfgmod
            cfgmod.save_config(self.cfg)
        return str(root), ""

    async def _provision_and_launch(self, root: Path, port: int) -> str:
        """Run the repo's run.sh (creates venv, installs deps, incl. GPU stack) and
        leave the server running. run.sh execs uvicorn, so it IS the server process."""
        env = {**os.environ,
               "TRAINFORGE_HOST": "127.0.0.1",   # no auth ⇒ loopback only, always
               "TRAINFORGE_PORT": str(port),
               "TRAINFORGE_MAX_CONCURRENT_JOBS": "1"}
        py = root / ".venv" / "bin" / ("python.exe" if os.name == "nt" else "python")
        provisioned = py.exists()
        run_sh = root / "run.sh"
        if provisioned:
            # fast path: venv exists, launch the server module directly
            self.proc = await asyncio.create_subprocess_exec(
                str(py), "-m", "server.main", cwd=str(root), env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True)
            wait_ticks = 60          # ~30s
        elif run_sh.exists():
            self.setup_state = "installing"
            await self._note("installing TrainForge dependencies (first run — this can take "
                             "several minutes, GPU stack is a few GB)…")
            self.proc = await asyncio.create_subprocess_exec(
                "bash", str(run_sh), cwd=str(root), env=env,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True)
            wait_ticks = 1200        # up to ~10 min for the first-run install
        else:
            return f"[error] {root} has no .venv and no run.sh — can't provision TrainForge"

        for _ in range(wait_ticks):
            await asyncio.sleep(0.5)
            if self.proc.returncode is not None:  # process died during install
                self.setup_state = "error: setup process exited"
                return "[error] TrainForge setup process exited before the server came up — " \
                       "run its ./run.sh manually to see the error"
            if (await self.health())["running"]:
                self.setup_state = ""
                await self._note(f"started at {self.base_url()}")
                return f"TrainForge running at {self.base_url()} — open the Train app to watch it"
        return "[error] TrainForge did not come up in time — check its logs (its data/ dir)"

    async def start(self) -> str:
        if (await self.health())["running"]:
            return f"TrainForge already running at {self.base_url()}"
        if self.setup_state in ("fetching", "installing"):
            return f"TrainForge setup already in progress ({self.setup_state})…"
        c = conf(self.cfg)
        path = c["path"]
        if not path:                       # not on disk → fetch it
            path, err = await self._fetch()
            if err:
                return err
        return await self._provision_and_launch(Path(path), c["port"])

    async def stop(self) -> str:
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except Exception:
                self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                self.proc.kill()
            self.proc = None
            self.store.log("system", "TrainForge stopped")
            return "TrainForge stopped"
        if (await self.health())["running"]:
            return ("[error] TrainForge is running but wasn't started by AgentOS — "
                    "stop it where it was launched")
        return "TrainForge is not running"

    # ---- API ----------------------------------------------------------------

    async def api(self, method: str, path: str, body: dict | None = None,
                  params: dict | None = None, timeout: float = 60) -> tuple[int, object]:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.request(method, f"{self.base_url()}{path}",
                                         json=body, params=params)
                try:
                    return r.status_code, r.json()
                except Exception:
                    return r.status_code, r.text[:2000]
        except httpx.ConnectError:
            return 0, "TrainForge is not running — start it first (trainforge_service action=start)"
        except Exception as e:
            return 0, f"{type(e).__name__}: {e}"

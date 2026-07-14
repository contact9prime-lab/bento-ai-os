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
import os
import signal
from pathlib import Path

import httpx

DEFAULT_PATH = ""     # resolved from config or by probing known locations
DEFAULT_PORT = 8377   # deliberately not TrainForge's default 8000 (dev-server collisions)

_KNOWN_LOCATIONS = [
    "~/Documents/scripts/doneitrightai/doneitrightai",
    "~/doneitrightai/doneitrightai",
    "~/doneitrightai",
]


def conf(cfg: dict) -> dict:
    tf = cfg.get("trainforge") or {}
    path = tf.get("path", "")
    if not path:
        for cand in _KNOWN_LOCATIONS:
            p = Path(os.path.expanduser(cand))
            if (p / "server" / "main.py").exists():
                path = str(p)
                break
    return {"path": path, "port": int(tf.get("port", DEFAULT_PORT))}


class TrainForge:
    """Lifecycle + API access for the local TrainForge instance."""

    def __init__(self, cfg: dict, store):
        self.cfg = cfg
        self.store = store
        self.proc: asyncio.subprocess.Process | None = None

    # ---- service lifecycle -------------------------------------------------

    def base_url(self) -> str:
        return f"http://127.0.0.1:{conf(self.cfg)['port']}"

    async def health(self) -> dict:
        """{"running": bool, "managed": bool, "url": str, ...api health fields}"""
        out = {"running": False, "managed": self.proc is not None and self.proc.returncode is None,
               "url": self.base_url(), "path": conf(self.cfg)["path"]}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                r = await client.get(f"{self.base_url()}/api/system/health")
                if r.status_code == 200:
                    out["running"] = True
                    out.update(r.json() if isinstance(r.json(), dict) else {})
        except Exception:
            pass
        return out

    async def start(self) -> str:
        c = conf(self.cfg)
        if not c["path"]:
            return ("[error] TrainForge not found — set trainforge.path in config.json to the "
                    "doneitrightai checkout (the folder containing server/main.py)")
        if (await self.health())["running"]:
            return f"TrainForge already running at {self.base_url()}"
        root = Path(c["path"])
        py = root / ".venv" / "bin" / "python"
        if not py.exists():
            return (f"[error] TrainForge venv missing at {py} — run its ./run.sh once to "
                    f"provision it, then retry")
        env = {**os.environ,
               "TRAINFORGE_HOST": "127.0.0.1",   # no auth ⇒ loopback only, always
               "TRAINFORGE_PORT": str(c["port"]),
               "TRAINFORGE_MAX_CONCURRENT_JOBS": "1"}  # single shared GPU
        self.proc = await asyncio.create_subprocess_exec(
            str(py), "-m", "server.main", cwd=str(root), env=env,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True)
        for _ in range(40):  # up to ~20s to come up
            await asyncio.sleep(0.5)
            if (await self.health())["running"]:
                self.store.log("system", f"TrainForge started at {self.base_url()}")
                return f"TrainForge running at {self.base_url()} — open the Train app to watch it"
        return "[error] TrainForge did not come up within 20s — check its logs (data/ dir)"

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

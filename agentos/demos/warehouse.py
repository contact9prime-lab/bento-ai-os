"""`bento demo warehouse`: a warehouse to play with, run by a hub, three zone Pis and six ESP32s.

Asked for as "is the simulation something people can try with Bento, to play around, for demo
purposes". It is the warehouse run (packaging/dev/warehouse/run.py) made into something a person
starts from Devices or a terminal and stops again:

  the hub          a `bento serve` of its own, on your brain (copied from this machine's settings)
                   or on the scripted one (warehouse_brain.py: free, offline, a few requests)
  three zone Pis   `bento serve`s set up from the hub's one line, as real Pis are: zone-cold,
                   zone-dock, zone-aisle
  six ESP32 nodes  esp_sim.py, speaking ESPHome's web server API and mDNS on each zone's network
  the floor        a page of its own (floor.html): every node's readings live, and buttons to
                   trip a compressor or open a dock door, so there is something to ask about

Five rules:

  * On a machine with accounts it runs as a Bento user of its own, made for it (`owner`): only
    that user starts it, so a person's own chats, devices and memory never sit beside it. A
    machine with no accounts runs it as before; making a first account there would hand the
    whole machine to it.
  * It never touches this machine's Bento. Every server has its own home under the demo folder
    (~/.cache/bento-demo/warehouse), its own ports (BASE onwards, all checked before a start),
    its own discovery port, and no keyring (AGENTOS_VAULT_KEYRING=0). The hub never asks its
    zones to update: a zone's code root is this install, and an update there would pull it.
  * Your brain is copied by value (BRAIN_KEYS), a folder set for an agent CLI is dropped so it
    works in the demo's own workspace, and the file holding it is 0600. With no brain here, or
    with --scripted, the hub runs on the scripted one and says so.
  * One supervisor owns it all (`python -m agentos.demos.warehouse run`, in a session of its
    own), so Stop ends every process at once and nothing outlives it. Its progress is
    status.json, read by the CLI, the route and the floor page alike.
  * Set up once, started fast after: the zones' links and nodes are kept, and a second start
    only starts the servers. --fresh starts from nothing.

Free of HTTP frameworks and asyncio, like jobs.py: the CLI and the route call the same functions.
POSIX only: a session of its own and killpg are how Stop is sure.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HUB = "warehouse-hub"
ZONES = ("zone-cold", "zone-dock", "zone-aisle")
MACHINES = (HUB, *ZONES)
BASE = int(os.environ.get("AGENTOS_DEMO_PORT") or 18900)
FLOOR = BASE                        # the floor page and its readings
SPEED = 2.0                         # model seconds per real second: a tripped room warms within a few minutes
MARK = ".bento-demo"                # a folder is ours to delete only if it carries this
SCRIPTED = "custom/warehouse-script"
BRAIN_KEYS = ("engine", "default_model", "providers", "executors", "brain_fallbacks", "pricing", "pricing_skip")
TRY = ("Morning. Walk me through the warehouse.",
       "Cold room B looks warm. What's going on?",
       "Put the fans on in aisles 7-12.")
STEPS = ("Starting the six ESP32 nodes", "Starting the hub", "Setting up the three zone Pis from the hub",
         "Waiting for each zone to answer", "Adding each zone's ESP32 nodes", "Allowing the sensors and switches")
SOUL = """You are Aria. You look after a warehouse from this hub. Three Raspberry Pis, one per zone, each
look after ESP32 nodes: zone-cold (cold rooms A and B), zone-dock (the loading dock and the forklift
bay) and zone-aisle (aisles 1-6 and 7-12). You read them with device_get and switch them with
device_set; a person says yes to every switch. Read before you answer, and say what you read.
This warehouse is a simulation for a demo, and the person may cause trouble on the floor page.
"""


def http_port(m: str) -> int:
    return BASE + 1 + MACHINES.index(m)


def link_port(m: str) -> int:
    return BASE + 11 + MACHINES.index(m)


def door_port(z: str) -> int:
    return BASE + 22 + ZONES.index(z)


def sim_port(z: str) -> int:
    return BASE + 40 + 10 * ZONES.index(z)


BRAIN = BASE + 30
UDP = BASE + 70


def ports() -> list[int]:
    out = [FLOOR, BRAIN]
    for m in MACHINES:
        out += [http_port(m), link_port(m)]
    for z in ZONES:
        out += [door_port(z), sim_port(z), sim_port(z) + 1, sim_port(z) + 8]
    return out


def where() -> Path:
    if os.environ.get("AGENTOS_DEMO_DIR"):
        return Path(os.environ["AGENTOS_DEMO_DIR"])
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return cache / "bento-demo" / "warehouse"


def _owner_path() -> Path:
    # beside the demo's folder, so Start over (which deletes the folder) keeps whose demo it is
    return where().parent / (where().name + "-owner.json")


def owner() -> dict | None:
    """The Bento user the demo runs as, on a machine with accounts: {"uid", "name"}."""
    with contextlib.suppress(Exception):
        d = json.loads(_owner_path().read_text())
        if d.get("uid"):
            return d
    return None


def set_owner(uid: str, name: str) -> None:
    _owner_path().parent.mkdir(parents=True, exist_ok=True)
    _owner_path().write_text(json.dumps({"uid": uid, "name": name, "at": time.time()}))


def urls() -> dict:
    return {"floor": f"http://127.0.0.1:{FLOOR}/", "hub": f"http://127.0.0.1:{http_port(HUB)}/"}


# ---- the person's side: start, stop, status, poke --------------------------------------------

def _alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    with contextlib.suppress(Exception):        # a zombie we started and nobody reaped
        if Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] == "Z":
            return False
    return True


def _write_status(**kw) -> dict:
    d = where()
    d.mkdir(parents=True, exist_ok=True)
    st = {**_read_status(), **kw, "at": time.time()}
    tmp = d / "status.json.tmp"
    tmp.write_text(json.dumps(st))
    tmp.replace(d / "status.json")
    return st


def _read_status() -> dict:
    with contextlib.suppress(Exception):
        return json.loads((where() / "status.json").read_text())
    return {}


def status() -> dict:
    """What the demo is doing now: phase off | starting | ready | failed, and where it is."""
    st = _read_status()
    running = _alive(int(st.get("pid") or 0))
    phase = st.get("phase") or "off"
    if not running and phase in ("starting", "ready"):
        phase = "off"
    out = {"phase": phase, "step": st.get("step", ""), "done": st.get("done", 0), "of": len(STEPS),
           "brain": st.get("brain", ""), "error": st.get("error", "") if phase == "failed" else "",
           "set_up": (where() / "ready.json").exists(), "dir": str(where()), "try": list(TRY), **urls()}
    if os.name != "posix":
        out["unavailable"] = "The warehouse demo runs on Linux and macOS."
    return out


def brain_of(cfg: dict) -> tuple[dict, str]:
    """The person's brain, copied by value for the demo's hub, and its name in words. ({}, '')
    when there is no brain here to copy."""
    from .. import executors
    eng = executors.resolve_engine(cfg)
    if eng == "aria" and not cfg.get("default_model"):
        return {}, ""
    keys = {k: copy.deepcopy(cfg[k]) for k in BRAIN_KEYS if k in cfg}
    keys["engine"] = eng
    # an agent CLI's folder is the person's; in the demo it works in the hub's own workspace
    for v in (keys.get("executors") or {}).values():
        if isinstance(v, dict) and "workspace" in v:
            v["workspace"] = ""
    if eng != "aria":
        model = ((cfg.get("executors") or {}).get(eng.replace("-", "_")) or {}).get("model") or ""
        title = executors.EXECUTORS_BY_ID.get(eng, {}).get("title", eng)
        return keys, title + (f" ({model})" if model else "")
    return keys, cfg["default_model"]


def _port_taken(port: int) -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def start(cfg: dict, scripted: bool = False, fresh: bool = False) -> dict:
    """Start the demo in the background and return at once; status() says how it is going."""
    if os.name != "posix":
        return {**status(), "error": "The warehouse demo runs on Linux and macOS."}
    st = status()
    if st["phase"] in ("starting", "ready"):
        return st
    taken = [p for p in ports() if _port_taken(p)]
    if taken:
        return {**st, "phase": "failed", "error": f"Port {taken[0]} is in use by something else, so the demo "
                f"can't start. Free it, or set AGENTOS_DEMO_PORT to start it on other ports."}
    d = where()
    if fresh and d.exists():
        if not (d / MARK).exists():
            return {**st, "phase": "failed", "error": f"{d} isn't a demo folder, so it was left alone."}
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / MARK).write_text("A Bento demo. Everything here can be deleted.\n")
    keys, words = ({}, "") if scripted else brain_of(cfg)
    note = ""
    if not keys:
        note = "" if scripted else "No brain is set up here, so the hub runs on the scripted one."
        words = "the scripted brain (free, offline, understands a warehouse floor)"
    brain = d / "brain.json"
    brain.touch(mode=0o600)
    os.chmod(brain, 0o600)
    brain.write_text(json.dumps({"keys": keys, "words": words}))
    log = open(d / "demo.log", "a")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_") or k in ("AGENTOS_DEMO_DIR", "AGENTOS_DEMO_PORT")}
    p = subprocess.Popen([sys.executable, "-m", "agentos.demos.warehouse", "run"], cwd=d, env=env,
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _write_status(phase="starting", pid=p.pid, step=STEPS[0], done=0, brain=words, error="", note=note)
    return {**status(), "note": note}


def stop() -> dict:
    st = _read_status()
    pid = int(st.get("pid") or 0)
    if _alive(pid):
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        t0 = time.time()
        while _alive(pid) and time.time() - t0 < 15:
            time.sleep(0.2)
        if _alive(pid):
            with contextlib.suppress(OSError):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
    if st:
        _write_status(phase="off", step="", pid=0)
    return status()


def floor() -> dict:
    """Every node's readings, from the floor page's own server."""
    with urllib.request.urlopen(f"http://127.0.0.1:{FLOOR}/state", timeout=5) as r:
        return json.loads(r.read())


def poke(node: str, entity: str, value) -> dict:
    """Cause something on the floor (trip a compressor, open a door), as the floor page's buttons do."""
    req = urllib.request.Request(f"http://127.0.0.1:{FLOOR}/poke", method="POST",
                                 data=json.dumps({"node": node, "entity": entity, "value": value}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}")


# ---- the supervisor: one process that owns every other ----------------------------------------

def _home(m: str) -> Path:
    return where() / m


def _env(m: str, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTOS_")}
    env.update({"AGENTOS_HOME": str(_home(m)), "AGENTOS_VAULT_KEYRING": "0", "PYTHONUNBUFFERED": "1",
                "AGENTOS_DISCOVER_UDP": str(UDP), "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
                # the hub hears its zones on loopback; a zone's broadcast goes nowhere (TEST-NET-3)
                "AGENTOS_DISCOVER_TARGETS": "127.255.255.255" if m == HUB else "203.0.113.255"})
    if m in ZONES:
        # each zone its own address, as Pis on a network have, and its own nodes' mDNS
        env.update({"AGENTOS_MDNS_TARGET": f"127.0.0.1:{sim_port(m) + 8}",
                    "AGENTOS_LINK_FROM": f"127.0.0.{ZONES.index(m) + 2}"})
    return {**env, **(extra or {})}


def _config(m: str, brain: dict) -> None:
    home = _home(m)
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.json"
    cfg = {}
    with contextlib.suppress(Exception):
        cfg = json.loads(path.read_text())
    cfg.setdefault("agent_name", "Aria")
    cfg["team"] = {**(cfg.get("team") or {}), "link_port": link_port(m), "machine_name": m}
    cfg.setdefault("workspace", str(home / "workspace"))
    if m == HUB:
        for k in BRAIN_KEYS:
            cfg.pop(k, None)
        cfg.update(brain or {"engine": "aria", "default_model": SCRIPTED, "pricing_skip": [SCRIPTED],
                             "providers": {"custom": {"enabled": True, "base_url": f"http://127.0.0.1:{BRAIN}/v1",
                                                      "models": [SCRIPTED.split("/", 1)[1]]}}})
        cfg["setup_complete"] = True
        cfg["provision"] = {**(cfg.get("provision") or {}), "zero_updates": "off"}
        soul = home / "soul.md"
        if not soul.exists():
            soul.write_text(SOUL)
    else:
        cfg["provision"] = {**(cfg.get("provision") or {}), "port": door_port(m)}
        # a real Ollama here would be picked as the zone's own brain; a zone thinks with its hub
        cfg["providers"] = {"ollama": {"base_url": "http://127.0.0.1:9"}}
    path.write_text(json.dumps(cfg, indent=1))


def _http(m: str, method: str, path: str, body=None, timeout: float = 60):
    req = urllib.request.Request(f"http://127.0.0.1:{http_port(m)}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except (OSError, ValueError):
        return 0, {}


def _wait(what: str, fn, limit: float = 120, every: float = 1.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        got = fn()
        if got:
            return got
        time.sleep(every)
    raise RuntimeError(f"Timed out {what}. The servers' logs are in {where()}.")


class _Supervisor:
    def __init__(self):
        self.procs: dict[str, subprocess.Popen] = {}
        self.nodes: dict = {}
        self.stopping = False

    def step(self, i: int) -> None:
        _write_status(phase="starting", step=STEPS[i], done=i)

    def serve_bento(self, m: str, extra: dict | None = None) -> None:
        log = open(_home(m) / "server.log", "a")
        self.procs[m] = subprocess.Popen(
            [sys.executable, "-m", "agentos", "serve", "--port", str(http_port(m)), "--no-browser", "--if-running", "fail"],
            cwd=_home(m), env=_env(m, extra), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        _wait(f"for {m} to start", lambda: _http(m, "GET", "/api/provision", timeout=3)[0] == 200
              or (self.procs[m].poll() is not None and self._died(m)), limit=120, every=0.5)

    def _died(self, m: str):
        raise RuntimeError(f"{m} stopped while starting. Its log is {_home(m) / 'server.log'}.")

    def bento(self, m: str, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "agentos", *args], cwd=_home(m), env=_env(m),
                              capture_output=True, text=True, timeout=120)

    def row(self, zone: str):
        st, v = _http(HUB, "GET", "/api/network")
        return next((r for r in (v.get("rows") or []) if any(lk.get("label") == zone for lk in r.get("links") or [])), None)

    def run(self) -> None:
        import re
        from . import esp_sim
        brain = json.loads((where() / "brain.json").read_text())
        resume = (where() / "ready.json").exists()
        self.step(0)
        for z in ZONES:
            self.nodes[z] = esp_sim.build("warehouse", sim_port(z), zone=z)
            esp_sim.serve(self.nodes[z], mdns=sim_port(z) + 8, speed=SPEED)
        threading.Thread(target=self.floor_server, daemon=True).start()
        if not brain.get("keys"):
            self.procs["brain"] = subprocess.Popen(
                [sys.executable, "-m", "agentos.demos.warehouse_brain", str(BRAIN)], cwd=where(),
                env=_env(HUB), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for m in MACHINES:
            _config(m, brain.get("keys") or {})
        self.step(1)
        self.serve_bento(HUB)
        if resume:
            keys = json.loads((where() / "ready.json").read_text())["keys"]
            self.step(2)
            for z in ZONES:
                self.serve_bento(z)
        else:
            self.step(2)
            st, z = _http(HUB, "POST", "/api/provision/zero", {"hubs": ["127.0.0.1"]})
            if st != 200:
                raise RuntimeError(f"The hub wouldn't make a Zero line: {z.get('error') or st}")
            enroll = re.search(r"--enroll=(\S+)", z["line"]).group(1)
            hubs = re.search(r"--hub=(\S+)", z["line"]).group(1)
            for zone in ZONES:
                self.bento(zone, "pool", "hub", hubs)
                self.serve_bento(zone, {"AGENTOS_ENROLL": enroll})
            for zone in ZONES:
                _wait(f"for {zone} to be set up by the hub",
                      lambda: (_http(zone, "GET", "/api/provision")[1].get("this") or {}).get("claimed"), limit=120)
            keys = {zone: _wait(f"for {zone} on the hub's list", lambda: self.row(zone), limit=120)["key"] for zone in ZONES}
        self.step(3)
        for zone in ZONES:
            _wait(f"for {zone} to answer its hub", lambda: _http(HUB, "POST", "/api/network/hardware",
                                                                {"key": keys[zone]})[0] == 200, limit=180, every=3)
        if not resume:
            self.step(4)
            for zone in ZONES:
                st, f = _http(HUB, "POST", "/api/devices/esp", {"key": keys[zone], "action": "find"})
                for x in f.get("found") or []:
                    st, a = _http(HUB, "POST", "/api/devices/esp", {"key": keys[zone], "action": "add", "name": x["name"],
                                                                    "host": x["host"], "port": x["port"]})
                    if st != 200:
                        raise RuntimeError(f"{zone} couldn't add {x['name']}: {a.get('error') or st}")
            self.step(5)
            for zone in ZONES:
                can = (self.row(zone) or {}).get("device_can") or {}
                get = [i for i in can if i.startswith("esp.") and ".wifi_signal" not in i]
                set_ = [i for i, v in can.items() if v == "set" and i.startswith("esp.")]
                st, p = _http(HUB, "PUT", "/api/devices/permits", {"key": keys[zone], "get": get, "set": set_})
                if st != 200:
                    raise RuntimeError(f"{zone} wouldn't take its permits: {p.get('error') or st}")
            (where() / "ready.json").write_text(json.dumps({"keys": keys, "at": time.time()}))
        _write_status(phase="ready", step="", done=len(STEPS))
        while not self.stopping:
            for m, p in list(self.procs.items()):
                if p.poll() is not None and not self.stopping:
                    raise RuntimeError(f"{m} stopped. Its log is in {where()}. Start the demo again.")
            time.sleep(2)

    def end(self, *_):
        self.stopping = True
        for p in self.procs.values():
            with contextlib.suppress(Exception):
                p.terminate()
        for p in self.procs.values():
            with contextlib.suppress(Exception):
                p.wait(8)
        _write_status(phase="off", step="", pid=0)
        os._exit(0)

    # the floor page ------------------------------------------------------------------------------
    def state(self) -> dict:
        st = status()
        zones = {}
        for z, ns in self.nodes.items():
            zones[z] = [{"node": n.host_name, "title": n.title, "ents": [
                {"name": e.name, "domain": e.domain, "value": e.value, "uom": e.uom, "decimals": e.decimals}
                for e in n.ents.values() if e.category != "diagnostic"]} for n in ns]
        return {"phase": st["phase"], "step": st["step"], "done": st["done"], "of": st["of"], "brain": st["brain"],
                "error": st["error"], "hub": st["hub"], "try": list(TRY), "zones": zones}

    def poke(self, d: dict) -> dict:
        n = next((n for ns in self.nodes.values() for n in ns if n.host_name == d.get("node")), None)
        e = n and next((e for e in n.ents.values() if e.name == d.get("entity")), None)
        if not e:
            return {"ok": False, "error": f"there is no {d.get('entity')!r} on {d.get('node')!r}"}
        v = d.get("value")
        if e.domain in ("switch", "binary_sensor", "light", "fan"):
            v = v if isinstance(v, bool) else str(v).lower() in ("1", "on", "true", "open", "yes")
        else:
            try:
                v = float(v)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"{e.name} takes a number"}
        with n.lock:
            e.value = v
        n.push([e])
        return {"ok": True, "node": n.host_name, "entity": e.name, "value": v}

    def floor_server(self) -> None:
        sup, page = self, (Path(__file__).parent / "floor.html").read_bytes()

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    return self._send(200, page, "text/html; charset=utf-8")
                if self.path == "/state":
                    return self._send(200, json.dumps(sup.state()).encode())
                self._send(404, b"{}")

            def do_POST(self):
                # only the floor page itself (or a terminal, which sends no Origin) may cause things
                origin = self.headers.get("Origin")
                if origin and origin.rstrip("/") not in (f"http://127.0.0.1:{FLOOR}", f"http://localhost:{FLOOR}"):
                    return self._send(403, b'{"ok":false,"error":"only the floor page can do that"}')
                if self.path != "/poke":
                    return self._send(404, b"{}")
                try:
                    d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                except ValueError:
                    d = {}
                out = sup.poke(d)
                self._send(200 if out.get("ok") else 400, json.dumps(out).encode())

        srv = ThreadingHTTPServer(("127.0.0.1", FLOOR), H)
        srv.daemon_threads = True
        srv.serve_forever()


def _main() -> None:
    if sys.argv[1:2] != ["run"]:
        sys.exit("this is started by `bento demo warehouse`")
    sup = _Supervisor()
    signal.signal(signal.SIGTERM, sup.end)
    signal.signal(signal.SIGINT, sup.end)
    try:
        sup.run()
    except Exception as e:                       # the reason goes where every face reads it
        if not sup.stopping:
            _write_status(phase="failed", error=str(e) or e.__class__.__name__)
            for p in sup.procs.values():
                with contextlib.suppress(Exception):
                    p.terminate()
            time.sleep(1)
        os._exit(1)


if __name__ == "__main__":
    _main()

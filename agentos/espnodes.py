"""ESP32 nodes running ESPHome, as part of the Pi they are attached to.

Asked for as "Bento has a controlling effect on the Pi now, think about sense with ESP32": a Pi
is one box with a few pins, and a warehouse needs thermometers in the cold room, a contact on
every dock door and a relay on every fan. Those are ESP32s, usually flashed with ESPHome, and
this module makes each one's sensors and switches part of the Pi that looks after them. Then
everything the Pi's own hardware already has applies unchanged: the inventory on the hub
(hardware.py), the 90 days of readings (telemetry.py), get and set through the two gates and
the ledger on both sides (devio.py), and every set asked of a person.

Five rules:

  * A node is ADDED on purpose, from the hub, and never used because it was heard. mDNS says
    which nodes are on the network (`discover`, ESPHome's `_esphomelib._tcp` and `_http._tcp`);
    adding one reads it first, so a node that does not answer is not kept.
  * What a node has is read from the node (its web server's /events), never declared. An item
    is `esp.<node>.<domain>.<name>`, so `<pi>/esp.dock-1.binary_sensor.door_3` is its inventory
    name, and permits, grants and readings all use it.
  * Only sensors, binary sensors, text sensors, switches, lights and fans. A set is on or off on
    a switch, light or fan, and it is read back: done means the node now reports what was asked.
  * ESPHome's web server is plain HTTP, and its password is Basic auth. Anybody on that network
    can read the password and talk to the node. The words say so, and the fix is a network of
    the nodes' own (a VLAN or the Pi's own Wi-Fi), not something Bento can do from here.
  * The password is kept in this machine's vault (`esp.<node>`), never in esp.json, and nothing
    returns it.

Free of asyncio except `discover`, like hardware.py: the sampler, the link's op and the CLI call in.
"""
from __future__ import annotations

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

FILE = "esp.json"
NODE = re.compile(r"[a-z0-9][a-z0-9-]{0,15}")
DOMAINS = ("sensor", "binary_sensor", "text_sensor", "switch", "light", "fan")
SETTABLE = ("switch", "light", "fan")
ONOFF = ("binary_sensor", "switch", "light", "fan")
ITEM = re.compile(r"esp\.([a-z0-9][a-z0-9-]{0,15})\.(" + "|".join(DOMAINS) + r")\.([a-z0-9_]{1,24})")
MAX_NODES = 24
MAX_ENTITIES = 40            # per node
TIMEOUT = 3.0                # one request to a node
QUIET = 0.4                  # /events sends every state at once on connect; this long silent and it has
SNAP_MAX = 3.0               # a whole snapshot, at most
DOWN_S = 30                  # a node that did not answer is left alone this long by the sampler
SET_WAIT = 2.5               # how long a set may take to show in the node's own state
DOMAIN_WORDS = {"sensor": "sensor", "binary_sensor": "contact", "text_sensor": "text", "switch": "switch",
                "light": "light", "fan": "fan"}
SAY_PLAIN = ("ESPHome's web server is plain HTTP with Basic auth, so anybody on that network can read the "
             "password and switch things. Keep the nodes on a network of their own.")

_LOCK = threading.Lock()
_DOWN: dict[str, float] = {}       # node -> until when the sampler skips it
_LAST: dict[str, dict] = {}        # node -> last snapshot {at, ok, entities, error}


# ---- what this machine keeps ----------------------------------------------------------------

def _path() -> Path:
    from . import teamlink
    return teamlink.home() / FILE


def _load() -> dict:
    try:
        d = json.loads(_path().read_text())
    except (OSError, ValueError):
        d = {}
    nodes = [n for n in d.get("nodes") or [] if isinstance(n, dict) and NODE.fullmatch(str(n.get("name") or ""))]
    return {"nodes": nodes[:MAX_NODES]}


def _save(d: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_text(json.dumps(d, indent=1))
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def nodes() -> list[dict]:
    """The nodes this machine looks after: name, host, port, user, friendly name and the
    entities read last time (so the inventory lists them while a node is away)."""
    return _load()["nodes"]


def node(name: str) -> dict | None:
    return next((n for n in nodes() if n["name"] == name), None)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")[:24] or "x"


def node_name(s: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(s or "").lower()).strip("-")[:16].strip("-")


def address_ok(host: str) -> bool:
    """A node is on this machine's own network: a private, link-local or (for tests) loopback
    address, or a .local name. Never something on the internet."""
    host = str(host or "").strip()
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}\.local", host.lower()):
        return True
    try:
        a = ipaddress.ip_address(host)
    except ValueError:
        return False
    return a.is_private or a.is_link_local or a.is_loopback


def _secret(name: str) -> str:
    from . import vault
    try:
        return vault.get(f"esp.{name}", actor="esp32 node")
    except Exception:
        return ""


# ---- talking to a node ----------------------------------------------------------------------

def _headers(n: dict) -> dict:
    h = {"Accept": "application/json, text/event-stream"}
    if n.get("user"):
        token = base64.b64encode(f"{n['user']}:{_secret(n['name'])}".encode()).decode()
        h["Authorization"] = "Basic " + token
    return h


def _request(n: dict, method: str, path: str, timeout: float = TIMEOUT):
    conn = http.client.HTTPConnection(n["host"], int(n.get("port") or 80), timeout=timeout)
    conn.request(method, path, headers=_headers(n))
    conn.held = conn.sock               # http.client lets go of it once a stream says Connection: close
    return conn, conn.getresponse()


def _why(e: Exception) -> str:
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "it did not answer in time"
    if isinstance(e, ConnectionRefusedError):
        return "nothing is listening there (is its web_server: on?)"
    if isinstance(e, OSError):
        return f"couldn't reach it ({e.strerror or e.__class__.__name__})"
    return str(e)[:120] or e.__class__.__name__


def _entity(d: dict) -> dict | None:
    """One ESPHome state event, as this module keeps it: domain, name, unit, value."""
    nid = str(d.get("name_id") or "")
    domain, _, name = nid.partition("/")
    if not name:                       # before 2026.x: "sensor-object_id" and a separate name
        domain = str(d.get("domain") or str(d.get("id") or "").split("-", 1)[0])
        name = str(d.get("name") or str(d.get("id") or "").split("-", 1)[-1])
    if "/" in name:                    # a sub-device's entity: "Device/Name"
        name = name.rsplit("/", 1)[-1]
    if domain not in DOMAINS or not name:
        return None
    e = {"domain": domain, "name": name[:60], "slug": slug(name)}
    if d.get("uom"):
        e["unit"] = str(d["uom"])[:8]
    v = d.get("value")
    st = str(d.get("state") or "")
    if domain in ONOFF:
        e["value"] = 1 if (v is True or str(v).upper() == "ON" or st.upper() == "ON") else 0
    elif domain == "sensor":
        e["value"] = round(float(v), 3) if isinstance(v, (int, float)) and v == v else None
    else:
        e["value"] = str(v if v is not None else st)[:60]
    return e


def snapshot(n: dict) -> dict:
    """Everything the node has and what each reads now, from its /events stream: on connect
    ESPHome sends a ping with its title, then one state event per entity. Closed as soon as it
    goes quiet. {"ok", "title", "entities": [...]} or {"ok": False, "error"}."""
    got: dict[str, dict] = {}
    title, pinged = "", False
    try:
        conn, resp = _request(n, "GET", "/events", timeout=TIMEOUT)
    except Exception as e:
        return {"ok": False, "error": _why(e)}
    try:
        if resp.status == 401:
            return {"ok": False, "error": "it wants a password (the user or password is wrong)"}
        if resp.status != 200:
            return {"ok": False, "error": f"it answered {resp.status}: is web_server on in its YAML?"}
        conn.held.settimeout(QUIET)
        start, event = time.time(), ""
        while time.time() - start < SNAP_MAX:
            try:
                line = resp.fp.readline(65536)
            except (socket.timeout, TimeoutError):
                if pinged:
                    break
                continue
            if not line:
                break
            line = line.decode("utf-8", "replace").rstrip("\r\n")
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:") and event in ("ping", "state"):
                try:
                    d = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if event == "ping":
                    pinged = True
                    title = str(d.get("title") or "")[:60] if isinstance(d, dict) else ""
                elif isinstance(d, dict) and (e := _entity(d)) and len(got) < MAX_ENTITIES:
                    got[f"{e['domain']}.{e['slug']}"] = e
    except Exception as e:
        return {"ok": False, "error": _why(e)}
    finally:
        resp.close()
        conn.close()
    if not pinged and not got:
        return {"ok": False, "error": "it answered, but not as an ESPHome node"}
    return {"ok": True, "title": title, "entities": list(got.values())}


def _ents(n: dict) -> list[dict]:
    last = _LAST.get(n["name"]) or {}
    return last.get("entities") if last.get("ok") else n.get("entities") or []


def look(name: str, keep: bool = True) -> dict:
    """Snapshot one node now and remember what it has; a new set of entities is saved, so the
    inventory and the quick hash follow it."""
    n = node(name)
    if not n:
        return {"ok": False, "error": f"no ESP32 node called {name} here"}
    s = snapshot(n)
    s["at"] = time.time()
    with _LOCK:
        _LAST[name] = s
        if s["ok"]:
            _DOWN.pop(name, None)
        else:
            _DOWN[name] = time.time() + DOWN_S
    if s["ok"] and keep:
        shape = [{k: e[k] for k in ("domain", "name", "slug", "unit") if k in e} for e in s["entities"]]
        if shape != n.get("entities") or (s.get("title") and s["title"] != n.get("title")):
            d = _load()
            for x in d["nodes"]:
                if x["name"] == name:
                    x["entities"] = shape
                    x["title"] = s.get("title") or x.get("title") or name
            _save(d)
    return s


def look_all(skip_down: bool = True) -> dict[str, dict]:
    """Every node at once (a thread each), skipping the ones that just failed."""
    now = time.time()
    names = [n["name"] for n in nodes() if not (skip_down and _DOWN.get(n["name"], 0) > now)]
    if not names:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as ex:
        return dict(zip(names, ex.map(look, names)))


# ---- adding and removing (the hub asks, wire op esp_nodes) ----------------------------------

def add(name: str, host: str, port: int = 80, user: str = "", password: str = "", by: str = "") -> dict:
    """Keep a node, after reading it. The password goes in the vault."""
    name = node_name(name)
    host = str(host or "").strip()
    try:
        port = int(port or 80)
    except (TypeError, ValueError):
        port = 0
    if not NODE.fullmatch(name):
        return {"ok": False, "error": "a node's name is letters, digits and dashes"}
    if not address_ok(host):
        return {"ok": False, "error": f"{host or 'that'} isn't an address on this machine's own network"}
    if not 0 < port < 65536:
        return {"ok": False, "error": "the port is a number from 1 to 65535"}
    d = _load()
    if not node(name) and len(d["nodes"]) >= MAX_NODES:
        return {"ok": False, "error": f"this machine looks after {MAX_NODES} nodes already"}
    user = re.sub(r"[^\w.@-]", "", str(user or ""))[:40]
    from . import vault
    had = node(name) is not None
    if password:
        try:
            vault.put(f"esp.{name}", str(password))
        except Exception as e:
            return {"ok": False, "error": f"the password couldn't be kept in the vault: {e}"}
    n = {"name": name, "host": host, "port": port, "user": user}
    s = snapshot(n)
    if not s["ok"]:
        if password and not had:
            vault.forget(f"esp.{name}")
        return {"ok": False, "error": f"{host}:{port} {s['error']}"}
    n.update(title=s.get("title") or name, by=str(by)[:60], at=time.time(),
             entities=[{k: e[k] for k in ("domain", "name", "slug", "unit") if k in e} for e in s["entities"]])
    d["nodes"] = [x for x in d["nodes"] if x["name"] != name] + [n]
    _save(d)
    with _LOCK:
        _LAST[name] = {**s, "at": time.time()}
        _DOWN.pop(name, None)
    return {"ok": True, "node": public(n), "said": SAY_PLAIN}


def remove(name: str) -> dict:
    d = _load()
    if not any(x["name"] == name for x in d["nodes"]):
        return {"ok": False, "error": f"no ESP32 node called {name} here"}
    d["nodes"] = [x for x in d["nodes"] if x["name"] != name]
    _save(d)
    from . import vault
    try:
        vault.forget(f"esp.{name}")
    except Exception:
        pass
    with _LOCK:
        _LAST.pop(name, None)
        _DOWN.pop(name, None)
    return {"ok": True}


def public(n: dict) -> dict:
    """A node as a screen shows it: never the password."""
    last = _LAST.get(n["name"]) or {}
    return {"name": n["name"], "title": n.get("title") or n["name"], "host": n["host"], "port": n.get("port") or 80,
            "user": n.get("user") or "", "password": bool(n.get("user")),
            "things": len(n.get("entities") or []), "answering": last.get("ok") if last else None,
            "error": last.get("error") if last and not last.get("ok") else ""}


# ---- as hardware ----------------------------------------------------------------------------

def item_id(node_: str, e: dict) -> str:
    return f"esp.{node_}.{e['domain']}.{e['slug']}"


def items(fresh: bool = False) -> list[dict]:
    """The nodes and their entities as inventory items (hardware.probe). `fresh` reads every
    node now; otherwise what the sampler read last."""
    if fresh:
        look_all(skip_down=False)
    out = []
    for n in nodes():
        last = _LAST.get(n["name"]) or {}
        state = ("answering" if last.get("ok") else f"not answering: {last.get('error')}" if last
                 else "not read yet")
        out.append({"id": f"esp.{n['name']}", "kind": "esphome", "name": n.get("title") or n["name"],
                    "detail": f"ESPHome node at {n['host']}:{n.get('port') or 80}, {state}", "can": []})
        now = {e["slug"] + e["domain"]: e for e in (last.get("entities") or [])} if last.get("ok") else {}
        for e in n.get("entities") or []:
            cur = now.get(e["slug"] + e["domain"], {})
            it = {"id": item_id(n["name"], e), "kind": "esphome",
                  "name": f"{n.get('title') or n['name']}: {e['name']}",
                  "detail": f"{DOMAIN_WORDS[e['domain']]} on {n['name']}",
                  "can": ["read", "write"] if e["domain"] in SETTABLE else ["read"]}
            if cur.get("value") is not None:
                it["value"] = cur["value"]
            if e.get("unit"):
                it["unit"] = e["unit"]
            out.append(it)
    return out


def sample() -> dict:
    """The numbers worth keeping, by item id: a sensor's value, and 1 or 0 for a contact, a
    switch, a light or a fan. One /events read per node, at once."""
    out = {}
    for name, s in look_all().items():
        for e in s.get("entities") or [] if s.get("ok") else []:
            if isinstance(e.get("value"), (int, float)):
                out[item_id(name, e)] = e["value"]
    return out


def quick() -> list[str]:
    """What the nodes have, for hardware.quick's hash: a node added or an entity that appeared
    changes it, a reading doesn't."""
    return [f"esp:{n['name']}:" + ",".join(e["domain"] + "." + e["slug"] for e in n.get("entities") or [])
            for n in nodes()]


def _find(item: str):
    m = ITEM.fullmatch(str(item or ""))
    if not m:
        return None, None, f"{item} isn't an ESP32 node's item"
    n = node(m.group(1))
    if not n:
        return None, None, f"no ESP32 node called {m.group(1)} is attached to this machine"
    e = next((x for x in _ents(n) if x["domain"] == m.group(2) and x["slug"] == m.group(3)), None)
    if not e:
        return n, None, f"{n.get('title') or n['name']} has no {m.group(2).replace('_', ' ')} called {m.group(3)} now"
    return n, e, ""


def _state(n: dict, e: dict) -> dict:
    path = f"/{e['domain']}/{urllib.parse.quote(e['name'], safe='')}?detail=all"
    try:
        conn, resp = _request(n, "GET", path)
        try:
            body = resp.read(16384)
        finally:
            conn.close()
    except Exception as ex:
        return {"ok": False, "error": f"{n['name']} {_why(ex)}"}
    if resp.status == 401:
        return {"ok": False, "error": f"{n['name']} wants a password (the user or password is wrong)"}
    if resp.status != 200:
        return {"ok": False, "error": f"{n['name']} answered {resp.status} for {e['name']}"}
    try:
        got = _entity(json.loads(body))
    except ValueError:
        got = None
    if not got:
        return {"ok": False, "error": f"{n['name']} answered something that isn't ESPHome's"}
    return {"ok": True, **got}


def read(item: str) -> dict:
    n, e, err = _find(item)
    if err:
        return {"ok": False, "error": err}
    s = _state(n, e)
    if not s["ok"]:
        return s
    out = {"ok": True, "item": item, "name": f"{n.get('title') or n['name']}: {e['name']}", "at": time.time(),
           "value": s.get("value")}
    if s.get("unit") or e.get("unit"):
        out["unit"] = s.get("unit") or e.get("unit")
    if e["domain"] in ONOFF:
        out["detail"] = "on" if s.get("value") else "off"
    return out


def write(item: str, value) -> dict:
    """Turn a switch, light or fan on or off, then read it back from the node."""
    from .devio import level
    n, e, err = _find(item)
    if err:
        return {"ok": False, "error": err}
    if e["domain"] not in SETTABLE:
        return {"ok": False, "error": f"a {e['domain'].replace('_', ' ')} is read, not set"}
    want = level(value)
    if want is None:
        return {"ok": False, "error": f"a {e['domain']} is set on or off (1 or 0), not '{str(value)[:20]}'"}
    before = _state(n, e)
    if not before["ok"]:
        return before
    path = f"/{e['domain']}/{urllib.parse.quote(e['name'], safe='')}/{'turn_on' if want else 'turn_off'}"
    try:
        conn, resp = _request(n, "POST", path)
        resp.read()
        conn.close()
    except Exception as ex:
        return {"ok": False, "error": f"{n['name']} {_why(ex)}"}
    if resp.status != 200:
        return {"ok": False, "error": f"{n['name']} refused it ({resp.status})"}
    after, end = {}, time.time() + SET_WAIT
    while time.time() < end:           # ESPHome defers the action to its loop: give it a moment
        after = _state(n, e)
        if after.get("ok") and after.get("value") == want:
            break
        time.sleep(0.15)
    if not after.get("ok") or after.get("value") != want:
        return {"ok": False, "error": f"{e['name']} on {n['name']} still reads "
                                      f"{'on' if after.get('value') else 'off'} after it was set {'on' if want else 'off'}"}
    return {"ok": True, "item": item, "name": f"{n.get('title') or n['name']}: {e['name']}", "at": time.time(),
            "value": want, "detail": "on" if want else "off", "was": before.get("value"), "read_back": "the node"}


# ---- discovery: who is on the network -------------------------------------------------------

async def discover(timeout: float = 1.5) -> list[dict]:
    """Which ESPHome nodes answer on this network: one mDNS question for `_esphomelib._tcp` and
    `_http._tcp`, from a port of our own so the answers come straight back (RFC 6762 6.7).
    [{name, title, host, port, platform, board, mac, version, added}]; [] when nobody answers or
    this machine can't multicast. Sends nothing else and connects to nobody."""
    import asyncio
    from . import netscan
    loop = asyncio.get_running_loop()
    ptr: dict[str, str] = {}               # instance -> service
    srv: dict[str, tuple[str, int]] = {}   # instance -> (target host, port)
    txt: dict[str, dict] = {}
    addr: dict[str, str] = {}              # host.local -> ip

    def parse(buf: bytes):
        for name, rtype, off, rdlen in netscan._records(buf):
            if rtype == 12 and name in ("_esphomelib._tcp.local", "_http._tcp.local"):
                inst, _ = netscan._dns_name(buf, off)
                ptr[inst.lower().rstrip(".")] = name
            elif rtype == 33:
                port = struct.unpack("!H", buf[off + 4:off + 6])[0]
                target, _ = netscan._dns_name(buf, off + 6)
                srv[name] = (target.lower().rstrip("."), port)
            elif rtype == 16:
                t, i = {}, off
                while i < off + rdlen:
                    ln = buf[i]
                    k, _, v = buf[i + 1:i + 1 + ln].decode("utf-8", "replace").partition("=")
                    t[k[:20]] = v[:60]
                    i += 1 + ln
                txt[name] = t
            elif rtype == 1 and rdlen == 4:
                addr[name] = socket.inet_ntoa(buf[off:off + 4])

    class P(asyncio.DatagramProtocol):
        def datagram_received(self, data, a):
            if len(data) <= 9000:
                try:
                    parse(data)
                except Exception:
                    pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.bind(("", 0))
        s.setblocking(False)
        tr, _ = await loop.create_datagram_endpoint(P, sock=s)
    except OSError:
        return []
    try:
        tr.sendto(netscan._question(["_esphomelib._tcp.local", "_http._tcp.local"]), netscan._mdns_target())
        await asyncio.sleep(timeout)
    except OSError:
        return []
    finally:
        tr.close()
    kept = {(n["host"], int(n.get("port") or 80)) for n in nodes()}
    found: dict[str, dict] = {}
    for inst, service in ptr.items():
        if service != "_esphomelib._tcp.local":
            continue
        host = inst.split(".", 1)[0]
        t = txt.get(inst, {})
        target, _ = srv.get(inst, (host + ".local", 6053))
        ip = addr.get(target, "")
        web = srv.get(f"{host}._http._tcp.local")
        if not ip or not address_ok(ip):
            continue
        port = web[1] if web else 80
        found[host] = {"name": node_name(host), "title": t.get("friendly_name") or host, "host": ip, "port": port,
                       "web": bool(web), "platform": t.get("platform", ""), "board": t.get("board", ""),
                       "mac": t.get("mac", ""), "version": t.get("version", ""), "added": (ip, port) in kept}
    return sorted(found.values(), key=lambda d: d["name"])[:MAX_NODES * 2]


# ---- the wire op (the hub asks its own Zero) ------------------------------------------------

def answer(cfg: dict, lk: dict, req: dict) -> dict:
    """Wire op esp_nodes: list, look, add or remove. Only this machine's own hub is answered.
    `discover` is async and handled by the server before this is called."""
    from . import zero as zeromod
    from . import teamlink
    if not zeromod.is_my_hub(cfg, lk):
        return {"ok": False, "error": "only the hub that set this machine up can change its ESP32 nodes"}
    act = str(req.get("action") or "list")
    if act == "add":
        return add(teamlink.plain(req.get("name"), 16, newlines=False), teamlink.plain(req.get("host"), 64, newlines=False),
                   req.get("port") or 80, teamlink.plain(req.get("user"), 40, newlines=False),
                   str(req.get("password") or "")[:128], by=str(lk.get("label") or ""))
    if act == "remove":
        return remove(node_name(req.get("name")))
    if act == "look":
        look_all(skip_down=False)
    return {"ok": True, "nodes": [public(n) for n in nodes()], "said": SAY_PLAIN}


def words(req: dict, got: dict, frm: str) -> str:
    act = str(req.get("action") or "list")
    name = node_name(req.get("name")) or "a node"
    if not got.get("ok"):
        return f"{frm} asked to {act} ESP32 node {name}: {got.get('error')}"
    if act == "add":
        n = got.get("node") or {}
        return f"{frm} added ESP32 node {n.get('title') or name} at {n.get('host')}:{n.get('port')} ({n.get('things')} things)"
    if act == "remove":
        return f"{frm} removed ESP32 node {name}"
    return f"{frm} listed the ESP32 nodes ({len(got.get('nodes') or [])})"

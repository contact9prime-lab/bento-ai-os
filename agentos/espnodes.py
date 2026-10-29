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
import contextlib
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
STREAM_IDLE = 40             # a held /events stream with no line this long is dead (ESPHome pings every ~10 s)
STREAM_BACKOFF = (2, 5, 10, 30)  # seconds before connecting again, after one, two, three, more failures
DOMAIN_WORDS = {"sensor": "sensor", "binary_sensor": "contact", "text_sensor": "text", "switch": "switch",
                "light": "light", "fan": "fan"}
SAY_PLAIN = ("ESPHome's web server is plain HTTP with Basic auth, so anybody on that network can read the "
             "password and switch things. Keep the nodes on a network of their own.")

_LOCK = threading.Lock()
_DOWN: dict[str, float] = {}       # node -> until when the sampler skips it
_LAST: dict[str, dict] = {}        # node -> last snapshot {at, ok, entities, error[, live]}
_STREAMS: dict[str, "_Stream"] = {} # node -> the thread holding its /events open


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


class _SSE:
    """A node's /events, read off a plain socket. http.client's reader can't be read again after a
    timeout ("cannot read from timed out object"), and a held stream times out every quiet spell;
    ESPHome on ESP-IDF may also send it chunked. So: the request by hand, the chunks undone here,
    and a line at a time, each wait its own."""

    def __init__(self, n: dict):
        self.sock = socket.create_connection((n["host"], int(n.get("port") or 80)), timeout=TIMEOUT)
        h = "".join(f"{k}: {v}\r\n" for k, v in _headers(n).items())
        self.sock.sendall(f"GET /events HTTP/1.1\r\nHost: {n['host']}\r\n{h}Connection: keep-alive\r\n\r\n".encode())
        raw = b""
        while b"\r\n\r\n" not in raw:
            got = self.sock.recv(4096)
            if not got:
                raise ConnectionError("it closed the connection")
            raw += got
            if len(raw) > 16384:
                raise ConnectionError("it answered something that isn't HTTP")
        head, _, self.raw = raw.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        try:
            self.status = int(lines[0].split()[1])
        except (IndexError, ValueError):
            raise ConnectionError("it answered something that isn't HTTP") from None
        hdrs = {k.strip().lower(): v.strip() for k, _, v in (x.partition(":") for x in lines[1:])}
        self.chunked = "chunked" in hdrs.get("transfer-encoding", "").lower()
        self.body, self.left, self.eof = b"", 0, False

    def _decode(self):
        if not self.chunked:
            self.body, self.raw = self.body + self.raw, b""
            return
        while self.raw:
            if self.left:
                take = self.raw[:self.left]
                self.body += take
                self.raw, self.left = self.raw[len(take):], self.left - len(take)
                if not self.left:
                    self.left = -2                       # the chunk's own CRLF follows
                continue
            if self.left < 0:
                skip = min(-self.left, len(self.raw))
                self.raw, self.left = self.raw[skip:], self.left + skip
                continue
            if b"\r\n" not in self.raw:
                return
            size, _, self.raw = self.raw.partition(b"\r\n")
            try:
                self.left = int(size.split(b";")[0].strip() or b"0", 16)
            except ValueError:
                raise ConnectionError("its stream isn't chunked as it said") from None
            if self.left == 0:
                self.eof = True
                return

    def readline(self, wait: float) -> str | None:
        """One line, waiting at most `wait` for it (socket.timeout past that); None at the end."""
        while b"\n" not in self.body:
            if self.eof:
                return None
            self.sock.settimeout(wait)
            got = self.sock.recv(8192)
            if not got:
                return None
            self.raw += got
            self._decode()
            if len(self.body) > 262144:
                raise ConnectionError("a line too long for an ESPHome event")
        line, _, self.body = self.body.partition(b"\n")
        return line.decode("utf-8", "replace").rstrip("\r")

    def close(self):
        with contextlib.suppress(OSError):
            self.sock.close()


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
        sse = _SSE(n)
    except Exception as e:
        return {"ok": False, "error": _why(e)}
    try:
        if sse.status == 401:
            return {"ok": False, "error": "it wants a password (the user or password is wrong)"}
        if sse.status != 200:
            return {"ok": False, "error": f"it answered {sse.status}: is web_server on in its YAML?"}
        start, event = time.time(), ""
        while time.time() - start < SNAP_MAX:
            try:
                line = sse.readline(QUIET if pinged else max(0.05, SNAP_MAX - (time.time() - start)))
            except (socket.timeout, TimeoutError):
                if pinged:
                    break
                continue
            if line is None:
                break
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
        sse.close()
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
        _keep_shape(n, s.get("title") or "", s["entities"])
    return s


def _keep_shape(n: dict, title: str, ents: list[dict]) -> None:
    """Save what a node has when it changed, so the inventory and the quick hash follow it."""
    shape = [{k: e[k] for k in ("domain", "name", "slug", "unit") if k in e} for e in ents]
    if shape == n.get("entities") and (not title or title == n.get("title")):
        return
    with _LOCK:
        d = _load()
        for x in d["nodes"]:
            if x["name"] == n["name"]:
                x["entities"] = shape
                x["title"] = title or x.get("title") or n["name"]
        _save(d)


def look_all(skip_down: bool = True) -> dict[str, dict]:
    """Every node at once (a thread each), skipping the ones that just failed. A node whose
    stream is held open (`live`) is not connected to again: its state is already here."""
    now = time.time()
    out = {n["name"]: _LAST[n["name"]] for n in nodes() if skip_down and live(n["name"])}
    names = [n["name"] for n in nodes() if n["name"] not in out
             and not (skip_down and _DOWN.get(n["name"], 0) > now)]
    if not names:
        return out
    with ThreadPoolExecutor(max_workers=min(8, len(names))) as ex:
        return {**out, **dict(zip(names, ex.map(look, names)))}


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
    st = _STREAMS.pop(name, None)
    if st:
        st.stop.set()
    return {"ok": True}


def public(n: dict) -> dict:
    """A node as a screen shows it: never the password."""
    last = _LAST.get(n["name"]) or {}
    return {"name": n["name"], "title": n.get("title") or n["name"], "host": n["host"], "port": n.get("port") or 80,
            "user": n.get("user") or "", "password": bool(n.get("user")),
            "things": len(n.get("entities") or []), "answering": last.get("ok") if last else None,
            "live": live(n["name"]),
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


# ---- held open: every change as it happens ---------------------------------------------------
#
# ESPHome's web server pushes a state event on its /events stream each time an entity publishes,
# so a stream held open hears a door that opens for one second, which a sample every ten seconds
# mostly does not (measured: 1 of 8 three-second openings reached the hub). Whichever machine
# holds the node holds its stream: a Pi relays the changes to its hub with their inventory
# context, a hub uses them itself (server._device_changes). One thread per node, MAX_NODES at
# most, sleeping on the socket.

def live(name: str) -> bool:
    """Is this node's stream held open and heard from lately?"""
    last = _LAST.get(name) or {}
    return bool(last.get("live")) and time.time() - float(last.get("heard") or 0) < STREAM_IDLE


def _event(name: str, title: str, e: dict, prev: dict | None) -> dict:
    """One change, with what the hub needs to file it: the item's inventory id, what it is
    called, its kind, its unit, the node it is on."""
    ev = {"item": item_id(name, e), "node": name, "title": title or name, "domain": e["domain"],
          "name": f"{title or name}: {e['name']}", "value": e.get("value"), "at": round(time.time(), 2)}
    if e.get("unit"):
        ev["unit"] = e["unit"]
    if prev is not None:
        ev["prev"] = prev.get("value")
    else:
        ev["first"] = True
    return ev


class _Stream(threading.Thread):
    def __init__(self, name: str, on_change):
        super().__init__(daemon=True, name=f"esp-{name}")
        self.node, self.on_change, self.stop = name, on_change, threading.Event()

    def run(self):
        fails = 0
        while not self.stop.is_set():
            n = node(self.node)
            if not n:
                break
            fails = 0 if self._once(n) else fails + 1
            self.stop.wait(STREAM_BACKOFF[min(fails, len(STREAM_BACKOFF)) - 1] if fails else 1)
        with _LOCK:
            if _STREAMS.get(self.node) is self:
                _STREAMS.pop(self.node, None)
            last = _LAST.get(self.node)
            if last:
                last["live"] = False

    def _once(self, n: dict) -> bool:
        """One connection, held until it ends. True when it heard the node at all."""
        name, title, ents, heard = n["name"], n.get("title") or n["name"], {}, False
        try:
            sse = _SSE(n)
        except Exception as e:
            self._down(name, _why(e))
            return False
        try:
            if sse.status != 200:
                self._down(name, "it wants a password (the user or password is wrong)" if sse.status == 401
                           else f"it answered {sse.status}: is web_server on in its YAML?")
                return False
            event, settled, last = "", False, time.time()
            while not self.stop.is_set():
                try:
                    # a short wait while the burst of every state comes in, then one ping's worth
                    line = sse.readline(QUIET if heard and not settled else 1.0)
                except (socket.timeout, TimeoutError):
                    if heard and not settled:
                        # the burst is over: this is what it has now
                        settled = True
                        _keep_shape(node(name) or n, title, list(ents.values()))
                    if time.time() - last > STREAM_IDLE:
                        break                                 # not even a ping: connect again
                    continue
                if line is None:
                    break
                last = time.time()
                if line.startswith("event:"):
                    event = line[6:].strip()
                    continue
                if not line.startswith("data:") or event not in ("ping", "state"):
                    continue
                try:
                    d = json.loads(line[5:].strip())
                except ValueError:
                    continue
                heard = True
                if event == "ping":
                    if isinstance(d, dict) and d.get("title"):
                        title = str(d["title"])[:60]
                elif isinstance(d, dict) and (e := _entity(d)):
                    key = f"{e['domain']}.{e['slug']}"
                    if key not in ents and len(ents) >= MAX_ENTITIES:
                        continue
                    prev = ents.get(key)
                    ents[key] = e
                    if prev is None or prev.get("value") != e.get("value"):
                        self._tell(name, title, e, prev)
                with _LOCK:
                    _LAST[name] = {"ok": True, "title": title, "entities": list(ents.values()), "at": time.time(),
                                   "heard": time.time(), "live": True}
                    _DOWN.pop(name, None)
        except Exception as e:
            self._down(name, _why(e))
        finally:
            sse.close()
        return heard

    def _tell(self, name, title, e, prev):
        if self.on_change:
            try:
                self.on_change(_event(name, title, e, prev))
            except Exception:
                pass

    def _down(self, name: str, why: str):
        with _LOCK:
            _LAST[name] = {**(_LAST.get(name) or {}), "ok": False, "error": why, "at": time.time(), "live": False}
            _DOWN[name] = time.time() + DOWN_S


def stream_sync(on_change) -> int:
    """Hold every node's stream open, and let go of the ones no longer kept. `on_change(event)`
    is called from the stream's thread for every change. Returns how many are held."""
    names = {n["name"] for n in nodes()}
    with _LOCK:
        for name in list(_STREAMS):
            if name not in names:
                _STREAMS.pop(name).stop.set()
        for name in names:
            st = _STREAMS.get(name)
            if not st or not st.is_alive() or st.stop.is_set():
                st = _STREAMS[name] = _Stream(name, on_change)
                st.start()
        return len(_STREAMS)


def stream_stop() -> None:
    with _LOCK:
        for st in _STREAMS.values():
            st.stop.set()
        _STREAMS.clear()


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

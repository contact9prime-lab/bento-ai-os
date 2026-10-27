"""Stand-in ESP32 nodes that speak ESPHome's own web server API and mDNS, for the tests and the
warehouse run. Nothing here is a real ESP32: it is the protocol ESPHome 2026.6's web_server
(and its mdns component) speaks, read from ESPHome's source, so espnodes.py talks to it exactly
as it would to a flashed board.

  GET  /events                          SSE: a "ping" with {title, comment, ...}, then a "state"
                                        event (detail all) for every entity, then changes
  GET  /{domain}/{name}[?detail=all]    one entity: {name_id, id, value, state[, domain, name, uom]}
  POST /{domain}/{name}/turn_on|turn_off|toggle   200, applied a moment later (ESPHome defers it)
  mDNS _esphomelib._tcp and _http._tcp  PTR + SRV + TXT (friendly_name, platform, board, mac) + A

Each node is a small physical model (a cold room warms with its door open and cools while its
compressor runs; a fan relay lowers the air temperature; dock doors open and close), so a chart
over minutes looks like a building, not noise. A control port serves /state (every node) and
/poke (open a door, break a compressor) for the run and the film.

    python esp_sim.py --layout warehouse --base 18600 [--mdns 18653] [--control 18699]
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import socket
import struct
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Entity:
    def __init__(self, domain, name, value, uom="", decimals=1, category=""):
        self.domain, self.name, self.value, self.uom, self.decimals = domain, name, value, uom, decimals
        self.category = category

    @property
    def object_id(self):
        return "".join(c if c.isalnum() else "_" for c in self.name.lower())

    def json(self, detail=True):
        d = {"name_id": f"{self.domain}/{self.name}", "id": f"{self.domain}-{self.object_id}"}
        v = self.value
        if self.domain == "sensor":
            d["value"] = None if v is None or (isinstance(v, float) and math.isnan(v)) else round(v, self.decimals)
            d["state"] = "NA" if d["value"] is None else f"{d['value']:.{self.decimals}f}" + (f" {self.uom}" if self.uom else "")
        elif self.domain in ("binary_sensor", "switch", "fan"):
            d["value"] = bool(v)
            d["state"] = "ON" if v else "OFF"
        elif self.domain == "light":
            d["value"] = "ON" if v else "OFF"
            d["state"] = "ON" if v else "OFF"
        else:
            d["value"] = str(v)
            d["state"] = str(v)
        if detail:
            d.update(domain=self.domain, name=self.name, entity_category=0 if not self.category else 1)
            if self.uom:
                d["uom"] = self.uom
        return d


class Node:
    """One ESP32: its entities and a tick that moves them like the room it is in."""

    def __init__(self, host, title, kind, port, mac, user="", password=""):
        self.host, self.title, self.kind, self.port, self.mac = host, title, kind, port, mac
        self.user, self.password = user, password
        self.ents: dict[str, Entity] = {}
        self.listeners: list = []
        self.lock = threading.Lock()
        self.t0 = time.time()
        getattr(self, "_make_" + kind)()

    def add(self, *a, **k):
        e = Entity(*a, **k)
        self.ents[f"{e.domain}/{e.name}"] = e
        return e

    # the rooms --------------------------------------------------------------------------------
    def _make_coldroom(self):
        self.add("sensor", "Cold room temperature", -18.4, "°C")
        self.add("sensor", "Humidity", 71.0, "%", 0)
        self.add("binary_sensor", "Cold room door", False)
        self.add("switch", "Compressor", True)
        self.add("sensor", "WiFi signal", -58.0, "dBm", 0, category="diagnostic")

    def _make_dock(self):
        for i in (1, 2, 3):
            self.add("binary_sensor", f"Dock door {i}", False)
        self.add("switch", "Dock lights", False)
        self.add("sensor", "Dock temperature", 14.2, "°C")
        self.add("sensor", "WiFi signal", -64.0, "dBm", 0, category="diagnostic")

    def _make_aisle(self):
        self.add("sensor", "Aisle temperature", 27.5, "°C")
        self.add("sensor", "Humidity", 52.0, "%", 0)
        self.add("switch", "Ceiling fan", False)
        self.add("binary_sensor", "Motion", False)
        self.add("sensor", "WiFi signal", -61.0, "dBm", 0, category="diagnostic")

    def _make_charger(self):
        self.add("sensor", "Charger power", 0.0, "W", 0)
        self.add("sensor", "Forklift battery", 64.0, "%", 0)
        self.add("switch", "Charger", False)
        self.add("sensor", "WiFi signal", -55.0, "dBm", 0, category="diagnostic")

    def tick(self, dt):
        """Move the room by dt seconds of the model. Returns the entities that changed."""
        g = lambda n: self.ents[n]         # noqa: E731
        changed = []
        with self.lock:
            if self.kind == "coldroom":
                t = g("sensor/Cold room temperature")
                door, comp = g("binary_sensor/Cold room door").value, g("switch/Compressor").value
                target = 4.0 if door else (-20.0 if comp else 6.0)
                rate = 0.05 if door else (0.012 if comp else 0.006)
                t.value += (target - t.value) * min(1, rate * dt) + random.uniform(-0.03, 0.03)
                h = g("sensor/Humidity")
                h.value += ((82 if door else 70) - h.value) * min(1, 0.02 * dt) + random.uniform(-0.2, 0.2)
                changed += [t, h]
            elif self.kind == "dock":
                t = g("sensor/Dock temperature")
                opened = sum(1 for i in (1, 2, 3) if g(f"binary_sensor/Dock door {i}").value)
                t.value += ((14 + 4 * opened) - t.value) * min(1, 0.01 * dt) + random.uniform(-0.03, 0.03)
                changed.append(t)
            elif self.kind == "aisle":
                t = g("sensor/Aisle temperature")
                fan = g("switch/Ceiling fan").value
                hour = (time.time() / 3600) % 24
                warm = 27 + 4 * math.sin((hour - 9) / 24 * 2 * math.pi)
                t.value += ((warm - 4.5 if fan else warm) - t.value) * min(1, 0.01 * dt) + random.uniform(-0.03, 0.03)
                h = g("sensor/Humidity")
                h.value += ((46 if fan else 54) - h.value) * min(1, 0.01 * dt) + random.uniform(-0.2, 0.2)
                m = g("binary_sensor/Motion")
                if random.random() < 0.04 * dt:
                    m.value = not m.value
                    changed.append(m)
                changed += [t, h]
            elif self.kind == "charger":
                on = g("switch/Charger").value
                b, p = g("sensor/Forklift battery"), g("sensor/Charger power")
                p.value = (1450 + random.uniform(-30, 30)) if on and b.value < 100 else 0.0
                b.value = min(100.0, b.value + (0.08 * dt if on else -0.01 * dt))
                changed += [b, p]
            for e in self.ents.values():
                if e.name == "WiFi signal" and random.random() < 0.05 * dt:
                    e.value = max(-80, min(-40, e.value + random.choice((-1, 1))))
                    changed.append(e)
        return changed

    def act(self, key, action):
        e = self.ents[key]
        with self.lock:
            e.value = (not e.value) if action == "toggle" else (action == "turn_on")
        self.push([e])

    def push(self, ents):
        for q in list(self.listeners):
            for e in ents:
                q.append(("state", json.dumps(e.json(True))))


def handler_for(node: Node):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _auth(self):
            if not node.user:
                return True
            want = "Basic " + base64.b64encode(f"{node.user}:{node.password}".encode()).decode()
            if self.headers.get("Authorization") == want:
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Login Required"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _match(self):
            u = urllib.parse.urlsplit(self.path)
            parts = [urllib.parse.unquote(p) for p in u.path.strip("/").split("/")]
            if len(parts) < 2:
                return None, None, u
            key = f"{parts[0]}/{parts[1]}"
            return (key if key in node.ents else None), (parts[2] if len(parts) > 2 else ""), u

        def do_GET(self):
            if not self._auth():
                return
            if self.path.startswith("/events"):
                return self._events()
            key, action, u = self._match()
            if not key or action:
                return self._send(404)
            detail = urllib.parse.parse_qs(u.query).get("detail") == ["all"]
            with node.lock:
                body = json.dumps(node.ents[key].json(detail)).encode()
            self._send(200, body)

        def do_POST(self):
            if not self._auth():
                return
            key, action, _ = self._match()
            dom = key.split("/")[0] if key else ""
            if not key or dom not in ("switch", "light", "fan") or action not in ("turn_on", "turn_off", "toggle"):
                return self._send(404)
            threading.Timer(0.08, node.act, (key, action)).start()     # ESPHome defers it to its loop
            self._send(200)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            q: list = []

            def emit(ev, data):
                self.wfile.write(f"event: {ev}\ndata: {data}\n\n".encode())
                self.wfile.flush()
            try:
                emit("ping", json.dumps({"title": node.title, "comment": "", "ota": True, "log": True, "lang": "en",
                                         "uptime": int(time.time() - node.t0)}))
                with node.lock:
                    snap = [json.dumps(e.json(True)) for e in node.ents.values()]
                for d in snap:
                    emit("state", d)
                node.listeners.append(q)
                last_ping = time.time()
                while True:
                    while q:
                        emit(*q.pop(0))
                    if time.time() - last_ping > 10:
                        emit("ping", "{}")
                        last_ping = time.time()
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                if q in node.listeners:
                    node.listeners.remove(q)
            self.close_connection = True
    return H


# ---- mDNS: answer the two questions espnodes.discover asks ---------------------------------

def _name(n: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".") if p) + b"\0"


def _rr(name, rtype, rdata, ttl=120):
    return _name(name) + struct.pack("!HHIH", rtype, 0x8001, ttl, len(rdata)) + rdata


def _txt(d: dict) -> bytes:
    out = b""
    for k, v in d.items():
        s = f"{k}={v}".encode()[:255]
        out += bytes([len(s)]) + s
    return out


def mdns_answer(nodes: list[Node]) -> bytes:
    recs = []
    for n in nodes:
        hn = f"{n.host_name}.local"
        api, web = f"{n.host_name}._esphomelib._tcp.local", f"{n.host_name}._http._tcp.local"
        recs.append(_rr("_esphomelib._tcp.local", 12, _name(api)))
        recs.append(_rr("_http._tcp.local", 12, _name(web)))
        recs.append(_rr(api, 33, struct.pack("!HHH", 0, 0, 6053) + _name(hn)))
        recs.append(_rr(web, 33, struct.pack("!HHH", 0, 0, n.port) + _name(hn)))
        recs.append(_rr(api, 16, _txt({"friendly_name": n.title, "version": "2026.6.5", "mac": n.mac.replace(":", ""),
                                        "platform": "ESP32", "board": "esp32dev", "network": "wifi"})))
        recs.append(_rr(hn, 1, socket.inet_aton(n.host)))
    return struct.pack("!6H", 0, 0x8400, 0, len(recs), 0, 0) + b"".join(recs)


def mdns_loop(port: int, nodes: list[Node]):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    while True:
        data, addr = s.recvfrom(9000)
        if b"_esphomelib" in data or b"\x05_http" in data:
            s.sendto(mdns_answer(nodes), addr)


# ---- the layouts -----------------------------------------------------------------------------

LAYOUTS = {
    # zone -> [(node host name, friendly name, kind)]
    "warehouse": {
        "zone-cold": [("cold-1", "Cold room A", "coldroom"), ("cold-2", "Cold room B", "coldroom")],
        "zone-dock": [("dock-1", "Loading dock", "dock"), ("charge-1", "Forklift bay", "charger")],
        "zone-aisle": [("aisle-1", "Aisles 1-6", "aisle"), ("aisle-2", "Aisles 7-12", "aisle")],
    },
    "one": {"zone": [("cold-1", "Cold room A", "coldroom"), ("dock-1", "Loading dock", "dock")]},
}


def build(layout: str, base: int, auth: dict | None = None, zone: str = "") -> list[Node]:
    nodes, port = [], base
    for z, specs in LAYOUTS[layout].items():
        if zone and z != zone:
            continue
        for i, (hn, title, kind) in enumerate(specs):
            mac = "a4:cf:12:%02x:%02x:%02x" % (len(nodes) + 1, port % 256, (port // 256) % 256)
            u, p = (auth or {}).get(hn, ("", ""))
            n = Node("127.0.0.1", title, kind, port, mac, u, p)
            n.host_name, n.zone = hn, z
            nodes.append(n)
            port += 1
    return nodes


def serve(nodes: list[Node], mdns: int = 0, control: int = 0, speed: float = 1.0):
    for n in nodes:
        srv = ThreadingHTTPServer((n.host, n.port), handler_for(n))
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    if mdns:
        threading.Thread(target=mdns_loop, args=(mdns, nodes), daemon=True).start()

    def physics():
        last = time.time()
        while True:
            time.sleep(0.5)
            now = time.time()
            for n in nodes:
                n.push(n.tick((now - last) * speed))
            last = now
    threading.Thread(target=physics, daemon=True).start()
    if control:
        by = {n.host_name: n for n in nodes}

        class C(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _ok(self, d):
                b = json.dumps(d).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                self._ok({n.host_name: {"title": n.title, "zone": n.zone, "kind": n.kind, "port": n.port,
                                        "ents": {e.name: e.value for e in n.ents.values()}} for n in nodes})

            def do_POST(self):
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                n = by[d["node"]]
                e = next(e for e in n.ents.values() if e.name == d["entity"])
                with n.lock:
                    e.value = d["value"]
                n.push([e])
                self._ok({"ok": True})
        srv = ThreadingHTTPServer(("127.0.0.1", control), C)
        threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="warehouse", choices=sorted(LAYOUTS))
    ap.add_argument("--base", type=int, default=18600)
    ap.add_argument("--mdns", type=int, default=0)
    ap.add_argument("--control", type=int, default=0)
    ap.add_argument("--speed", type=float, default=1.0, help="model seconds per real second")
    ap.add_argument("--zone", default="", help="only this zone's nodes (a zone Pi's own network)")
    a = ap.parse_args()
    nodes = build(a.layout, a.base, zone=a.zone)
    serve(nodes, a.mdns, a.control, a.speed)
    for n in nodes:
        print(f"{n.zone:<11} {n.host_name:<9} {n.title:<14} http://{n.host}:{n.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()

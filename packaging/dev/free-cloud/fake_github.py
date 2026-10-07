"""A stand-in for the part of GitHub's REST API that keep.py uses: secret gists.

Modelled on the real one where it matters: the API truncates a file's `content` over
1 MB and the full text is at `raw_url`; listing gists returns files without content;
a PATCH with a file set to null deletes it; a bad key is a 401. Used by
tests/test_keep.py (in a thread) and by run.sh (as the container's GitHub).

    python fake_github.py 9303         # serves http://0.0.0.0:9303, key: good-token
"""
import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

TOKEN = "good-token"
TRUNC = 1 << 20
GISTS: dict = {}
LOG: list = []


def _file(gid, name, content, base, full=True):
    out = {"filename": name, "size": len(content), "raw_url": f"{base}/raw/{gid}/{name}"}
    if full:
        out["truncated"] = len(content) > TRUNC
        out["content"] = content[:TRUNC]
    return out


def _gist(g, base, full=True):
    return {"id": g["id"], "description": g["description"], "public": g["public"],
            "html_url": f"https://gist.github.com/fake/{g['id']}", "updated_at": g["updated_at"],
            "files": {n: _file(g["id"], n, c, base, full) for n, c in g["files"].items()}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _base(self):
        return f"http://{self.headers.get('Host')}"

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self):
        return self.headers.get("Authorization", "") == f"Bearer {TOKEN}"

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlsplit(self.path)
        LOG.append({"m": "GET", "p": u.path, "at": time.time()})
        if u.path == "/log":
            return self._send(200, {"log": LOG[-200:], "gists": {k: {"files": {n: len(c) for n, c in g["files"].items()},
                                                                    "description": g["description"]}
                                                                for k, g in GISTS.items()}})
        if u.path.startswith("/raw/"):
            _, _, gid, name = u.path.split("/", 3)
            g = GISTS.get(gid)
            if not g or name not in g["files"]:
                return self._send(404, {"message": "Not Found"})
            return self._send(200, g["files"][name].encode(), "text/plain; charset=utf-8")
        if not self._authed():
            return self._send(401, {"message": "Bad credentials"})
        if u.path == "/gists":
            q = dict(p.split("=", 1) for p in (u.query or "").split("&") if "=" in p)
            per, page = int(q.get("per_page", 30)), int(q.get("page", 1))
            items = sorted(GISTS.values(), key=lambda g: g["updated_at"], reverse=True)
            return self._send(200, [_gist(g, self._base(), False) for g in items[(page - 1) * per: page * per]])
        if u.path.startswith("/gists/"):
            g = GISTS.get(u.path.split("/")[2])
            return self._send(200, _gist(g, self._base())) if g else self._send(404, {"message": "Not Found"})
        self._send(404, {"message": "Not Found"})

    def do_POST(self):
        LOG.append({"m": "POST", "p": self.path, "at": time.time()})
        if not self._authed():
            return self._send(401, {"message": "Bad credentials"})
        b = self._body()
        gid = uuid.uuid4().hex[:20]
        GISTS[gid] = {"id": gid, "description": b.get("description", ""), "public": bool(b.get("public")),
                      "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + f".{time.time_ns()}",
                      "files": {n: f["content"] for n, f in (b.get("files") or {}).items() if f}}
        self._send(201, _gist(GISTS[gid], self._base()))

    def do_PATCH(self):
        LOG.append({"m": "PATCH", "p": self.path, "at": time.time()})
        if not self._authed():
            return self._send(401, {"message": "Bad credentials"})
        g = GISTS.get(self.path.split("/")[2])
        if not g:
            return self._send(404, {"message": "Not Found"})
        for n, f in (self._body().get("files") or {}).items():
            if f is None:
                g["files"].pop(n, None)
            else:
                g["files"][n] = f["content"]
        g["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + f".{time.time_ns()}"
        self._send(200, _gist(g, self._base()))


def serve(port: int = 0) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    s = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9303)
    print(f"fake GitHub on :{s.server_address[1]}", flush=True)
    threading.Event().wait()

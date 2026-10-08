# ruff: noqa  -- a test stand-in
"""A stand-in for an S3-compatible storage service, stdlib only.

The subset keep.py uses (ListObjectsV2 with paging, GET and PUT of an object) plus the
three refusals a person meets (a key the service does not know, a signature that does not
match, a bucket that does not exist), each with S3's own error codes. Every request's
Signature Version 4 is CHECKED, with a verifier written apart from keep.py's signer, so a
wrong signature fails here the way it fails at Backblaze or Cloudflare.

    python fake_s3.py PORT            # serves bucket `bento-test` for KEY_ID / SECRET
"""
import hashlib
import hmac
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, quote, unquote, urlsplit

KEY_ID = "test-key-id"
SECRET = "test-secret/with+odd=chars"
BUCKETS = {"bento-test": {}}
PAGE = 2            # small, so the caller's paging is exercised
LOG = []


def _err(code, status, msg=""):
    body = f"<?xml version='1.0' encoding='UTF-8'?><Error><Code>{code}</Code><Message>{msg}</Message></Error>"
    return status, body.encode()


def _check(method, raw_path, headers, payload):
    auth = headers.get("authorization", "")
    m = re.match(r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8})/([^/]+)/s3/aws4_request, "
                 r"SignedHeaders=([^,]+), Signature=([0-9a-f]{64})$", auth)
    if not m:
        return _err("AccessDenied", 403, "no signature")
    key_id, day, region, signed, sig = m.groups()
    if key_id != KEY_ID:
        return _err("InvalidAccessKeyId", 403)
    claimed = headers.get("x-amz-content-sha256", "")
    if claimed != hashlib.sha256(payload).hexdigest():
        return _err("XAmzContentSHA256Mismatch", 400)
    u = urlsplit(raw_path)
    q = sorted((quote(k, safe="-_.~"), quote(v, safe="-_.~")) for k, v in parse_qsl(u.query, keep_blank_values=True))
    names = signed.split(";")
    canon = "\n".join([method, quote(unquote(u.path), safe="/-_.~"), "&".join(f"{a}={b}" for a, b in q),
                       "".join(f"{n}:{' '.join(headers.get(n, '').split())}\n" for n in names), signed, claimed])
    stamp = headers.get("x-amz-date", "")
    sts = f"AWS4-HMAC-SHA256\n{stamp}\n{day}/{region}/s3/aws4_request\n{hashlib.sha256(canon.encode()).hexdigest()}"
    k = ("AWS4" + SECRET).encode()
    for part in (day, region, "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(hmac.new(k, sts.encode(), hashlib.sha256).hexdigest(), sig):
        return _err("SignatureDoesNotMatch", 403)
    return None


def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status, body=b"", ctype="application/xml"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _go(self, method):
        n = int(self.headers.get("content-length") or 0)
        payload = self.rfile.read(n) if n else b""
        headers = {k.lower(): v for k, v in self.headers.items()}
        if self.path == "/__log":            # for the end-to-end run's report, unsigned
            import json
            return self._send(200, json.dumps({"log": LOG[-200:], "objects": {
                b: {k: len(v) for k, v in o.items()} for b, o in BUCKETS.items()}}).encode(), "application/json")
        LOG.append({"m": method, "p": self.path, "bytes": len(payload)})
        bad = _check(method, self.path, headers, payload)
        if bad:
            return self._send(*bad)
        u = urlsplit(self.path)
        bucket, _, key = unquote(u.path).lstrip("/").partition("/")
        if bucket not in BUCKETS:
            return self._send(*_err("NoSuchBucket", 404))
        objs = BUCKETS[bucket]
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        if method == "GET" and not key:
            keys = sorted(k for k in objs if k.startswith(q.get("prefix", "")))
            start = int(q.get("continuation-token") or 0)
            page = keys[start:start + PAGE]
            more = start + PAGE < len(keys)
            body = ("<?xml version='1.0' encoding='UTF-8'?><ListBucketResult>"
                    + "".join(f"<Contents><Key>{_xml(k)}</Key><Size>{len(objs[k])}</Size></Contents>" for k in page)
                    + f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>"
                    + (f"<NextContinuationToken>{start + PAGE}</NextContinuationToken>" if more else "")
                    + "</ListBucketResult>")
            return self._send(200, body.encode())
        if method == "GET":
            if key not in objs:
                return self._send(*_err("NoSuchKey", 404))
            return self._send(200, objs[key], "application/octet-stream")
        if method == "PUT":
            objs[key] = payload
            return self._send(200, b"")
        return self._send(*_err("NotImplemented", 501))

    def do_GET(self):
        self._go("GET")

    def do_PUT(self):
        self._go("PUT")


def serve(port=0):
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 9303), H)
    print(f"fake S3 on :{srv.server_address[1]}, bucket bento-test", flush=True)
    srv.serve_forever()

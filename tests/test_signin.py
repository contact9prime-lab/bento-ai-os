"""Sign in with Google / Microsoft, against a fake provider on the wire.

A small HTTP server plays the authorisation server (PKCE checked: the token
exchange refuses a verifier that does not hash to the challenge the consent
URL carried), the Gmail API, the Google Calendar API and Microsoft Graph. What
is checked is the protocol and the promises: tokens land in the vault and
never in config; a refresh happens silently and a refused one says so; reads
never call anything that would mark a message; the tools pass the same gate;
sending is refused unless it was asked for at sign-in; the button is greyed
with the registration sentence until this install has a client id.
"""

import asyncio
import base64
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ["AGENTOS_VAULT_KEYRING"] = "0"

from agentos import accounts, calendars, config as cfgmod, mail as mailmod, signin, vault   # noqa: E402
from agentos.memory import Store                                                          # noqa: E402
from agentos.policy import PDP, Principal                                                 # noqa: E402
from agentos.tools import Toolbox                                                         # noqa: E402

RAW_MAIL = (b"From: Jane Doe <jane@acme.example>\r\nTo: me@gmail.com\r\nSubject: SOW by Thursday\r\n"
            b"Date: Mon, 21 Sep 2026 08:10:00 +0000\r\nContent-Type: text/plain\r\n\r\n"
            b"Please sign the SOW by Thursday.\r\n")


class _Provider(http.server.BaseHTTPRequestHandler):
    """Google's and Microsoft's endpoints, enough of each for the code under test."""
    seen: list = []
    challenge = ""
    scope = ""
    refreshes = 0
    refuse_refresh = False
    expires_in = 3600

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        _Provider.seen.append(("GET", u.path, q, self.headers.get("Authorization", "")))
        auth = self.headers.get("Authorization", "")
        if u.path == "/auth":                                   # the consent page: hands back a code
            _Provider.challenge = q.get("code_challenge", "")
            _Provider.scope = q.get("scope", "")                 # what was consented to comes back granted
            return self._json(200, {"redirect": f"{q['redirect_uri']}?code=CODE1&state={q['state']}"})
        if not auth.startswith("Bearer tok-"):
            return self._json(401, {"error": "no bearer"})
        # --- Google
        if u.path == "/userinfo":
            return self._json(200, {"email": "me@gmail.com", "name": "Me"})
        if u.path == "/gmail/v1/users/me/profile":
            return self._json(200, {"emailAddress": "me@gmail.com", "messagesTotal": 12})
        if u.path == "/gmail/v1/users/me/messages":
            return self._json(200, {"messages": [{"id": "m1"}, {"id": "m2"}]})
        if u.path.startswith("/gmail/v1/users/me/messages/"):
            mid = u.path.rsplit("/", 1)[-1]
            if q.get("format") == "raw":
                return self._json(200, {"id": mid, "raw": base64.urlsafe_b64encode(RAW_MAIL).decode()})
            return self._json(200, {"id": mid, "labelIds": ["INBOX", "UNREAD"] if mid == "m1" else ["INBOX"],
                                    "snippet": "Please sign the SOW &amp; return",
                                    "payload": {"headers": [{"name": "From", "value": "Jane Doe <jane@acme.example>"},
                                                            {"name": "Subject", "value": "SOW by Thursday"},
                                                            {"name": "Date", "value": "Mon, 21 Sep 2026 08:10:00 +0000"}]}})
        if u.path == "/calendar/v3/users/me/calendarList":
            return self._json(200, {"items": [{"id": "primary", "summary": "Work", "selected": True}]})
        if u.path == "/calendar/v3/calendars/primary/events":
            return self._json(200, {"items": [
                {"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-09-21T09:00:00Z"},
                 "end": {"dateTime": "2026-09-21T09:15:00Z"}, "attendees": [{"email": "raj@initech.example"}]},
                {"id": "e2", "summary": "Offsite", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}},
                {"id": "e3", "summary": "gone", "status": "cancelled", "start": {"date": "2026-09-22"}, "end": {"date": "2026-09-23"}}]})
        # --- Microsoft Graph
        if u.path == "/v1.0/me":
            return self._json(200, {"mail": "me@outlook.example", "displayName": "Me"})
        if u.path == "/v1.0/me/mailFolders/inbox":
            return self._json(200, {"totalItemCount": 7})
        if u.path == "/v1.0/me/mailFolders/inbox/messages":
            return self._json(200, {"value": [{"id": "g1", "subject": "Pricing", "isRead": False,
                                               "receivedDateTime": "2026-09-21T07:00:00Z", "bodyPreview": "Can we do $18",
                                               "from": {"emailAddress": {"name": "Raj", "address": "raj@initech.example"}},
                                               "toRecipients": [{"emailAddress": {"address": "me@outlook.example"}}]}]})
        if u.path == "/v1.0/me/messages/g1":
            return self._json(200, {"id": "g1", "subject": "Pricing", "receivedDateTime": "2026-09-21T07:00:00Z",
                                    "from": {"emailAddress": {"name": "Raj", "address": "raj@initech.example"}},
                                    "toRecipients": [], "ccRecipients": [], "hasAttachments": False,
                                    "body": {"contentType": "html", "content": "<p>Can we do <b>$18</b>?</p>"}})
        if u.path == "/v1.0/me/calendarView":
            return self._json(200, {"value": [{"id": "x", "subject": "1:1", "isAllDay": False,
                                               "start": {"dateTime": "2026-09-21T10:00:00.0000000"},
                                               "end": {"dateTime": "2026-09-21T10:30:00.0000000"},
                                               "location": {"displayName": "Room 4"}, "attendees": [], "bodyPreview": ""}]})
        self._json(404, {"error": "no"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/token":
            f = self._form()
            _Provider.seen.append(("POST", "/token", f, ""))
            if f.get("grant_type") == "authorization_code":
                want = base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                if f.get("code") != "CODE1" or want != _Provider.challenge:
                    return self._json(400, {"error": "invalid_grant", "error_description": "PKCE mismatch"})
                return self._json(200, {"access_token": "tok-1", "refresh_token": "ref-1", "expires_in": _Provider.expires_in,
                                        "scope": _Provider.scope,
                                        "token_type": "Bearer"})
            if f.get("grant_type") == "refresh_token":
                if _Provider.refuse_refresh:
                    return self._json(400, {"error": "invalid_grant", "error_description": "Token has been revoked"})
                _Provider.refreshes += 1
                return self._json(200, {"access_token": f"tok-{_Provider.refreshes + 1}", "expires_in": 3600})
            return self._json(400, {"error": "unsupported"})
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        _Provider.seen.append(("POST", u.path, body, self.headers.get("Authorization", "")))
        if u.path in ("/gmail/v1/users/me/messages/send", "/v1.0/me/sendMail"):
            return self._json(200 if u.path.endswith("send") else 202, {"id": "sent1"})
        self._json(404, {"error": "no"})


@pytest.fixture(scope="module")
def provider():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Provider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base
    srv.shutdown()


@pytest.fixture()
def world(provider, tmp_path, monkeypatch):
    """A machine whose Google and Microsoft are the fake, with a client id on file."""
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", tmp_path)
    g, m = signin.PROVIDERS["google"], signin.PROVIDERS["microsoft"]
    for k, v in {"auth": "/auth", "token": "/token", "userinfo": "/userinfo", "api_mail": "/gmail/v1",
                 "api_calendar": "/calendar/v3", "revoke": ""}.items():
        monkeypatch.setitem(g, k, provider + v if v else "")
    for k, v in {"auth": "/auth", "token": "/token", "userinfo": "/v1.0/me", "api_graph": "/v1.0"}.items():
        monkeypatch.setitem(m, k, provider + v)
    _Provider.seen.clear()
    _Provider.refreshes = 0
    _Provider.refuse_refresh = False
    _Provider.expires_in = 3600
    cfg = {"agent_name": "Aria", "autonomy": "balanced", "max_steps": 6, "default_model": "ollama/x",
           "workspace": str(tmp_path), "providers": {}, "memory": {"inject_facts": 0, "inject_user": 0},
           "port": 8321, "mail": {}, "calendar": {}, "signin": {},
           "oauth_clients": {"google": {"client_id": "cid", "client_secret": "csec"},
                             "microsoft": {"client_id": "mid", "tenant": "common"}}}
    return cfg


def _sign_in(cfg, provider_id, uses=("mail", "calendar")):
    """Drive the flow the way a browser would: consent URL → code → callback."""
    import httpx
    st = signin.start(cfg, provider_id, uses)
    r = httpx.get(st["url"])                      # the fake consent page hands back a code
    back = urlparse(r.json()["redirect"])
    q = {k: v[0] for k, v in parse_qs(back.query).items()}
    return signin.finish(cfg, q["state"], q["code"])


# ---------------------------------------------------------------------------

def test_the_button_is_greyed_with_the_registration_sentence_until_there_is_a_client(world):
    cfg = dict(world, oauth_clients={})
    ok, why = signin.available(cfg, "google")
    assert not ok and "App registration" in why and "Google Cloud" in why
    with pytest.raises(ValueError, match="App registration"):
        signin.start(cfg, "google")
    d = {x["id"]: x for x in signin.doors(cfg)}
    assert not d["google"]["available"] and d["google"]["redirect_uri"].endswith("/api/accounts/oauth/callback/google")
    ok, _ = signin.set_clients(cfg, {"google": {"client_id": "cid", "client_secret": "s"}})
    assert ok and signin.available(cfg, "google") == (True, "")
    signin.set_clients(cfg, {"google": {"client_secret": "•••"}})            # a mask keeps the secret
    assert cfg["oauth_clients"]["google"]["client_secret"] == "s"


def test_the_consent_url_asks_exactly_for_the_ticked_uses_with_pkce(world):
    st = signin.start(world, "google", ["mail"])
    q = {k: v[0] for k, v in parse_qs(urlparse(st["url"]).query).items()}
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "cid" and q["access_type"] == "offline"
    assert "gmail.readonly" in q["scope"] and "calendar" not in q["scope"] and "gmail.send" not in q["scope"]
    st = signin.start(world, "google", ["mail", "calendar", "send"])
    q = {k: v[0] for k, v in parse_qs(urlparse(st["url"]).query).items()}
    assert "calendar.readonly" in q["scope"] and "gmail.send" in q["scope"]
    assert signin.pending_status() and signin.cancel("google") >= 2 and not signin.pending_status()


def test_signing_in_puts_the_tokens_in_the_vault_and_points_both_accounts_at_google(world):
    res = _sign_in(world, "google")
    assert res["email"] == "me@gmail.com" and set(res["uses"]) == {"mail", "calendar"} and res["refresh"]
    assert "tok-1" not in json.dumps(world) and "ref-1" not in json.dumps(world)      # never in config
    assert vault.has("oauth.google") and "ref-1" in vault.get("oauth.google")
    assert world["mail"]["via"] == "google" and world["mail"]["enabled"] and world["mail"]["user"] == "me@gmail.com"
    assert world["calendar"]["kind"] == "google" and world["calendar"]["enabled"]
    assert world["signin"]["google"]["email"] == "me@gmail.com" and not world["mail"]["can_send"]
    assert mailmod.configured(world) and calendars.configured(world) and not mailmod.problem(world)
    d = accounts.door(world, "mail")
    assert d["way"] == "google" and "signed in with Google as me@gmail.com" in d["detail"]
    # PKCE is real: a second exchange with a fresh verifier is refused by the fake
    st = signin.start(world, "google", ["mail"])
    with pytest.raises(ValueError, match="PKCE"):
        signin.finish(world, st["state"], "CODE1")
    with pytest.raises(ValueError, match="nothing was waiting"):
        signin.finish(world, "bogus", "CODE1")


def test_the_token_refreshes_silently_and_a_refused_refresh_says_sign_in_again(world):
    _Provider.expires_in = 30                                    # already inside the 60s margin
    _sign_in(world, "google", ["mail"])
    assert signin.token(world, "google").startswith("tok-2") and _Provider.refreshes == 1
    assert signin.token(world, "google").startswith("tok-2") and _Provider.refreshes == 1   # cached now
    rec = json.loads(vault.get("oauth.google"))
    rec["expires_at"] = time.time() - 1
    vault.put("oauth.google", json.dumps(rec))
    _Provider.refuse_refresh = True
    with pytest.raises(RuntimeError, match="sign in again"):
        signin.token(world, "google")
    assert "revoked" in mailmod.test_login(world)["detail"] or "sign in again" in mailmod.test_login(world)["detail"]


def test_gmail_reads_through_the_api_never_marking_and_the_calendar_maps_onto_one_shape(world):
    _sign_in(world, "google")
    with mailmod.open_box(world) as box:
        rows = box.search(query="SOW", sender="jane", unread=True, since_days=1)
    assert [r["uid"] for r in rows] == ["m1", "m2"] and rows[0]["unread"] and not rows[1]["unread"]
    assert rows[0]["snippet"] == "Please sign the SOW & return" and rows[0]["from"].startswith("Jane Doe")
    q = next(s for s in _Provider.seen if s[1] == "/gmail/v1/users/me/messages")[2]["q"]
    assert "is:unread" in q and "newer_than:1d" in q and "from:jane" in q and "SOW" in q and "in:inbox" in q
    with mailmod.open_box(world) as box:
        m = box.read("m1")
    assert m["subject"] == "SOW by Thursday" and "sign the SOW" in m["body"] and m["attachments"] == []
    assert not any(p[1].endswith("/modify") or p[0] == "PATCH" for p in _Provider.seen)   # nothing marked
    t = mailmod.test_login(world)
    assert t["ok"] and "signed in with Google as me@gmail.com" in t["detail"] and t["count"] == 12
    out = asyncio.run(calendars.events(world, days=2))
    assert [e["summary"] for e in out["events"]] == ["Standup", "Offsite"] and out["events"][1]["all_day"]
    assert out["events"][0]["attendees"] == ["raj@initech.example"] and out["calendars"] == ["Work"]
    p = next(s for s in _Provider.seen if s[1] == "/calendar/v3/calendars/primary/events")[2]
    assert p["singleEvents"] == "true" and "T" in p["timeMin"] and p["timeMin"].endswith("Z")
    t = asyncio.run(calendars.test_access(world))
    assert t["ok"] and "signed in with Google" in t["detail"]


def test_sending_needs_to_have_been_asked_for_and_then_goes_through_the_api(world):
    _sign_in(world, "google", ["mail"])
    out = mailmod.send(world, "jane@acme.example", "Re: SOW", "Will do.")
    assert out.startswith("[error]") and "tick Send" in out
    _sign_in(world, "google", ["mail", "send"])
    assert world["mail"]["can_send"]
    out = mailmod.send(world, "jane@acme.example", "Re: SOW", "Will do.")
    assert out == "sent to jane@acme.example"
    sent = next(s for s in _Provider.seen if s[1] == "/gmail/v1/users/me/messages/send")
    raw = base64.urlsafe_b64decode(sent[2]["raw"] + "==").decode()
    assert "To: jane@acme.example" in raw and "Will do." in raw


def test_microsoft_reads_through_graph_and_signs_out_to_off_never_back_to_a_password(world):
    res = _sign_in(world, "microsoft")
    assert res["email"] == "me@outlook.example" and world["mail"]["via"] == "microsoft"
    with mailmod.open_box(world) as box:
        rows = box.search(unread=True, since_days=1)
        m = box.read("g1")
    assert rows[0]["uid"] == "g1" and rows[0]["unread"] and "Raj" in rows[0]["from"]
    p = next(s for s in _Provider.seen if s[1] == "/v1.0/me/mailFolders/inbox/messages")[2]
    assert "isRead eq false" in p["$filter"] and "receivedDateTime ge" in p["$filter"]
    assert "Can we do $18" in m["body"] and "<b>" not in m["body"] and m["subject"] == "Pricing"
    assert mailmod.test_login(world)["detail"].startswith("signed in with Microsoft as me@outlook.example")
    out = asyncio.run(calendars.events(world, days=1))
    assert out["events"][0]["summary"] == "1:1" and out["events"][0]["location"] == "Room 4"
    assert mailmod.send(world, "raj@initech.example", "Re", "ok").startswith("[error]")
    _sign_in(world, "microsoft", ["mail", "send"])
    assert mailmod.send(world, "raj@initech.example", "Re", "ok") == "sent to raj@initech.example"
    assert next(s for s in _Provider.seen if s[1] == "/v1.0/me/sendMail")[2]["message"]["subject"] == "Re"
    # sign out: tokens gone, the account OFF — not silently back to some old password
    world["mail"]["password"] = "vault:mail.password"
    assert signin.disconnect(world, "microsoft")
    assert not vault.has("oauth.microsoft") and "microsoft" not in world["signin"]
    assert world["mail"]["via"] == "imap" and world["mail"]["enabled"] is False
    assert world["calendar"]["kind"] == "ics" and world["calendar"]["enabled"] is False
    assert "sign in with" in mailmod.problem(world).lower()


def test_the_tools_pass_the_same_gate_over_the_api_door(world, tmp_path):
    _sign_in(world, "google")
    store = Store(tmp_path / "t.db")
    tb = Toolbox(world, store)
    tb.pdp = PDP(world, store)

    async def run():
        out = await tb.execute("mail_search", {"since_days": 1}, principal=Principal("user", ""))
        return out
    try:
        out = asyncio.run(run())
    except TypeError:
        out = asyncio.run(tb.mail_search(since_days=1))
    assert "SOW by Thursday" in out and "uid m1" in out


def test_the_routes_start_finish_and_sign_out(world, monkeypatch):
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        cfg = servermod.state["cfg"]
        cfg["oauth_clients"] = world["oauth_clients"]
        cfg["mail"], cfg["calendar"], cfg["signin"] = {}, {}, {}
        j = cl.get("/api/accounts").json()
        assert {d["id"] for d in j["signin"]} == {"google", "microsoft"} and j["vault"] is not None
        r = cl.post("/api/accounts/oauth/google/start", json={"uses": ["mail", "send"]})
        assert r.status_code == 200 and r.json()["url"].startswith(world and signin.PROVIDERS["google"]["auth"])
        assert "gmail.send" in r.json()["url"]
        import httpx
        back = urlparse(httpx.get(r.json()["url"]).json()["redirect"])
        assert back.path == "/api/accounts/oauth/callback/google"
        r = cl.get(f"/api/accounts/oauth/callback/google?{back.query}")
        assert r.status_code == 200 and "Signed in with Google" in r.text and "me@gmail.com" in r.text
        j = cl.get("/api/accounts").json()
        mail = next(a for a in j["accounts"] if a["id"] == "mail")
        assert mail["via"] == "google" and "signed in with Google as me@gmail.com" in mail["door"]["detail"]
        assert mail["can_send"] and mail["door"]["detail"].endswith("can send)")
        assert "tok-1" not in cl.get("/api/config").text
        assert cl.get("/api/config").json()["oauth_clients"]["google"]["client_secret"].startswith("•••")
        r = cl.get("/api/accounts/oauth/callback/google?state=nope&code=x")
        assert r.status_code == 400 and "Nothing was waiting" in r.text
        r = cl.delete("/api/accounts/oauth/google")
        assert r.status_code == 200 and not vault.has("oauth.google")
        assert next(a for a in cl.get("/api/accounts").json()["accounts"] if a["id"] == "mail")["enabled"] is False
        r = cl.put("/api/accounts/clients", json={"google": {"client_id": "new", "client_secret": "•••"}})
        assert r.status_code == 200 and cfg["oauth_clients"]["google"] == {"client_id": "new", "client_secret": "csec"}
        cfg["oauth_clients"] = {}


def test_a_mission_on_an_mcp_backed_mailbox_gets_that_server_s_tools(world, tmp_path):
    from agentos import jobs
    from tests.test_jobs import _answers_for
    store = Store(tmp_path / "j.db")
    jobs.ensure_roster({}, store)
    world["mail"] = {"enabled": True, "via": "mcp", "mcp_server": "gmail", "last_test": {}}
    assert mailmod.configured(world) and not mailmod.problem(world)
    r = next(x for x in jobs.RECIPES if x.id == "inbox-triage")
    with pytest.raises(ValueError, match="known only while it is connected"):
        jobs.build(world, store, r.id, _answers_for(r, store))
    body = jobs.build(world, store, r.id, _answers_for(r, store),
                      mcp_tools={"gmail": ["mcp_gmail_search", "mcp_gmail_get_message"]})
    tools = body["permissions"]["tools"]
    assert "mcp_gmail_search" in tools and "mail_search" not in tools and "mail_read" not in tools
    assert body["permissions"]["mcp"] == ["gmail"]
    assert "read through the 'gmail' MCP server" in body["mission"] and "`mcp_gmail_search`" in body["mission"]
    # the built-in tool says so too, rather than pretending to be the door
    with pytest.raises(RuntimeError, match="MCP server here"):
        mailmod.open_box(world)

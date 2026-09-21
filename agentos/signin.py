"""Sign in with Google / Microsoft: the account door that asks for nothing to type.

The first Accounts card asked for an IMAP host, a port and an app password —
the 2005 way in, and the one every provider is closing. What a person expects
in 2026 is the button: *Sign in with Google*, a consent page that names what
this machine will be able to read, and a revocable grant that shows up in
their Google account's list of connected apps. This module is that button.

- **OAuth 2.0 with PKCE, run by this OS itself.** The consent page opens where
  the human is (the UI opens it if one is watching; a terminal prints the URL;
  a phone driving a headless box finishes it from the phone — the callback is
  an ordinary route, reachable at `mcp_oauth.redirect_base()`, the same setting
  the MCP Store's sign-ins use). The code comes back, the token exchange
  happens here, and what it yields goes in the VAULT — never config.
- **One sign-in, the uses you tick.** Mail, calendar, and — separately, never
  by default — sending. The scopes asked for are exactly those; the consent
  page shows them; `signed_in()` records which were granted, so the card can
  say "reads mail and calendar" in the account's own words.
- **The client id is this install's, and it ships EMPTY.** Google and Microsoft
  hand out an OAuth client per application; a self-hosted OS has no central
  application. `BUILTIN_CLIENTS` is empty for the same reason
  `appregistry.BUILTIN_KEYS` is: a credential the project would have to keep on
  a build machine. The owner registers one (five minutes, `docs/accounts.md`
  walks it) and pastes it in Settings → Accounts → App registration; until
  then the button is greyed with that sentence and the app-password door still
  works. A button that opened a consent page for an app that does not exist
  would be the dead control the honesty rules forbid.

Tokens are refreshed silently (`token()`), read from and written back to the
vault, and revoked with the sign-in (`disconnect()`), so "Sign out" means the
next click asks again. Kept free of asyncio: `bento mail signin google` runs
the same code.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from . import vault

#: What each provider needs to be asked, and where. Endpoints are module data so a
#: test can point them at a fake authorisation server; nothing here is secret.
PROVIDERS = {
    "google": {
        "label": "Google",
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "revoke": "https://oauth2.googleapis.com/revoke",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "api_mail": "https://gmail.googleapis.com/gmail/v1",
        "api_calendar": "https://www.googleapis.com/calendar/v3",
        "scopes": {"identity": ["openid", "email"],
                   "mail": ["https://www.googleapis.com/auth/gmail.readonly"],
                   "send": ["https://www.googleapis.com/auth/gmail.send"],
                   "calendar": ["https://www.googleapis.com/auth/calendar.readonly"]},
        "extra_auth": {"access_type": "offline", "prompt": "consent",
                       "include_granted_scopes": "true"},
        # Google's "Desktop app" client type issues a client secret and wants it at
        # the exchange; Google documents it as not actually secret for installed apps.
        "needs_secret": True,
        "register": "https://console.cloud.google.com/apis/credentials",
        "hint": ("Google Cloud → APIs & Services → Credentials → Create OAuth client "
                 "(Desktop app), enable the Gmail and Google Calendar APIs, and paste the "
                 "client id and secret here. While the app is in Testing, add your own "
                 "address under Audience → Test users."),
    },
    "microsoft": {
        "label": "Microsoft",
        "auth": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "revoke": "",
        "userinfo": "https://graph.microsoft.com/v1.0/me",
        "api_graph": "https://graph.microsoft.com/v1.0",
        "scopes": {"identity": ["openid", "email", "offline_access", "User.Read"],
                   "mail": ["Mail.Read"], "send": ["Mail.Send"], "calendar": ["Calendars.Read"]},
        "extra_auth": {"response_mode": "query"},
        "needs_secret": False,             # a public client with PKCE, as Microsoft documents
        "register": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "hint": ("Microsoft Entra → App registrations → New: 'Accounts in any organizational "
                 "directory and personal Microsoft accounts', platform 'Mobile and desktop', "
                 "redirect URI as shown here, and 'Allow public client flows' on. Paste the "
                 "Application (client) ID."),
    },
}

USES = ("mail", "calendar", "send")

# Support switch, like AGENTOS_EXEC_TRACE: AGENTOS_SIGNIN_BASE=http://127.0.0.1:8427
# points every provider endpoint at one host, so a whole sign-in can be walked
# through against a fake Google on loopback. Never set in production — and if it
# is, `doors()` says so on the card.
_FAKE_BASE = os.environ.get("AGENTOS_SIGNIN_BASE", "").rstrip("/")
if _FAKE_BASE:
    from urllib.parse import urlparse as _up
    for _p in PROVIDERS.values():
        for _k, _v in list(_p.items()):
            if isinstance(_v, str) and _v.startswith("https://"):
                _u = _up(_v)
                _p[_k] = _FAKE_BASE + _u.path

#: Ships empty — see the module docstring. Config's `oauth_clients` fills it in.
BUILTIN_CLIENTS = {"google": {"client_id": "", "client_secret": ""},
                   "microsoft": {"client_id": "", "tenant": "common"}}

AUTH_TIMEOUT = 600.0      # a person may have to log in and pick an account first
_pending: dict[str, dict] = {}


# ---- who can sign in here ---------------------------------------------------------

def client(cfg: dict, provider: str) -> dict:
    base = dict(BUILTIN_CLIENTS.get(provider) or {})
    base.update({k: v for k, v in ((cfg or {}).get("oauth_clients") or {}).get(provider, {}).items()
                 if v not in (None, "")})
    return base


def available(cfg: dict, provider: str) -> tuple[bool, str]:
    """Can this install open a consent page for this provider — and if not, the
    sentence that would fix it. Decided by what is configured, never assumed."""
    p = PROVIDERS.get(provider)
    if not p:
        return False, f"no sign-in called '{provider}'"
    c = client(cfg, provider)
    if not c.get("client_id"):
        return False, (f"Sign in with {p['label']} needs an OAuth client for this install — "
                       f"Settings → Accounts → App registration. {p['hint']}")
    if p.get("needs_secret") and not c.get("client_secret"):
        return False, (f"Sign in with {p['label']} needs the client secret that came with "
                       f"the client id — Settings → Accounts → App registration.")
    return True, ""


def redirect_uri(provider: str) -> str:
    from . import mcp_oauth
    return f"{mcp_oauth.redirect_base()}/api/accounts/oauth/callback/{provider}"


def _fill(url: str, cfg: dict, provider: str) -> str:
    return url.replace("{tenant}", client(cfg, provider).get("tenant") or "common")


# ---- the flow -----------------------------------------------------------------------

def start(cfg: dict, provider: str, uses: list[str] | tuple[str, ...] = ("mail", "calendar"),
          uid: str = "") -> dict:
    """The consent URL, and a pending entry the callback resolves. `uid` is whose
    vault the tokens will land in — the callback arrives in another request."""
    ok, why = available(cfg, provider)
    if not ok:
        raise ValueError(why)
    p = PROVIDERS[provider]
    uses = [u for u in uses if u in USES] or ["mail"]
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    scopes = list(p["scopes"]["identity"])
    for u in uses:
        scopes += p["scopes"][u]
    q = {"client_id": client(cfg, provider)["client_id"], "redirect_uri": redirect_uri(provider),
         "response_type": "code", "scope": " ".join(scopes), "state": state,
         "code_challenge": challenge, "code_challenge_method": "S256", **p.get("extra_auth", {})}
    url = _fill(p["auth"], cfg, provider) + "?" + urlencode(q)
    _pending[state] = {"provider": provider, "verifier": verifier, "uses": uses, "uid": uid or "",
                       "started": time.time(), "url": url}
    _sweep()
    return {"url": url, "state": state, "provider": provider, "uses": uses}


def pending_for(state: str) -> dict | None:
    return _pending.get(state)


def pending_status() -> list[dict]:
    _sweep()
    return [{"provider": v["provider"], "uses": v["uses"], "waiting_for": int(time.time() - v["started"]),
             "url": v["url"]} for v in _pending.values()]


def cancel(provider: str) -> int:
    gone = [s for s, v in _pending.items() if v["provider"] == provider]
    for s in gone:
        _pending.pop(s, None)
    return len(gone)


def _sweep() -> None:
    now = time.time()
    for s in [s for s, v in _pending.items() if now - v["started"] > AUTH_TIMEOUT]:
        _pending.pop(s, None)


def finish(cfg: dict, state: str, code: str, error: str = "") -> dict:
    """The callback's half: exchange the code, learn who signed in, put the tokens in
    the vault and point the accounts at this provider. Runs in the signer's context
    (the route enters `users.as_user(pending['uid'])`)."""
    pend = _pending.pop(state, None)
    if not pend:
        raise ValueError("nothing was waiting for this sign-in — it may have timed out; start again")
    provider = pend["provider"]
    # the attempt that finished is the one that counts: an earlier click's entry
    # would otherwise read as "waiting for you" under a card that says signed in
    for s_, v in list(_pending.items()):
        if v["provider"] == provider:
            _pending.pop(s_, None)
    p = PROVIDERS[provider]
    if error:
        raise ValueError(f"{p['label']} refused the sign-in: {error}")
    if not code:
        raise ValueError(f"{p['label']} sent no code back")
    c = client(cfg, provider)
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(provider),
            "client_id": c["client_id"], "code_verifier": pend["verifier"]}
    if c.get("client_secret"):
        data["client_secret"] = c["client_secret"]
    with httpx.Client(timeout=30.0) as cl:
        r = cl.post(_fill(p["token"], cfg, provider), data=data,
                    headers={"Accept": "application/json"})
        if r.status_code != 200:
            raise ValueError(f"the token exchange failed ({r.status_code}): {_err(r)}")
        tok = r.json()
        access = tok.get("access_token") or ""
        who = _identity(cl, provider, access) if access else {}
    if not access:
        raise ValueError(f"{p['label']} answered without an access token")
    granted = tok.get("scope") or ""
    record = {"access_token": access, "refresh_token": tok.get("refresh_token") or "",
              "expires_at": time.time() + float(tok.get("expires_in") or 3600),
              "scope": granted, "token_type": tok.get("token_type") or "Bearer"}
    vault.put(f"oauth.{provider}", json.dumps(record))
    uses = [u for u in pend["uses"] if _granted(p, u, granted)] if granted else list(pend["uses"])
    email = who.get("email") or who.get("mail") or who.get("userPrincipalName") or ""
    cfg.setdefault("signin", {})[provider] = {"email": email, "uses": uses, "at": time.time(),
                                             "name": who.get("name") or who.get("displayName") or ""}
    _point_accounts(cfg, provider, email, uses)
    return {"provider": provider, "email": email, "uses": uses,
            "refresh": bool(record["refresh_token"])}


def _granted(p: dict, use: str, granted: str) -> bool:
    want = set(p["scopes"][use])
    have = set(granted.split())
    return bool(want & have) or want <= have


def _identity(cl: httpx.Client, provider: str, access: str) -> dict:
    try:
        r = cl.get(PROVIDERS[provider]["userinfo"], headers={"Authorization": f"Bearer {access}"})
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _err(r: httpx.Response) -> str:
    try:
        j = r.json()
        return str(j.get("error_description") or j.get("error") or r.text)[:200]
    except Exception:
        return r.text[:200]


def _point_accounts(cfg: dict, provider: str, email: str, uses: list[str]) -> None:
    """After a sign-in the accounts read THROUGH it. A use that was not granted
    leaves that account alone — an unticked calendar keeps its ICS address."""
    from . import calendars as calmod
    from . import mail as mailmod
    if "mail" in uses or "send" in uses:
        m = cfg.setdefault("mail", {})
        for k, v in mailmod.DEFAULTS.items():
            m.setdefault(k, v)
        m.update({"via": provider, "user": email or m.get("user", ""), "enabled": True,
                  "last_test": {}, "can_send": "send" in uses})
    if "calendar" in uses:
        cal = cfg.setdefault("calendar", {})
        for k, v in calmod.DEFAULTS.items():
            cal.setdefault(k, v)
        cal.update({"kind": provider, "enabled": True, "last_test": {},
                    "name": cal.get("name") or email})


def doors(cfg: dict) -> list[dict]:
    """Per provider: can this install open its consent page, who is signed in and
    for what, and the registration sentence when it cannot — the card's data."""
    out = []
    for pid, p in PROVIDERS.items():
        ok, why = available(cfg, pid)
        rec = signed_in(cfg, pid)
        out.append({"id": pid, "label": p["label"], "available": ok, "why": why,
                    "fake": _FAKE_BASE or "",
                    "register": p["register"], "hint": p["hint"], "redirect_uri": redirect_uri(pid),
                    "needs_secret": bool(p.get("needs_secret")),
                    "client_id": client(cfg, pid).get("client_id", ""),
                    "has_secret": bool(client(cfg, pid).get("client_secret")),
                    "tenant": client(cfg, pid).get("tenant", "") if pid == "microsoft" else "",
                    "signed_in": rec, "uses": USES})
    return out


def set_clients(cfg: dict, patch: dict) -> tuple[bool, str]:
    """Settings → Accounts → App registration. A masked secret ("•••") keeps the
    one on file, as every other masked field on this OS does."""
    clients = cfg.setdefault("oauth_clients", {})
    for pid, vals in (patch or {}).items():
        if pid not in PROVIDERS or not isinstance(vals, dict):
            return False, f"no sign-in called '{pid}'"
        c = clients.setdefault(pid, dict(BUILTIN_CLIENTS.get(pid) or {}))
        for k in ("client_id", "client_secret", "tenant"):
            if k in vals:
                v = str(vals[k] or "").strip()
                if k == "client_secret" and v.startswith("•••"):
                    continue
                c[k] = v
    return True, "saved"


# ---- the token, kept fresh ----------------------------------------------------------

def signed_in(cfg: dict, provider: str) -> dict:
    """Who is signed in with this provider, and for what — the card's sentence. It is
    the recorded fact of a sign-in, not the token: the token is in the vault."""
    rec = dict(((cfg or {}).get("signin") or {}).get(provider) or {})
    if rec and not vault.has(f"oauth.{provider}"):
        rec["problem"] = "the sign-in's tokens are gone from the vault — sign in again"
    return rec


def token(cfg: dict, provider: str, actor: str = "") -> str:
    """A valid access token, refreshed when it is about to expire. '' when there
    is no sign-in; raises when a refresh is refused (the sign-in was revoked), with
    the sentence that says so."""
    raw = vault.get(f"oauth.{provider}", actor=actor or provider)
    if not raw:
        return ""
    try:
        rec = json.loads(raw)
    except ValueError:
        return ""
    if rec.get("access_token") and time.time() < float(rec.get("expires_at") or 0) - 60:
        return rec["access_token"]
    if not rec.get("refresh_token"):
        raise RuntimeError(f"the {PROVIDERS[provider]['label']} sign-in has expired and cannot "
                           "be refreshed — sign in again in Settings → Accounts")
    p = PROVIDERS[provider]
    c = client(cfg, provider)
    data = {"grant_type": "refresh_token", "refresh_token": rec["refresh_token"],
            "client_id": c["client_id"]}
    if c.get("client_secret"):
        data["client_secret"] = c["client_secret"]
    if provider == "microsoft":
        data["scope"] = rec.get("scope") or ""
    with httpx.Client(timeout=30.0) as cl:
        r = cl.post(_fill(p["token"], cfg, provider), data=data, headers={"Accept": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"{p['label']} refused to refresh the sign-in ({_err(r)}) — it may "
                           "have been revoked; sign in again in Settings → Accounts")
    tok = r.json()
    rec["access_token"] = tok.get("access_token") or rec["access_token"]
    rec["expires_at"] = time.time() + float(tok.get("expires_in") or 3600)
    if tok.get("refresh_token"):
        rec["refresh_token"] = tok["refresh_token"]
    vault.put(f"oauth.{provider}", json.dumps(rec))
    return rec["access_token"]


def disconnect(cfg: dict, provider: str) -> bool:
    """Sign out: revoke where the provider offers it, drop the tokens, and turn the
    accounts that read through this sign-in off — never silently back to a
    password that may be years stale."""
    p = PROVIDERS.get(provider) or {}
    raw = vault.get(f"oauth.{provider}", actor="sign-out")
    if raw and p.get("revoke"):
        try:
            rec = json.loads(raw)
            with httpx.Client(timeout=15.0) as cl:
                cl.post(p["revoke"], data={"token": rec.get("refresh_token") or rec.get("access_token")})
        except Exception:
            pass
    existed = vault.forget(f"oauth.{provider}")
    (cfg.get("signin") or {}).pop(provider, None)
    m = cfg.get("mail") or {}
    if m.get("via") == provider:
        m.update({"via": "imap", "enabled": False, "last_test": {}, "can_send": False})
    cal = cfg.get("calendar") or {}
    if cal.get("kind") == provider:
        cal.update({"kind": "ics", "enabled": False, "last_test": {}})
    return existed


def auth_header(cfg: dict, provider: str, actor: str = "") -> dict:
    t = token(cfg, provider, actor=actor)
    if not t:
        raise RuntimeError(f"not signed in with {PROVIDERS[provider]['label']} — Settings → Accounts")
    return {"Authorization": f"Bearer {t}"}

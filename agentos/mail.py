"""Mail: one IMAP account, read for the agent — and, gated apart, sent from.

Why IMAP and not a vendor API. Gmail, Outlook, iCloud, Fastmail, Proton (via its
bridge), a self-hosted Dovecot — every one of them speaks IMAP, and every one of
them issues an app password without registering an OAuth application with
anybody. One door, no vendor SDK, nothing to renew. The cost is honest: an app
password is a real credential, stored in the person's own config (mail is a
USER_KEY), masked on every read, and never handed to the model — the tools
below are the only way in, and each call is a `mail.read` decision in the ledger.

What it does NOT do, on purpose:

- **It never marks anything read.** Every fetch is `BODY.PEEK`: the agent reading
  your inbox must not change what your inbox looks like to you.
- **It never deletes, moves or flags.** There is no tool for it. A mission that
  "tidies" a mailbox is one that loses a message somebody needed.
- **Sending is its own action** (`mail.send`), risky, and in ALWAYS_ASK: even at
  full autonomy a send confirms unless a person wrote a grant for it. No recipe
  grants it. A draft reply belongs in the report, not in somebody's inbox.

Everything here is synchronous (imaplib and smtplib are), and the tools run it in
a thread. Kept free of HTTP and asyncio so `bento mail` works with the server
down.
"""

from __future__ import annotations

import base64
import email
import email.header
import email.utils
import html
import imaplib
import re
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage

import httpx

#: Well-known hosts, so "set up Gmail" is one choice and not four fields. The
#: `hint` is the sentence that stops the commonest failure: pasting the account
#: password where an app password is required.
PRESETS = {
    "gmail": {"label": "Gmail / Google Workspace",
              "host": "imap.gmail.com", "port": 993,
              "smtp_host": "smtp.gmail.com", "smtp_port": 587,
              "hint": "Use an APP PASSWORD, not your Google password: "
                      "myaccount.google.com → Security → 2-Step Verification → App passwords. "
                      "IMAP must be on in Gmail → Settings → Forwarding and POP/IMAP."},
    "outlook": {"label": "Outlook / Microsoft 365",
                "host": "outlook.office365.com", "port": 993,
                "smtp_host": "smtp.office365.com", "smtp_port": 587,
                "hint": "Personal accounts: an app password from account.microsoft.com → "
                        "Security. Work accounts often have basic IMAP disabled by the "
                        "admin — if sign-in fails with a right password, that is why."},
    "icloud": {"label": "iCloud Mail",
               "host": "imap.mail.me.com", "port": 993,
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587,
               "hint": "An app-specific password from appleid.apple.com → Sign-In and "
                       "Security → App-Specific Passwords. The user name is the full "
                       "iCloud address."},
    "fastmail": {"label": "Fastmail",
                 "host": "imap.fastmail.com", "port": 993,
                 "smtp_host": "smtp.fastmail.com", "smtp_port": 465,
                 "hint": "An app password from Settings → Privacy & Security → "
                         "Integrations → New app password, with Mail access."},
    "custom": {"label": "Another IMAP server", "host": "", "port": 993,
               "smtp_host": "", "smtp_port": 587,
               "hint": "The IMAP host and port from your provider; SMTP is only needed "
                       "if you ever grant sending."},
}

DEFAULTS = {"enabled": False, "via": "imap", "preset": "", "host": "", "port": 993, "user": "",
            "password": "", "smtp_host": "", "smtp_port": 587, "from": "", "can_send": False,
            "mcp_server": "",
            # TLS from the first byte (IMAPS). None = decide by port: 143 is the
            # plain/STARTTLS port, everything else is assumed IMAPS. A test server
            # on loopback sets it False explicitly.
            "ssl": None,
            "last_test": {}}

SNIPPET = 240            # chars of body shown in a search row
BODY_LIMIT = 12_000      # chars of body a read returns — a newsletter is not a mission
MAX_RESULTS = 50


def conf(cfg: dict) -> dict:
    """The mail section with its secret RESOLVED — config holds `vault:mail.password`,
    the mailbox needs the bytes. Only the code that opens the mailbox calls this;
    `accounts.state()` reads the raw section and never sees the password."""
    from . import vault
    c = {**DEFAULTS, **((cfg or {}).get("mail") or {})}
    c["password"] = vault.resolve(c.get("password", ""), actor="mail")
    return c


VIAS = ("imap", "google", "microsoft", "mcp")


def via(cfg: dict) -> str:
    v = str(((cfg or {}).get("mail") or {}).get("via") or "imap")
    return v if v in VIAS else "imap"


def configured(cfg: dict) -> bool:
    """Is there a door at all — a sign-in, a chosen MCP server, or the three IMAP
    fields. Decided from the raw section: a reference counts as a password."""
    c = {**DEFAULTS, **((cfg or {}).get("mail") or {})}
    v = via(cfg)
    if v in ("google", "microsoft"):
        from . import signin
        return bool(signin.signed_in(cfg, v)) and not signin.signed_in(cfg, v).get("problem")
    if v == "mcp":
        return bool(c.get("mcp_server"))
    return bool(c["host"] and c["user"] and c["password"])


def problem(cfg: dict) -> str:
    """'' when mail can be read here, else the sentence that would fix it."""
    c = {**DEFAULTS, **((cfg or {}).get("mail") or {})}
    v = via(cfg)
    if not configured(cfg):
        if v in ("google", "microsoft"):
            from . import signin
            rec = signin.signed_in(cfg, v)
            return (f"The {signin.PROVIDERS[v]['label']} sign-in needs redoing: {rec['problem']} — "
                    "Settings → Accounts → Mail." if rec.get("problem") else
                    f"Needs a mail account — Settings → Accounts → Mail (Sign in with "
                    f"{signin.PROVIDERS[v]['label']}).")
        if v == "mcp":
            return "Mail is set to read through an MCP server, but none is chosen — Settings → Accounts → Mail."
        return ("Needs a mail account — Settings → Accounts → Mail (sign in with Google or "
                "Microsoft, or an app password for any other provider).")
    if not c.get("enabled", True):
        return "Mail is set up but switched off — Settings → Accounts → Mail."
    lt = c.get("last_test") or {}
    if lt and not lt.get("ok"):
        return f"The last sign-in failed: {lt.get('detail', 'unknown error')} — Settings → Accounts → Mail."
    return ""


def guess_preset(user: str, host: str = "") -> str:
    """Which preset an address or host belongs to, or ''."""
    s = f"{user} {host}".lower()
    if "gmail" in s or "googlemail" in s or "google" in s:
        return "gmail"
    if "outlook" in s or "office365" in s or "hotmail" in s or "live.com" in s:
        return "outlook"
    if "icloud" in s or "me.com" in s or "mac.com" in s:
        return "icloud"
    if "fastmail" in s:
        return "fastmail"
    return ""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _dec(value) -> str:
    """A header, decoded whatever RFC 2047 did to it."""
    if not value:
        return ""
    try:
        parts = email.header.decode_header(str(value))
    except Exception:
        return str(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return " ".join(" ".join(out).split())


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def _html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>", "\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = "\n".join(_WS.sub(" ", ln).strip() for ln in s.splitlines())
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def _body_of(msg) -> tuple[str, list[str]]:
    """(text, attachment names). text/plain preferred; HTML stripped otherwise."""
    plain, htmls, attachments = [], [], []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        disp = str(part.get("Content-Disposition") or "")
        fname = part.get_filename()
        if fname or "attachment" in disp.lower():
            attachments.append(_dec(fname) or ctype)
            continue
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
        except Exception:
            continue
        (plain if ctype == "text/plain" else htmls).append(text)
    if plain:
        return "\n".join(plain).strip(), attachments
    if htmls:
        return _html_to_text("\n".join(htmls)), attachments
    return "", attachments


def _imap_date(days: int) -> str:
    t = time.localtime(time.time() - max(0, int(days)) * 86400)
    return time.strftime("%d-%b-%Y", t)


def _quote(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_box(cfg: dict):
    """The mailbox behind whichever door is configured, with one shape: `search`,
    `read`, `folders`, usable as a context manager. The tools and the CLI never
    know which it was."""
    v = via(cfg)
    if v == "google":
        return GmailBox(cfg)
    if v == "microsoft":
        return GraphBox(cfg)
    if v == "mcp":
        raise RuntimeError(f"mail reads through the '{(cfg.get('mail') or {}).get('mcp_server')}' MCP "
                           "server here — its tools are the mailbox, not mail_search")
    return Mailbox(conf(cfg))


class _ApiBox:
    """What the two API mailboxes share: a bearer from the sign-in, an httpx client,
    the same context-manager shape as the IMAP box."""
    provider = ""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cl = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *a):
        self.close()

    def connect(self):
        from . import signin
        self.cl = httpx.Client(timeout=30.0, headers={**signin.auth_header(self.cfg, self.provider, actor="mail"),
                                                      "Accept": "application/json"})
        return self

    def close(self):
        if self.cl is not None:
            self.cl.close()
            self.cl = None

    def _get(self, url: str, **params) -> dict:
        r = self.cl.get(url, params={k: v for k, v in params.items() if v not in (None, "")})
        if r.status_code == 401:
            raise RuntimeError("the sign-in was refused by the server — sign in again in Settings → Accounts")
        if r.status_code == 403:
            raise RuntimeError("the sign-in does not cover this (the scope was not granted) — "
                               "sign in again and tick Mail")
        r.raise_for_status()
        return r.json()


class GmailBox(_ApiBox):
    """Gmail over its REST API. Reading uses `format=full` and never touches labels,
    so nothing is marked read — the PEEK rule, kept by not calling `modify`."""
    provider = "google"

    def _base(self) -> str:
        from . import signin
        return signin.PROVIDERS["google"]["api_mail"] + "/users/me"

    def folders(self) -> list[str]:
        j = self._get(self._base() + "/labels")
        return [lb.get("name", "") for lb in j.get("labels", [])]

    def search(self, query: str = "", sender: str = "", unread: bool = False,
               since_days: int = 7, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        q = []
        if folder and folder.upper() != "INBOX":
            q.append(f"label:{folder}")
        else:
            q.append("in:inbox")
        if unread:
            q.append("is:unread")
        if since_days is not None and int(since_days) >= 0:
            q.append(f"newer_than:{max(1, int(since_days))}d")
        if sender:
            q.append(f"from:{sender}")
        if query:
            q.append(query)
        j = self._get(self._base() + "/messages", q=" ".join(q),
                      maxResults=max(1, min(int(limit or 20), MAX_RESULTS)))
        out = []
        for m in j.get("messages", []) or []:
            row = self._head(m["id"])
            if row:
                out.append(row)
        return out

    def _head(self, mid: str) -> dict | None:
        j = self._get(self._base() + f"/messages/{mid}", format="metadata",
                      metadataHeaders=["From", "To", "Cc", "Subject", "Date"])
        h = {x["name"].lower(): x["value"] for x in (j.get("payload") or {}).get("headers", [])}
        return {"uid": j["id"], "from": h.get("from", ""), "to": h.get("to", ""),
                "subject": h.get("subject") or "(no subject)", "date": h.get("date", ""),
                "unread": "UNREAD" in (j.get("labelIds") or []),
                "snippet": html.unescape(j.get("snippet", ""))[:SNIPPET]}

    def read(self, uid: str, folder: str = "INBOX") -> dict:
        j = self._get(self._base() + f"/messages/{uid}", format="raw")
        raw = base64.urlsafe_b64decode(j.get("raw", "") + "==")
        msg = email.message_from_bytes(raw)
        body, attachments = _body_of(msg)
        cut = len(body) > BODY_LIMIT
        return {"uid": str(uid), "folder": folder,
                "from": _dec(msg.get("From")), "to": _dec(msg.get("To")),
                "cc": _dec(msg.get("Cc")), "subject": _dec(msg.get("Subject")) or "(no subject)",
                "date": _dec(msg.get("Date")), "body": body[:BODY_LIMIT] + ("\n[…cut]" if cut else ""),
                "attachments": attachments}

    def send(self, msg: EmailMessage) -> str:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        r = self.cl.post(self._base() + "/messages/send", json={"raw": raw})
        if r.status_code == 403:
            return "[error] the Google sign-in does not allow sending — sign in again and tick Send"
        r.raise_for_status()
        return f"sent to {msg['To']}"


class GraphBox(_ApiBox):
    """Outlook / Microsoft 365 over Microsoft Graph. Reads only `/me/messages`;
    nothing here calls PATCH, so isRead is never touched."""
    provider = "microsoft"

    def _base(self) -> str:
        from . import signin
        return signin.PROVIDERS["microsoft"]["api_graph"] + "/me"

    def folders(self) -> list[str]:
        j = self._get(self._base() + "/mailFolders", **{"$top": 50})
        return [f.get("displayName", "") for f in j.get("value", [])]

    def search(self, query: str = "", sender: str = "", unread: bool = False,
               since_days: int = 7, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        url = self._base() + (f"/mailFolders/{folder}/messages" if folder and folder.upper() != "INBOX"
                              else "/mailFolders/inbox/messages")
        params = {"$top": max(1, min(int(limit or 20), MAX_RESULTS)),
                  "$select": "id,from,toRecipients,subject,receivedDateTime,isRead,bodyPreview",
                  "$orderby": "receivedDateTime desc"}
        filt = []
        if unread:
            filt.append("isRead eq false")
        if since_days is not None and int(since_days) >= 0:
            since = (time.time() - max(1, int(since_days)) * 86400)
            filt.append("receivedDateTime ge " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(since)))
        if sender:
            filt.append(f"contains(from/emailAddress/address,'{sender}')")
        if query:
            params["$search"] = f'"{query}"'
            params.pop("$orderby", None)       # Graph refuses $orderby with $search
        if filt and not query:
            params["$filter"] = " and ".join(filt)
        j = self._get(url, **params)
        out = []
        for m in j.get("value", []) or []:
            if query and filt:                 # $search cannot combine with $filter: apply here
                if unread and m.get("isRead"):
                    continue
            frm = (m.get("from") or {}).get("emailAddress") or {}
            out.append({"uid": m["id"], "from": f"{frm.get('name', '')} <{frm.get('address', '')}>".strip(),
                        "to": ", ".join((r.get("emailAddress") or {}).get("address", "")
                                        for r in m.get("toRecipients", [])),
                        "subject": m.get("subject") or "(no subject)", "date": m.get("receivedDateTime", ""),
                        "unread": not m.get("isRead", True),
                        "snippet": " ".join((m.get("bodyPreview") or "").split())[:SNIPPET]})
        return out

    def read(self, uid: str, folder: str = "INBOX") -> dict:
        j = self._get(self._base() + f"/messages/{uid}",
                      **{"$select": "id,from,toRecipients,ccRecipients,subject,receivedDateTime,body,hasAttachments"})
        frm = (j.get("from") or {}).get("emailAddress") or {}
        body = j.get("body") or {}
        text = _html_to_text(body.get("content", "")) if body.get("contentType", "").lower() == "html" \
            else body.get("content", "")
        cut = len(text) > BODY_LIMIT
        att = []
        if j.get("hasAttachments"):
            try:
                a = self._get(self._base() + f"/messages/{uid}/attachments", **{"$select": "name"})
                att = [x.get("name", "") for x in a.get("value", [])]
            except Exception:
                att = ["(attachments)"]
        return {"uid": str(uid), "folder": folder,
                "from": f"{frm.get('name', '')} <{frm.get('address', '')}>".strip(),
                "to": ", ".join((r.get("emailAddress") or {}).get("address", "") for r in j.get("toRecipients", [])),
                "cc": ", ".join((r.get("emailAddress") or {}).get("address", "") for r in j.get("ccRecipients", [])),
                "subject": j.get("subject") or "(no subject)", "date": j.get("receivedDateTime", ""),
                "body": text[:BODY_LIMIT] + ("\n[…cut]" if cut else ""), "attachments": att}

    def send(self, msg: EmailMessage) -> str:
        payload = {"message": {"subject": str(msg["Subject"] or ""),
                               "body": {"contentType": "Text", "content": msg.get_content()},
                               "toRecipients": [{"emailAddress": {"address": str(msg["To"])}}]},
                   "saveToSentItems": True}
        r = self.cl.post(self._base() + "/sendMail", json=payload)
        if r.status_code == 403:
            return "[error] the Microsoft sign-in does not allow sending — sign in again and tick Send"
        r.raise_for_status()
        return f"sent to {msg['To']}"


class Mailbox:
    """One IMAP connection, opened lazily, closed by `close()` or `with`."""

    def __init__(self, c: dict):
        self.c = c
        self.im = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *a):
        self.close()

    def connect(self):
        c = self.c
        port = int(c.get("port") or 993)
        timeout = 25
        use_ssl = c.get("ssl")
        if use_ssl is None:
            use_ssl = port != 143
        if use_ssl:
            self.im = imaplib.IMAP4_SSL(c["host"], port, timeout=timeout,
                                        ssl_context=ssl.create_default_context())
        else:
            self.im = imaplib.IMAP4(c["host"], port, timeout=timeout)
            if "STARTTLS" in (self.im.capabilities or ()):
                self.im.starttls(ssl.create_default_context())
        self.im.login(c["user"], c["password"])
        return self

    def close(self):
        if self.im is not None:
            try:
                self.im.logout()
            except Exception:
                pass
            self.im = None

    def folders(self) -> list[str]:
        typ, rows = self.im.list()
        out = []
        for row in rows or []:
            if not row:
                continue
            m = re.search(rb'(?:"([^"]*)"|(\S+))\s*$', row if isinstance(row, bytes) else row[0])
            if m:
                name = (m.group(1) or m.group(2) or b"").decode(errors="replace")
                out.append(name)
        return out

    def search(self, query: str = "", sender: str = "", unread: bool = False,
               since_days: int = 7, folder: str = "INBOX", limit: int = 20) -> list[dict]:
        """Headers plus a snippet for the newest matches. Never marks anything read."""
        typ, _ = self.im.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"no folder called '{folder}'")
        crit = []
        if unread:
            crit.append("UNSEEN")
        if since_days is not None and int(since_days) >= 0:
            crit += ["SINCE", _imap_date(int(since_days))]
        if sender:
            crit += ["FROM", _quote(sender)]
        if query:
            crit += ["TEXT", _quote(query)]
        if not crit:
            crit = ["ALL"]
        typ, data = self.im.uid("SEARCH", None, *crit)
        if typ != "OK":
            raise RuntimeError("the server refused the search")
        uids = (data[0] or b"").split()
        uids = uids[-max(1, min(int(limit or 20), MAX_RESULTS)):][::-1]     # newest first
        out = []
        for uid in uids:
            row = self._head(uid)
            if row:
                out.append(row)
        return out

    def _head(self, uid: bytes) -> dict | None:
        typ, data = self.im.uid(
            "FETCH", uid,
            "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID)] "
            "BODY.PEEK[TEXT]<0.2048>)")
        if typ != "OK" or not data:
            return None
        raw_head, raw_text, flags = b"", b"", b""
        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                meta, payload = item
                if b"HEADER" in meta:
                    raw_head = payload
                    flags = meta
                elif b"TEXT" in meta:
                    raw_text = payload
        msg = email.message_from_bytes(raw_head)
        snippet = _html_to_text(raw_text.decode(errors="replace"))
        snippet = re.sub(r"^(Content-[^\n]*\n)+", "", snippet).strip()
        return {"uid": uid.decode(), "from": _dec(msg.get("From")), "to": _dec(msg.get("To")),
                "subject": _dec(msg.get("Subject")) or "(no subject)",
                "date": _dec(msg.get("Date")), "unread": b"\\Seen" not in flags,
                "snippet": " ".join(snippet.split())[:SNIPPET]}

    def read(self, uid: str, folder: str = "INBOX") -> dict:
        typ, _ = self.im.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"no folder called '{folder}'")
        typ, data = self.im.uid("FETCH", str(uid).encode(), "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            raise RuntimeError(f"no message with uid {uid} in {folder}")
        msg = email.message_from_bytes(data[0][1])
        body, attachments = _body_of(msg)
        cut = len(body) > BODY_LIMIT
        return {"uid": str(uid), "folder": folder,
                "from": _dec(msg.get("From")), "to": _dec(msg.get("To")),
                "cc": _dec(msg.get("Cc")), "subject": _dec(msg.get("Subject")) or "(no subject)",
                "date": _dec(msg.get("Date")), "message_id": _dec(msg.get("Message-ID")),
                "body": body[:BODY_LIMIT] + (f"\n\n[… {len(body) - BODY_LIMIT} more chars]" if cut else ""),
                "attachments": attachments}


def test_login(cfg: dict) -> dict:
    """Sign in, count the inbox, sign out. The sentence a Settings card shows."""
    v = via(cfg)
    if v in ("google", "microsoft"):
        return _test_api(cfg, v)
    c = conf(cfg)
    if not (c["host"] and c["user"] and c["password"]):
        return {"ok": False, "detail": "host, user and password are all needed", "at": time.time()}
    try:
        with Mailbox(c) as mb:
            typ, data = mb.im.select('"INBOX"', readonly=True)
            n = int((data[0] or b"0").decode() or 0) if typ == "OK" else 0
        return {"ok": True, "detail": f"signed in as {c['user']} — {n} messages in INBOX",
                "at": time.time(), "count": n}
    except imaplib.IMAP4.error as e:
        text = str(e)
        hint = ""
        preset = c.get("preset") or guess_preset(c["user"], c["host"])
        if preset in PRESETS and "AUTHENTICATIONFAILED" in text.upper() or "Invalid credentials" in text:
            hint = " — " + PRESETS.get(preset, PRESETS["custom"])["hint"]
        return {"ok": False, "detail": f"sign-in refused: {text[:160]}{hint}", "at": time.time()}
    except (socket.gaierror, socket.timeout, ConnectionError, OSError) as e:
        return {"ok": False, "detail": f"could not reach {c['host']}:{c.get('port')}: {e}",
                "at": time.time()}
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200], "at": time.time()}


def _test_api(cfg: dict, provider: str) -> dict:
    """The probe for a signed-in account: who the server says we are, and how many
    messages it sees — the same shape of sentence the IMAP probe gives."""
    from . import signin
    label = signin.PROVIDERS[provider]["label"]
    try:
        with open_box(cfg) as box:
            if provider == "google":
                j = box._get(box._base() + "/profile")
                who, n = j.get("emailAddress", ""), int(j.get("messagesTotal") or 0)
                detail = f"signed in with Google as {who} — {n} messages"
            else:
                j = box._get(box._base() + "/mailFolders/inbox", **{"$select": "totalItemCount"})
                who = signin.signed_in(cfg, provider).get("email", "")
                n = int(j.get("totalItemCount") or 0)
                detail = f"signed in with Microsoft as {who} — {n} messages in Inbox"
        return {"ok": True, "detail": detail, "at": time.time(), "count": n}
    except (httpx.HTTPError, RuntimeError, ValueError) as e:
        return {"ok": False, "detail": f"{label}: {e}"[:220], "at": time.time()}
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200], "at": time.time()}


# ---------------------------------------------------------------------------
# Sending — its own action, never granted by a recipe
# ---------------------------------------------------------------------------

def send(cfg: dict, to: str, subject: str, body: str) -> str:
    """Send one plain-text message. Returns a sentence, '[error] …' on failure."""
    c = conf(cfg)
    to = str(to or "").strip()
    if not to or "@" not in to:
        return "[error] a recipient address is needed"
    v = via(cfg)
    if v in ("google", "microsoft"):
        if not c.get("can_send"):
            from . import signin
            return (f"[error] the {signin.PROVIDERS[v]['label']} sign-in reads mail and was not asked "
                    "to send — sign in again in Settings → Accounts and tick Send")
        msg = EmailMessage()
        msg["From"] = c.get("from") or c["user"]
        msg["To"] = to
        msg["Subject"] = str(subject or "")[:300]
        msg.set_content(str(body or ""))
        try:
            with open_box(cfg) as box:
                return box.send(msg)
        except Exception as e:                                      # noqa: BLE001
            return f"[error] send failed: {type(e).__name__}: {e}"[:300]
    if v == "mcp":
        return "[error] mail reads through an MCP server here; sending goes through that server's own tools"
    host = c.get("smtp_host") or ""
    if not host:
        preset = PRESETS.get(c.get("preset") or guess_preset(c["user"], c["host"]))
        host = (preset or {}).get("smtp_host", "")
        if not c.get("smtp_port") and preset:
            c["smtp_port"] = preset["smtp_port"]
    if not host:
        return "[error] no SMTP host is set for this account — Settings → Accounts → Mail"
    msg = EmailMessage()
    msg["From"] = c.get("from") or c["user"]
    msg["To"] = to
    msg["Subject"] = str(subject or "")[:300]
    msg.set_content(str(body or ""))
    port = int(c.get("smtp_port") or 587)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=25,
                                  context=ssl.create_default_context()) as s:
                s.login(c["user"], c["password"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=25) as s:
                s.ehlo()
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass
                s.login(c["user"], c["password"])
                s.send_message(msg)
    except Exception as e:                                          # noqa: BLE001
        return f"[error] send failed: {type(e).__name__}: {e}"[:300]
    return f"sent to {to}: {msg['Subject']}"

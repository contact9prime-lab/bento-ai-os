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

DEFAULTS = {"enabled": False, "preset": "", "host": "", "port": 993, "user": "",
            "password": "", "smtp_host": "", "smtp_port": 587, "from": "",
            # TLS from the first byte (IMAPS). None = decide by port: 143 is the
            # plain/STARTTLS port, everything else is assumed IMAPS. A test server
            # on loopback sets it False explicitly.
            "ssl": None,
            "last_test": {}}

SNIPPET = 240            # chars of body shown in a search row
BODY_LIMIT = 12_000      # chars of body a read returns — a newsletter is not a mission
MAX_RESULTS = 50


def conf(cfg: dict) -> dict:
    return {**DEFAULTS, **((cfg or {}).get("mail") or {})}


def configured(cfg: dict) -> bool:
    c = conf(cfg)
    return bool(c["host"] and c["user"] and c["password"])


def problem(cfg: dict) -> str:
    """'' when mail can be read here, else the sentence that would fix it."""
    c = conf(cfg)
    if not (c["host"] and c["user"] and c["password"]):
        return "Needs a mail account — Settings → Accounts → Mail (an app password, not your login password)."
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


# ---------------------------------------------------------------------------
# Sending — its own action, never granted by a recipe
# ---------------------------------------------------------------------------

def send(cfg: dict, to: str, subject: str, body: str) -> str:
    """Send one plain-text message. Returns a sentence, '[error] …' on failure."""
    c = conf(cfg)
    host = c.get("smtp_host") or ""
    if not host:
        preset = PRESETS.get(c.get("preset") or guess_preset(c["user"], c["host"]))
        host = (preset or {}).get("smtp_host", "")
        if not c.get("smtp_port") and preset:
            c["smtp_port"] = preset["smtp_port"]
    if not host:
        return "[error] no SMTP host is set for this account — Settings → Accounts → Mail"
    to = str(to or "").strip()
    if not to or "@" not in to:
        return "[error] a recipient address is needed"
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

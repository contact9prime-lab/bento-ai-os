"""Calendar: read the next days of one calendar, from an ICS address or a CalDAV
account, for the agent.

Two doors, because the two big providers open different ones without an OAuth
application: Google publishes a "secret address in iCal format" per calendar
(a plain HTTPS URL that returns ICS, no sign-in), while iCloud, Fastmail,
Nextcloud, Zimbra and most self-hosted servers speak CalDAV with an app
password. Outlook.com publishes an ICS URL too. Either way the agent reads; it
never creates, moves or deletes an event — there is no tool for it.

CalDAV here is the minimum that works: discover the person's calendar home from
the server root (current-user-principal → calendar-home-set → the collections
that are calendars), then a `calendar-query` REPORT per collection with a
time-range and `expand`, so the SERVER unrolls recurring events. The ICS door
has no server to ask, so `parse_ics` expands RRULE itself for the common shapes
(DAILY / WEEKLY / MONTHLY / YEARLY, INTERVAL, COUNT, UNTIL, BYDAY on weekly,
EXDATE, RECURRENCE-ID overrides). Anything stranger is reported as its first
occurrence, and the function says so in `notes` rather than guessing.

Times come back as ISO strings in the machine's local zone (TZIDs resolved via
zoneinfo). Every tool call is a `calendar.read` decision in the ledger; the
credential is a USER_KEY, masked on read, never handed to the model. Kept free
of asyncio in the parsing half so `bento calendar` works with the server down.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx

try:
    from zoneinfo import ZoneInfo
except Exception:                                                   # pragma: no cover
    ZoneInfo = None

DEFAULTS = {"enabled": False, "kind": "ics", "url": "", "user": "", "password": "",
            "name": "", "mcp_server": "", "last_test": {}}
KINDS = ("ics", "caldav", "google", "microsoft", "mcp")
MAX_EVENTS = 200
WINDOW_DAYS_MAX = 62

PRESETS = {
    "google": {"label": "Google Calendar (secret iCal address)", "kind": "ics",
               "hint": "calendar.google.com → Settings → your calendar → Integrate calendar "
                       "→ 'Secret address in iCal format'. Anyone with the address can read "
                       "the calendar, so treat it as a password."},
    "outlook": {"label": "Outlook.com (published ICS)", "kind": "ics",
                "hint": "outlook.live.com → Settings → Calendar → Shared calendars → Publish "
                        "a calendar → the ICS link."},
    "icloud": {"label": "iCloud Calendar (CalDAV)", "kind": "caldav",
               "url": "https://caldav.icloud.com/",
               "hint": "Your Apple ID address and an app-specific password from "
                       "appleid.apple.com. The URL is just https://caldav.icloud.com/ — the "
                       "calendars are discovered."},
    "fastmail": {"label": "Fastmail (CalDAV)", "kind": "caldav",
                 "url": "https://caldav.fastmail.com/",
                 "hint": "An app password with Calendar access. The URL is "
                         "https://caldav.fastmail.com/ — the calendars are discovered."},
    "nextcloud": {"label": "Nextcloud / another CalDAV server", "kind": "caldav", "url": "",
                  "hint": "The server's CalDAV root, e.g. https://cloud.example.com/remote.php/dav/ "
                          "— or one calendar's own URL. An app password if the server issues them."},
    "ics": {"label": "Any ICS address", "kind": "ics", "hint": "A URL that returns an .ics file."},
}


def conf(cfg: dict) -> dict:
    """The calendar section with its secret resolved out of the vault (see mail.conf)."""
    from . import vault
    c = {**DEFAULTS, **((cfg or {}).get("calendar") or {})}
    c["password"] = vault.resolve(c.get("password", ""), actor="calendar")
    return c


def kind(cfg: dict) -> str:
    k = str(((cfg or {}).get("calendar") or {}).get("kind") or "ics")
    return k if k in KINDS else "ics"


def configured(cfg: dict) -> bool:
    c = {**DEFAULTS, **((cfg or {}).get("calendar") or {})}    # raw: a reference counts
    k = kind(cfg)
    if k in ("google", "microsoft"):
        from . import signin
        rec = signin.signed_in(cfg, k)
        return bool(rec) and not rec.get("problem")
    if k == "mcp":
        return bool(c.get("mcp_server"))
    if not c["url"]:
        return False
    if k == "caldav":
        return bool(c["user"] and c["password"])
    return True


def problem(cfg: dict) -> str:
    c = {**DEFAULTS, **((cfg or {}).get("calendar") or {})}
    k = kind(cfg)
    if not configured(cfg):
        if k in ("google", "microsoft"):
            from . import signin
            rec = signin.signed_in(cfg, k)
            label = signin.PROVIDERS[k]["label"]
            return (f"The {label} sign-in needs redoing: {rec['problem']} — Settings → Accounts → Calendar."
                    if rec.get("problem") else
                    f"Needs a calendar — Settings → Accounts → Calendar (Sign in with {label}).")
        if k == "mcp":
            return "The calendar is set to read through an MCP server, but none is chosen — Settings → Accounts → Calendar."
        return ("Needs a calendar — Settings → Accounts → Calendar (sign in with Google or "
                "Microsoft, an ICS address, or a CalDAV account with an app password).")

    if not c.get("enabled", True):
        return "The calendar is set up but switched off — Settings → Accounts → Calendar."
    lt = c.get("last_test") or {}
    if lt and not lt.get("ok"):
        return f"The last check failed: {lt.get('detail', 'unknown error')} — Settings → Accounts → Calendar."
    return ""


# ---------------------------------------------------------------------------
# iCalendar parsing
# ---------------------------------------------------------------------------

_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _unfold(text: str) -> list[str]:
    out: list[str] = []
    for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if ln[:1] in (" ", "\t") and out:
            out[-1] += ln[1:]
        else:
            out.append(ln)
    return out


def _prop(line: str) -> tuple[str, dict, str]:
    """'DTSTART;TZID=Europe/Paris:20260921T090000' → ('DTSTART', {'TZID': …}, value)."""
    if ":" not in line:
        return line.upper(), {}, ""
    head, value = line.split(":", 1)
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _parse_dt(value: str, params: dict, tz_default):
    """A DATE or DATE-TIME as an aware datetime (all-day → midnight local, flag)."""
    v = value.strip()
    all_day = params.get("VALUE", "").upper() == "DATE" or (len(v) == 8 and v.isdigit())
    if all_day:
        d = dt.datetime.strptime(v[:8], "%Y%m%d")
        return d.replace(tzinfo=tz_default), True
    utc = v.endswith("Z")
    v = v.rstrip("Z")
    fmt = "%Y%m%dT%H%M%S" if len(v) >= 15 else "%Y%m%dT%H%M"
    d = dt.datetime.strptime(v[:15], fmt)
    if utc:
        return d.replace(tzinfo=dt.timezone.utc).astimezone(tz_default), False
    tzid = params.get("TZID")
    tz = None
    if tzid and ZoneInfo is not None:
        try:
            tz = ZoneInfo(tzid)
        except Exception:
            tz = None
    return d.replace(tzinfo=tz or tz_default).astimezone(tz_default), False


def _parse_duration(v: str) -> dt.timedelta:
    m = re.match(r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", v.strip())
    if not m:
        return dt.timedelta(0)
    sign = -1 if m.group(1) == "-" else 1
    w, d, h, mi, s = (int(x or 0) for x in m.groups()[1:])
    return sign * dt.timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _rrule(v: str) -> dict:
    out = {}
    for part in v.split(";"):
        if "=" in part:
            k, val = part.split("=", 1)
            out[k.upper()] = val
    return out


def _add_months(d: dt.datetime, n: int) -> dt.datetime:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    last = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
            31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, month=m, day=min(d.day, last))


def _occurrences(start: dt.datetime, rule: dict, window_start, window_end,
                 exdates: set, tz_default) -> tuple[list[dt.datetime], bool]:
    """Start times of a recurring event inside the window. (list, fully_understood)."""
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    until = None
    if rule.get("UNTIL"):
        until, _ = _parse_dt(rule["UNTIL"], {}, tz_default)
    understood = freq in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
    for k in ("BYMONTHDAY", "BYMONTH", "BYSETPOS", "BYYEARDAY", "BYWEEKNO", "BYHOUR"):
        if k in rule:
            understood = False
    if freq != "WEEKLY" and "BYDAY" in rule:
        understood = False
    if not understood:
        return ([start] if window_start <= start <= window_end else []), False
    out: list[dt.datetime] = []
    n = 0
    if freq == "WEEKLY":
        days = sorted({_WD[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _WD}) \
            or [start.weekday()]
        week0 = start - dt.timedelta(days=start.weekday())
        w = 0
        while True:
            base = week0 + dt.timedelta(weeks=w * interval)
            produced_any = False
            for wd in days:
                t = base + dt.timedelta(days=wd)
                if t < start:
                    continue
                n += 1
                if count is not None and n > count:
                    return out, True
                if until is not None and t > until:
                    return out, True
                if t > window_end:
                    return out, True
                produced_any = True
                if t >= window_start and t.date() not in exdates:
                    out.append(t)
            w += 1
            if base > window_end + dt.timedelta(days=7) or (not produced_any and w > 5000):
                return out, True
    step = 0
    while True:
        if freq == "DAILY":
            t = start + dt.timedelta(days=step * interval)
        elif freq == "MONTHLY":
            t = _add_months(start, step * interval)
        else:                                   # YEARLY
            t = _add_months(start, 12 * step * interval)
        n += 1
        if count is not None and n > count:
            break
        if until is not None and t > until:
            break
        if t > window_end:
            break
        if t >= window_start and t.date() not in exdates:
            out.append(t)
        step += 1
        if step > 20000:
            break
    return out, True


def parse_ics(text: str, window_start: dt.datetime, window_end: dt.datetime,
              calendar_name: str = "") -> dict:
    """Events inside [window_start, window_end], newest last. Returns
    {"events": [...], "notes": [...]} — notes say what could not be expanded."""
    tz = _local_tz()
    lines = _unfold(text)
    events, notes = [], []
    cur: dict | None = None
    cal_name = calendar_name
    for ln in lines:
        name, params, value = _prop(ln)
        if name == "X-WR-CALNAME" and not cal_name:
            cal_name = value.strip()
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"exdates": set(), "attendees": []}
            continue
        if name == "END" and value.strip().upper() == "VEVENT" and cur is not None:
            events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        if name == "DTSTART":
            cur["start"], cur["all_day"] = _parse_dt(value, params, tz)
        elif name == "DTEND":
            cur["end"], _ = _parse_dt(value, params, tz)
        elif name == "DURATION":
            cur["duration"] = _parse_duration(value)
        elif name == "SUMMARY":
            cur["summary"] = _unescape(value)
        elif name == "LOCATION":
            cur["location"] = _unescape(value)
        elif name == "DESCRIPTION":
            cur["description"] = _unescape(value)
        elif name == "UID":
            cur["uid"] = value.strip()
        elif name == "RRULE":
            cur["rrule"] = _rrule(value)
        elif name == "EXDATE":
            for v in value.split(","):
                try:
                    d, _ = _parse_dt(v, params, tz)
                    cur["exdates"].add(d.date())
                except Exception:
                    pass
        elif name == "RECURRENCE-ID":
            try:
                cur["recurrence_id"], _ = _parse_dt(value, params, tz)
            except Exception:
                pass
        elif name == "STATUS":
            cur["status"] = value.strip().upper()
        elif name == "ATTENDEE":
            who = params.get("CN") or value.replace("mailto:", "").strip()
            cur["attendees"].append(who)
        elif name == "ORGANIZER":
            cur["organizer"] = params.get("CN") or value.replace("mailto:", "").strip()
        elif name == "URL":
            cur["url"] = value.strip()

    # overrides replace one occurrence of their series
    overridden: dict[str, set] = {}
    for e in events:
        if e.get("recurrence_id") and e.get("uid"):
            overridden.setdefault(e["uid"], set()).add(e["recurrence_id"].date())

    out = []
    for e in events:
        if "start" not in e or e.get("status") == "CANCELLED":
            continue
        length = (e["end"] - e["start"]) if e.get("end") else \
            e.get("duration", dt.timedelta(days=1) if e.get("all_day") else dt.timedelta(hours=1))
        starts: list[dt.datetime]
        if e.get("rrule") and not e.get("recurrence_id"):
            ex = set(e["exdates"]) | overridden.get(e.get("uid", ""), set())
            starts, ok = _occurrences(e["start"], e["rrule"], window_start, window_end, ex, tz)
            if not ok:
                notes.append(f"'{e.get('summary', '(untitled)')}' repeats in a way this reader "
                             f"cannot expand ({e['rrule'].get('FREQ', '?')}) — only its first "
                             f"date is shown")
        else:
            starts = [e["start"]] if e["start"] <= window_end and e["start"] + length >= window_start else []
        for s in starts:
            out.append({"uid": e.get("uid", ""), "summary": e.get("summary", "(untitled)"),
                        "start": s.isoformat(timespec="minutes"),
                        "end": (s + length).isoformat(timespec="minutes"),
                        "all_day": bool(e.get("all_day")),
                        "location": e.get("location", ""),
                        "description": (e.get("description", "") or "")[:1200],
                        "attendees": e.get("attendees", [])[:20],
                        "organizer": e.get("organizer", ""),
                        "url": e.get("url", ""),
                        "calendar": cal_name})
    out.sort(key=lambda x: x["start"])
    return {"events": out[:MAX_EVENTS], "notes": notes, "calendar": cal_name}


def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


# ---------------------------------------------------------------------------
# Fetching: ICS and CalDAV
# ---------------------------------------------------------------------------

def window(days: int = 1, start: str = "", end: str = "") -> tuple[dt.datetime, dt.datetime]:
    tz = _local_tz()
    now = dt.datetime.now(tz)
    if start:
        s = dt.datetime.fromisoformat(start)
        s = s if s.tzinfo else s.replace(tzinfo=tz)
    else:
        s = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if end:
        e = dt.datetime.fromisoformat(end)
        e = e if e.tzinfo else e.replace(tzinfo=tz)
    else:
        e = s + dt.timedelta(days=max(1, min(int(days or 1), WINDOW_DAYS_MAX)))
    return s, e


def _auth(c: dict):
    return (c["user"], c["password"]) if c.get("user") else None


async def _get_ics(c: dict) -> str:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                 headers={"User-Agent": "AgentOS/0.1"}, auth=_auth(c)) as cl:
        r = await cl.get(c["url"])
        r.raise_for_status()
        return r.text


_NS = {"D": "DAV:", "C": "urn:ietf:params:xml:ns:caldav"}


def _ns_text(el, path) -> str:
    x = el.find(path, _NS)
    return (x.text or "").strip() if x is not None else ""


async def _caldav_calendars(cl: httpx.AsyncClient, root: str) -> list[dict]:
    """The calendar collections behind a CalDAV root or principal URL."""
    async def propfind(url, body, depth):
        r = await cl.request("PROPFIND", url, content=body,
                             headers={"Depth": str(depth), "Content-Type": "application/xml"})
        if r.status_code >= 400:
            raise RuntimeError(f"{url} answered {r.status_code}")
        return ET.fromstring(r.content)

    # 1. is the URL itself a calendar?
    body = ('<?xml version="1.0"?><D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            '<D:prop><D:resourcetype/><D:displayname/><D:current-user-principal/>'
            '<C:calendar-home-set/></D:prop></D:propfind>')
    tree = await propfind(root, body, 0)
    resp = tree.find("D:response", _NS)
    if resp is not None and resp.find(".//D:resourcetype/C:calendar", _NS) is not None:
        return [{"url": root, "name": _ns_text(resp, ".//D:displayname") or "calendar"}]
    # 2. principal → home
    principal = _ns_text(tree, ".//D:current-user-principal/D:href")
    home = _ns_text(tree, ".//C:calendar-home-set/D:href")
    if not home:
        if not principal:
            raise RuntimeError("the server did not say where the calendars are (no "
                               "current-user-principal) — try the calendar's own URL")
        ptree = await propfind(urljoin(root, principal), body, 0)
        home = _ns_text(ptree, ".//C:calendar-home-set/D:href")
        if not home:
            raise RuntimeError("no calendar-home-set on the principal — try the calendar's own URL")
    home = urljoin(root, home)
    # 3. the collections in the home
    tree = await propfind(home, body, 1)
    cals = []
    for r in tree.findall("D:response", _NS):
        if r.find(".//D:resourcetype/C:calendar", _NS) is None:
            continue
        href = _ns_text(r, "D:href")
        cals.append({"url": urljoin(home, href), "name": _ns_text(r, ".//D:displayname") or href})
    if not cals:
        raise RuntimeError("no calendars found in the calendar home")
    return cals


def _utc(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _rfc3339(d: dt.datetime) -> str:
    """What the Google and Graph APIs take — CalDAV's compact form is refused there."""
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _caldav_events(c: dict, ws: dt.datetime, we: dt.datetime) -> dict:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                 headers={"User-Agent": "AgentOS/0.1"}, auth=_auth(c)) as cl:
        cals = await _caldav_calendars(cl, c["url"])
        report = (f'<?xml version="1.0"?><C:calendar-query xmlns:D="DAV:" '
                  f'xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop><D:getetag/>'
                  f'<C:calendar-data><C:expand start="{_utc(ws)}" end="{_utc(we)}"/>'
                  f'</C:calendar-data></D:prop><C:filter><C:comp-filter name="VCALENDAR">'
                  f'<C:comp-filter name="VEVENT"><C:time-range start="{_utc(ws)}" end="{_utc(we)}"/>'
                  f'</C:comp-filter></C:comp-filter></C:filter></C:calendar-query>')
        events, notes = [], []
        for cal in cals:
            r = await cl.request("REPORT", cal["url"], content=report,
                                 headers={"Depth": "1", "Content-Type": "application/xml"})
            if r.status_code >= 400:
                notes.append(f"{cal['name']}: the server answered {r.status_code} to the query")
                continue
            tree = ET.fromstring(r.content)
            for resp in tree.findall("D:response", _NS):
                data = _ns_text(resp, ".//C:calendar-data")
                if not data:
                    continue
                parsed = parse_ics(data, ws, we, calendar_name=cal["name"])
                events += parsed["events"]
                notes += parsed["notes"]
        events.sort(key=lambda x: x["start"])
        return {"events": events[:MAX_EVENTS], "notes": notes,
                "calendars": [x["name"] for x in cals]}


async def events(cfg: dict, days: int = 1, start: str = "", end: str = "") -> dict:
    """The events in the window, from whichever door is configured."""
    c = conf(cfg)
    p = problem(cfg)
    if p:
        return {"error": p, "events": [], "notes": []}
    ws, we = window(days, start, end)
    k = kind(cfg)
    if k == "google":
        out = await _google_events(cfg, ws, we)
    elif k == "microsoft":
        out = await _graph_events(cfg, ws, we)
    elif k == "caldav":
        out = await _caldav_events(c, ws, we)
    else:
        text = await _get_ics(c)
        out = parse_ics(text, ws, we, calendar_name=c.get("name") or "")
    out["window"] = {"start": ws.isoformat(timespec="minutes"), "end": we.isoformat(timespec="minutes")}
    return out


# ---------------------------------------------------------------------------
# The signed-in doors: Google Calendar and Microsoft Graph, mapped onto the same
# event shape the ICS parser produces, so the tool and every mission read one thing
# ---------------------------------------------------------------------------

def _iso_min(s: str) -> str:
    """'2026-09-21T09:00:00+02:00' / '2026-09-21' → what parse_ics emits (minutes)."""
    s = str(s or "")
    if len(s) == 10:
        return s + "T00:00"
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.astimezone(_local_tz()).isoformat(timespec="minutes")
    except ValueError:
        return s[:16]


async def _google_events(cfg: dict, ws: dt.datetime, we: dt.datetime) -> dict:
    from . import signin
    base = signin.PROVIDERS["google"]["api_calendar"]
    headers = {**signin.auth_header(cfg, "google", actor="calendar"), "Accept": "application/json"}
    evs, names, notes = [], [], []
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as cl:
        r = await cl.get(f"{base}/users/me/calendarList", params={"minAccessRole": "reader"})
        _raise_signin(r)
        cals = [c for c in r.json().get("items", []) if c.get("selected", True)] or [{"id": "primary", "summary": "primary"}]
        for c in cals[:10]:
            r = await cl.get(f"{base}/calendars/{c['id']}/events",
                             params={"timeMin": _rfc3339(ws), "timeMax": _rfc3339(we), "singleEvents": "true",
                                     "orderBy": "startTime", "maxResults": MAX_EVENTS})
            _raise_signin(r)
            names.append(c.get("summary") or c["id"])
            for e in r.json().get("items", []):
                if e.get("status") == "cancelled":
                    continue
                st, en = e.get("start") or {}, e.get("end") or {}
                all_day = "date" in st and "dateTime" not in st
                evs.append({"uid": e.get("id", ""), "summary": e.get("summary") or "(no title)",
                            "start": _iso_min(st.get("dateTime") or st.get("date")),
                            "end": _iso_min(en.get("dateTime") or en.get("date")),
                            "all_day": all_day, "location": e.get("location", ""),
                            "description": (e.get("description") or "")[:2000],
                            "attendees": [a.get("email", "") for a in e.get("attendees", []) if a.get("email")],
                            "calendar": c.get("summary") or c["id"]})
    evs.sort(key=lambda e: e["start"])
    return {"events": evs[:MAX_EVENTS], "calendars": names, "notes": notes}


async def _graph_events(cfg: dict, ws: dt.datetime, we: dt.datetime) -> dict:
    from . import signin
    base = signin.PROVIDERS["microsoft"]["api_graph"]
    headers = {**signin.auth_header(cfg, "microsoft", actor="calendar"), "Accept": "application/json",
               "Prefer": f'outlook.timezone="{_tz_name()}"'}
    evs = []
    async with httpx.AsyncClient(timeout=30.0, headers=headers) as cl:
        r = await cl.get(f"{base}/me/calendarView",
                         params={"startDateTime": _rfc3339(ws), "endDateTime": _rfc3339(we), "$top": MAX_EVENTS,
                                 "$orderby": "start/dateTime",
                                 "$select": "id,subject,start,end,isAllDay,location,bodyPreview,attendees,isCancelled"})
        _raise_signin(r)
        for e in r.json().get("value", []):
            if e.get("isCancelled"):
                continue
            evs.append({"uid": e.get("id", ""), "summary": e.get("subject") or "(no title)",
                        "start": _iso_min((e.get("start") or {}).get("dateTime", "")),
                        "end": _iso_min((e.get("end") or {}).get("dateTime", "")),
                        "all_day": bool(e.get("isAllDay")),
                        "location": ((e.get("location") or {}).get("displayName") or ""),
                        "description": (e.get("bodyPreview") or "")[:2000],
                        "attendees": [((a.get("emailAddress") or {}).get("address") or "")
                                      for a in e.get("attendees", [])],
                        "calendar": "Outlook"})
    return {"events": evs, "calendars": ["Outlook"], "notes": []}


def _raise_signin(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise RuntimeError("the sign-in was refused by the server — sign in again in Settings → Accounts")
    if r.status_code == 403:
        raise RuntimeError("the sign-in does not cover the calendar (the scope was not granted) — "
                           "sign in again and tick Calendar")
    r.raise_for_status()


def _tz_name() -> str:
    try:
        import zoneinfo  # noqa: F401
        return str(dt.datetime.now().astimezone().tzinfo) or "UTC"
    except Exception:
        return "UTC"


async def test_access(cfg: dict) -> dict:
    """Fetch the next seven days; the sentence a Settings card shows."""
    c = conf(cfg)
    if not configured(cfg):
        k = kind(cfg)
        return {"ok": False, "detail": problem(cfg) if k in ("google", "microsoft", "mcp") else
                "a URL is needed" + (" with a user and password" if k == "caldav" else ""),
                "at": time.time()}
    try:
        out = await events(cfg, days=7)
    except RuntimeError as e:
        return {"ok": False, "detail": str(e)[:220], "at": time.time()}
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        hint = {401: " — wrong user name or password, or the account needs an app password",
                403: " — the account may not allow this client", 404: " — no calendar at that URL"}.get(code, "")
        return {"ok": False, "detail": f"the server answered {code}{hint}", "at": time.time()}
    except Exception as e:                                          # noqa: BLE001
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"[:200], "at": time.time()}
    if out.get("error"):
        return {"ok": False, "detail": out["error"], "at": time.time()}
    n = len(out["events"])
    names = ", ".join(out.get("calendars") or ([out.get("calendar")] if out.get("calendar") else []))
    k = kind(cfg)
    who = ""
    if k in ("google", "microsoft"):
        from . import signin
        who = f"signed in with {signin.PROVIDERS[k]['label']} — "
    return {"ok": True, "detail": f"{who}{n} event{'s' if n != 1 else ''} in the next 7 days"
                                  + (f" ({names})" if names else ""),
            "at": time.time(), "count": n}

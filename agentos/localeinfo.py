"""Where and when the user is — the context every "today" question needs.

"What's in the news?" is meaningless without a country; "what's on today?" is
meaningless without a timezone. This module keeps one locale record, detected
from the machine and confirmable by the user, and feeds it to three places:

  * the agent's system prompt (so it reasons in the right place and time)
  * the shell (clock format, date rendering)
  * the AgentOS session itself (LANG/LC_*/TZ exported into the compositor, so
    native apps launched from AgentOS agree with it)
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

#: what a fully-specified locale looks like. Empty strings mean "detect".
FIELDS = ("language", "country", "timezone", "city", "units", "clock")

UNITS = ("metric", "imperial")
CLOCKS = ("24h", "12h")

#: country code → a readable name for the prompt (the ones a desktop actually
#: ships in; anything else falls back to the raw code, which is still useful).
COUNTRIES = {
    "IN": "India", "US": "United States", "GB": "United Kingdom", "CA": "Canada",
    "AU": "Australia", "DE": "Germany", "FR": "France", "ES": "Spain", "IT": "Italy",
    "NL": "Netherlands", "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "FI": "Finland",
    "PL": "Poland", "PT": "Portugal", "IE": "Ireland", "CH": "Switzerland", "AT": "Austria",
    "BE": "Belgium", "CZ": "Czechia", "GR": "Greece", "RO": "Romania", "UA": "Ukraine",
    "RU": "Russia", "TR": "Turkey", "IL": "Israel", "AE": "United Arab Emirates",
    "SA": "Saudi Arabia", "EG": "Egypt", "ZA": "South Africa", "NG": "Nigeria",
    "KE": "Kenya", "BR": "Brazil", "MX": "Mexico", "AR": "Argentina", "CL": "Chile",
    "CO": "Colombia", "JP": "Japan", "KR": "South Korea", "CN": "China", "HK": "Hong Kong",
    "TW": "Taiwan", "SG": "Singapore", "MY": "Malaysia", "ID": "Indonesia",
    "TH": "Thailand", "VN": "Vietnam", "PH": "Philippines", "PK": "Pakistan",
    "BD": "Bangladesh", "LK": "Sri Lanka", "NP": "Nepal", "NZ": "New Zealand",
}


def _run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return (r.stdout or "").strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _tz_country_map() -> dict:
    """Timezone → ISO country, straight from the system tzdb (zone1970.tab).

    Authoritative and always current; the small fallback below only matters on a
    machine without the tzdb tables."""
    out: dict[str, str] = {}
    for name in ("zone1970.tab", "zone.tab"):
        p = Path("/usr/share/zoneinfo") / name
        if not p.is_file():
            continue
        try:
            for line in p.read_text(errors="replace").splitlines():
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 3:
                    continue
                codes, tz = cols[0].split(",")[0].strip(), cols[2].strip()
                if tz and codes and tz not in out:
                    out[tz] = codes.upper()
        except Exception:
            pass
        if out:
            break
    return out or {"Asia/Kolkata": "IN", "Asia/Calcutta": "IN", "Europe/London": "GB",
                   "America/New_York": "US", "America/Los_Angeles": "US",
                   "Europe/Berlin": "DE", "Asia/Tokyo": "JP", "Australia/Sydney": "AU"}


def detect() -> dict:
    """Best-effort locale from the machine itself. Never raises, never blocks long.

    Precedence matters: the TIMEZONE decides the country, not $LANG. Running an
    en_US locale in India is completely normal, and taking the country from LANG
    would tell the agent "United States" for a machine sitting in Kolkata.
    """
    out = {"language": "", "country": "", "timezone": "", "city": "",
           "units": "", "clock": ""}
    tz = ""
    p = Path("/etc/timezone")
    if p.is_file():
        tz = p.read_text().strip()
    if not tz:
        try:
            lt = Path("/etc/localtime")
            if lt.is_symlink():
                s = str(lt.resolve())
                if "/zoneinfo/" in s:
                    tz = s.split("/zoneinfo/", 1)[1]
        except Exception:
            pass
    if not tz:
        tz = _run(["timedatectl", "show", "-p", "Timezone", "--value"]).strip()
    out["timezone"] = tz or os.environ.get("TZ", "")

    env = (os.environ.get("LC_ALL") or os.environ.get("LC_TIME")
           or os.environ.get("LANG") or "")
    base = env.split(".")[0].replace("_", "-")
    if base and base.lower() not in ("c", "posix"):
        out["language"] = base

    # country: timezone first (authoritative), $LANG's region only as a fallback
    if out["timezone"]:
        out["country"] = _tz_country_map().get(out["timezone"], "")
    if not out["country"] and "-" in (out["language"] or ""):
        out["country"] = out["language"].split("-", 1)[1].upper()

    if out["timezone"] and "/" in out["timezone"]:
        out["city"] = out["timezone"].split("/")[-1].replace("_", " ")
    out["units"] = "imperial" if out["country"] in ("US", "LR", "MM") else "metric"
    out["clock"] = "12h" if out["country"] in ("US", "CA", "AU", "IN", "PH", "NZ") else "24h"
    return out


def effective(cfg: dict) -> dict:
    """The user's configured locale, with detection filling every blank."""
    saved = (cfg.get("locale") or {}) if isinstance(cfg.get("locale"), dict) else {}
    det = detect()
    out = {}
    for k in FIELDS:
        v = str(saved.get(k) or "").strip()
        out[k] = v or det.get(k, "")
    if out["units"] not in UNITS:
        out["units"] = "metric"
    if out["clock"] not in CLOCKS:
        out["clock"] = "24h"
    out["country_name"] = COUNTRIES.get(out["country"], out["country"])
    out["configured"] = bool(saved)
    return out


def describe(cfg: dict) -> str:
    """The line the agent reads. Concrete enough to change what it does."""
    lo = effective(cfg)
    where = lo["country_name"] or "an unspecified country"
    bits = [f"The user is in {where}"]
    if lo["city"]:
        bits[0] += f" (near {lo['city']})"
    if lo["timezone"]:
        bits.append(f"timezone {lo['timezone']}")
    if lo["language"]:
        bits.append(f"interface language {lo['language']}")
    bits.append(f"{lo['units']} units")
    line = ", ".join(bits) + "."
    return (line + " Localise anything place- or time-dependent — news, weather, prices, "
                   "holidays, sports, opening hours, units — to that country and timezone, "
                   "and prefer local sources for it. Never assume the US.")


def now_string(cfg: dict) -> str:
    """Current time rendered in the user's timezone (what the prompt shows)."""
    import datetime
    lo = effective(cfg)
    tz = None
    if lo["timezone"]:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(lo["timezone"])
        except Exception:
            tz = None
    now = datetime.datetime.now(tz) if tz else datetime.datetime.now()
    stamp = now.strftime("%A %Y-%m-%d %H:%M")
    return f"{stamp} {lo['timezone']}" if lo["timezone"] else now.strftime("%A %Y-%m-%d %H:%M %Z")


def session_env(cfg: dict) -> dict:
    """Environment the AgentOS session exports, so native apps agree with us."""
    lo = effective(cfg)
    env = {}
    if lo["timezone"]:
        env["TZ"] = lo["timezone"]
    if lo["language"]:
        posix = lo["language"].replace("-", "_")
        if "." not in posix:
            posix += ".UTF-8"
        env["LANG"] = posix
        env["LC_TIME"] = posix
        env["LC_NUMERIC"] = posix
        env["LC_MONETARY"] = posix
    return env


def timezones() -> list[str]:
    try:
        from zoneinfo import available_timezones
        return sorted(available_timezones())
    except Exception:
        return sorted({detect().get("timezone", "") or "UTC", "UTC"})

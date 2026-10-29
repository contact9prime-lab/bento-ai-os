"""Readings: what each sensor on a Zero said over time, kept on its hub.

Asked for as "the hub would be storing those information based on the data preserving rules of
how long … available associated with the inventory on the hub" and "drill further to see the data
visualization for the last 90 days". Step 3 of docs/design/devices.md. Two halves:

  * On the Zero, `Buffer`: `hardware.sample()` every SAMPLE_S seconds into memory, numbered, so
    the hub can ask for "everything after n". A GPIO pin is recorded when it changes, not every
    time. Nothing is written to the SD card. A restart starts a new `boot`, and the hub then takes
    the buffer from its start.
  * On the hub, `telemetry.db` in the machine's home (beside inventory.json, admin only, like the
    inventory): raw samples, and per-minute and per-hour summaries kept up as samples arrive.
    Retention (RETAIN): raw 7 days, per minute 30, per hour 90. `prune` runs from the minute watch.

The readings ride the hello the hub already sends every minute (`readings_since` asks, `readings`
answers), so no new connection, door or permission: these are the numbers discovery already reads.
Times are the hub's: the Zero says what its clock reads and the hub shifts by the difference.

A raw sample equal to the last one kept is skipped unless KEEP_ANYWAY has passed (the summaries
still count it), which is most of a Pi's disk-free and voltage samples. Free of HTTP and asyncio.
"""
from __future__ import annotations

import collections
import math
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SAMPLE_S = 10                    # how often a Zero samples
BUFFER_MAX = 6000                # samples a Zero keeps while its hub is away (about an hour and a half)
SEND_MAX = 1500                  # samples in one hello's answer; the rest come with the next
KEEP_ANYWAY = 300                # a raw sample equal to the last one kept is kept again after this
RETAIN = {"raw": 7 * 86400, "minute": 30 * 86400, "hour": 90 * 86400}
RANGES = {"day": 86400, "week": 7 * 86400, "month": 30 * 86400, "quarter": 90 * 86400}
RANGE_WORDS = {"day": "the last day", "week": "the last week", "month": "the last 30 days",
               "quarter": "the last 90 days"}
POINTS = 360                     # a chart's resolution, whatever the range
CLOCK_SLACK = 5                  # seconds of clock difference that are not corrected


# ---- on the Zero ----------------------------------------------------------------------------

class Buffer:
    """The samples this machine took, numbered, until its hub has them."""

    def __init__(self):
        self.boot = secrets.token_hex(6)
        self.seq = 0
        self.rows: collections.deque = collections.deque(maxlen=BUFFER_MAX)
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def add(self, values: dict, ts: float | None = None) -> int:
        """One round of samples. A pin is recorded only when its level moved."""
        ts = ts or time.time()
        n = 0
        with self._lock:
            for item, v in values.items():
                if item.startswith("gpio.") and self._last.get(item) == v:
                    continue
                self._last[item] = v
                self.seq += 1
                self.rows.append((self.seq, round(ts, 1), item, v))
                n += 1
        return n

    def since(self, cur) -> dict:
        """What the hub has not got. `cur` is what it said it has: {boot, seq}."""
        cur = cur if isinstance(cur, dict) else {}
        after = int(cur.get("seq") or 0) if cur.get("boot") == self.boot else 0
        with self._lock:
            rows = [list(r) for r in self.rows if r[0] > after]
            first = self.rows[0][0] if self.rows else self.seq + 1
        out = rows[:SEND_MAX]
        return {"boot": self.boot, "now": time.time(), "every": SAMPLE_S, "rows": out,
                "seq": out[-1][0] if out else after, "more": len(rows) > SEND_MAX,
                # samples that fell out of the buffer before the hub came back
                "lost": max(0, first - after - 1) if after and cur.get("boot") == self.boot else 0}


BUFFER = Buffer()


# ---- on the hub -----------------------------------------------------------------------------

_DBS: dict[str, sqlite3.Connection] = {}
_KEPT: dict[tuple, tuple] = {}        # (machine, item) -> (value kept, its time, newest time seen)
_DB_LOCK = threading.RLock()


def path() -> Path:
    from . import teamlink
    return teamlink.home() / "telemetry.db"


def db() -> sqlite3.Connection:
    p = str(path())
    with _DB_LOCK:
        c = _DBS.get(p)
        if c is None:
            Path(p).parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(p, check_same_thread=False, isolation_level=None)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            c.executescript("""
                CREATE TABLE IF NOT EXISTS raw (m TEXT, i TEXT, ts REAL, v REAL, PRIMARY KEY (m, i, ts)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS minute (m TEXT, i TEXT, b INTEGER, lo REAL, hi REAL, sum REAL, n INTEGER,
                                                   last REAL, PRIMARY KEY (m, i, b)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS hour (m TEXT, i TEXT, b INTEGER, lo REAL, hi REAL, sum REAL, n INTEGER,
                                                 last REAL, PRIMARY KEY (m, i, b)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS cursor (m TEXT PRIMARY KEY, boot TEXT, seq INTEGER, at REAL,
                                                   first REAL, rows INTEGER);
            """)
            _DBS[p] = c
        return c


def cursor(machine: str) -> dict:
    r = db().execute("SELECT boot, seq, at, first, rows FROM cursor WHERE m=?", (machine,)).fetchone()
    return {"boot": r[0], "seq": r[1], "at": r[2], "first": r[3], "rows": r[4]} if r else {}


def _num(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return None


def store(machine: str, batch) -> dict:
    """Keep what a Zero sent (its hello's `readings`), read field by field. Returns how many
    samples were new and whether this was the first batch from it."""
    from .hardware import _ID
    if not isinstance(batch, dict) or not isinstance(batch.get("rows"), list) or not machine:
        return {"stored": 0}
    now = time.time()
    off = now - float(_num(batch.get("now")) or now)
    if abs(off) < CLOCK_SLACK:
        off = 0.0
    c = db()
    stored, last_seq = 0, None
    # a batch sent again is known by its numbers: the clock offset is worked out per call, so a
    # time rounded a tenth later would read as new and be counted twice in the summaries
    had = cursor(machine)
    seen_to = had.get("seq") if had and had.get("boot") == str(batch.get("boot") or "")[:24] else None
    with _DB_LOCK:
        c.execute("BEGIN")
        try:
            for row in batch["rows"][:SEND_MAX]:
                if not isinstance(row, (list, tuple)) or len(row) != 4:
                    continue
                seq, ts, item, v = row
                if isinstance(seq, int) and seen_to is not None and seq <= seen_to:
                    continue
                ts, v = _num(ts), _num(v)
                if ts is None or v is None or not isinstance(item, str) or not _ID.fullmatch(item):
                    continue
                ts = round(ts + off, 1)
                if ts < now - RETAIN["raw"] or ts > now + 60:
                    continue
                last_seq = seq if isinstance(seq, int) else last_seq
                key = (machine, item)
                kept = _KEPT.get(key)          # (value kept, when kept, the newest time seen)
                if kept and ts <= kept[2]:
                    continue                   # already had this one: a batch sent twice
                if not kept or kept[0] != v or ts - kept[1] >= KEEP_ANYWAY:
                    if not c.execute("INSERT OR IGNORE INTO raw VALUES (?,?,?,?)", (machine, item, ts, v)).rowcount:
                        continue               # the same, kept before this hub restarted
                    kept = (v, ts, ts)
                _KEPT[key] = (kept[0], kept[1], ts)
                for table, size in (("minute", 60), ("hour", 3600)):
                    c.execute(f"INSERT INTO {table} VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(m,i,b) DO UPDATE SET "
                              "lo=min(lo,excluded.lo), hi=max(hi,excluded.hi), sum=sum+excluded.sum, n=n+1, "
                              "last=excluded.last", (machine, item, int(ts // size), v, v, v, v))
                stored += 1
            cur = cursor(machine)
            first = not cur
            seq = int(batch.get("seq") or 0) if isinstance(batch.get("seq"), int) else (last_seq or 0)
            c.execute("INSERT INTO cursor VALUES (?,?,?,?,?,?) ON CONFLICT(m) DO UPDATE SET boot=excluded.boot, "
                      "seq=excluded.seq, at=excluded.at, rows=rows+excluded.rows",
                      (machine, str(batch.get("boot") or "")[:24], seq, now, now, stored))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return {"stored": stored, "first": first, "more": bool(batch.get("more")),
            "lost": int(_num(batch.get("lost")) or 0)}


def items(machine: str) -> list[str]:
    """The items of this machine that have readings."""
    return [r[0] for r in db().execute("SELECT DISTINCT i FROM hour WHERE m=?", (machine,))]


def series(machine: str, item: str, rng: str = "day", now: float | None = None) -> dict:
    """One item's readings over a range, as at most POINTS buckets of [time, mean, min, max],
    with the range's last, min, max and mean. A range shorter than the raw retention reads raw
    samples; longer ones the per-minute or per-hour summaries."""
    span = RANGES.get(rng, RANGES["day"])
    now = now or time.time()
    start = now - span
    step = max(1, span // POINTS)
    c = db()
    if span <= 86400:
        sql = (f"SELECT min(CAST((ts - ?) / ? AS INTEGER), {POINTS - 1}) AS k, avg(v), min(v), max(v), count(*) "
               "FROM raw WHERE m=? AND i=? AND ts>=? GROUP BY k ORDER BY k")
        args = (start, step, machine, item, start)
    else:
        table, size = ("minute", 60) if span <= RETAIN["minute"] else ("hour", 3600)
        sql = (f"SELECT min(CAST((b * {size} - ?) / ? AS INTEGER), {POINTS - 1}) AS k, sum(sum)/sum(n), min(lo), "
               f"max(hi), sum(n) FROM {table} WHERE m=? AND i=? AND b>=? GROUP BY k ORDER BY k")
        args = (start, step, machine, item, int(start // size))
    pts = [[round(start + k * step + step / 2, 1), round(a, 4), lo, hi] for k, a, lo, hi, _n in c.execute(sql, args)
           if k is not None and 0 <= k < POINTS]
    last = c.execute("SELECT ts, v FROM raw WHERE m=? AND i=? ORDER BY ts DESC LIMIT 1", (machine, item)).fetchone()
    if pts:
        n = sum(1 for _ in pts)
        stats = {"min": min(p[2] for p in pts), "max": max(p[3] for p in pts),
                 "mean": round(sum(p[1] for p in pts) / n, 3)}
    else:
        stats = {}
    if last:
        stats.update(last=last[1], last_at=last[0])
    return {"item": item, "range": rng, "words": RANGE_WORDS.get(rng, rng), "start": start, "end": now,
            "step": step, "points": pts, "stats": stats}


def prune(now: float | None = None) -> dict:
    """Drop what is older than RETAIN. Returns how many rows each table lost."""
    now = now or time.time()
    c = db()
    out = {}
    with _DB_LOCK:
        out["raw"] = c.execute("DELETE FROM raw WHERE ts < ?", (now - RETAIN["raw"],)).rowcount
        out["minute"] = c.execute("DELETE FROM minute WHERE b < ?", (int((now - RETAIN["minute"]) // 60),)).rowcount
        out["hour"] = c.execute("DELETE FROM hour WHERE b < ?", (int((now - RETAIN["hour"]) // 3600),)).rowcount
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return out


SPARK = "▁▂▃▄▅▆▇█"


def text(name: str, item: str, s: dict, unit: str = "") -> str:
    """One item's readings as a terminal shows them: the numbers and a line of blocks."""
    pts = s.get("points") or []
    head = f"  {name}/{item} · {s.get('words')}"
    if not pts:
        return head + "\n  no readings in this range yet"
    lo, hi = min(p[1] for p in pts), max(p[1] for p in pts)
    width = 60
    step = max(1, len(pts) // width)
    line = "".join(SPARK[3 if hi == lo else min(7, int((p[1] - lo) / (hi - lo) * 7.999))] for p in pts[::step])
    st = s["stats"]
    share = round(100 * sum(p[1] for p in pts) / len(pts))
    if item == "power.throttle":       # 1 is under-voltage or throttled, 0 is fine (hardware.sample)
        said = f"under-voltage or throttled {share}% of the time · now {'bad' if st.get('last') else 'fine'}"
    elif item.startswith("gpio."):
        said = f"high {share}% of the time · now {'high' if st.get('last') else 'low'}"
    else:
        u = f" {unit}" if unit else ""
        r = lambda v: v if v is None else round(v, 1)
        said = (f"last {r(st.get('last'))}{u} · min {r(st.get('min'))}{u} · max {r(st.get('max'))}{u} · "
                f"mean {r(st.get('mean'))}{u}")
    return "\n".join([head, f"  {line}", f"  {said} · {len(pts)} points"])

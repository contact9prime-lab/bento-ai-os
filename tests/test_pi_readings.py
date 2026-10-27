"""What a Zero's sensors read over time, kept on its hub (telemetry.py, the hello's readings,
Devices → Hardware → a sensor, bento network readings). Asked for as "the hub would be storing those
information based on the data preserving rules" and "drill further to see the data visualization for
the last 90 days"."""
import math
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from agentos import telemetry, teamlink, ties                # noqa: E402
from test_zero_mind import _on, hz                            # noqa: E402,F401

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def tm(tmp_path, monkeypatch):
    monkeypatch.setattr(teamlink, "home", lambda: tmp_path)
    monkeypatch.setattr(telemetry, "BUFFER", telemetry.Buffer())
    telemetry._KEPT.clear()
    yield tmp_path
    for c in telemetry._DBS.values():
        c.close()
    telemetry._DBS.clear()


def test_a_zero_keeps_its_samples_numbered_and_a_pin_only_when_it_moves(tm):
    b = telemetry.BUFFER
    b.add({"cpu.temp": 50.1, "gpio.17": 0}, ts=1000)
    b.add({"cpu.temp": 50.3, "gpio.17": 0}, ts=1010)
    b.add({"cpu.temp": 50.2, "gpio.17": 1}, ts=1020)
    got = b.since({})
    assert [r[2] for r in got["rows"]] == ["cpu.temp", "gpio.17", "cpu.temp", "cpu.temp", "gpio.17"]
    assert got["seq"] == 5 and got["boot"] == b.boot and not got["more"]
    assert b.since({"boot": b.boot, "seq": 3})["rows"][0][0] == 4, "only what the hub hasn't got"
    assert len(b.since({"boot": "another", "seq": 3})["rows"]) == 5, "a restart: the hub takes it from the start"


def test_a_long_absence_comes_back_in_pieces_and_says_what_was_lost(tm, monkeypatch):
    monkeypatch.setattr(telemetry, "BUFFER_MAX", 50)
    b = telemetry.Buffer()
    for n in range(10):
        b.add({"cpu.temp": float(n)}, ts=1000 + n)
    cur = {"boot": b.boot, "seq": 10}
    for n in range(80):
        b.add({"cpu.temp": float(n)}, ts=2000 + n)
    got = b.since(cur)
    assert len(got["rows"]) == 50 and got["lost"] == 30
    monkeypatch.setattr(telemetry, "SEND_MAX", 20)
    first = b.since(cur)
    assert len(first["rows"]) == 20 and first["more"] and first["seq"] == first["rows"][-1][0]


def test_the_hub_keeps_them_once_on_its_own_clock_and_reads_them_field_by_field(tm):
    now = time.time()
    batch = {"boot": "b1", "seq": 6, "now": now - 3600,          # the Pi's clock is an hour slow
             "rows": [[1, now - 3660, "cpu.temp", 50.0], [2, now - 3650, "cpu.temp", 50.0],
                      [3, now - 3640, "cpu.temp", 52.0], [4, now - 3630, "Bad ID!", 1.0],
                      [5, now - 3620, "cpu.temp", float("nan")], [6, now - 3610, "cpu.temp", "hot"]]}
    got = telemetry.store("pi1", batch)
    assert got["stored"] == 3 and got["first"]
    raw = telemetry.db().execute("SELECT ts, v FROM raw WHERE m='pi1' ORDER BY ts").fetchall()
    assert len(raw) == 2, "an equal value isn't kept raw again within KEEP_ANYWAY"
    assert abs(raw[0][0] - (now - 60)) < 2, "times are shifted onto the hub's clock"
    mn = telemetry.db().execute("SELECT sum(n), min(lo), max(hi) FROM minute WHERE m='pi1'").fetchone()
    assert mn == (3, 50.0, 52.0), "the summaries count every sample"
    assert telemetry.store("pi1", batch)["stored"] == 0, "a batch sent twice is kept once"
    assert telemetry.cursor("pi1")["seq"] == 6 and telemetry.items("pi1") == ["cpu.temp"]


def test_a_range_is_at_most_360_points_from_the_right_table(tm):
    now = 1_800_000_000.0
    rows, n = [], 0
    for k in range(0, 90 * 86400, 600):                    # one every 10 minutes for 90 days
        n += 1
        rows.append([n, now - k, "cpu.temp", 40 + 10 * math.sin(k / 86400)])
    # stored as if it all just arrived: write the summaries directly, raw only for the last week
    c = telemetry.db()
    for _s, ts, i, v in rows:
        if ts > now - telemetry.RETAIN["raw"]:
            c.execute("INSERT OR IGNORE INTO raw VALUES (?,?,?,?)", ("pi1", i, ts, v))
        for t, size in (("minute", 60), ("hour", 3600)):
            c.execute(f"INSERT INTO {t} VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(m,i,b) DO UPDATE SET n=n+1, "
                      "sum=sum+excluded.sum, lo=min(lo,excluded.lo), hi=max(hi,excluded.hi)",
                      ("pi1", i, int(ts // size), v, v, v, v))
    day = telemetry.series("pi1", "cpu.temp", "day", now=now)
    q = telemetry.series("pi1", "cpu.temp", "quarter", now=now)
    assert 100 < len(day["points"]) <= telemetry.POINTS and len(q["points"]) <= telemetry.POINTS
    assert q["points"][0][0] < now - 85 * 86400, "90 days reaches back 90 days"
    assert 29 < q["stats"]["min"] < 31 and 49 < q["stats"]["max"] < 51
    assert all(p[2] <= p[1] <= p[3] for p in q["points"])
    assert telemetry.series("pi1", "nothing", "week", now=now)["points"] == []
    out = telemetry.prune(now=now + 31 * 86400)
    assert out["raw"] > 0 and out["minute"] > 0
    assert telemetry.series("pi1", "cpu.temp", "quarter", now=now + 31 * 86400)["points"], "hours are kept 90 days"
    assert "▁" in telemetry.text("pi", "cpu.temp", q, "°C") or "█" in telemetry.text("pi", "cpu.temp", q, "°C")


def test_readings_ride_the_hello_to_their_own_hub_and_land_once(hz, monkeypatch):
    H, Z, loop = hz
    monkeypatch.setattr(telemetry, "BUFFER", telemetry.Buffer())
    telemetry._KEPT.clear()
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["url"] = f"127.0.0.1:{Z['lst'].port}"
        teamlink._save(d)
        lk = d["links"][0]
    now = time.time()
    for n in range(6):
        telemetry.BUFFER.add({"cpu.temp": 50.0 + n, "gpio.4": n % 2}, ts=now - 60 + n * 10)
    _on(H, loop, lambda: ties.probe([lk], force=True))
    got = ties._READ.pop(lk["id"])
    assert got["stored"] == 12 and got["first"]
    with teamlink.at(H["home"]):
        m = ties.machine_of(lk)
        s = telemetry.series(m, "cpu.temp", "day")
        assert s["stats"]["last"] == 55.0 and s["stats"]["min"] == 50.0
        assert telemetry.cursor(m)["seq"] == telemetry.BUFFER.seq
    _on(H, loop, lambda: ties.probe([lk], force=True))
    assert ties._READ.pop(lk["id"])["stored"] == 0, "the next hello asks only for what is new"


def test_the_doors():
    tl = (ROOT / "agentos/teamlink.py").read_text()
    hello = tl[tl.index('if op == "hello":'):]
    hello = hello[:hello.index("return out")]
    assert "is_my_hub(self.cfg, lk)" in hello and "BUFFER.since" in hello, "readings go to its own hub only"
    srv = (ROOT / "agentos/server.py").read_text()
    s = srv[srv.index("async def _readings_sampler"):]
    s = s[:s.index("\n_READINGS_SAID")]
    assert 'get("leader_fp")' in s and "hardware.sample" in s, "only a machine a hub set up samples"
    r = srv[srv.index('@app.get("/api/devices/readings")'):]
    assert "_require_admin()" in r[:600]
    assert "telemetry.prune" in srv[srv.index("async def _ties_check"):srv.index("async def _ties_watch")]
    js = (ROOT / "agentos/ui/src/js/24u-devchart.js").read_text()
    assert "innerHTML" not in js, "an item's name came from another machine: text nodes only"
    for need in ("function devChartOpen", "function devChartFill", "Show the numbers", "pointermove", "keydown"):
        assert need in js
    assert "devChartFill(box)" in (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert '"readings"' in (ROOT / "agentos/__main__.py").read_text()

"""Each Chat tab lists its own newest conversations (chattabs.newest_per_tab), and what ran on its
own has a tab of its own (Missions).

Reported as "the Telegram chats are not coming", then "my yesterday chats are also not coming",
then "the prompt based chats are also coming in, that should have a separate section": the list was
the newest 100 overall, and a 5-minute scan made 98 of them."""
from agentos import chattabs


def _convs():
    out = [{"id": "b1", "origin": "brief", "title": "Brief · Thu"}]
    out += [{"id": f"s{i}", "origin": "schedule", "title": f"run {i}"} for i in range(150)]
    out += [{"id": f"u{i}", "origin": "user", "title": f"yesterday {i}"} for i in range(120)]
    out += [{"id": "t1", "origin": "telegram", "title": "Telegram · PC"},
            {"id": "w1", "origin": "whatsapp", "title": "WhatsApp · Ana"}]
    return [{**c, "tab": chattabs.home_of(c, set()), "tabs": [chattabs.home_of(c, set())]} for c in out]


def test_scheduled_runs_and_the_brief_live_under_missions():
    by = {c["id"]: c["tab"] for c in _convs()}
    assert by["s0"] == by["b1"] == "missions"
    assert by["u0"] == "desktop"
    from agentos import scheduler
    assert set(scheduler.OS_ORIGINS) <= set(chattabs.AUTO)       # whatever the OS starts by itself
    assert chattabs.TABS[:2] == ("desktop", "missions") and chattabs.NAMES["missions"] == "Missions"


def test_a_busy_schedule_pushes_nothing_out():
    convs = _convs()
    kept = chattabs.newest_per_tab(convs)
    ids = [c["id"] for c in kept]
    assert "t1" in ids and "w1" in ids and "b1" in ids
    assert sum(1 for i in ids if i.startswith("u")) == chattabs.PER_TAB
    assert "u0" in ids and "u99" in ids
    assert ids == [c["id"] for c in convs if c["id"] in set(ids)]      # newest first, as given


def test_counts_are_over_everything_not_the_cut():
    n = chattabs.counts(_convs())
    assert n["desktop"] == 120 and n["missions"] == 151 and n["channels"] == 2


def test_a_huddle_kept_by_either_tab_stays():
    c = [{"id": "h", "tab": "desktop", "tabs": ["desktop", "huddles"]}]
    assert chattabs.newest_per_tab(c, n=0) == []
    assert chattabs.newest_per_tab(c, n=1) == c


def test_the_route_cuts_per_tab_and_the_page_reads_counts():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    src = (root / "agentos/server.py").read_text()
    assert "chattabs.newest_per_tab(convs)" in src and "limit=chattabs.SCAN" in src
    page = (root / "agentos/ui/src/js/10-chat.js").read_text()
    assert "d.counts?d.counts[t.id]" in page
    assert "CONVTAB==='missions'" in page and "convMisToggle" in page and "convWhen(c.updated_at)" in page
    assert "chattabs.missions(" in src and '"mission_runs": runs' in src


class _DB:
    """task_runs for two schedules: s0..s4 are runs of t1, s5 of t2."""
    def __init__(self):
        import sqlite3
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("CREATE TABLE tasks(id TEXT, prompt TEXT);"
                              "CREATE TABLE task_runs(conversation_id TEXT, task_id TEXT, prompt TEXT);")
        self.db.execute("INSERT INTO tasks VALUES('t1', '[schedule] Signal Desk 5-minute scan (paper only). Run it.')")
        self.db.execute("INSERT INTO tasks VALUES('t2', 'Watch these US Markets tickers: AAPL')")
        for i in range(5):
            self.db.execute("INSERT INTO task_runs VALUES(?, 't1', '')", (f"s{i}",))
        self.db.execute("INSERT INTO task_runs VALUES('s5', 't2', '')")


def test_runs_are_grouped_by_the_schedule_that_made_them():
    convs = chattabs.missions(_DB(), _convs())
    by = {c["id"]: c.get("mission") for c in convs}
    assert by["s0"]["key"] == by["s4"]["key"] == "task:t1"
    assert by["s0"]["name"] == "Signal Desk 5-minute scan"
    assert by["s5"]["name"] == "Watch these US Markets tickers"
    assert by["b1"]["name"] == "Your Brief" and by["u0"] is None
    n = chattabs.mission_counts(convs)
    assert n["task:t1"] == 5 and n["task:t2"] == 1


def test_a_busy_schedule_keeps_its_own_share_under_missions():
    convs = chattabs.missions(_DB(), _convs())
    kept = chattabs.newest_per_tab(convs)
    # 150 runs with no task row fall into title groups, each its own mission; t1's five all stay
    assert all(f"s{i}" in {c["id"] for c in kept} for i in range(5))
    each = {}
    for c in kept:
        if c.get("mission"):
            each[c["mission"]["key"]] = each.get(c["mission"]["key"], 0) + 1
    assert max(each.values()) <= chattabs.PER_MISSION

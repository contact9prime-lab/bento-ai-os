"""Each Chat tab lists its own newest conversations (chattabs.newest_per_tab).

Reported as "the Telegram chats are not coming": the list was the newest 100 overall, and on the
owner's machine 118 scheduled runs and briefs were newer than the last Telegram thread, so
Channels said "Telegram and WhatsApp chats show here" over chats that were there."""
from agentos import chattabs


def _convs():
    out = [{"id": f"s{i}", "origin": "schedule", "title": f"run {i}"} for i in range(150)]
    out += [{"id": f"u{i}", "origin": "user", "title": f"yesterday {i}"} for i in range(120)]
    out += [{"id": "t1", "origin": "telegram", "title": "Telegram · PC"},
            {"id": "w1", "origin": "whatsapp", "title": "WhatsApp · Ana"}]
    return [{**c, "tab": chattabs.home_of(c, set()), "tabs": [chattabs.home_of(c, set())]} for c in out]


def test_a_busy_desktop_does_not_push_phone_threads_out():
    convs = _convs()
    kept = chattabs.newest_per_tab(convs)
    ids = [c["id"] for c in kept]
    assert "t1" in ids and "w1" in ids
    assert sum(1 for c in kept if c["origin"] == "schedule") == chattabs.PER_AUTO
    assert ids == [c["id"] for c in convs if c["id"] in set(ids)]      # newest first, as given


def test_scheduled_runs_never_push_out_what_a_person_said():
    """The owner's account: a 5-minute scan made 98 of the newest 100, and yesterday's chats fell off."""
    kept = {c["id"] for c in chattabs.newest_per_tab(_convs())}
    assert sum(1 for i in kept if i.startswith("u")) == chattabs.PER_TAB
    assert "u0" in kept and "u99" in kept


def test_counts_are_over_everything_not_the_cut():
    n = chattabs.counts(_convs())
    assert n["desktop"] == 270 and n["channels"] == 2


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
    assert "var CONV_AUTO=['schedule','brief']" in page and "'Scheduled runs'" in page
    assert chattabs.AUTO == ("schedule", "brief")

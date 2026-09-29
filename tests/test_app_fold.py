"""One concept, one app: eight apps became tabs of the app their concept belongs to.

UX review S2 found four ways to schedule something (Missions, Scheduler, Automations,
the Build tab), four ways to say what is allowed (Permissions, Policies, Quarantine,
Audit) and four views of what the agent knows (Profile, Memory, Knowledge Graph, Soul).
Each existed for a reason in the code, and the code stayed: the render functions are
unchanged. What changed is that each is a TAB of one host, and `APP_FOLD` (04-wm.js)
maps the old id to that host and tab, so nothing that opens one by name breaks.

What these pin: every folded id opens its host on the right tab, is no longer a window
of its own or a tile anywhere, is findable by its old name, and repaints only while its
tab is the one on screen.
"""

import re
from pathlib import Path

JS = Path(__file__).parent.parent / "agentos" / "ui" / "src" / "js"


def _js(name: str) -> str:
    return (JS / name).read_text()


def _fold() -> dict:
    src = _js("04-wm.js")
    body = src[src.index("var APP_FOLD={"):]
    body = body[:body.index("};")]
    return {k: (h, t) for k, h, t in re.findall(r"(\w+):\{host:'(\w+)',tab:'(\w+)'\}", body)}


def _apps() -> set:
    return set(re.findall(r"^\s{2}(\w+):\{id:'\1'", _js("05-apps-registry.js"), re.M))


def test_the_eight_folded_apps_and_their_hosts():
    assert _fold() == {
        "memory": ("profile", "memory"), "kg": ("profile", "graph"), "soul": ("profile", "soul"),
        "policies": ("permissions", "rules"), "audit": ("permissions", "ledger"),
        "quarantine": ("permissions", "quarantine"),
        "tasks": ("jobs", "schedule"), "automations": ("jobs", "routines")}


def test_a_folded_app_is_not_a_window_or_a_tile():
    apps = _apps()
    for fid, (host, _tab) in _fold().items():
        assert fid not in apps, f"{fid} is still an app of its own beside its tab"
        assert host in apps, f"{fid} folds into {host}, which is not an app"
    for f, marker in (("06a-deck.js", "const DECK_DEFAULTS="), ("06-icon-layout.js", "const BENTO_GROUPS="),
                      ("05-apps-registry.js", "const DESKTOP_APPS=")):
        src = _js(f)
        block = src[src.index(marker):]
        block = block[:block.index(";")]
        for fid in _fold():
            assert f"'{fid}'" not in block, f"{f} still lists '{fid}' as a tile"


def test_each_host_draws_the_tab():
    perm, profile, jobs = _js("20-permissions.js"), _js("12-memory-profile.js"), _js("14a-jobs.js")
    assert "['rules','Rules'],['ledger','Ledger']" in perm
    assert "rules:b=>renderPolicies(b),ledger:b=>renderAudit(b,PERM.w)" in perm
    assert "['memory','Memory'],['graph','Graph'],['soul','Soul']" in profile
    assert "{memory:renderMemory,graph:renderKG,soul:renderSoul}" in profile
    assert "var JOB_TABS=['run','build','schedule','routines'];" in jobs
    assert "JOBS.tab==='schedule'?renderTasks:renderAutomations" in jobs


def test_the_old_id_opens_the_host_on_its_tab():
    wm = _js("04-wm.js")
    alias = wm[wm.index("function appAlias("):]
    alias = alias[:alias.index("\n}")]
    assert "foldGo(f.host,f.tab);return f.host" in alias
    op = wm[wm.index("function openApp("):]
    op = op[:op.index("function openAppNew")]
    assert "if(asked!==id)w.app.render(" in op, "an open host must move to the tab asked for"


def test_a_folded_app_repaints_only_while_its_tab_shows():
    """refreshApp('audit') runs on a ten-second tick; it must not redraw the map."""
    wm = _js("04-wm.js")
    body = wm[wm.index("function refreshApp("):]
    body = body[:body.index("\n}\n")]
    assert "if(foldTab(f.host)!==f.tab)return" in body


def test_every_folded_app_is_findable_by_its_old_name():
    places = _js("05b-places.js")
    for fid in _fold():
        assert f"placeFold('{fid}')" in places, f"typing the old name of {fid} finds nothing"


def test_the_graph_stops_when_its_tab_or_window_goes():
    profile, reg = _js("12-memory-profile.js"), _js("05-apps-registry.js")
    assert "if(PROFILE_TAB!=='graph')profileStopGraph(w)" in profile
    assert "onClose(w){profileStopGraph(w);return true}" in reg


def test_the_state_the_window_manager_reads_is_not_a_top_level_let():
    """foldTab reads PERM from 04-wm.js, which loads first; a `let` there is the
    temporal-dead-zone trap CLAUDE.md names."""
    assert "\nvar PERM={" in _js("20-permissions.js")
    assert "\nvar PROFILE_TAB=" in _js("12-memory-profile.js")
    assert "\nvar JOBS=" in _js("14a-jobs.js")

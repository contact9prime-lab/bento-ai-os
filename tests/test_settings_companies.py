"""Settings → Companies, sub-sections in Settings, and keeping your place.

"I need it in the settings please, and all the confusion in the settings is so much messed
up, we need sub settings. Also when I am changing the settings it takes me to the top of the
page." What these defend:

- one company, open or parked, is read whole (what it is, its departments, its folders, its
  Brief flag) and its name, line and objective are changed where it lives, open or parked;
- a name another of the person's companies has is refused in a sentence;
- the routes say so over HTTP, and an unknown company is a 404;
- every section the Settings chips offer starts at a card title that exists in the page's
  source, so a renamed card cannot silently drop its chip;
- a redraw of Settings keeps the pane where it was (measured: master put a pane scrolled to
  600px back at 0; this branch kept it at 600), and only the same tab does;
- the Companies tab is in Settings, its place is in the launchers, and a Zero has none.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import company                                           # noqa: E402
from agentos.memory import Store                                      # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos" / "ui" / "src" / "js"


def _two(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cfg = {"agent_name": "Aria", "workspace": str(ws),
           "company": {"name": "Bhav Capital", "about": "options on Indian indices"},
           "office": {"departments": [{"name": "Tech", "members": ["tech-lead", "qa"], "lead": "tech-lead"}]}}
    store = Store(tmp_path / "a.db")
    for n in ("tech-lead", "qa"):
        store.save_subagent({"name": n, "soul": n, "tools": ["read_file"]})
    company.create(cfg, store, "Kidstube", about="a kids channel")
    return cfg, store


def test_one_company_is_read_whole_open_or_parked(tmp_path):
    cfg, store = _two(tmp_path)
    ids = {c["name"]: c["id"] for c in company.companies(cfg)}
    open_ = company.detail(cfg, store, ids["Kidstube"])
    assert open_["active"] is True and open_["name"] == "Kidstube"
    parked = company.detail(cfg, store, ids["Bhav Capital"])
    assert parked["active"] is False and parked["about"] == "options on Indian indices"
    tech = next(d for d in parked["departments"] if d["name"] == "Tech")
    assert tech["head"] == "tech-lead" and tech["people"] == 2
    assert parked["folders"]["inherit"] is True and parked["brief"] is True
    with pytest.raises(KeyError):
        company.detail(cfg, store, "deadbeef")


def test_a_parked_company_is_edited_where_it_lives(tmp_path):
    cfg, store = _two(tmp_path)
    ids = {c["name"]: c["id"] for c in company.companies(cfg)}
    company.update_profile(cfg, ids["Bhav Capital"], {"about": "index options", "objective": "steady returns"})
    assert cfg["company"]["name"] == "Kidstube", "the open company is left alone"
    rec = cfg["companies"][ids["Bhav Capital"]]["company"]
    assert rec["about"] == "index options" and rec["objective"] == "steady returns"
    company.update_profile(cfg, ids["Kidstube"], {"name": "Kids Learn"})
    assert cfg["company"]["name"] == "Kids Learn"
    with pytest.raises(ValueError, match="already have a company called"):
        company.update_profile(cfg, ids["Kidstube"], {"name": "bhav capital"})
    with pytest.raises(ValueError, match="needs a name"):
        company.update_profile(cfg, ids["Kidstube"], {"name": "  "})


def test_the_routes():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        cfg = servermod.state["cfg"]
        had = {k: cfg.get(k) for k in ("company", "companies", "office")}
        try:
            cfg["company"] = {"name": "Forge", "about": "metal"}
            one = cl.get("/api/companies/one").json()
            assert one["name"] == "Forge" and "departments" in one and "folders" in one
            assert cl.get("/api/companies/one?id=deadbeef").status_code == 404
            r = cl.put("/api/companies/one", json={"about": "steel and iron"})
            assert r.status_code == 200 and r.json()["company"]["about"] == "steel and iron"
            r = cl.put("/api/companies/one", json={"id": "deadbeef", "about": "x"})
            assert r.status_code == 404
        finally:
            for k, v in had.items():
                if v is None:
                    cfg.pop(k, None)
                else:
                    cfg[k] = v


def _subs():
    src = (JS / "11l-setsubs.js").read_text()
    body = src[src.index("var SETSUBS={"):src.index("};", src.index("var SETSUBS={"))]
    out = {}
    for tab, rows in re.findall(r"^\s+(\w+):\[(.*)\],?$", body, re.M):
        out[tab] = re.findall(r"\['([^']+)','([^']+)'\]", rows)
    return out


def test_every_section_starts_at_a_card_that_exists():
    subs = _subs()
    assert set(subs) >= {"ai", "agent", "companies", "network", "channels", "accounts", "system"}
    every = "\n".join(f.read_text() for f in JS.glob("*.js"))
    for tab, rows in subs.items():
        assert len(rows) >= 2, tab
        for label, title in rows:
            assert len(label) <= 22, (tab, label)
            # a card's title is written as a heading (or a group title) somewhere in the page
            assert re.search(r"(<h3[^>]*>|pGroup\(['`]|chsec[^>]*>|h3:\s*['`])" + re.escape(title), every) \
                or f">{title}" in every or f"'{title}" in every, (tab, title)


def test_a_redraw_keeps_your_place():
    st = (JS / "11-settings.js").read_text()
    render = st[st.index("function renderSettings(body)"):]
    render = render[:render.index("\nfunction ", 10)]
    assert "setKeepTake(body)" in render and "setKeepGive(body,keep)" in render
    assert render.index("setKeepTake(body)") < render.index("innerHTML"), "taken before the redraw"
    assert "setSubsApply(pm)" in render and "setKeepHold(pm)" in render
    subs = (JS / "11l-setsubs.js").read_text()
    # another tab starts at its top; the same tab keeps its place; scrolling ends the hold
    assert "k.tab===SETTAB" in subs and "main.scrollTop=0" in subs
    assert "'wheel','touchstart','keydown'" in subs
    # the row goes away while searching: a search shows every card of every tab
    assert "classList.contains('searching')" in subs


def test_a_card_scrolled_to_shows_its_section_first():
    for f, el in (("11d-accounts.js", "c"), ("11i-clouddeploy.js", "el"), ("11b-openclaw.js", "out"),
                  ("24n-network.js", "m"), ("11-settings.js", "e")):
        t = (JS / f).read_text()
        assert f"setSubReveal({el})" in t, f


def test_the_companies_tab_has_a_home_everywhere():
    st = (JS / "11-settings.js").read_text()
    assert "['companies','" in st and 'id="co-set"' in st
    assert "coSetPaint()" in st
    places = (JS / "05b-places.js").read_text()
    assert "placeSettings('companies')" in places
    assert "'companies'" in (JS / "00k-zeroface.js").read_text()
    co = (JS / "11k-companies.js").read_text()
    for route in ("/api/companies/one", "/api/companies/active", "/api/company/folders", "/api/brief/schedule"):
        assert route in co, route
    # the folders card is the Office panel's own drawing, never a second one
    assert "companyFoldersHTML(" in co and "companyFoldersWire(" in co
    # a field here never matches the page-wide auto save, which would write the open company
    pat = re.search(r"SET_AUTO\s*=\s*/(.+?)/", st)
    if pat:
        for fid in ("co-s-name", "co-s-about", "co-s-goal", "co-n-name"):
            assert not re.search(pat.group(1), fid), fid


def test_the_terminal_edits_a_company(tmp_path):
    import json
    import subprocess
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "ws").mkdir()
    (home / "config.json").write_text(json.dumps({"workspace": str(tmp_path / "ws"), "setup_complete": True,
                                                  "port": 8996, "company": {"name": "Forge"}}))
    env = {**os.environ, "AGENTOS_HOME": str(home), "NO_COLOR": "1", "AGENTOS_VAULT_KEYRING": "0"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "company", *a], cwd=ROOT,  # noqa: E731
                                    env=env, capture_output=True, text=True, timeout=60)
    r = run("edit", "Forge", "--about", "a machine shop", "--rename", "Forgeline")
    assert r.returncode == 0 and "Forgeline" in r.stdout, r.stdout + r.stderr
    co = json.loads((home / "config.json").read_text())["company"]
    assert co["name"] == "Forgeline" and co["about"] == "a machine shop"
    r = run("edit", "Forgeline")
    assert r.returncode == 1 and "say what to change" in r.stdout

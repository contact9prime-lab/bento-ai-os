"""The menu bar fits its screen, and the machine's network is on it.

Reported with a 1366x768 screenshot: the space chip lay over Window and Help, the brand
wrapped onto two lines and the clock onto three. Then: "it is not showing a wifi option on
the top". Measured in Chrome at 1920, 1440, 1366, 1280, 1024, 930 and a 390px phone; these
pin the rules that came out of it."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "agentos" / "ui" / "src"
CSS = (SRC / "css" / "44-menubar-fit.css").read_text()
FIT = (SRC / "js" / "04g-menubar-fit.js").read_text()
NET = (SRC / "js" / "22b-traynet.js").read_text()
SHELL = (SRC / "shell.html").read_text()


def test_nothing_in_the_bar_shrinks_or_wraps_but_the_spacer():
    assert "#menubar>*,#tray>*{flex-shrink:0;white-space:nowrap}" in CSS
    assert re.search(r"#menubar>#mb-spacer\{flex:1 1 0;min-width:0\}", CSS)


def test_every_step_the_fit_takes_has_a_rule_and_none_is_skipped():
    top = int(re.search(r"max:(\d+)", FIT).group(1))
    for i in range(1, top + 1):
        assert f"#menubar.f{i} " in CSS, f"step f{i} hides nothing"
    assert f"#menubar.f{top + 1} " not in CSS


def test_the_order_gives_up_the_least_useful_first():
    step = {m.group(2): int(m.group(1)) for m in re.finditer(r"#menubar\.f(\d+) ([^{,]+)", CSS)}
    assert step["#tbclock .dt"] < step["#mb-name"] < step["#mbmenus button:not(.mbm-all)"]
    # the app's menus are the last thing a desktop-sized bar folds
    assert step["#mbmenus button:not(.mbm-all)"] == max(v for k, v in step.items()
                                                           if "fwdchip" not in k and "mbspace" not in k
                                                           and "mb-user" not in k)


def test_folding_is_css_so_it_never_repaints_the_menus():
    app = (SRC / "js" / "04b-appmenu.js").read_text()
    assert 'class="mbm-all"' in app and "mbFolded(set)" in app
    assert "#mbmenus .mbm-all{display:none" in CSS


def test_the_fit_does_not_watch_its_own_classes():
    # it toggles `class` on #menubar; watching that attribute would loop
    assert "attributeFilter:['hidden']" in FIT


def test_the_network_button_starts_hidden_and_only_joins_through_the_admin_route():
    assert '<button id="tray-net" type="button" hidden' in SHELL
    assert NET.count("/api/wifi/connect") == 1
    # from another device it asks first: that device may lose the page
    assert "remoteClient()&&typeof osConfirm" in NET
    # a scan only while the panel is open
    assert "trayNetLoad(false)" in NET and "setInterval" not in NET


def test_the_connect_route_is_still_a_machine_route():
    mr = (Path(__file__).resolve().parent.parent / "agentos" / "machineroutes.py").read_text()
    assert '"/api/wifi/connect"' in mr


def test_the_right_edge_is_used_before_anything_is_hidden():
    body = FIT[FIT.index("function menubarFit()"):]
    assert body.index("menubarRail(1)") < body.index("set(1)") < body.index("menubarRail(2)") < body.index("set(n)}")
    # the chips that carry words go only after the plain icons
    first = FIT[FIT.index("var MBRAIL_STAGES"):].split("\n")[0]
    assert "'mb-user'" in first.split("],[")[1] and "'fwdchip'" in first.split("],[")[1]
    # moved, never copied: one element per id, its handlers with it
    assert "rail.appendChild(e)" in FIT and "cloneNode" not in FIT
    assert '<div id="mbrail"' in SHELL


def test_a_window_stops_at_the_rail():
    assert "body.mb-rail #desktop{right:var(--railw)}" in CSS


def test_no_rail_where_native_windows_would_cover_it_or_on_a_phone():
    allowed = FIT[FIT.index("function menubarRailAllowed"):FIT.index("function menubarRail(")]
    assert "suiActive()" in allowed and "dev-mobile" in allowed and "kiosk" in allowed


def test_the_fit_drops_its_own_moves_from_the_observer():
    assert "MBFIT.obs.takeRecords()" in FIT


def test_the_fit_measures_with_no_transition_running():
    """With Reduce Motion on, every transition is .01ms rather than none, so a class changed
    by the fit was read back at its old size: a phone's bar 547px wide on a 390px screen was
    called a fit at f2, and the brain chip lay over the clock and the power button."""
    body = FIT.split("function menubarFit(){", 1)[1].split("function menubarFitSoon", 1)[0]
    assert body.index("classList.add('mbfit')") < body.index("set(0)")
    assert body.index("classList.remove('mbfit')") > body.index("MBFIT.n=n")
    assert "#menubar.mbfit *" in CSS and "transition:none!important" in CSS


def test_a_phone_dock_is_sized_in_whole_icons():
    """Snapping keeps one edge of a scrolling row whole. The other showed half an icon, whose
    centre is outside its own row: the eighth default icon spanned x=364..404 in a row that
    ended at 374."""
    dock = (SRC / "js" / "06b-dockfit.js").read_text()
    assert "Math.floor((avail+gap)/pitch)" in dock
    assert "dev-mobile" in dock, "only a phone's dock scrolls"
    assert "ResizeObserver" in dock and "MutationObserver" in dock
    assert "setInterval" not in dock


def test_a_phone_bar_holds_its_own_buttons():
    """The bar was 34px and its touch buttons 36, so each stood out of it."""
    resp = (SRC / "css" / "15-responsive.css").read_text()
    assert "body.dev-mobile{--mbh:38px;" in resp
    assert "body.dev-touch #omnibar button,body.dev-touch #tray button{min-width:36px;min-height:36px}" in resp

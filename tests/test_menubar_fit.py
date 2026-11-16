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

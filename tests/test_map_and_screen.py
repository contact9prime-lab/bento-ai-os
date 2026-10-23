"""The maps, the Pi's screen after an update, and Update on a Pi that is current.

Reported on the owner's hub: "the desktop is flickering like crazy", "this map is not making any
sense, too cluttered … zoom out to see things, zoom in to see more, click a node or search", "after
the update I lost the Pi, it is not showing Bento", and "clicking Update is not working on the Pi".
What these defend:

  * every map is the one zoomable view, a fixed window (contain:strict), showing one place at a time:
    the Agents map drew 2,448 curves on a 1034x2794 sheet in a blurred window, and Chrome re-tiled
    it on every scroll;
  * the screen's browser is started in a unit of its own, so a restart of Bento (every update) no
    longer takes it down, and a screen with nothing showing is opened again, not reported as such;
  * a Pi already on the hub's version is told so, rather than "updating" for good.
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import screen, ties   # noqa: E402

ROOT = Path(__file__).parent.parent
JS = ROOT / "agentos/ui/src/js"


def test_every_map_is_the_one_zoomable_view():
    zm = (JS / "24s-zmap.js").read_text()
    css = (ROOT / "agentos/ui/src/css/36-zmap.css").read_text()
    assert re.search(r"\.zm\{[^}]*contain:strict", css), "its repaints stay inside its window"
    assert re.search(r"\.zm\{[^}]*height:min\(", css), "a fixed window, whatever the size of the team"
    for fn in ("function zmLogical(", "function zmPhysical(", "function zmSelect(", "function zmFit("):
        assert fn in zm, fn
    assert "st.focus" in zm and "zm-up" in zm and "zm-q" in zm, "one place at a time, the way back, and search"
    hands = (JS / "11e-hands.js").read_text()
    assert "agraph-canvas" not in hands and "zmMount(box,zmLogical(tree)" in hands, "the Agents map"
    dev = (JS / "24o-devices.js").read_text()
    assert "zmPhysical(NET.v)" in dev and "dev-logical" in dev, "Devices: physical and logical"
    topo = (JS / "24r-topology.js").read_text()
    assert "zmLogical(TOPO.tree)" in topo and "zmPhysical(nv)" in topo, "Network & Teams → Maps"


def test_the_screens_browser_lives_outside_the_server(monkeypatch, tmp_path):
    monkeypatch.setattr(screen.shutil, "which", lambda x: "/usr/bin/systemd-run" if x == "systemd-run" else None)
    real = screen.Path.exists
    monkeypatch.setattr(screen.Path, "exists", lambda self: True if str(self).endswith("/systemd") else real(self))
    monkeypatch.setattr(screen, "_wayland", lambda: "/run/user/1000/wayland-0")
    argv = screen.open_argv()
    assert argv[:2] == ["systemd-run", "--user"] and "--setenv=WAYLAND_DISPLAY=wayland-0" in argv
    assert argv[-3:] == ["agentos", "screen", "run"]
    monkeypatch.setattr(screen.shutil, "which", lambda x: None)
    assert screen.open_argv()[1:] == ["-m", "agentos", "screen", "run"], "no systemd: as before"


def test_a_screen_with_nothing_showing_is_opened_again(monkeypatch, tmp_path):
    auto = tmp_path / "bento-screen.desktop"
    auto.write_text("[Desktop Entry]\n")
    monkeypatch.setattr(screen, "AUTOSTART", auto)
    monkeypatch.setattr(screen, "close_now", lambda: 0)
    monkeypatch.setattr(screen, "road", lambda: ("desktop", ""))
    opened = []
    monkeypatch.setattr(screen, "open_now", lambda cfg=None: opened.append(1) or True)
    assert screen.restart_now({}, wait=0.1) == "opened Bento on its screen again" and opened
    auto.unlink()
    assert "no browser" in screen.restart_now({}, wait=0.1), "a machine that never opens its screen is left alone"
    src = (ROOT / "agentos/server.py").read_text()
    assert "screenmod.showing() or screenmod.AUTOSTART.exists()" in src, "checked after every start"


def test_update_on_a_current_pi_says_so(monkeypatch):
    from agentos import __version__, teamlink
    from agentos import zero as zeromod
    monkeypatch.setattr(zeromod, "ships_to", lambda lk: True)
    lk = {"id": "z9", "label": "pi"}

    says = {"v": __version__}

    async def probe(lks, force=False, wait=0):
        ties._VERSION["z9"] = says["v"]
    monkeypatch.setattr(ties, "probe", probe)
    called = []

    async def call(*a, **k):
        called.append(1)
        return {"ok": True}
    monkeypatch.setattr(teamlink, "call", call)
    got = asyncio.run(ties.ask_update(lk))
    assert got["ok"] and got["current"] and "already on" in got["said"] and not called
    says["v"] = "0.0.1"
    got = asyncio.run(ties.ask_update(lk))
    assert called and not got.get("current"), "one that is behind is still asked"
    js = (JS / "24p-ties.js").read_text()
    assert "if(r.current)" in js

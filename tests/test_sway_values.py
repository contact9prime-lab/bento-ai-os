"""Every value that reaches sway is one shape, because a newline or `;` is a second command run
as the server's user (S-32). /api/nightlight learned this first; its neighbours had not.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient                           # noqa: E402

from agentos import compositor, session                             # noqa: E402
from agentos import server as servermod                             # noqa: E402
from agentos import users as usersmod                               # noqa: E402

EVIL = ['us"\nexec_always id>/tmp/x', "us\nexec_always id", "1920x1080;exec id", "a b", "x\x00y", '"; exec id; "']


@pytest.mark.parametrize("v", EVIL)
def test_a_keyboard_layout_cannot_become_a_config_line(v):
    for k in ("layout", "variant", "options"):
        text = session.input_config_text({"keyboard": {k: v}})
        assert "exec" not in text
        with pytest.raises(ValueError):
            session.clean_keyboard({k: v}, strict=True)


def test_real_keyboard_values_survive():
    text = session.input_config_text({"keyboard": {"layout": "us,in", "variant": "dvorak",
                                                   "options": "ctrl:nocaps,grp:alt_shift_toggle",
                                                   "repeat_rate": 30}})
    assert 'xkb_layout "us,in"' in text and "ctrl:nocaps,grp:alt_shift_toggle" in text and "repeat_rate 30" in text


@pytest.mark.parametrize("field", ["name", "mode", "scale", "transform", "position"])
@pytest.mark.parametrize("v", EVIL)
def test_an_output_value_cannot_become_a_command(field, v):
    with pytest.raises(ValueError):
        compositor.clean_output({field: v})


def test_a_saved_layout_with_a_bad_value_is_left_out(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SWAY_DROPIN_DIR", tmp_path)
    p = session.write_output_config([{"name": "HDMI-A-1", "mode": "1920x1080@60Hz", "scale": 1.5,
                                      "transform": "90", "position": "0,0"},
                                     {"name": "DP-1", "mode": "1x1\nexec_always id"}])
    text = p.read_text()
    assert "HDMI-A-1" in text and "mode 1920x1080@60Hz" in text and "transform 90" in text
    assert "DP-1" not in text and "exec_always" not in text


def test_configure_output_refuses_before_it_reaches_ipc():
    c = compositor.Compositor.__new__(compositor.Compositor)
    sent = []
    c.command = sent.append
    with pytest.raises(ValueError):
        c.configure_output("DP-1", mode="1920x1080; exec id")
    with pytest.raises(ValueError):
        c.configure_output('DP-1"; exec id; "', scale=1.0)
    assert not sent
    c.configure_output("DP-1", mode="1920x1080@60Hz", scale=1.25, transform="flipped-90", position=(0, 0))
    assert sent == ['output "DP-1" mode 1920x1080@60Hz scale 1.25 transform flipped-90 position 0 0']


@pytest.mark.parametrize("keys", ["Ctrl+a\nexec_always id", "Ctrl+;exec id", "Ctrl+a b", "Ctrl+\x01"])
def test_a_shortcut_cannot_become_a_config_line(tmp_path, monkeypatch, keys):
    monkeypatch.setattr(session, "SWAY_DROPIN_DIR", tmp_path)
    assert session._sway_binding(keys) == ""


def test_real_shortcuts_survive():
    assert session._sway_binding("Ctrl+Shift+A") == "Ctrl+Shift+a"
    assert session._sway_binding("Alt+Space") == "Mod1+space"
    assert session._sway_binding("Super+F3") == "Mod4+F3"


def test_a_locale_value_cannot_become_a_shell_line(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "LOCALE_ENV", tmp_path / "locale.env")
    session.write_locale_env({"TZ": 'x"; id>/tmp/x; "', "LANG": "en_IN.UTF-8", "LC_TIME": "a\nb"})
    text = (tmp_path / "locale.env").read_text()
    assert 'LANG="en_IN.UTF-8"' in text and "id>" not in text and "LC_TIME" not in text


@pytest.fixture()
def admin_only_routes():
    usersmod.reset_caches()
    with TestClient(servermod.app) as cl:
        yield cl
    usersmod.reset_caches()


def test_the_routes_refuse_with_a_sentence(admin_only_routes, tmp_path, monkeypatch):
    monkeypatch.setattr(session, "SWAY_DROPIN_DIR", tmp_path)
    c = admin_only_routes
    r = c.post("/api/input", json={"keyboard": {"layout": 'us"\nexec_always id'}})
    assert r.status_code == 400 and "keyboard" in r.json()["error"]
    assert not (tmp_path / "input.conf").exists()
    assert c.post("/api/input", json={"keyboard": {"repeat_rate": "x"}}).status_code == 400
    r = c.post("/api/wm/outputs", json={"name": "DP-1", "mode": "1x1; exec id"})
    assert r.status_code == 400 and "display" in r.json()["error"]
    assert c.post("/api/input", json={"keyboard": {"layout": "us"}}).status_code == 200
    assert 'xkb_layout "us"' in (tmp_path / "input.conf").read_text()

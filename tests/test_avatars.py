"""The crew's characters: one face per agent, the same one everywhere it appears.

What these defend: a character is generated once, stored, and deterministic; no
two live agents share a shirt colour and your agent always wears teal; a change
can only come from the closed set, and a refusal names the choices; the painter
keeps the rules four drawing passes taught (two eyes that read on every skin, a
lip-coloured mouth, glasses that do not mask, hands and shoes, one outline pass);
the PNG, the face crop, the sheet and the terminal are cut from ONE grid; and the
editor, the agent's tool and the CLI all reach the same rows through the same gate.
"""

import asyncio
import os
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import avatars as av                                   # noqa: E402
from agentos import policy                                          # noqa: E402
from agentos.memory import Store                                    # noqa: E402
from agentos.tools import TOOL_SCHEMAS, Toolbox                     # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "a.db")
    for n in ("researcher", "writer", "validator"):
        s.save_subagent({"name": n, "soul": n, "tools": []})
    return s


CFG = {"agent_name": "Aria"}


def _px(buf, x, y):
    i = (y * av.W + x) * 4
    return tuple(buf[i:i + 4])


def _base(**kw):
    rec = {"skin": 1, "hair": 0, "style": "short", "pants": 0, "glasses": False,
           "blush": False, "hue": 34}
    rec.update(kw)
    return rec


# ---- generation -----------------------------------------------------------------

def test_a_character_is_deterministic_and_the_agent_wears_teal():
    assert av.generate("researcher") == av.generate("researcher")
    assert any(av.generate("researcher", salt=k) != av.generate("researcher") for k in range(1, 6)), \
        "a reroll's salt must be able to change the look"
    assert av.generate(av.AGENT)["hue"] == av.AGENT_HUE
    # nobody else is handed the agent's colour, however their hash falls
    for n in ("a", "b", "c", "d", "e", "f", "g", "h", "researcher", "writer"):
        assert av.generate(n)["hue"] != av.AGENT_HUE


def test_everybody_gets_one_stored_and_no_two_share_a_shirt(store):
    people = av.ensure(store, CFG)
    keys = [p["key"] for p in people]
    assert keys[:2] == [av.AGENT, av.ME] and set(keys[2:]) == {"researcher", "writer", "validator"}
    hues = [p["recipe"]["hue"] for p in people if p["key"] != av.ME]
    assert len(hues) == len(set(hues)), "two agents in one colour"
    # stored, so reading again changes nothing — and adding a colleague recolours nobody
    before = {p["key"]: p["recipe"] for p in people}
    store.save_subagent({"name": "analyst", "soul": "x", "tools": []})
    after = {p["key"]: p["recipe"] for p in av.ensure(store, CFG)}
    assert all(after[k] == v for k, v in before.items())
    assert after["analyst"]["hue"] not in {before[k]["hue"] for k in before if k != av.ME}


def test_a_character_is_never_invented_for_somebody_who_is_not_there(store):
    av.ensure(store, CFG)
    n = len(store.avatar_all())
    # a log line from a deleted specialist still gets a stable face...
    assert av.recipe_for(store, "ghost") == av.recipe_for(store, "ghost")
    assert len(store.avatar_all()) == n, "...without a row being written for it"
    with pytest.raises(KeyError):
        av.update(store, CFG, "ghost", {"hair": "pink"})
    with pytest.raises(KeyError):
        av.reroll(store, CFG, "ghost")


def test_characters_are_per_person_not_per_space():
    """Nothing in the module reads a space: switching project never changes who
    your colleagues look like. The rows live in the person's own database."""
    src = (ROOT / "agentos" / "avatars.py").read_text()
    assert "space_id" not in src.split('"""', 2)[2]
    mem = (ROOT / "agentos" / "memory.py").read_text()
    table = mem.split("CREATE TABLE IF NOT EXISTS avatars")[1].split(");")[0]
    assert "space_id" not in table


# ---- the closed set ----------------------------------------------------------------

def test_a_change_comes_from_the_closed_set_or_is_refused_with_the_choices():
    assert av.validate({"hair": "dark-brown"}) == {"hair": 1}      # typed on a command line
    assert av.validate({"hair": "Dark_Brown"}) == {"hair": 1}
    assert av.validate({"shirt": "violet"}) == {"hue": 264}
    assert av.validate({"glasses": "yes", "blush": "off"}) == {"glasses": True, "blush": False}
    with pytest.raises(ValueError, match="pink"):
        av.validate({"hair": "#ff00ff"})
    with pytest.raises(ValueError, match="curly"):
        av.validate({"style": "mohawk"})
    with pytest.raises(ValueError, match="teal"):
        av.validate({"shirt": 173})                                   # a hue, but not one of ours
    with pytest.raises(ValueError, match="not part of a character"):
        av.validate({"hat": "top"})
    with pytest.raises(ValueError):
        av.validate({"skin": True})                                   # a bool is not an index
    # a broken stored row still paints a face rather than failing
    assert av.clean({"skin": 99, "style": "?"})["style"] == "short"


def test_an_edit_sticks_and_a_reroll_keeps_the_colour(store):
    av.ensure(store, CFG)
    hue = av.recipe_for(store, "writer")["hue"]
    rec = av.update(store, CFG, "writer", {"style": "bun", "glasses": True})
    assert rec["style"] == "bun" and rec["glasses"] and rec["hue"] == hue
    assert av.recipe_for(store, "writer") == rec
    assert av.reroll(store, CFG, "writer")["hue"] == hue, "the shirt is how this one is told apart"
    assert av.describe({**rec, "hue": 34}).count("an amber shirt") == 1   # not "a amber"


# ---- the painter ------------------------------------------------------------------

def test_a_face_is_two_eyes_that_read_on_every_skin():
    """Two eyes, never one centred mark (that made the first cut frightening). The
    eye ink is chosen against the skin: the outline shade on deep skin was eyes you
    had to know were there."""
    for skin in range(len(av.SKINS)):
        buf = av.paint(_base(skin=skin))
        sk = av.SKINS[skin][1]
        for x in (6, 9):
            eye = _px(buf, x, 8)[:3]
            assert abs(av._lum(eye) - av._lum(sk)) > 60, f"eye lost on {av.SKINS[skin][0]} skin"
        assert _px(buf, 7, 8)[:3] == _px(buf, 8, 8)[:3], "nothing in the middle of the face"
    blink = av.paint(_base(), frame=1)
    assert _px(blink, 6, 7)[:3] != _px(av.paint(_base()), 6, 7)[:3], "no blink frame"


def test_the_mouth_is_a_lip_and_glasses_do_not_mask_the_face():
    buf = av.paint(_base(skin=0))
    sk = av.SKINS[0][1]
    mouth = _px(buf, 7, 10)[:3]
    assert mouth[0] > mouth[1] and mouth[0] > mouth[2], "a mouth is redder than the face"
    assert mouth != av._tone(sk, .55), "a darker skin under the nose reads as a goatee"
    g = av.paint(_base(skin=4, glasses=True))
    lens = [_px(g, x, 7)[:3] for x in (5, 7, 8, 10)]
    assert all(av._lum(c) > 180 for c in lens), "glasses need a pale lens"
    assert av._lum(_px(g, 6, 8)[:3]) < 40 and av._lum(_px(g, 9, 8)[:3]) < 40, "the eyes are still there"


def test_limbs_end_in_hands_and_shoes_and_working_waves_one_arm_then_the_other():
    rec = _base()
    sk = av.SKINS[1][1]
    stand, left, right = av.paint(rec, 0), av.paint(rec, 2), av.paint(rec, 3)
    assert _px(stand, 2, 17)[:3] == sk and _px(stand, 13, 17)[:3] == sk, "no hands"
    assert _px(left, 2, 8)[:3] == sk and _px(left, 13, 17)[:3] == sk, "frame 2: left arm up"
    assert _px(right, 13, 8)[:3] == sk and _px(right, 2, 17)[:3] == sk, "frame 3: right arm up"
    assert _px(stand, 5, 24)[3] and _px(stand, 10, 24)[3], "no shoes"


def test_every_character_is_outlined_in_its_own_colour_by_one_pass():
    for style in av.STYLES:
        buf = av.paint(_base(style=style, hue=264))
        ln = av._hsl(264, .28, .13)
        # after the pass, nothing but the line itself touches empty space: skin,
        # hair or shirt beside a transparent pixel would be a gap in the outline
        for y in range(av.H):
            for x in range(av.W):
                p = _px(buf, x, y)
                if not p[3] or p[:3] == ln:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    assert 0 <= nx < av.W and 0 <= ny < av.H and _px(buf, nx, ny)[3], (style, x, y)
        for y in range(av.H):
            row = [x for x in range(av.W) if _px(buf, x, y)[3]]
            if row:
                assert _px(buf, row[0], y)[:3] == ln and _px(buf, row[-1], y)[:3] == ln, (style, y)


# ---- one grid, four outputs -------------------------------------------------------------

def _png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", b[16:24])


def test_the_png_the_face_and_the_sheet_are_cut_from_one_grid():
    rec = _base()
    assert _png_size(av.png_of(rec)) == (16, 26)
    assert _png_size(av.png_of(rec, crop="face")) == (14, 14)
    assert _png_size(av.png_of(rec, sheet=True)) == (64, 26)
    assert _png_size(av.png_of(rec, scale=4)) == (64, 104)
    assert _png_size(av.png_of(rec, scale=999)) == (16 * 12, 26 * 12), "scale is capped"
    # the sheet's frames ARE the frames
    w, h, sheet = av.image(rec, sheet=True)
    for f in range(av.FRAMES):
        one = av.paint(rec, f)
        for y in (7, 8, 17):
            row = sheet[(y * w + f * 16) * 4:(y * w + f * 16 + 16) * 4]
            assert row == bytes(one[y * 16 * 4:(y + 1) * 16 * 4]), (f, y)
    # and the PNG decodes back to the grid (filter byte 0 per row, then RGBA)
    b = av.png_of(rec)
    n = struct.unpack(">I", b[33:37])[0]
    assert b[37:41] == b"IDAT"
    raw = zlib.decompress(b[41:41 + n])
    assert b"".join(raw[y * 65 + 1:(y + 1) * 65] for y in range(26)) == bytes(av.paint(rec, 0))


def test_the_terminal_draws_the_same_pixels_two_rows_a_line():
    rec = _base(hue=96)
    lines = av.terminal(rec, crop="face")
    assert len(lines) == 7                                   # 14 rows, two per line
    sk = av.SKINS[1][1]
    assert any(f"38;2;{sk[0]};{sk[1]};{sk[2]}m" in ln or f"48;2;{sk[0]};{sk[1]};{sk[2]}m" in ln
               for ln in lines), "the terminal's face is not the desktop's skin"
    assert len(av.terminal(rec)) == 13


def test_the_editor_offers_exactly_what_validate_accepts():
    pal = av.palette()
    for s in pal["skin"]:
        assert av.validate({"skin": s["i"]}) == {"skin": s["i"]}
    for s in pal["shirt"]:
        assert av.validate({"hue": s["hue"]}) == {"hue": s["hue"]}
    assert pal["style"] == av.STYLES


# ---- the doors: routes, tool, CLI --------------------------------------------------------

@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from agentos import server as servermod
    with TestClient(servermod.app) as cl:
        s = servermod.state["store"]
        s.db.execute("DELETE FROM avatars")
        s.db.commit()
        yield cl, servermod


def test_the_routes_list_paint_edit_and_refuse(client):
    cl, servermod = client
    sent = []

    async def fake(msg):
        sent.append(msg)
    servermod.state["broadcast"], real = fake, servermod.state["broadcast"]
    try:
        d = cl.get("/api/avatars").json()
        assert d["avatars"][0]["key"] == "@agent" and d["palette"]["style"] == av.STYLES
        r = cl.get("/api/avatar.png", params={"key": "@agent", "crop": "face"})
        assert r.headers["content-type"] == "image/png" and _png_size(r.content) == (14, 14)
        assert _png_size(cl.get("/api/avatar.png", params={"key": "@me", "sheet": 1}).content) == (64, 26)
        ok = cl.put("/api/avatars/@me", json={"hair": "mint", "glasses": True})
        assert ok.status_code == 200 and "mint hair" in ok.json()["about"]
        assert sent[-1] == {"type": "avatars", "key": "@me"}, "every open desktop must repaint"
        bad = cl.put("/api/avatars/@me", json={"hair": "plaid"})
        assert bad.status_code == 400 and "mint" in bad.json()["error"]
        assert cl.put("/api/avatars/nobody", json={"hair": "mint"}).status_code == 404
        hue = cl.get("/api/avatars").json()["avatars"][0]["recipe"]["hue"]
        rr = cl.post("/api/avatars/@agent/reroll").json()
        assert rr["recipe"]["hue"] == hue
        assert cl.post("/api/avatars/nobody/reroll").status_code == 404
    finally:
        servermod.state["broadcast"] = real


def test_the_agent_can_restyle_through_the_gate_and_only_from_the_set(store):
    """The parity law: the editor's power is also a tool, and it is its OWN action
    so "may restyle the crew" is grantable apart from everything else."""
    assert any(t["name"] == "set_avatar" for t in TOOL_SCHEMAS)
    assert policy.action_of("set_avatar", {"who": "writer"}) == ("avatar.write", "avatar:writer")
    tb = Toolbox(CFG, store)
    out = asyncio.run(tb.set_avatar(who="writer"))
    assert "looks like" in out and "curly" in out, "asking with no change lists the choices"
    out = asyncio.run(tb.set_avatar(who="writer", hair="pink", glasses=True))
    assert out.startswith("Done") and "pink hair" in out and "glasses" in out
    assert av.recipe_for(store, "writer")["hair"] == 6
    assert asyncio.run(tb.set_avatar(who="writer", hair="plaid")).startswith("[error]")
    assert "nobody called" in asyncio.run(tb.set_avatar(who="stranger", hair="pink"))
    out = asyncio.run(tb.set_avatar(who="yourself", shirt="violet"))
    assert "violet" in av.describe(av.recipe_for(store, av.AGENT))
    assert asyncio.run(tb.set_avatar(who="me", style="bun")).startswith("Done")


def test_the_cli_reads_and_edits_with_the_server_down(tmp_path):
    env = {**os.environ, "AGENTOS_HOME": str(tmp_path), "NO_COLOR": "1"}
    run = lambda *a: subprocess.run([sys.executable, "-m", "agentos", "avatar", *a],  # noqa: E731
                                    cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    r = run("list")
    assert r.returncode == 0 and "you" in r.stdout and "shirt" in r.stdout, r.stderr
    r = run("set", "me", "hair=blue", "style=bob")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "bob of blue hair" in run("show", "me").stdout
    r = run("set", "me", "hair=plaid")
    assert r.returncode == 2 and "pink" in r.stdout
    assert run("show", "nobody").returncode == 2


# ---- the desktop: one door for a face, on every surface -----------------------------------

JS = ROOT / "agentos" / "ui" / "src" / "js"


def _js(name):
    return (JS / name).read_text()


def test_every_surface_shows_the_face_through_one_door():
    """Chat, the live stream, approvals, Logs, the Missions roster, the home line and
    Settings all call avatarImg — nobody builds an <img> of a character by hand, so the
    alt text, the off switch and the in-place repaint reach every one of them."""
    chat, ws = _js("10-chat.js"), _js("09-websocket.js")
    assert "chatWho('@me','you')" in chat and "chatWho('@agent',msgWho(msg.meta))" in chat
    assert "chatWho(sp," in chat, "a specialist's own reply must wear its own face"
    assert "avatarImg((s.args||{}).subagent,'av-tool')" in chat, "a delegation shows who got the work"
    assert "avatarImg((ev.args||{}).subagent" in ws and "avatarImg(askKey,'av-ap')" in ws
    assert "function curWho(" in ws and "speaker:ev.speaker" in ws
    assert "case 'avatars':" in ws, "an edit anywhere must repaint every open desktop"
    assert "avatarImg(avatarKeyOf(m.principal),'av-log')" in _js("16-mcp-telegram-logs.js")
    fab = _js("13-fabric.js")
    assert "avatarImg(s.name,'av-card')" in fab and "avatarEdit('${esc(s.name)}')" in fab
    assert "avatarImg('@agent','av-home')" in _js("01b-immersive.js")
    st = _js("11-settings.js")
    assert "avatarEdit('@me')" in st and "avatarEdit('@agent')" in st and "setAvatarsOff(" in st
    for f in JS.glob("*.js"):
        if f.name != "00e-avatars.js":
            assert "/api/avatar.png" not in f.read_text(), f"{f.name} builds its own face URL"


def test_only_characters_get_a_face():
    """A flow, an app or the system is not a person; a face would claim it was."""
    body = _js("00e-avatars.js").split("function avatarKeyOf(")[1].split("\nfunction ")[0]
    assert "p.startsWith('subagent:')" in body and "return '';" in body
    assert "'user'" in body, "the user principal is your agent acting for you"


def test_off_means_off_and_the_repaint_is_in_place():
    js = _js("00e-avatars.js")
    img = js.split("function avatarImg(")[1].split("\nfunction ")[0]
    assert "AVATARS.off)return ''" in img
    assert 'data-av="' in img and "alt=" in img, "every face says who it is in words"
    rep = js.split("function avatarsRepaint(")[1].split("\nfunction ")[0]
    assert "img.av[data-av]" in rep and "searchParams.set('v'" in rep
    for line in js.splitlines():
        assert not line.startswith(("let ", "const ")), line          # bundle rule


def test_the_editor_saves_every_click_and_is_a_real_target_on_a_phone():
    js, css = _js("00e-avatars.js"), (ROOT / "agentos/ui/src/css/22-avatars.css").read_text()
    ed = js.split("async function avatarEdit(")[1]
    assert "method:'PUT'" in ed and "avatarsChanged()" in ed and "/reroll" in ed
    assert "AVATARS.pal" in ed, "the choices are the server's own closed set"
    assert "body.dev-touch .ave-sw,body.dev-touch .ave-chip{min-width:var(--tap);min-height:var(--tap)}" in css
    assert "image-rendering:pixelated" in css
    assert "prefers-reduced-motion" in css

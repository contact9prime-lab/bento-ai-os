"""A build asked for in chat ends up in App Studio.

The gap: an executor is told — correctly — that it cannot use AgentOS's own tools,
`create_app` among them. So "build me an app" in a chat answered by Claude Code
produced real files in a scratch directory and nothing App Studio had ever heard
of. The work happened; it landed somewhere the OS does not look, and the app the
user then opened still showed an older build.

The fix is one known file. A checkout with no app behind it has the same shape as
one taken from an existing app, so the same commit path installs it — and the
executor keeps only filesystem tools, which is the point.

The condition that matters most is the negative one: most turns are not app
builds, and a turn that was not one must install nothing.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import executors as execmod                   # noqa: E402
from agentos.memory import Store                           # noqa: E402


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return str(ws)


def test_a_turn_that_was_not_a_build_installs_nothing(tmp_path):
    """The file starts EMPTY and an unchanged file is not a commit. Without this
    every question answered would leave an app behind."""
    store = Store(tmp_path / "a.db")
    co = execmod.new_app_checkout(_ws(tmp_path), "what is the weather today")
    saved, _why = execmod.commit_app(store, co)
    assert saved is False
    assert store.list_apps() == []


def test_a_written_app_is_installed(tmp_path):
    store = Store(tmp_path / "a.db")
    co = execmod.new_app_checkout(_ws(tmp_path), "unit converter")
    Path(co["path"]).write_text("<h1>Converter</h1><script>/* real */</script>")
    saved, why = execmod.commit_app(store, co)
    assert saved and "installed" in why
    assert [a["name"] for a in store.list_apps()] == ["unit converter"]


def test_the_message_says_installed_for_a_new_app_and_version_for_an_old_one(tmp_path):
    """Whether there is now something NEW on the desktop is the one thing the
    reader needs, and "a new version" would be false for half of these."""
    store = Store(tmp_path / "a.db")
    fresh = execmod.new_app_checkout(_ws(tmp_path), "notes")
    Path(fresh["path"]).write_text("<h1>a</h1>")
    assert "installed" in execmod.commit_app(store, fresh)[1]

    existing = execmod.new_app_checkout(_ws(tmp_path), "notes")
    existing["app_id"] = "some-id"
    Path(existing["path"]).write_text("<h1>b</h1>")
    assert "new version" in execmod.commit_app(store, existing)[1]


def test_an_emptied_file_is_refused(tmp_path):
    """Saving an empty app over a real one is the worst outcome available."""
    store = Store(tmp_path / "a.db")
    co = execmod.new_app_checkout(_ws(tmp_path), "notes")
    Path(co["path"]).write_text("<h1>real</h1>")
    execmod.commit_app(store, co)
    co2 = execmod.new_app_checkout(_ws(tmp_path), "notes")
    co2["before"] = "<h1>real</h1>"
    Path(co2["path"]).write_text("   ")
    saved, why = execmod.commit_app(store, co2)
    assert not saved and "empt" in why.lower()


def test_the_note_is_conditional(tmp_path):
    """An instruction that read as "write an app" would answer every question
    with a file nobody wanted."""
    co = execmod.new_app_checkout(_ws(tmp_path), "x")
    note = execmod.new_app_note(co)
    assert "only if" in note.lower()
    assert co["path"] in note, "the note must name the file it is about"
    assert "empty" in note.lower(), "it must say what NOT building looks like"


def test_the_checkout_has_the_same_shape_as_one_from_a_real_app(tmp_path):
    """Same shape, so one commit path serves both — a second one would drift."""
    co = execmod.new_app_checkout(_ws(tmp_path), "x")
    for key in ("app_id", "name", "icon", "description", "path", "dir", "before"):
        assert key in co, f"new_app_checkout is missing {key}"
    assert co["app_id"] == "", "a new app has no id yet; that is what makes it new"
    assert co["before"] == "", "it must start empty or every turn looks like a build"

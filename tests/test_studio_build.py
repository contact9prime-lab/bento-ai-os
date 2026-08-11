"""App Studio: a build you can watch, name, and consent to.

Three failures this pins down, all of them from the same twelve-minute build
that looked like a hang:

  * an executor build that SUCCEEDED reported itself as producing nothing — the
    Studio keys on `app_id` and that path sent `app`, so the preview stayed
    empty and no permissions were ever asked for;
  * the progress log named tools without saying what they were on, so `Bash`
    for four minutes and `Bash` for four seconds looked identical;
  * the app was named after the sentence that asked for it, and a second one
    appeared next time the sentence differed.
"""

import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import executors as ex                                   # noqa: E402
from agentos.memory import Store                                      # noqa: E402


# --- watching the work ------------------------------------------------------

def test_a_tool_call_says_what_it_is_working_on():
    assert ex.tool_detail("Write", {"file_path": "/tmp/builds/nifty/app.html"}) == "app.html"
    assert ex.tool_detail("Bash", {"command": "python -m pytest -q"}) == "python -m pytest -q"
    assert ex.tool_detail("Grep", {"pattern": "appLLM", "path": "/x/app.html"}) \
        == "appLLM in app.html"
    assert ex.tool_detail("WebFetch", {"url": "https://example.com/quote"}) \
        == "https://example.com/quote"
    # a description beats a 400-character shell one-liner
    assert ex.tool_detail("Bash", {"description": "run the harness",
                                   "command": "x" * 400}) == "run the harness"
    # unknown tools are not a dead end: something identifying still shows
    assert ex.tool_detail("Mystery", {"target": "the thing"}) == "the thing"
    assert ex.tool_detail("Mystery", {}) == ""


def test_long_arguments_are_trimmed_not_dumped_into_the_log():
    assert len(ex.tool_detail("Bash", {"command": "y" * 500})) <= 91


def test_a_tool_result_recovers_the_name_of_the_call_it_ended():
    """The CLI reports a result with only an id. Without the pairing, a failed
    call reads "✗ — failed" with no way to tell WHICH call failed."""
    run = ex.Run()
    ex.translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Edit",
         "input": {"file_path": "/w/app.html"}}]}}, run)
    end = ex.translate({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}, run)
    assert end[0]["name"] == "Edit" and end[0]["detail"] == "app.html"


def test_the_run_tracks_what_it_is_on_for_the_heartbeat():
    """Between tool calls there is nothing to relay, so the heartbeat reads the
    run itself — silence is what made a working build look dead."""
    run = ex.Run()
    ex.translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t1", "name": "Bash",
         "input": {"command": "npm test"}}]}}, run)
    assert run.steps == 1 and run.last == "Bash · npm test"


def test_a_tool_start_carries_its_detail_to_the_ui():
    run = ex.Run()
    out = ex.translate({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t9", "name": "Read",
         "input": {"file_path": "/w/builds/x/app.html"}}]}}, run)
    assert out[0]["detail"] == "app.html" and out[0]["step"] == 1


# --- finishing a build ------------------------------------------------------

def test_the_executor_path_reports_the_app_the_studio_can_open():
    """It sent {"app": …}. The Studio branches on `app_id`, so a build that had
    genuinely succeeded printed "no app was produced"."""
    import inspect

    from agentos import server
    src = inspect.getsource(server._run_build)
    executor_path = src.split('if model == "claude-code":', 1)[1].split("# Auto model selection", 1)[0]
    assert '"app_id": built["id"]' in executor_path
    assert '"manifest_status": manifest_status' in executor_path
    # and it must not fall back to the alphabetically-first app
    assert "apps[0]" not in executor_path


def test_the_app_just_built_is_found_by_name_not_by_list_order(tmp_path):
    """`list_apps()` sorts by NAME. Taking `[0]` to mean "the new one" is right
    on an empty machine and wrong on every machine after that."""
    from agentos.server import _app_by_name
    store = Store(tmp_path / "t.db")
    store.save_app("Alpha", "", "first", "<p>a</p>")
    store.save_app("Zulu", "", "second", "<p>z</p>")
    assert store.list_apps()[0]["name"] == "Alpha"        # the trap
    assert _app_by_name(store, "Zulu")["description"] == "second"
    assert _app_by_name(store, "zulu") is not None        # names are not case-sensitive here
    assert _app_by_name(store, "nothing") is None


def test_every_finished_build_asks_for_its_permissions(tmp_path, monkeypatch):
    """Whichever engine built it, an app that reaches for a tool has to say so
    and be approved. The executor path used to skip this entirely."""
    from agentos import server
    store = Store(tmp_path / "t.db")
    monkeypatch.setitem(server.state, "store", store)
    aid = store.save_app("Pulse", "", "watches a feed",
                         "<div id=x></div><script>(async()=>{"
                         "await appTool('fetch_url',{url:'https://e.co'});"
                         "await appLLM('what next?');await appData.set({});})()</script>")
    status, warnings = server._finish_build_checks(aid)
    assert status == "proposed"
    acts = {(p["action"], p["resource"]) for p in server._app_manifest(store.get_app(aid))["permissions"]}
    assert ("net.fetch", "net:*") in acts                  # it fetches
    assert ("tool.use", "tool:llm_generate*") in acts      # it uses the model inside itself
    assert ("app.data.*", "app:self/data") in acts         # and keeps its own state
    assert warnings == []


def test_a_declared_manifest_is_not_overwritten_by_the_scan(tmp_path, monkeypatch):
    """A builder that declared its own permissions has already been specific;
    re-deriving them from a source scan would widen or lose that."""
    import json

    from agentos import server
    store = Store(tmp_path / "t.db")
    monkeypatch.setitem(server.state, "store", store)
    aid = store.save_app("Declared", "", "", "<p>hi</p>")
    store.set_app_manifest(aid, json.dumps(
        {"format": 1, "name": "Declared", "permissions":
            [{"action": "tool.use", "resource": "tool:notify*", "reason": "alerts",
              "required": True}]}), "proposed")
    status, _ = server._finish_build_checks(aid)
    assert status == "proposed"
    perms = server._app_manifest(store.get_app(aid))["permissions"]
    assert [p["resource"] for p in perms] == ["tool:notify*"]


def test_a_lost_stream_does_not_discard_an_app_already_written_to_disk():
    """The file IS the deliverable — `build_task` tells the executor exactly
    that. A stream that dies after a finished app.html was written is a lost
    progress feed, not a lost app, and the work is already done and paid for."""
    import inspect

    from agentos import server
    src = inspect.getsource(server._run_build)
    executor_path = src.split('if model == "claude-code":', 1)[1].split("# Auto model selection", 1)[0]
    relay = executor_path.split("relay_failed = ", 1)[1]
    # the read happens AFTER the failure is caught, not instead of it
    assert relay.index("execmod.read_build(co)") > relay.index("store.log")
    assert "raise" in executor_path.split("except asyncio.CancelledError:", 1)[1][:40]


# --- the app's identity is the user's ---------------------------------------

def test_a_name_typed_by_the_user_reaches_the_build(monkeypatch):
    import inspect

    from agentos import server
    src = inspect.getsource(server._run_build)
    assert 'want_name = (data.get("name") or "").strip()' in src
    # applied to an existing app BEFORE the build, so create_app updates in place
    assert "store.rename_app(app_id, name=want_name, icon=want_icon)" in src


def test_renaming_keeps_the_app_and_everything_keyed_to_it(tmp_path):
    """Identity is metadata, not a new app: data, versions and grants key on the
    id, so a rename must not fork a second copy."""
    store = Store(tmp_path / "t.db")
    aid = store.save_app("build an application that tracks x", "", "", "<p>v1</p>")
    store.save_app("build an application that tracks x", "", "", "<p>v2</p>")
    assert store.rename_app(aid, name="Nifty Oracle", icon="glyph:timeline") is None
    app = store.get_app(aid)
    assert app["name"] == "Nifty Oracle" and app["icon"] == "glyph:timeline"
    assert len(store.list_apps()) == 1
    assert len(store.app_versions(aid)) == 2


def test_a_name_already_in_use_is_refused_rather_than_silently_merged(tmp_path):
    store = Store(tmp_path / "t.db")
    store.save_app("Taken", "", "", "<p>a</p>")
    other = store.save_app("Mine", "", "", "<p>b</p>")
    assert "already exists" in (store.rename_app(other, name="Taken") or "")
    assert store.get_app(other)["name"] == "Mine"

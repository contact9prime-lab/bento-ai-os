"""The seams between the OS's surfaces, asserted in the source.

Three of them, each one reported as "this makes no sense" before it existed:

  bar → chat      the prompt bar's thread is a real conversation, visible in
                  Chat's sidebar, and a turn that has not started says so
  chat → studio   a turn that built an app offers the door to App Studio
  chat → flows    a turn that wrote a workflow offers the door to Workflows

and the picker they all hang off: an executor and one of ITS models, never a
single dropdown holding both kinds of choice.

These are source-level assertions because the behaviour is a convention rather
than a function's return value — the moment the two selects become one again, or
the model options are marked selected without asking which executor is chosen,
the bug is back and nothing else would notice.
"""
import pathlib

JS = pathlib.Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "js"


def read(name: str) -> str:
    return (JS / name).read_text()


# --- the brain picker -------------------------------------------------------

def test_the_chat_header_has_two_coupled_selects():
    src = read("10-chat.js")
    assert 'id="execchip"' in src and 'id="modelchip"' in src
    assert "chatPickExecutor(this.value)" in src
    assert "chatPickModel(this.value)" in src


def test_no_surface_offers_engines_and_models_in_one_list():
    """`<option value="engine:…">` beside model options is the shape that let two
    options carry `selected` at once — the picker then showed whichever came
    last, which is how choosing Claude Code displayed a Gemini model."""
    for name in ("10-chat.js", "11-settings.js", "21-skills-web-native-models.js"):
        src = read(name)
        assert 'value="engine:' not in src, \
            f"{name} still builds a conflated engine/model option list"
        assert "indexOf('engine:')" not in src, \
            f"{name} still parses an engine out of a model value"


def test_both_pickers_write_through_one_endpoint():
    """One decision, one write. Two round trips is how the executor and the model
    end up disagreeing in config."""
    chat, settings = read("10-chat.js"), read("11-settings.js")
    assert "'/api/brain'" in chat
    assert "function setBrain(" in chat
    for fn in ("function pickExecutor", "function pickModel", "function pickEngine"):
        assert fn in settings, f"{fn} missing from Settings"
    # Settings reuses the shared writer rather than PUTting config itself
    assert "setBrain(" in settings


def test_the_model_list_belongs_to_the_chosen_executor():
    src = read("10-chat.js")
    assert "curExecutor()" in src
    assert "(sel&&sel.models)||[]" in src


def test_the_top_bar_states_the_brain_even_when_nothing_is_forwarded():
    """It used to appear only while forwarding, so the common case — a provider
    and a model — had no answer on screen at all."""
    src = read("10-chat.js")
    assert "function paintForwardChip" in src
    assert "chip.hidden=false" in src


# --- bar → chat ------------------------------------------------------------

def test_the_bar_creates_its_thread_rather_than_waiting_for_one():
    src = read("28a-omnibar.js")
    assert "'/api/conversations'" in src
    assert "method:'POST'" in src
    assert "origin:'omni'" in src


def test_a_queued_turn_says_queued_and_keeps_its_own_clock():
    cop = read("04a-copilot.js")
    assert "queued(msg)" in cop, "miniFeed has no queued state"
    assert "o.sink.queued" in cop, "agentTurn does not tell the sink it queued"
    # and the shared ticker must not paint the running turn's line into it
    assert "el.dataset.queued==='1'" in cop


# --- chat → studio / workflows --------------------------------------------

def test_the_handoff_map_covers_the_things_a_turn_can_make():
    src = read("10a-handoff.js")
    for tool in ("create_app", "create_flow", "enable_flow", "save_automation",
                 "schedule_task"):
        assert f"case '{tool}'" in src, f"{tool} makes something and offers no door"
    assert "default:\n      return null;" in src, \
        "an unlisted tool must NOT get an invented handoff"


def test_a_handoff_opens_the_thing_not_just_the_app():
    src = read("10a-handoff.js")
    assert "STUDIO.sel=hit.id" in src
    assert "FLOW_FOCUS=h.what" in src


def test_the_stream_feeds_the_handoff_from_the_args_it_remembered():
    """`tool_end` carries no args (agent.py), so `tool_start` has to keep them."""
    ws = read("09-websocket.js")
    assert "TOOL_ARGS[ev.call_id]=ev.args||{}" in ws
    assert "handoffEmit(ev,_cid,_sk,_cur)" in ws


def test_every_live_surface_can_show_a_handoff():
    assert "handoff(h){" in read("04a-copilot.js")


def test_a_handoff_is_not_repeated_for_the_same_thing():
    src = read("10a-handoff.js")
    assert "HANDOFF_SEEN" in src

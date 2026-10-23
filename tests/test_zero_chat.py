"""A person talking to a Zero: the turn runs on its hub, and the session is kept there.

Asked for as "when zero is talking the context, session and KB are all on the hub, keeping
zero light". Before, the Pi built a 24,000-token prompt itself and only borrowed the hub's
model, so the window filled ("HeyIII") and nothing of it showed on the hub. A hub and a Zero
stand up in this process, linked over real mTLS (the fixture of test_zero_mind)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agentos import providers, teamlink, zero, zeromind  # noqa: E402
from agentos.memory import Store                          # noqa: E402
from test_zero_mind import _on, _section, hz              # noqa: E402,F401

ROOT = Path(__file__).parent.parent


def _brain(monkeypatch, seen):
    def chat(cfg, model, messages, tools, options=None):
        seen.append(messages)

        async def gen():
            said = [m["content"] for m in messages if m["role"] == "user"]
            yield {"type": "text", "text": f"Hello from the hub ({len(said)} said so far)."}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    monkeypatch.setattr(providers, "chat", chat)


def _zero_on(hz, monkeypatch):
    H, Z, loop = hz

    async def on_ask(lk, req):
        with teamlink.at(H["home"]):
            if req.get("op") == "zero_chat":
                return await H["cp"].zero_chat(lk, req)
            if req.get("op") == "zero_mind":
                return await zeromind.answer(H["store"], H["cfg"], lk, req)
            return await H["cp"].answer_linked(lk, req)
    H["lst"].on_ask = on_ask
    return H, Z, loop


def test_the_turn_runs_on_the_hub_and_is_kept_there_in_the_zeros_section(hz, monkeypatch):
    seen = []
    _brain(monkeypatch, seen)
    H, Z, loop = _zero_on(hz, monkeypatch)
    assert _on(Z, loop, lambda: _async(zero.chat_on_hub, Z["cfg"]))
    events = []

    async def emit(ev):
        events.append(ev)
    r1 = _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c-screen", "Hi Mr Pi", emit))
    r2 = _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c-screen", "and again", emit))
    assert r1["content"] == "Hello from the hub (1 said so far)."
    assert "2 said so far" in r2["content"], "the session is the hub's: the second turn has the first"
    assert any(e.get("type") == "text_delta" for e in events)
    convs = [c for c in H["store"].list_conversations() if c.get("origin") == "zero"]
    assert len(convs) == 1, "one conversation on the hub for one on the Zero"
    assert convs[0]["space_id"] == _section(H), "kept in the Zero's section"
    msgs = H["store"].get_messages(convs[0]["id"])
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert Z["store"].list_conversations() == [], "the hub_turn itself writes nothing on the Zero"


def test_a_machine_the_hub_did_not_set_up_is_refused(hz, monkeypatch):
    seen = []
    _brain(monkeypatch, seen)
    H, Z, loop = _zero_on(hz, monkeypatch)
    from agentos import provision
    with teamlink.at(H["home"]):
        d = provision.load()
        d["enabled"] = {}
        provision.save(d)

    async def emit(ev):
        pass
    r = _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c", "hello", emit))
    assert r["content"].startswith("[error]") and "set up" in r["content"]
    assert not seen, "no model call for a stranger"


def test_a_zero_set_to_chat_here_keeps_its_own_turns(hz):
    H, Z, loop = hz
    Z["cfg"]["zero"]["chat"] = "here"
    assert not _on(Z, loop, lambda: _async(zero.chat_on_hub, Z["cfg"]))


def test_the_chat_runner_branches_before_any_brain():
    src = (ROOT / "agentos/server.py").read_text()
    i = src.index("async def _run_chat(")
    body = src[i:src.index("\ndef _validate_app_html")]
    assert body.index("_zero().chat_on_hub(cfg)") < body.index("elif model in execmod.ENGINES")


async def _async(fn, *a):
    return fn(*a)


def test_an_older_hub_lets_the_zero_answer_itself(hz, monkeypatch):
    H, Z, loop = hz

    async def on_ask(lk, req):
        return {"ok": False, "error": f"unknown request '{req.get('op')}'"}
    H["lst"].on_ask = on_ask

    async def emit(ev):
        pass
    r = _on(Z, loop, lambda: zero.hub_turn(Z["cfg"], "c", "hello", emit))
    assert r.get("fallback") and "older Bento" in r["fallback"]

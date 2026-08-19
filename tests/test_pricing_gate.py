"""The price gate must never be the reason a turn looks stuck.

It is the only gate that runs BEFORE `turn_start`, so anything it does costs the
user a chat that says "working" with no step, no tool and no sentence — the UI's
own clock ticking against nothing. That is what it did: `needs_price` answered
"unknown" for `claude-code`, which is an ENGINE id and not a model anyone can
price, so every delegated turn was held in front of a `price_request` card that no
surface renders, until the ask timed out five minutes later. Then the CLI was
spawned and the turn ran normally, which is why it read as "the executor is slow
to start" rather than as a gate.

Two halves, and both are needed. An executor is never asked about (the cause), and
an ask nobody answered is not repeated on the next turn (what made it permanent
rather than a one-off).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import executors                                # noqa: E402
from agentos import server                                   # noqa: E402
from agentos import usage                                    # noqa: E402


def test_an_executor_engine_is_never_price_gated():
    """`claude-code` bills against the CLI's own subscription and reports its own
    spend. There is no per-million-token number to ask for, so asking is pure
    delay."""
    cfg: dict = {}
    for engine in executors.ENGINES:
        if engine == "aria":
            continue                       # the built-in loop runs real models
        assert usage.price_state(cfg, engine) == "executor"
        assert not usage.needs_price(cfg, engine), \
            f"{engine} is an engine, not a model — pricing it holds every delegated turn"


def test_an_unknown_cloud_model_is_still_gated():
    """The no-regression half: the gate exists because a model released after the
    shipped price table was written should not run and be costed later."""
    assert usage.needs_price({}, "someprovider/brand-new-model")
    assert not usage.needs_price({}, "ollama/thinky")             # local: free, exempt
    assert not usage.needs_price({}, "anthropic/claude-sonnet-5")  # in the shipped table


class _FakeStore:
    def __init__(self):
        self.lines = []

    def log(self, kind, message, meta=None):
        self.lines.append((kind, message, meta or {}))


def _fake_state(cfg):
    return {"cfg": cfg, "store": _FakeStore()}


def test_an_unanswered_ask_is_remembered_and_never_repeated(monkeypatch):
    """Nobody answered, so the turn runs unpriced — and the NEXT turn must not pay
    the same wait. Before this, the timeout changed nothing: the stall was not a
    first-run cost, it was the price of every turn on that model, forever."""
    cfg: dict = {}
    saved = []
    monkeypatch.setattr(server, "state", _fake_state(cfg))
    monkeypatch.setattr(server.cfgmod, "save_config", lambda c: saved.append(c))
    monkeypatch.setattr(server, "PRICE_ASK_TIMEOUT", 0.05)

    async def no_lookup(cfg, model):
        return {"found": False}
    monkeypatch.setattr(server.usagemod, "discover_price", no_lookup)

    events = []

    async def evsend(ev):
        events.append(ev)

    assert asyncio.run(server.request_price("someprovider/brand-new", evsend=evsend)) is True

    # The wait says what it is waiting for. This is the only gate ahead of
    # `turn_start`, so without a status the chat can only draw a bare spinner.
    assert any(e["type"] == "status" and "price" in e["message"] for e in events), \
        "the turn was held with nothing on screen explaining why"
    assert any(e["type"] == "price_request" for e in events)

    # Asked once. Remembered either way — that is what the log line always claimed.
    assert usage.price_state(cfg, "someprovider/brand-new") == "skipped"
    assert not usage.needs_price(cfg, "someprovider/brand-new")
    assert saved, "the skip was recorded in memory only — the next restart asks again"

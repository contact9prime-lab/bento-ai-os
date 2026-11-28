"""A step added after a machine was set up is offered once, right after the update.

Asked for as "the registry login should be given at the time of initial setup or
upgrading; it should show immediately after upgrade". Pins onboarding.news, the two
routes, the page's call after load and `bento update`'s terminal offer."""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import onboarding as ob                               # noqa: E402
from agentos import registryhub                                    # noqa: E402
from agentos.memory import Store                                   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "t.db")


def _unregistered():
    return mock.patch.object(registryhub, "status",
                             return_value={"registered": False, "signed_in": False})


def test_a_new_machine_meets_the_registry_in_the_arc_not_as_news(store):
    assert "registry" in ob.PLANS["one"] and "registry" in ob.PLANS["company"]
    with _unregistered():
        assert ob.news({}, store) == []


def test_a_machine_set_up_before_the_step_is_offered_it_once(store):
    cfg = {"setup_complete": True}
    with _unregistered():
        got = ob.news(cfg, store)
        assert [s["id"] for s in got] == ["registry"]
        ob.news_seen(cfg, "registry")
        assert ob.news(cfg, store) == []


def test_done_or_skipped_is_never_offered(store):
    cfg = {"setup_complete": True, "onboarding": {"skipped": ["registry"]}}
    with _unregistered():
        assert ob.news(cfg, store) == []
    with mock.patch.object(registryhub, "status",
                           return_value={"registered": True, "handle": "bento"}):
        assert ob.news({"setup_complete": True}, store) == []


def test_walking_setup_again_offers_it_again():
    cfg = {"setup_complete": True, "onboarding": {"news_seen": ["registry"]}}
    ob.restart(cfg)
    assert cfg["onboarding"]["news_seen"] == []


def test_only_news_steps_can_be_marked():
    with pytest.raises(ValueError):
        ob.news_seen({}, "model")


def test_every_news_step_has_a_terminal_handler():
    from agentos import setup_tui
    assert all(s in ob.BY_ID and s in setup_tui.HANDLERS for s in ob.NEWS)


def test_the_page_asks_after_load_on_a_machine_already_set_up():
    js = (ROOT / "agentos/ui/src/js/14-docs-setup.js").read_text()
    assert "if(!s.first_run){setupNews();return}" in js
    assert "/api/onboarding/news/seen" in js and "obShow({step:s.id})" in js
    srv = (ROOT / "agentos/server.py").read_text()
    assert '@app.get("/api/onboarding/news")' in srv
    assert '@app.post("/api/onboarding/news/seen")' in srv


def test_bento_update_offers_it_in_a_fresh_process(capsys):
    from agentos import __main__ as cli
    with mock.patch.object(cli.sys.stdin, "isatty", return_value=False):
        cli._update_news(None)
    assert "bento setup --news" in capsys.readouterr().out
    with mock.patch.object(cli.sys.stdin, "isatty", return_value=True), \
         mock.patch.object(cli.sys.stdout, "isatty", return_value=True), \
         mock.patch.object(cli.subprocess, "run") as run:
        cli._update_news(None)
    assert run.call_args[0][0][-3:] == ["agentos", "setup", "--news"]

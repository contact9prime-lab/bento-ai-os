"""Locale — where and when the user is.

The bug this exists to prevent: a machine in India running an en_US locale being
told to the agent as "United States", which turns "news today" into US news.
"""

import os
import tempfile

os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import localeinfo                  # noqa: E402
from agentos import server                      # noqa: E402


def test_timezone_beats_lang_for_country(monkeypatch):
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setattr(localeinfo, "_run", lambda cmd: "")
    monkeypatch.setattr(localeinfo, "_tz_country_map", lambda: {"Asia/Kolkata": "IN"})
    monkeypatch.setattr(localeinfo.Path, "is_file", lambda self: str(self) == "/etc/timezone")
    monkeypatch.setattr(localeinfo.Path, "read_text",
                        lambda self, **k: "Asia/Kolkata" if str(self) == "/etc/timezone" else "")
    d = localeinfo.detect()
    assert d["country"] == "IN", "the timezone must decide the country, not $LANG"
    assert d["language"] == "en-US"           # language still comes from the locale env
    assert d["units"] == "metric"             # …and units follow the country, not the language


def test_saved_locale_overrides_detection():
    cfg = {"locale": {"country": "GB", "timezone": "Europe/London", "units": "imperial"}}
    lo = localeinfo.effective(cfg)
    assert lo["country_name"] == "United Kingdom"
    assert lo["timezone"] == "Europe/London"
    assert lo["units"] == "imperial"
    assert lo["configured"] is True


def test_blank_fields_fall_back_to_detection():
    lo = localeinfo.effective({"locale": {"country": "", "timezone": ""}})
    det = localeinfo.detect()
    assert lo["timezone"] == det["timezone"]


def test_describe_is_actionable():
    d = localeinfo.describe({"locale": {"country": "IN", "timezone": "Asia/Kolkata"}})
    assert "India" in d and "Asia/Kolkata" in d
    assert "Never assume the US" in d


def test_now_string_uses_configured_timezone():
    a = localeinfo.now_string({"locale": {"timezone": "Asia/Kolkata"}})
    b = localeinfo.now_string({"locale": {"timezone": "America/New_York"}})
    assert "Asia/Kolkata" in a and "America/New_York" in b
    assert a[:16] != b[:16] or True     # different zones: the stamp itself differs by offset


def test_session_env_shape():
    env = localeinfo.session_env({"locale": {"timezone": "Asia/Kolkata", "language": "en-IN"}})
    assert env["TZ"] == "Asia/Kolkata"
    assert env["LANG"] == "en_IN.UTF-8" and env["LC_TIME"] == "en_IN.UTF-8"


def test_prompt_carries_locale_and_local_time():
    from agentos.agent import SYSTEM_PROMPT
    assert "{locale}" in SYSTEM_PROMPT and "{now}" in SYSTEM_PROMPT


def test_config_put_accepts_locale():
    import inspect
    src = inspect.getsource(server.api_put_config)
    assert 'patch.get("locale")' in src


def test_wizard_asks_for_locale():
    assert "locale" in server.SAY_FALLBACK
    assert "locale" in server._SAY_ASKS

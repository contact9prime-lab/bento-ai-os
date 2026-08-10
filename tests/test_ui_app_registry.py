"""Every app offered in the launcher must actually open.

Adding an app means touching four separate lists in three files (`APPS`,
`DESKTOP_APPS`, the deck defaults, the bento groups), and nothing checked that they
agreed. Listing an id with no `APPS` entry, or an entry whose `render` function was
never written, produces an icon that opens nothing — the dead control the honesty
rules exist to prevent, in the one place a user is most likely to click.

Quarantine is what prompted this: it existed only as a tab inside Permissions, so
"my app stopped working" had no findable answer.
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "agentos" / "ui" / "src" / "js"


def _read(name: str) -> str:
    return (SRC / name).read_text()


def _all_js() -> str:
    return "\n".join(p.read_text() for p in sorted(SRC.glob("*.js")))


def _js_list(text: str, marker: str) -> list[str]:
    """Pull the string ids out of the first [...] following a marker."""
    i = text.index(marker)
    body = text[i + len(marker):]
    body = body[body.index("["): body.index("]") + 1]
    return re.findall(r"'([a-z0-9_]+)'", body)


def _apps_registry() -> dict[str, str]:
    """app id -> its render function name, parsed from the APPS object literal.

    Entries span several lines, so each one runs from its own key to the start of the
    next key (or the closing `};`) — slicing at the first indented newline instead
    truncates every multi-line entry before its `render:`.
    """
    text = _read("05-apps-registry.js")
    body = text[text.index("const APPS={"):]
    body = body[:body.index("\n};") + 1]
    keys = list(re.finditer(r"^\s{2}([a-z][a-z0-9_]*):\{", body, re.M))
    out = {}
    for i, m in enumerate(keys):
        end = keys[i + 1].start() if i + 1 < len(keys) else len(body)
        r = re.search(r"render:(\w+)", body[m.end():end])
        if r:
            out[m.group(1)] = r.group(1)
    return out


def test_every_launcher_app_is_registered_and_renderable():
    apps = _apps_registry()
    everything = _all_js()
    ids = _js_list(_read("05-apps-registry.js"), "const DESKTOP_APPS=")
    assert ids, "DESKTOP_APPS did not parse"
    for app_id in ids:
        assert app_id in apps, f"'{app_id}' is in DESKTOP_APPS but has no APPS entry"
        fn = apps[app_id]
        assert re.search(rf"function {fn}\b", everything), \
            f"'{app_id}' renders with {fn}(), which is not defined anywhere"


@pytest.mark.parametrize("filename,marker", [
    ("06a-deck.js", "const DECK_DEFAULTS="),
    ("06-icon-layout.js", "const BENTO_GROUPS="),
])
def test_group_layouts_only_reference_real_apps(filename, marker):
    """A group listing a non-existent id silently drops it, so the app never appears
    in that layout and nothing says so."""
    apps = _apps_registry()
    text = _read(filename)
    body = text[text.index(marker):]
    body = body[:body.index("\n];") + 1]
    for app_id in re.findall(r"'([a-z0-9_]+)'", body):
        if app_id in ("Essentials", "Create"):
            continue
        assert app_id in apps or app_id.startswith("ua_"), \
            f"{filename} lists '{app_id}', which is not an app"


def test_quarantine_is_reachable_on_its_own():
    """The point of the change: findable without knowing it lives under Permissions."""
    apps = _apps_registry()
    assert apps.get("quarantine") == "renderQuarantine"
    assert "quarantine" in _js_list(_read("05-apps-registry.js"), "const DESKTOP_APPS=")
    assert "renderQuarantine" in _read("20-permissions.js")


def test_quarantine_app_and_tab_share_one_renderer():
    """Two copies of the list would drift, and the drift would be in the screen that
    explains why the OS stopped something."""
    text = _read("20-permissions.js")
    assert text.count("function permQuarantine(") == 1
    body = text[text.index("async function renderQuarantine("):]
    body = body[:body.index("async function permRelease(")]
    assert "permQuarantine(" in body, "the app must reuse the tab's renderer"


def test_release_refreshes_both_surfaces():
    """Releasing from one surface must not leave the other showing a stale hold."""
    text = _read("20-permissions.js")
    body = text[text.index("async function permRelease("):]
    assert "refreshApp('quarantine')" in body and "refreshApp('permissions')" in body
    ws = _read("09-websocket.js")
    for case in ("case 'quarantined':", "case 'quarantine':"):
        seg = ws[ws.index(case):]
        seg = seg[:seg.index("break;")]
        assert "refreshApp('quarantine')" in seg, f"{case} does not refresh the app"

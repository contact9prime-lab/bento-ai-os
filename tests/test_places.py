"""The launchers find the places inside apps by the words people use.

Reported as: "when I type something like channel it is not indexed; I say flow and it
should relate to jobs". The launchers knew app names only, and Telegram and WhatsApp
live in a Settings pane called Channels, flows in a Missions tab. `05b-places.js` is
one index every launcher reads.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "agentos" / "ui" / "src" / "js"


def _js(name: str) -> str:
    return (JS / name).read_text()


def _places() -> list[tuple[str, str, list[str], str]]:
    src = _js("05b-places.js")
    rows = re.findall(r"\['([^']+)','(\w+)','([^']+)',\[([^\]]*)\],(place\w+\([^)]*\))\]", src)
    return [(label, app, [w.strip("'") for w in words.split(",")], go) for label, app, _h, words, go in rows]


def test_the_words_that_were_reported_find_their_place():
    by_word = {}
    for label, app, words, _go in _places():
        for w in words:
            by_word.setdefault(w, []).append(label)
    assert "Channels" in by_word["channel"] and "Channels" in by_word["whatsapp"]
    assert "Flows" in by_word["flow"] and "Flows" in by_word["workflow"]
    assert "Run missions" in by_word["job"]
    # the app itself answers to its old names too
    assert re.search(r"jobs:\[[^\]]*'flow'[^\]]*'workflow'", _js("05b-places.js"))


def test_every_place_goes_somewhere_that_exists():
    apps = set(re.findall(r"^\s{2}(\w+):\{id:'\1'", _js("05-apps-registry.js"), re.M))
    tabs = set(re.findall(r"\['(\w+)','[^']*','[^']+','[\w-]+'\]", _js("11-settings.js")))
    assert tabs >= {"ai", "channels", "accounts"}
    for label, app, _w, go in _places():
        assert app in apps, f"{label} lives in {app}, which is not an app"
        m = re.match(r"placeSettings\('(\w+)'\)", go)
        if m:
            assert m.group(1) in tabs, f"{label} opens Settings tab {m.group(1)}, which does not exist"
    fab = _js("13-fabric.js")
    for sub in re.findall(r"placeMissions\('build','(\w+)'\)", _js("05b-places.js")):
        assert f"fabTab==='{sub}'" in fab or sub == "flows"


def test_every_launcher_reads_the_one_index():
    assert "PLACES" in _js("29-keyboard-palette.js") and "APP_WORDS" in _js("29-keyboard-palette.js")
    assert "placeWordScore" in _js("28a-omnibar.js") and "'In apps'" in _js("28a-omnibar.js")
    deck = _js("06a-deck.js")
    assert "deckPlacesHTML()" in deck and "placeWordScore" in deck
    assert "placesFind" in _js("02-themes-shells.js")
    # the wall read an icon span as the tile's name, so names matched by id only
    assert ":scope > span:not([class])" in deck


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_a_word_counts_whole_or_as_its_start():
    src = _js("05b-places.js")
    fn = src[src.index("function placeWordScore"):src.index("function placeScore")]
    out = subprocess.run(["node", "-e", fn + """
      const w=['channel','channels','telegram','api key'];
      console.log(JSON.stringify([placeWordScore('channel',w),placeWordScore('chan',w),
        placeWordScore('annel',w),placeWordScore('key',w),placeWordScore('c',w)]))"""],
        capture_output=True, text=True, check=True).stdout
    whole, start, middle, second_word, one_letter = json.loads(out)
    assert whole > start >= 2 and second_word >= 2
    assert middle == 0 and one_letter == 0, "a launcher, not a full-text search"

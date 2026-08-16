"""The shipped UI bundle must be syntactically valid JavaScript.

This exists because of a real outage: a search-and-replace matched the first line
of a two-line `pRow(...)` call and left the second line orphaned. Every test
passed — they test Python — the server started, every endpoint answered 200, and
the desktop was a blank window.

The bundle is ONE concatenated <script>, so a syntax error anywhere is a syntax
error everywhere: no dock, no windows, no chat, and nothing in the server log,
because the failure is entirely in the browser. That asymmetry is the whole
reason this guard is worth its runtime — it is the one class of change that can
take the entire product down while looking perfectly healthy from the outside.

Checked per source part as well as on the built file, so the failure names the
file somebody edited rather than a line number in a 1MB artefact.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "agentos" / "ui" / "src" / "js"
BUNDLE = REPO / "agentos" / "ui" / "index.html"

pytestmark = pytest.mark.skipif(not shutil.which("node"),
                                reason="node is needed to parse JavaScript")


def _check(js: str, label: str):
    """Parse without executing. `--check` needs a file, and a browser script is
    not a CommonJS module, so it is wrapped the way the browser sees it."""
    proc = subprocess.run([shutil.which("node"), "--input-type=module", "--check"],
                          input=js, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.fail(f"{label} is not valid JavaScript:\n{proc.stderr[:1200]}")


@pytest.mark.parametrize("part", sorted(SRC.glob("*.js")), ids=lambda p: p.name)
def test_every_ui_source_part_parses(part):
    _check(part.read_text(), part.name)


def test_the_shipped_bundle_parses():
    """The artefact actually served. A part can be fine and the concatenation not
    — that is exactly what a stray unbalanced brace does."""
    html = BUNDLE.read_text()
    start = html.find("<script>")
    end = html.rfind("</script>")
    assert start > 0 and end > start, "no <script> block in the shipped bundle"
    _check(html[start + len("<script>"):end], "agentos/ui/index.html")

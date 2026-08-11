"""Every picture in the docs points at a file that exists.

A broken image in a README is a small, permanent lie about the software, and it is
the kind that survives for years because nobody reads their own README on GitHub.
It happens the same way every time: a screenshot is renamed or regenerated under a
different name, and the reference somewhere else is not.

Also checks the reverse, loosely: a screenshot nobody references is either a
leftover from a flow that changed, or a picture somebody forgot to use.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s]+)\)")
DOCS = sorted(ROOT.glob("docs/*.md")) + [ROOT / "README.md"]


def refs():
    for md in DOCS:
        for m in IMAGE.finditer(md.read_text()):
            src = m.group("src")
            if src.startswith("http"):
                continue                     # badges; not ours to keep alive
            yield md, m.group("alt"), (md.parent / src).resolve()


@pytest.mark.parametrize("md,alt,path",
                         list(refs()),
                         ids=lambda v: v.name if isinstance(v, Path) else None)
def test_the_picture_is_there(md, alt, path):
    assert path.exists(), f"{md.relative_to(ROOT)} points at a missing {path.name}"


@pytest.mark.parametrize("md,alt,path", list(refs()),
                         ids=lambda v: v.name if isinstance(v, Path) else None)
def test_the_picture_says_what_it_shows(md, alt, path):
    """Alt text is what somebody gets when the image does not load, and what a
    screen reader reads out. "screenshot" is neither."""
    assert len(alt.strip()) > 25, f"{path.name} in {md.name} needs real alt text"


def test_no_screenshot_is_orphaned():
    used = {p.name for _, _, p in refs()}
    have = {p.name for p in (ROOT / "docs" / "screenshots").glob("*.png")}
    orphans = sorted(have - used)
    assert not orphans, ("nothing references " + ", ".join(orphans) +
                         " — a leftover from a flow that changed, or a picture "
                         "somebody forgot to use")

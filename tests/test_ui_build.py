"""The shipped ui/index.html must always match what ui/src assembles to."""
import pathlib

from agentos.ui import build


def test_index_html_is_fresh():
    assembled = build.assemble()
    shipped = build.OUT.read_text()
    assert assembled == shipped, (
        "agentos/ui/index.html is stale — edit files under agentos/ui/src/ "
        "and run: python -m agentos.ui.build"
    )


def test_src_layout_complete():
    src = pathlib.Path(build.SRC)
    assert (src / "head.html").exists()
    assert (src / "shell.html").exists()
    assert list((src / "css").glob("*.css")), "no css parts"
    assert list((src / "js").glob("*.js")), "no js parts"

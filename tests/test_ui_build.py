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


def test_the_shipped_bundle_parses():
    """One missing `pRow(` in Settings made the whole bundle a syntax error: every app,
    the dock and the wizard were dead, and every other test passed because none of
    them runs the script. When Node is here, the built <script> must at least parse."""
    import re
    import shutil
    import subprocess
    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    html = build.OUT.read_text()
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert scripts
    for i, body in enumerate(scripts):
        r = subprocess.run([node, "-e", "new Function(require('fs').readFileSync(0,'utf8'))"],
                           input=body, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"script {i} does not parse: {r.stderr.strip()[:400]}"

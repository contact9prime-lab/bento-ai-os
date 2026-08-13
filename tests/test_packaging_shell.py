"""The shell the installers actually run on, which is not the shell they were written on.

Every wizard here is authored and built on Linux, where /bin/bash is 5.x, and then
run on somebody else's machine. macOS is the one that bites: it still ships bash
**3.2.57**, frozen in 2007 at the last GPLv2 release, and that bash parses variable
names as BYTES rather than characters.

So `"$PREFIX…"` — an ordinary progress line — makes bash 3.2 read the ellipsis's
UTF-8 bytes as part of the name, look up `PREFIX\xe2\x80\xa6`, find nothing, and
abort under `set -u`. The macOS installer died on exactly that line, on every stock
Mac, before it created the venv. Nothing on the build machine can reveal it: bash 5
gets it right, so the script is correct everywhere it is tested and broken
everywhere it is used.

That is why this is a test and not a review note. `${VAR}` is the fix, and it is
invisible enough that the next person writing a progress line will not think of it.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# Shipped to end users' shells. dist/ is excluded: those carry an appended binary
# tarball, and random compressed bytes match anything.
SHELL_SCRIPTS = sorted(
    p for p in list((REPO / "packaging").rglob("*.sh")) + [REPO / "install.sh"]
    if "dist" not in p.parts and p.is_file()
)

# `$NAME` or `${NAME}` immediately followed by a byte that starts a UTF-8 sequence.
_UNBRACED = re.compile(rb"\$([A-Za-z_][A-Za-z0-9_]*)([\x80-\xff])")


def test_there_are_shell_scripts_to_check():
    """A glob that silently matches nothing would make every test below vacuous."""
    assert SHELL_SCRIPTS, "no packaging shell scripts found — has the layout moved?"


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_no_bare_variable_touches_a_non_ascii_character(script):
    """`$VAR…` is fatal on macOS's bash 3.2. Braces make it a variable again."""
    bad = []
    for lineno, line in enumerate(script.read_bytes().split(b"\n"), 1):
        # A full-line comment cannot break a shell, and the note explaining this very
        # trap has to be allowed to quote the broken form. Inline comments are left in
        # scope: they sit on a line that does run, and the cost of reading one is a set
        # of braces.
        if line.lstrip().startswith(b"#"):
            continue
        for m in _UNBRACED.finditer(line):
            tail = line[m.start(2):m.start(2) + 4].decode("utf-8", "replace")[0]
            bad.append(f"{script.relative_to(REPO)}:{lineno}: ${m.group(1).decode()}{tail}"
                       f"  →  write ${{{m.group(1).decode()}}}{tail}")
    assert not bad, (
        "bash 3.2 (macOS) will read the non-ASCII bytes as part of the variable name "
        "and abort under `set -u`:\n  " + "\n  ".join(bad))


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_parses_under_the_oldest_bash_we_ship_to(script):
    """Syntax the build machine's bash accepts and macOS's does not, caught here.

    Skipped rather than faked when there is no bash 3.2 to hand — a green tick from
    bash 5 would say nothing about the shell this is guarding.
    """
    bash = "/bin/bash"
    if not Path(bash).exists():
        pytest.skip("no /bin/bash")
    ver = subprocess.run([bash, "-c", "echo $BASH_VERSION"],
                         capture_output=True, text=True).stdout.strip()
    if not ver.startswith("3."):
        pytest.skip(f"/bin/bash is {ver}; this guard needs the macOS 3.2 parser")
    r = subprocess.run([bash, "-n", str(script)], capture_output=True, text=True)
    assert r.returncode == 0, f"{script.name} does not parse on bash {ver}:\n{r.stderr}"


# ---------------------------------------------------------------------------
# install.sh: the promise is a machine that ANSWERS, not files that landed
# ---------------------------------------------------------------------------

INSTALL_SH = REPO / "install.sh"


def test_the_installer_proves_the_thing_it_installed_works():
    """Every failure this project has shipped looked like a successful install.

    A wheel that unpacked and a server that could not start; a bridge whose flags
    the installed CLI did not have; a first-run screen answering 404 because the
    process predated the route. In all of them the installer said "done". So the
    last thing it does is start the server and ask it a question that needs the
    whole stack alive — and it must FAIL if that does not answer, rather than
    printing a success nobody checked.
    """
    src = INSTALL_SH.read_text()
    assert "/api/onboarding" in src, \
        "the check must hit a route that needs config, database and routes together"
    assert "--no-browser" in src, "the verification must not open a window"
    assert "stopping here rather than reporting a success nobody checked" in src, \
        "a failed verification has to fail the install"


def test_the_verification_uses_a_spare_port():
    """A machine already running AgentOS must not have its session disturbed by
    its own installer."""
    src = INSTALL_SH.read_text()
    assert "AGENTOS_PROBE_PORT" in src and "8321" not in src.split("PROBE_PORT")[1][:80]


def test_the_installer_asks_agentos_what_is_missing_rather_than_its_own_shell():
    """`command -v node` is the wrong test: the server resolves binaries over an
    extended PATH because a GUI-launched process does not inherit nvm. Asking this
    script's PATH reports a gap for a Node the product can see perfectly well."""
    src = INSTALL_SH.read_text()
    assert "wa_baileys" in src, "the WhatsApp gap must come from the product's own probe"
    # Comments stripped, like the bash-3.2 check above and for the same reason: the
    # note explaining the trap has to be free to name the broken form.
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert "command -v node" not in code, "a second, weaker copy of the Node check"


# ---------------------------------------------------------------------------
# The container image
# ---------------------------------------------------------------------------

DOCKERFILE = REPO / "Dockerfile"


def test_the_image_does_not_pipe_curl_into_bash_at_runtime():
    """The original was `CMD ["curl", url, "|", "bash"]`, which cannot work.

    Exec-form CMD runs no shell, so `|` and `bash` went to curl as extra URLs —
    the script was printed, never run. And it ran at container START, so the image
    held nothing and every restart re-installed the world from `master`, meaning a
    build told you nothing about the code you were sitting next to.
    """
    src = DOCKERFILE.read_text()
    # Comments stripped: the note explaining the trap quotes the broken form, as
    # in the shell checks above.
    code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
    assert '"|"' not in code, "a pipe in exec form is an argument, not a pipe"
    # Only the RUNTIME command. `curl … astral.sh/uv/install.sh | sh` at build time
    # is how uv (and therefore Python) gets into the image at all — a blanket ban on
    # the string would forbid the one line that has to be there.
    # Unindented only: HEALTHCHECK's own `CMD curl …` is a continuation line, and it
    # is *supposed* to curl — that is how the check checks.
    runtime = [ln for ln in code.splitlines()
               if ln.startswith(("ENTRYPOINT", "CMD"))]
    assert runtime, "the image has no ENTRYPOINT or CMD"
    joined = " ".join(runtime)
    assert "curl" not in joined and "install.sh" not in joined, \
        "the image builds the app at BUILD time; it must not install itself on start"


def test_the_entrypoint_comes_from_the_build_context():
    """It is packaging, not application code.

    Taken from the cloned tree, `SOURCE=git REF=<older than the file>` built an
    image that could not start — `[FATAL tini] exec …docker-entrypoint.sh failed`,
    which says nothing about refs.
    """
    src = DOCKERFILE.read_text()
    assert "COPY packaging/docker-entrypoint.sh" in src
    assert "/opt/agentos/packaging/docker-entrypoint.sh" not in src.split("ENTRYPOINT")[-1]


def test_both_source_modes_exist_and_are_separate_stages():
    """A Dockerfile has no `if`, and a clone layered over a COPY would half-mix."""
    src = DOCKERFILE.read_text()
    assert "FROM base AS src-local" in src
    assert "FROM base AS src-git" in src
    assert "FROM src-${SOURCE}" in src


def test_the_image_declares_what_is_inside_it():
    src = DOCKERFILE.read_text()
    assert "ai.bento.ref" in src and "ai.bento.source" in src

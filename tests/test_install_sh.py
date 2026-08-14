"""install.sh — the two claims it makes about `bento` that were both untrue on Linux.

The failure this file exists to prevent is not a crash. It is an install that prints
`✓ AgentOS is installed`, tells you to run `bento tui`, and leaves a machine where
`bento` is `command not found` — with nothing anywhere admitting the gap. That shape
of bug survives every kind of review, because reading the script it looks correct:
the PATH block is there, it is well commented, and it is dead code.

Two invariants, both structural, both about ORDERING — which is exactly what a
reader's eye skips:

1. install.sh prepends $HOME/.local/bin to its OWN PATH in step 2, so `uv` is
   runnable for the rest of the script. Every later question of the form "is
   $HOME/.local/bin on the user's PATH?" must therefore be asked of the PATH we were
   STARTED with, never of $PATH. Asking $PATH always answers yes, which skipped
   writing the line to the user's shell rc, on every platform, every time.

2. The `bento` shim must resolve `uv` to an absolute path. `exec uv run …` inherits
   PATH from whoever runs the shim — fine from an interactive shell that just found
   `bento` in the same directory, and wrong from a systemd unit, a cron line, or a
   .desktop `Exec=`, each of which gets "uv: not found" for a command that is
   plainly installed.

Both are asserted against the source rather than by running an install, because a
real install needs the network, a Python download and several minutes. The
end-to-end proof belongs in a container; this is the guard that runs on every commit.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO / "install.sh"
SRC = INSTALL_SH.read_text()
LINES = SRC.split("\n")


def _lineno(pattern: str) -> int:
    """1-based line number of the first line matching `pattern`, or 0."""
    rx = re.compile(pattern)
    return next((i for i, ln in enumerate(LINES, 1) if rx.search(ln)), 0)


def test_install_sh_exists():
    """A moved installer would make every assertion below vacuously true."""
    assert INSTALL_SH.is_file()


# ------------------------------------------------- 1. the PATH check must be honest

def test_original_path_is_captured_before_the_script_widens_its_own():
    """ORIG_PATH has to be read before the line that destroys the answer.

    Capturing it afterwards is the same bug with an extra variable, and it looks
    just as correct.
    """
    captured = _lineno(r'^\s*ORIG_PATH="\$PATH"')
    widened = _lineno(r'^\s*PATH="\$HOME/\.local/bin:\$HOME/\.cargo/bin:\$PATH"')
    assert captured, "install.sh no longer captures the inherited PATH as ORIG_PATH"
    assert widened, "install.sh no longer prepends ~/.local/bin to its own PATH"
    assert captured < widened, (
        f"ORIG_PATH is captured on line {captured}, after PATH is widened on line "
        f"{widened} — so it records the widened copy and the rc-file block below "
        f"becomes dead code again")


def test_the_on_path_test_asks_the_inherited_path_not_the_widened_one():
    """The `case` that decides whether to write the user's shell rc."""
    m = re.search(r'case\s+":(\$\w+):"\s+in\s*\n\s*\*":\$BIN:"\*\)', SRC)
    assert m, "the ~/.local/bin PATH membership test has moved or changed shape"
    assert m.group(1) == "$ORIG_PATH", (
        f"the PATH membership test asks {m.group(1)}, which this script widened "
        f"itself — it will always match, and no PATH line will ever be written")


def test_a_shell_rc_is_created_when_none_exists():
    """`[ -f "$rc" ] || continue` over three fixed files writes nothing at all on a
    fresh Debian/Alpine/Arch account, or for anyone on zsh with no ~/.zshrc — the
    same silent "installed but not found", reached a different way."""
    assert re.search(r'\[ ! -f "\$want" \] && : > "\$want"', SRC), (
        "install.sh no longer creates the login shell's rc file when it is absent")


def test_fish_users_are_told_the_syntax_that_works_for_them():
    """`export PATH=...` in config.fish is a syntax error, so silence there would be
    advice that actively fails."""
    assert "fish_add_path" in SRC


# ------------------------------------------------------------- 2. the `bento` shim

def _shim() -> str:
    m = re.search(r"cat > \"\$BIN/\$cmd\" <<SHIM\n(.*?)\nSHIM", SRC, re.S)
    assert m, "the bento/agentos shim heredoc has moved or changed shape"
    return m.group(1)


def test_the_shim_execs_uv_by_absolute_path():
    # The heredoc is unquoted, so `$DIR` interpolates at install time and anything
    # meant to survive into the shim is written `\$`. Both forms are read here.
    shim = _shim()
    assert re.search(r'^exec "\\?\$UV" run --project', shim, re.M), (
        "the shim execs a bare `uv`, so it only works from a shell whose PATH "
        "already has it — not from systemd, cron or a .desktop Exec=")
    assert 'UV="$UV_BIN"' in shim or re.search(r'^UV="/', shim, re.M), (
        "the shim does not bake in a resolved uv path")


def test_the_shim_falls_back_and_says_so_rather_than_dying_as_127():
    """After `uv self update` or a distro package swap the baked path can go stale.
    `command -v` recovers it; a sentence is what is left when even that fails."""
    shim = _shim()
    assert "command -v uv" in shim, "no fallback when the baked uv path goes stale"
    assert "astral.sh/uv/install.sh" in shim, (
        "the shim fails without telling anyone how to put uv back")


# --------------------------------------------------- 3. the address it answers on

def test_bind_and_port_are_accepted_as_flags():
    """`--passphrase` alone binds 0.0.0.0:8321. A server that has to answer on one
    interface, or on a particular port, could only be set up by installing first and
    then reconfiguring — two steps and a restart, for something known at install time."""
    for flag in ("--bind=*)", "--port=*)"):
        assert flag in SRC, f"install.sh no longer accepts {flag.rstrip(')*')}"


def test_bind_without_a_passphrase_is_refused_not_silently_applied():
    """Binding off loopback without a lock is the one thing this project will not do
    on a flag alone — the agent has a real shell, so an open port is an open shell.
    `serve` refuses it anyway; accepting it here would teach that it worked."""
    assert re.search(r'elif \[ -n "\$BIND" \]; then', SRC), (
        "--bind given without --passphrase is no longer reported")
    assert "binding off loopback needs a passphrase" in SRC


def test_the_bind_is_decided_before_the_port_is_verified():
    """`bento remote --port` proves the port by binding it against whichever
    interface the config currently names. macOS refuses 127.0.0.1:80 to a non-root
    process while ALLOWING 0.0.0.0:80, so verifying the port while the config still
    said loopback printed a refusal for a setup that was two lines from working."""
    bind_at = _lineno(r'^if \[ -n "\$PASSPHRASE" \]; then')
    port_at = _lineno(r'^if \[ -n "\$PORT_WANTED" \]; then')
    assert bind_at and port_at
    assert bind_at < port_at, (
        f"the port is verified on line {port_at}, before the bind is set on line "
        f"{bind_at} — so port 80 on 0.0.0.0 is checked against 127.0.0.1")


def test_the_installer_does_not_guess_privilege_from_the_port_number():
    """The guess is wrong on macOS and tunable on Linux. install.sh must show what
    `bento remote --port` learned by binding, not re-derive it in shell."""
    assert "-lt 1024" not in SRC, (
        "install.sh decides privilege from the port number again")


def test_the_probe_follows_the_bind_address():
    """Step 6 asks 'is it listening?' before deciding to start a second copy. A server
    bound to one named interface does not answer on 127.0.0.1 at all, so probing
    loopback reports a healthy machine as dead and then starts a rival beside it."""
    assert "PROBE_HOST" in SRC
    assert re.search(r'listening\(\).*\$\{PROBE_HOST\}:\$\{PORT\}', SRC), (
        "the liveness probe no longer uses the address the server was bound to")


def test_the_curl_pipe_argument_trap_is_documented():
    """`curl … | sh --port=80` gives the flag to sh, which rejects it. The error names
    sh, not AgentOS, so it reads as a broken installer."""
    assert "sh -s --" in SRC, "the `sh -s --` form is not documented anywhere"


def test_an_unknown_flag_is_refused_rather_than_ignored():
    """A typo in a piped one-liner used to install a DIFFERENT configuration than the
    one asked for, silently — `--pasphrase=x` produced a loopback-only machine and a
    success message."""
    assert re.search(r"^\s*-\*\).*exit 2", SRC, re.M), (
        "unknown flags are silently ignored again")


def test_the_installer_proves_the_shim_runs_before_advertising_it():
    """Step 5 of this installer exists because every shipped failure looked like a
    successful install. The command it prints at the end deserves the same bar."""
    assert re.search(r'if "\$BIN/bento" --help', SRC), (
        "install.sh announces the `bento` command without ever running it")

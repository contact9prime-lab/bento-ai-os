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
    assert re.search(r'for w in \$want; do\n\s*\[ -f "\$w" \] \|\| : > "\$w"', SRC), (
        "install.sh no longer creates the login shell's rc file when it is absent")


def test_zsh_gets_zprofile_as_well_as_zshrc():
    """`.zshrc` alone is not enough: zsh reads it for INTERACTIVE shells only.

    A zsh user in a terminal is fine, but `ssh host 'bento service status'` is a
    login, non-interactive shell — it reads .zshenv/.zprofile/.zlogin and never
    .zshrc. So the command was still not found over SSH, which is exactly how a
    headless machine gets driven. Found by a container test doing precisely that.
    """
    assert re.search(r'\*/zsh\)\s+want="\$HOME/\.zshrc \$HOME/\.zprofile"', SRC), (
        "zsh's login shell is not covered — only its interactive one")
    assert '"$HOME/.zprofile"' in SRC, ".zprofile is not in the list of files written"


def test_the_source_line_names_the_rc_the_users_own_shell_reads():
    """The message was hardcoded to `. ~/.bashrc`. zsh is the default shell on macOS
    and common on Linux, so those users ran it, nothing changed, and had to work out
    for themselves that they wanted ~/.zshrc.

    A script cannot put a directory on the PATH of the shell that invoked it — the
    export happens in a child and dies with it — so this really is the user's step.
    All the more reason for it to be one correct line they can paste.
    """
    assert 'source $rc_now' in SRC or 'source %s' in SRC, (
        "no `source <rc>` line is printed")
    assert re.search(r'\*/zsh\)\s+rc_now="\$HOME/\.zshrc"', SRC), (
        "the source line does not branch on the user's shell")
    # Comments are exempt, as in tests/test_packaging_shell.py: the note recording
    # this trap has to be allowed to quote the broken form it replaced.
    code = "\n".join(ln for ln in LINES if not ln.strip().startswith("#"))
    assert '. ~/.bashrc' not in code, "the hardcoded bashrc advice is back"


def test_the_source_step_is_printed_outside_the_gaps_list():
    """Every `bento …` line the installer prints is unreachable until this is done,
    so it is a required step, not a gap. Buried in a list headed 'working, with these
    gaps' it reads as optional."""
    assert "SOURCE_ME" in SRC
    assert re.search(r'if \[ -n "\$SOURCE_ME" \]; then', SRC), (
        "the source step is no longer printed in the closing block")


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


def test_the_final_line_reports_what_was_found_not_what_was_attempted():
    """`✓ AgentOS is running.` was printed whenever the service step had been TRIED.

    On a box with no service manager to reach — a container, a non-systemd distro,
    SSH with no user D-Bus — step 6 reported "the background service did not come up"
    and then this line claimed it was running, four lines later, in the same output.
    Both sentences on screen at once, and the false one last. That is precisely the
    shape of lie step 5 of this installer exists to prevent.
    """
    assert re.search(r'^if \[ -n "\$RUNNING" \]; then\n\s*ok "AgentOS is running\."',
                     SRC, re.M), (
        "the closing 'AgentOS is running' is no longer conditional on anything "
        "actually listening")
    assert 'RUNNING=1' in SRC, "nothing ever records that the server came up"


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


# ------------------------------------------- 3. the network preflight must be honest
#
# This gate can only ever be wrong in one direction that matters. A false PASS
# costs a clear error a few seconds later, from whichever step actually needed the
# network. A false FAIL refuses the whole install and blames the user's wifi — and
# it did, on every network whose proxy answers a bare GET with 403.

def test_the_preflight_probes_the_package_index_it_installs_from():
    """`uv sync` cannot proceed without PyPI, and the old probe list never asked."""
    assert re.search(r'probes=".*pypi\.org', SRC), (
        "the network preflight no longer probes PyPI, which is the one host the "
        "dependency install genuinely requires")


def test_the_preflight_does_not_veto_on_astral_when_uv_is_already_here():
    """astral.sh exists to INSTALL uv. Probing it when uv is present lets a host we
    have no use for decide the install cannot happen."""
    guarded = _lineno(r'command -v uv .*\|\| probes=".*astral\.sh')
    assert guarded, (
        "astral.sh is probed unconditionally again — a machine that already has uv "
        "is refused because a host it will never contact is unreachable")
    unconditional = _lineno(r'^\s*for probe in .*astral\.sh')
    assert not unconditional, (
        f"line {unconditional} probes astral.sh unconditionally in the loop itself")


def test_the_git_remote_is_accepted_as_proof_of_a_working_network():
    """The clone is the one operation this script cannot skip, so a remote that
    answers is better evidence than any homepage — and it is the only probe that
    tests an AGENTOS_REPO override rather than assuming it."""
    assert re.search(r'git ls-remote --heads "\$REPO"', SRC), (
        "the git-remote fallback is gone; the preflight is back to judging the "
        "network by hosts it does not clone from")


def test_the_git_probe_cannot_hang_on_a_credential_prompt():
    """A repo git cannot see is answered with a username prompt, not a 404 — the note
    at the top of install.sh is that incident. Unattended, that prompt is a hang."""
    assert re.search(r'GIT_TERMINAL_PROMPT=0 git ls-remote', SRC), (
        "the git probe can prompt for credentials, which hangs a piped install")


def test_the_git_fallback_runs_after_the_cheap_probes_not_before():
    """Ordering: curl against a CDN is milliseconds, a git handshake is not. The
    fallback is for when the cheap answer was wrong, so it must come second."""
    curl_probe = _lineno(r'^\s*for probe in \$probes')
    git_probe = _lineno(r'git ls-remote --heads "\$REPO"')
    assert curl_probe and git_probe, "the preflight has changed shape"
    assert curl_probe < git_probe, (
        f"the git handshake on line {git_probe} runs before the cheap curl probes "
        f"on line {curl_probe}, so every install pays for it")


# --- 32-bit Raspberry Pi: prefer prebuilt wheels, and show progress ----------

def test_32bit_arm_points_uv_at_piwheels_to_avoid_the_source_compile():
    """armv6l/armv7l has no PyPI wheel for cffi/cryptography/pydantic-core, so uv
    compiles them — minutes of 100% CPU that reads as a hang. piwheels is the Pi
    project's ARM wheelhouse; uv must be pointed at it, because unlike pip it does
    not use it by default. `unsafe-best-match` is what lets a supplemental index
    satisfy a wheel PyPI only has as an sdist, and it is added ONLY on 32-bit ARM."""
    assert re.search(r'armv6l\|armv7l\)', SRC), "the 32-bit ARM case must be detected"
    assert "https://www.piwheels.org/simple" in SRC, "piwheels must be offered on 32-bit ARM"
    assert "--index-strategy unsafe-best-match" in SRC, (
        "without unsafe-best-match uv stops at PyPI's sdist and never sees piwheels")


def test_uv_sync_shows_a_heartbeat_and_keeps_uvs_own_exit_status():
    """A silent multi-minute compile at full CPU looks stopped. The run is
    backgrounded with a heartbeat so it visibly works — and `wait`, not a `| tee`
    pipe, reports the status, so uv's real failure is not masked by tee's success."""
    assert re.search(r'uv sync \$UV_PI_ARGS >"\$UVSYNC_LOG" 2>&1 &', SRC), (
        "uv sync must run in the background so a heartbeat can be printed beside it")
    run = _lineno(r'run_uv_sync\(\)')
    wait = _lineno(r'wait "\$_uvpid"')
    assert run and wait and run < wait, "run_uv_sync must wait on uv's own pid for the status"
    # the failure classifier still runs uv through the same heartbeat wrapper
    assert SRC.count("run_uv_sync") >= 3, (
        "both the first sync and the post-build-deps retry must use the heartbeat wrapper")


def test_a_cryptography_build_is_caught_before_the_generic_c_header_path():
    """A cryptography source build — spotted by the OpenSSL #error, a Rust/cargo
    failure, or "could not compile cryptography" — must be handled BEFORE the
    generic ffi.h/apt path, which installs a C compiler that cannot fix any of
    those. Ordering is the mechanism; a plain later branch would swallow it."""
    crypto = _lineno(r'grep -qiE "MUST be linked with OpenSSL 3')
    cheader = _lineno(r'grep -qiE "ffi\\\.h')
    assert crypto and cheader and crypto < cheader, (
        "the cryptography build check must run before the C-toolchain check")
    # the OpenSSL/Rust telltales are one merged condition, because all are symptoms
    # of the same fallback-to-source, not independent failures with separate fixes
    seg = SRC[SRC.index('grep -qiE "MUST be linked'):]
    line = seg.split("\n", 1)[0]
    assert 'cargo' in line and 'could not compile' in line, (
        "OpenSSL, Rust and 'could not compile' must be one condition — they are the "
        "same event (a source build) seen from different angles")


# --- the interpreter is pinned so fresh installs get wheels, not a compile ----

PYVER = (REPO / ".python-version")


def test_the_interpreter_is_pinned_below_the_bleeding_edge():
    """requires-python has no ceiling, so uv would provision the NEWEST CPython —
    and the newest release is where prebuilt wheels have not caught up, so
    cryptography/pydantic-core compile from source (cryptography needs Rust) and a
    64-bit Pi install dies for a reason that has nothing to do with ARM. A pinned
    `.python-version` at a wheel-covered release is the fix; it must exist and must
    not itself be the bleeding edge."""
    assert PYVER.is_file(), ".python-version must pin the interpreter uv provisions"
    major, minor = (int(x) for x in PYVER.read_text().strip().split(".")[:2])
    assert (major, minor) >= (3, 10), "must satisfy requires-python >=3.10"
    assert (major, minor) <= (3, 13), (
        "pinned to a Python whose wheels may not exist yet — the exact bug this pins against")


def test_a_stale_venv_on_a_newer_python_is_rebuilt_so_the_pin_takes():
    """uv reuses an existing .venv; if a prior run built it on 3.14, the pin does
    nothing until that venv is gone. The installer must detect the mismatch and
    rebuild, or the fix never reaches a machine that already failed once."""
    assert re.search(r'\.venv/bin/python -c .*version_info', SRC), (
        "the installer must read the existing venv's Python version")
    assert re.search(r'rm -rf \.venv', SRC), "a mismatched venv must be rebuilt, not reused"


def test_the_cryptography_message_is_arch_aware():
    """The same source-build failure means different things by architecture, so the
    handler branches: armv7l, armv6l, and 64-bit each get their own message."""
    seg = SRC.split('MUST be linked with OpenSSL 3', 1)[1][:3000]
    assert re.search(r'armv7l\)', seg), "must branch for 32-bit armv7"
    assert re.search(r'armv6l\)', seg), "must branch for armv6 (Pi Zero / 1)"
    assert 'too new for it' in seg or '3.14' in seg, (
        "the 64-bit branch must name the too-new-Python cause, not send them to rustup")


def test_the_real_32bit_cause_is_named_as_glibc_not_openssl_or_rust():
    """The empirical finding: cryptography 49 SHIPS a prebuilt armv7 wheel
    (manylinux_2_31_armv7l), so the reason a 32-bit Pi compiles is glibc — Buster's
    2.28 is below the wheel's 2.31 floor, Bullseye's is exactly 2.31. OpenSSL and
    Rust are only what the fallback build then trips over. The message must send a
    Buster user to Bullseye+ for the prebuilt wheel, NOT to rustup."""
    # the handler measures glibc and compares against 2.31
    assert re.search(r'ldd --version', SRC), "the installer must read the system's glibc"
    assert re.search(r'-ge 31', SRC), "the 2.31 wheel floor must be the comparison"
    seg = SRC.split('MUST be linked with OpenSSL 3', 1)[1][:3000]
    assert 'glibc 2.31' in seg, "the armv7 message must name the real requirement (glibc 2.31)"
    assert 'Buster' in seg and ('Bullseye' in seg), (
        "it must name Buster as too-old and Bullseye/Bookworm as the fix")
    assert '32-BIT IS FINE' in seg or '32-bit is fine' in seg.lower(), (
        "the whole point: staying 32-bit is fine, only the OS version must move")


# ------------------------------------- 4. the question a headless install must ask

def test_the_interactive_test_is_not_stdin():
    """`[ -t 0 ]` is false on the ONE path everybody uses.

    The documented install is `curl … | sh`, so stdin is the pipe. Every question in
    this script — including "install the build tools?" — was therefore answered "no"
    without being asked, on a script whose whole design is to ask before it changes
    anything. The reads already targeted /dev/tty; the test has to agree with them.
    """
    assert 'INTERACTIVE=' in SRC, "install.sh no longer decides whether anybody is here"
    assert re.search(r'\[ -c /dev/tty \] && \(: </dev/tty\)', SRC), (
        "the interactive test does not look for a controlling terminal, so a piped "
        "install silently declines every question in this script")
    # And it must still be able to answer "nobody": a systemd unit or a docker build
    # has no /dev/tty, and blocking on a prompt there is worse than not asking.
    assert re.search(r'ask\(\)[^}]*\[ -n "\$INTERACTIVE" \] \|\| return 1', SRC, re.S), (
        "ask() no longer refuses to prompt when there is no terminal")


def test_the_machine_is_asked_how_it_will_be_reached():
    """On a Pi over SSH, loopback-only means "reachable by nothing" — and the desktop
    is a browser page, so an install nobody can open is the normal outcome of saying
    nothing. The old script's only mention of it was one line at the end of a long log.
    """
    assert 'bento remote --on --passphrase "$pass1"' in SRC, (
        "install.sh no longer offers to open the port")
    assert "make this machine reachable" in SRC


def test_opening_the_port_is_not_answered_by_yes():
    """`--yes` is consent to install THINGS. The agent behind this port has a real
    shell, so opening it is consent to hand that shell to whatever can reach the
    machine — a different decision, and not one a flag typed to skip package prompts
    may make. It needs a passphrase a person chose, which is why there is no
    `--remote` flag either."""
    m = re.search(r'ask_deliberate\(\) \{(.*?)\n\}', SRC, re.S)
    assert m, "the deliberate-consent prompt has gone"
    assert "ASSUME_YES" not in m.group(1), (
        "ask_deliberate consults --yes, so an unattended install can open the port")
    assert re.search(r'if ask_deliberate "make this machine reachable', SRC), (
        "the remote-access offer is back on the --yes-answerable prompt")


def test_the_passphrase_is_not_echoed_into_the_scrollback():
    """A shared terminal, a screen recording, a scrollback buffer somebody pastes
    into an issue. `stty` may be absent on a stripped image, and the fallback says so
    rather than pretending."""
    m = re.search(r'ask_secret\(\) \{(.*?)\n\}', SRC, re.S)
    assert m, "the secret prompt has gone"
    assert "stty -echo" in m.group(1)
    assert "typed in the clear" in m.group(1), (
        "the no-stty fallback echoes the passphrase without admitting it")


def test_the_port_is_decided_before_the_launcher_is_installed():
    """The systemd unit / LaunchAgent bakes in what the config says AT INSTALL TIME.
    Asked afterwards, the answer needs a restart nobody knows to perform, and the
    machine that was just told "reachable from your network" is not."""
    offer_at = _lineno(r'if ask_deliberate "make this machine reachable')
    launcher_at = _lineno(r'^\s*uv run bento install \|\| warn')
    assert offer_at and launcher_at
    assert offer_at < launcher_at, (
        f"the launcher is installed on line {launcher_at}, before the machine is "
        f"asked how it will be reached on line {offer_at}")


def test_the_closing_block_names_one_next_step():
    """Seven `bento …` lines at equal weight, printed to somebody who has just watched
    five minutes of log scroll past, is not an answer to "what do I do now?" — and on
    a machine that has never been set up that question has exactly one answer."""
    tail = SRC.split("# done\n# ---", 1)[-1]
    assert "bento setup" in tail, "the closing block no longer names the next step"
    assert "bento help" in tail, (
        "the closing block does not say where the rest of the commands are")
    # The old list, back in full, is the regression this guards. Counted over the
    # lines that PRINT, so a comment explaining the change does not inflate it.
    printed = "\n".join(ln for ln in tail.split("\n")
                        if re.match(r'\s*(echo|printf)\b', ln))
    verbs = sorted(set(re.findall(r'\bbento ([a-z][a-z-]*)', printed)))
    assert verbs, "the closing block names no commands at all"
    assert len(verbs) <= 5, (
        f"the closing block offers {len(verbs)} commands again: {verbs}")


def test_the_install_offers_an_account_as_well_as_a_passphrase():
    """"Where is the user?" is the question a passphrase leaves behind.

    A passphrase is not a login: on a machine with no accounts you sign in with
    one shared secret and you ARE the machine (uid ''), which is the right shape
    for one person and one Pi and is genuinely confusing if you expected a
    username. So the install asks which door you want.
    """
    assert "Two ways to sign in" in SRC, (
        "the install no longer offers an account — a passphrase is the only way "
        "in, and nothing says what you are signing in AS")
    assert re.search(r'uv run bento user add "\$who"', SRC), (
        "nothing creates the first account")
    assert re.search(r'uv run bento remote --on --bind "\$bind_to"', SRC), (
        "the account path still passes a passphrase — accounts ARE the lock, and "
        "a second secret in front of them is config nothing reads")


def test_the_chosen_sign_in_survives_a_retry():
    """`ask_line` writes ANSWER, and the retry loop asks for a username with it.
    Re-testing ANSWER for the MODE meant one mistyped password dropped you from
    the account path into the passphrase path — and the install then reported
    "sign in with that passphrase" to somebody who had just chosen a username."""
    assert re.search(r'signin="\$ANSWER"', SRC), (
        "the sign-in choice is not held apart from the last thing typed")
    assert '[ "$signin" = "2" ]' in SRC, (
        "the retry loop reads the mode out of ANSWER again")
    assert '[ "$ANSWER" = "2" ]' not in SRC


def test_the_last_lines_say_what_to_sign_in_with():
    """An address nobody can get into is not an address."""
    tail = SRC.split("# done\n# ---", 1)[-1]
    assert "sign in as:" in tail and "sign in with:" in tail, (
        "the closing block gives an address without saying who signs in there")

"""What a jailed command can see and do, measured by running one. These are not argv checks: the
audit's point (S-16, S-18, S-55) was that the argv looked fine and the secrets were in plain view."""
import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import config as cfgmod                                # noqa: E402
from agentos import protected                                       # noqa: E402
from agentos import ptyhub                                          # noqa: E402
from agentos import safeopen                                        # noqa: E402
from agentos import secevents                                       # noqa: E402
from agentos import tools as toolsmod                               # noqa: E402
from agentos import users as usersmod                               # noqa: E402

JAIL = pytest.mark.skipif(toolsmod.sandbox_mechanism() != "bwrap", reason="needs a bwrap that can be entered")
SECRETS = ["session.key", "vault.key", "config.json", "users.json", "agentos.db", "pki/ssh_ed25519",
           "oauth/token.json", "some-new-feature/x"]


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _plant(home: Path):
    for name in SECRETS:
        p = home / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("CANARY-" + name)
    (home / "workspace").mkdir(exist_ok=True)


def _clear(home: Path):
    """The planted files are not real ones, and creating an account reads the real ones."""
    for name in ("config.json", "users.json", "agentos.db"):
        (home / name).unlink(missing_ok=True)


@pytest.fixture(params=["/var/tmp", "/dev/shm", None], ids=["var-tmp", "dev-shm", "tmp"])
def machine(request, monkeypatch):
    """A home outside /home and /tmp is what made S-55: `--tmpfs /home` was the only cover."""
    where = request.param
    if where and not os.access(where, os.W_OK):
        pytest.skip(f"{where} is not writable here")
    home = Path(tempfile.mkdtemp(prefix="bento-jail-", dir=where))
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", home / "config.json")
    usersmod.reset_caches()
    usersmod.set_current("")
    _plant(home)
    secevents.forget_for_tests()
    yield home
    usersmod.reset_caches()
    usersmod.set_current("")
    secevents.forget_for_tests()
    shutil.rmtree(home, ignore_errors=True)


def _cfg(home, sandbox=True, root=""):
    return {"workspace": str(home / "workspace"), "sandbox": {"enabled": sandbox, "root": root}}


def _box(cfg, store=None):
    return toolsmod.Toolbox(cfg, store)


@JAIL
def test_the_machines_home_is_hidden_whatever_its_path(machine):
    tb = _box(_cfg(machine))
    out = run(tb.run_command(f"ls -la {machine} 2>&1; cat {machine}/session.key {machine}/config.json "
                             f"{machine}/pki/ssh_ed25519 2>&1; pwd"))
    assert "CANARY" not in out
    assert "session.key" not in out.replace(f"cat: {machine}/session.key", "")
    assert out.strip().endswith("workspace")


@JAIL
def test_a_root_that_contains_the_home_does_not_bring_it_back(machine):
    """A sandbox root of the folder above the home bound the home straight back in."""
    tb = _box(_cfg(machine, root=str(machine.parent)))
    out = run(tb.run_command(f"cat {machine}/session.key {machine}/vault.key 2>&1"))
    assert "CANARY" not in out


@JAIL
def test_a_root_that_is_the_home_binds_only_its_workspace(machine):
    tb = _box(_cfg(machine, root=str(machine)))
    out = run(tb.run_command(f"pwd; cat {machine}/vault.key 2>&1"))
    assert "CANARY" not in out
    assert "workspace" in out


@JAIL
def test_a_share_cannot_be_a_way_to_the_keys(machine):
    argv = toolsmod.bwrap_argv(str(machine / "workspace"), ["/bin/true"], ro_extra=[str(machine / "pki")],
                               extra=[str(machine)])
    assert str(machine / "pki") not in argv
    assert argv.count(str(machine)) == 1           # blanked once, never bound


@JAIL
def test_an_account_has_its_workspace_and_not_its_home(machine):
    _clear(machine)
    ada = usersmod.create("ada", "hunter2hunter")["id"]
    bob = usersmod.create("bob", "hunter2hunter", role="executor")["id"]
    (machine / "session.key").write_text("CANARY-machine")
    cfg = usersmod.cfg_for(bob)
    tb = toolsmod.Toolbox(cfg, usersmod.store_for(bob))
    own, other = usersmod.home_for(bob), usersmod.home_for(ada)
    for home in (own, other):
        (home / "vault.key").write_text("CANARY-vault")
    with usersmod.as_user(bob):
        out = run(tb.run_command(f"cat {own}/vault.key {other}/vault.key {machine}/session.key 2>&1; "
                                 f"test -e {own}/agentos.db && echo DB-SEEN; test -e {own}/config.json && echo CFG-SEEN; "
                                 "pwd; echo w > f.txt && echo WROTE"))
    assert "CANARY" not in out and "DB-SEEN" not in out and "CFG-SEEN" not in out
    assert "WROTE" in out and (own / "workspace" / "f.txt").exists()


@JAIL
def test_the_servers_environment_stays_out(machine, monkeypatch):
    for k in ("OPENAI_API_KEY", "BENTO_STORAGE_SECRET", "AGENTOS_PASSPHRASE", "MY_ODD_THING"):
        monkeypatch.setenv(k, "ENV-CANARY")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    out = run(_box(_cfg(machine)).run_command("cat /proc/self/environ | tr '\\0' '\\n'; env"))
    assert "ENV-CANARY" not in out
    assert "DBUS_SESSION" not in out
    assert "PATH=" in out and "HOME=" in out


@JAIL
def test_other_processes_cannot_be_seen_or_signalled(machine):
    me = os.getpid()
    out = run(_box(_cfg(machine)).run_command(
        f"kill -0 {me} 2>&1 && echo REACHED; ls /proc | grep -c '^[0-9]'; cat /proc/{me}/environ 2>&1"))
    assert "REACHED" not in out
    assert int([x for x in out.split() if x.isdigit()][0]) < 8        # bwrap, the shell, this pipeline


@JAIL
def test_the_session_bus_and_every_socket_in_run_are_gone(machine):
    out = run(_box(_cfg(machine)).run_command(
        "ls -A /run/user /run/dbus 2>&1; ls /run/docker.sock 2>&1; find /run -type s 2>/dev/null"))
    assert "docker.sock" not in out.replace("/run/docker.sock':", "").replace("access '/run/docker.sock'", "")
    assert "system_bus_socket" not in out


@JAIL
def test_a_program_still_finds_the_network_settings(machine):
    out = run(_box(_cfg(machine)).run_command("cat /etc/resolv.conf >/dev/null && echo RESOLV; getent hosts localhost"))
    assert "RESOLV" in out
    assert "localhost" in out


@JAIL
def test_a_snippet_of_python_runs_in_the_jail(machine):
    out = run(_box(_cfg(machine)).run_python("import os; print('PY', os.environ.get('AGENTOS_SANDBOX'), os.getcwd())"))
    assert "PY 1" in out
    assert "workspace" in out


@JAIL
def test_a_snippet_of_python_runs_on_an_account(machine):
    _clear(machine)
    bob = usersmod.create("bob", "hunter2hunter")["id"]
    tb = toolsmod.Toolbox(usersmod.cfg_for(bob), usersmod.store_for(bob))
    with usersmod.as_user(bob):
        out = run(tb.run_python("print('PY-OK')"))
    assert "PY-OK" in out


def test_a_command_is_cut_off_the_terminal_and_a_terminal_is_not():
    assert "--new-session" in toolsmod.bwrap_argv("/tmp/x", ["/bin/true"])
    assert "--new-session" not in toolsmod.bwrap_argv("/tmp/x", ["/bin/true"], new_session=False)


# ---- the Terminal, for real: a pty, a pid namespace, and what is in the foreground ----

async def _shell_session(machine):
    argv = toolsmod.bwrap_argv(str(machine / "workspace"), ["/bin/bash", "--norc", "-i"], new_session=False)
    s = ptyhub.spawn("jail-test", argv, cwd=str(machine / "workspace"))
    got = []

    async def sink(data):
        got.append(data)
    s.attach(sink)
    return s, got


async def _until(pred, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


@JAIL
def test_the_terminal_keeps_job_control_and_knows_what_is_running(machine):
    """CLAUDE.md: "In the jail an idle shell is bwrap's child in its own group", and terminal_send
    decides who may type from this. A pid namespace must not change the answer."""
    async def main():
        s, got = await _shell_session(machine)
        text = lambda: b"".join(got).decode(errors="replace")
        try:
            assert await _until(lambda: "$" in text() or "#" in text())
            assert "no job control" not in text()
            assert await _until(lambda: s.foreground() == "")
            s.write("sleep 30\n")
            assert await _until(lambda: s.foreground() == "sleep"), s.foreground()
            s.write("\x1a")                              # ctrl-Z: only job control can stop it
            assert await _until(lambda: "Stopped" in text()), text()
            assert await _until(lambda: s.foreground() == "")
            s.write("fg\n")
            assert await _until(lambda: s.foreground() == "sleep")
            s.write("\x03")                              # ctrl-C reaches the program
            assert await _until(lambda: s.foreground() == "")
            s.write("ps ax | wc -l; echo DONE-$((1+1))\n")
            assert await _until(lambda: "DONE-2" in text())
        finally:
            s.write("exit\n")
            await asyncio.sleep(0.2)
            ptyhub.end("jail-test", s.id) if hasattr(ptyhub, "end") else None
    asyncio.new_event_loop().run_until_complete(main())


# ---- the file tools: the same list, on every machine, whatever the toggle says ----

@pytest.mark.parametrize("sandbox", [True, False])
@pytest.mark.parametrize("name", SECRETS)
def test_the_file_tools_refuse_a_security_file(machine, sandbox, name):
    tb = _box(_cfg(machine, sandbox=sandbox))
    out = run(tb.read_file(str(machine / name)))
    assert out.startswith("[denied]") and "CANARY" not in out
    out = run(tb.write_file(str(machine / name), "overwritten"))
    assert out.startswith("[denied]")
    assert (machine / name).read_text().startswith("CANARY")


def test_a_link_in_the_workspace_does_not_reach_them(machine):
    link = machine / "workspace" / "harmless.txt"
    link.symlink_to(machine / "vault.key")
    tb = _box(_cfg(machine, sandbox=False))
    assert "CANARY" not in run(tb.read_file(str(link)))
    assert run(tb.write_file(str(link), "x")).startswith("[denied]")


def test_the_process_environment_is_not_a_file_anybody_reads(machine, monkeypatch):
    monkeypatch.setenv("BENTO_STORAGE_SECRET", "ENV-CANARY")
    out = run(_box(_cfg(machine, sandbox=False)).read_file("/proc/self/environ"))
    assert out.startswith("[denied]") and "ENV-CANARY" not in out


def test_an_agent_cli_config_cannot_be_written(machine):
    tb = _box(_cfg(machine, sandbox=False))
    for rel in (".claude/settings.json", ".mcp.json", ".git/hooks/pre-commit"):
        assert run(tb.write_file(str(machine / "workspace" / rel), "x")).startswith("[denied]")
        assert not (machine / "workspace" / rel).exists()


def test_the_wallpaper_is_not_a_way_to_read_a_file(machine):
    tb = _box(_cfg(machine, sandbox=False))
    assert run(tb.set_wallpaper(str(machine / "vault.key"))).startswith("[denied]")
    assert not (machine / "wallpaper.png").exists()


def test_reaching_for_them_is_flagged(machine):
    tb = _box(_cfg(machine, sandbox=False))
    for _ in range(3):
        run(tb.read_file(str(machine / "vault.key")))
    assert any(e["kind"] == "protected.refused" and e.get("alert") for e in secevents.recent())


def test_ordinary_work_still_works(machine):
    tb = _box(_cfg(machine))
    p = machine / "workspace" / "sub" / "config.json"
    assert run(tb.write_file(str(p), "héllo")).startswith("wrote")
    assert run(tb.read_file(str(p))) == "héllo"
    assert "not found" in run(tb.read_file(str(machine / "workspace" / "nope")))
    assert "directory" in run(tb.read_file(str(machine / "workspace")))


# ---- S-67: a link flipped after the check is refused ----

def test_a_link_that_appeared_after_the_check_is_refused(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("VICTIM")
    d = tmp_path / "d"
    d.mkdir()
    real = str(d / "f")
    os.symlink(victim, real)
    with pytest.raises(safeopen.Moved):
        safeopen.open_file(real)
    with pytest.raises(safeopen.Moved):
        safeopen.write_bytes(real, b"x")
    assert victim.read_text() == "VICTIM"
    other = tmp_path / "other"
    other.mkdir()
    (other / "f").write_text("VICTIM")
    d2 = tmp_path / "d2"
    d2.symlink_to(other)
    with pytest.raises(safeopen.Moved):
        safeopen.open_file(str(d2 / "f"))


def test_a_fifo_does_not_hang_the_server(tmp_path):
    f = tmp_path / "pipe"
    os.mkfifo(f)
    with pytest.raises(safeopen.Moved):
        safeopen.open_file(str(f))


def test_flipping_a_link_during_read_file_never_reads_the_victim(machine):
    """The audit read the victim's key 80 times in 26,631 tries with this race."""
    ws = machine / "workspace"
    ok = ws / "fine.txt"
    ok.write_text("FINE")
    secret = machine.parent / f"victim-{os.getpid()}"
    secret.write_text("VICTIM")
    link = ws / "flip"
    stop = threading.Event()

    def flip():
        tmp = str(link) + ".t"
        while not stop.is_set():
            for target in (ok, secret):
                with __import__("contextlib").suppress(OSError):
                    os.symlink(target, tmp)
                    os.replace(tmp, link)
    t = threading.Thread(target=flip, daemon=True)
    t.start()
    leaked = 0
    # the sandbox rule is what a link to `secret` would have to beat
    tb = _box(_cfg(machine))
    try:
        end = time.time() + 2.0
        while time.time() < end:
            if "VICTIM" in run(tb.read_file(str(link))):
                leaked += 1
    finally:
        stop.set()
        t.join(2)
        secret.unlink(missing_ok=True)
    assert leaked == 0


# ---- S-17: a sandbox that cannot start ----

def test_a_jail_that_cannot_be_entered_counts_as_no_jail(monkeypatch):
    """`which bwrap` said yes where every run then died on "setting up uid map"."""
    import subprocess
    monkeypatch.setitem(toolsmod._JAIL, "mech", None)
    monkeypatch.setattr(toolsmod.sys, "platform", "linux")
    monkeypatch.setattr(toolsmod.shutil, "which", lambda n: "/usr/bin/bwrap")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "bwrap: setting up uid map: Permission denied\n"))
    assert toolsmod.sandbox_mechanism() == ""
    assert "uid map" in toolsmod.jail_why_not()
    assert toolsmod.jail_state({"sandbox": {"enabled": True}})["working"] is False


def test_the_answer_is_kept_so_a_command_does_not_pay_for_a_probe(monkeypatch):
    calls = []
    monkeypatch.setitem(toolsmod._JAIL, "mech", None)
    monkeypatch.setattr(toolsmod, "_jail_probe", lambda: (calls.append(1) or ("bwrap", "")))
    for _ in range(50):
        assert toolsmod.sandbox_mechanism() == "bwrap"
    assert len(calls) == 1


@pytest.fixture()
def no_jail(machine, monkeypatch):
    monkeypatch.setattr(toolsmod, "sandbox_mechanism", lambda: "")
    monkeypatch.setitem(toolsmod._JAIL, "why", "bubblewrap is not installed.")
    return machine


def test_no_jail_means_no_command_without_a_person(no_jail):
    out = run(_box(_cfg(no_jail)).run_command("echo RAN-IT"))
    assert out.startswith("[denied]") and "RAN-IT" not in out
    out = run(_box(_cfg(no_jail)).run_python("print('RAN-IT')"))
    assert "RAN-IT" not in out


def test_no_jail_keeps_the_folder_rule_in_the_file_tools(no_jail):
    tb = _box(_cfg(no_jail))
    outside = no_jail.parent / f"outside-{os.getpid()}.txt"
    outside.write_text("OUTSIDE")
    try:
        out = run(tb.read_file(str(outside)))
        assert out.startswith("[denied]") and "OUTSIDE" not in out
        assert run(tb.read_file(str(no_jail / "vault.key"))).startswith("[denied]")
        assert run(tb.write_file(str(no_jail / "workspace" / "a.txt"), "ok")).startswith("wrote")
    finally:
        outside.unlink()


def test_no_jail_with_a_persons_yes_runs_without_the_servers_keys(no_jail, monkeypatch):
    monkeypatch.setenv("BENTO_STORAGE_SECRET", "ENV-CANARY")
    tok = toolsmod._jail_waived.set(True)
    try:
        out = run(_box(_cfg(no_jail)).run_command("echo RAN-IT; env"))
    finally:
        toolsmod._jail_waived.reset(tok)
    assert "RAN-IT" in out and "ENV-CANARY" not in out


def test_every_face_reads_one_sentence(no_jail):
    st = toolsmod.jail_state({"sandbox": {"enabled": True}})
    assert st["enabled"] and not st["working"] and "cannot start" in st["words"]
    assert toolsmod.jail_gap({"sandbox": {"enabled": True}})
    assert not toolsmod.jail_gap({"sandbox": {"enabled": False}})


def test_the_sentence_is_protected_too():
    # a new kind must exist before it can be flagged
    assert "protected.refused" in secevents.KINDS and "jail.missing" in secevents.KINDS
    assert "agentos/safeopen.py" in protected.SECURITY_MODULES

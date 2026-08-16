"""Safe folders — the other places the agent may work, and the one place it may not.

The jail has a single root and that root is the workspace, which is not where
anybody's data lives. "Summarise last quarter's invoices" therefore began with
copying them into the workspace — a chore that also duplicates the data. A safe
folder is the user saying "this one too".

The whole risk is in one sentence: `sandbox` is a MACHINE setting (it is not in
users.USER_KEYS), so on a machine with accounts a safe folder is a shared area
every account's agent may use. That is exactly what makes `check_safe_folder` the
load-bearing part — it is the only thing between "let the agent read /data" and
"let one account read another's home by naming its parent". The tests below that
matter most are the refusals, not the permissions.

The second theme is honesty. A folder that is ignored because it was mistyped
looks identical to a folder the agent refuses to use, so a refused entry has to
be reportable rather than silently dropped.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentos import tools as toolsmod                      # noqa: E402
from agentos import users as usersmod                      # noqa: E402
from agentos.tools import (Toolbox, bwrap_argv, check_safe_folder,  # noqa: E402
                           folder_binds, folder_problems, folder_shares,
                           safe_folders)


def _cfg(tmp_path, folders):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return {"workspace": str(ws), "autonomy": "balanced", "policies": [],
            "default_model": "m",
            "sandbox": {"enabled": True, "root": str(ws),
                        "folders": [str(f) for f in folders]}}


# ------------------------------------------------------------ what they buy

@pytest.mark.asyncio
async def test_the_agent_can_read_and_write_a_named_folder(tmp_path):
    data = tmp_path / "company-data"
    data.mkdir()
    (data / "q3.csv").write_text("region,revenue\nEMEA,120000\n")
    tb = Toolbox(_cfg(tmp_path, [data]), None)
    assert "EMEA" in await tb.read_file(str(data / "q3.csv"))
    await tb.write_file(str(data / "out.md"), "# done")
    assert (data / "out.md").read_text() == "# done"


@pytest.mark.asyncio
async def test_a_folder_that_was_not_named_is_still_denied(tmp_path):
    """The point is to widen the jail deliberately, not to remove it."""
    data, other = tmp_path / "data", tmp_path / "private"
    data.mkdir(); other.mkdir()
    (other / "secret.txt").write_text("nope")
    tb = Toolbox(_cfg(tmp_path, [data]), None)
    out = await tb.read_file(str(other / "secret.txt"))
    assert "[denied]" in out and "nope" not in out


@pytest.mark.asyncio
async def test_the_refusal_names_the_folders_that_would_have_worked(tmp_path):
    """"Only paths inside <root>" stopped being true the moment there was more
    than one place to be, and a wrong reason is worse than a terse one."""
    data, other = tmp_path / "data", tmp_path / "elsewhere"
    data.mkdir(); other.mkdir()
    tb = Toolbox(_cfg(tmp_path, [data]), None)
    out = await tb.read_file(str(other / "x"))
    assert str(data) in out, out


# ------------------------------------------------------------ what they refuse

def test_the_whole_filesystem_is_refused(tmp_path):
    """Naming / would switch the jail off while the toggle still read 'on'."""
    p, why = check_safe_folder("/")
    assert not p and "whole machine" in why


def test_a_folder_that_does_not_exist_is_refused_with_a_reason(tmp_path):
    p, why = check_safe_folder(str(tmp_path / "nope"))
    assert not p and "no such folder" in why


def test_a_refused_entry_is_reportable_rather_than_silently_dropped(tmp_path):
    """Silently ignoring it means retyping a path that was never the problem."""
    cfg = _cfg(tmp_path, ["/", str(tmp_path / "ghost")])
    assert safe_folders(cfg) == []
    bad = dict(folder_problems(cfg))
    assert set(bad) == {"/", str(tmp_path / "ghost")}
    assert all(v for v in bad.values()), "a refusal with no reason is not a report"


def test_a_sibling_with_a_shared_prefix_is_not_inside(tmp_path):
    """/data-old starts with /data as a STRING and is a different directory."""
    data, old = tmp_path / "data", tmp_path / "data-old"
    data.mkdir(); old.mkdir()
    assert not toolsmod._under_any(str(old), [str(data)])
    assert toolsmod._under_any(str(data / "sub"), [str(data)])


# --------------------------------------------- the boundary that cannot move

def test_the_accounts_root_can_never_be_a_safe_folder(tmp_path, monkeypatch):
    """The one refusal that is a security boundary rather than a convenience.

    `users/` holds every account's home — its memory, credentials and files. If it
    could be named here, one line in a machine setting would undo directory
    isolation entirely.
    """
    users_root = tmp_path / "agentos" / "users"
    (users_root / "ada").mkdir(parents=True)
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "users_root", lambda: users_root)

    for probe in (users_root,                    # the root itself
                  users_root / "ada",            # somebody's home
                  users_root.parent,             # the directory above it
                  tmp_path):                     # further above it
        p, why = check_safe_folder(str(probe))
        assert not p, f"{probe} was accepted as a safe folder"
        assert "private" in why or "whole machine" in why, why


@pytest.mark.asyncio
async def test_another_accounts_home_stays_denied_even_with_safe_folders_set(
        tmp_path, monkeypatch):
    """The tenant check runs first and a safe folder must not talk it round."""
    users_root = tmp_path / "agentos" / "users"
    ada, bob = users_root / "ada", users_root / "bob"
    ada.mkdir(parents=True); bob.mkdir(parents=True)
    (bob / "agentos.db").write_text("BOBSECRET")
    shared = tmp_path / "shared"
    shared.mkdir()

    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "users_root", lambda: users_root)
    monkeypatch.setattr(usersmod, "current", lambda: "ada")
    monkeypatch.setattr(usersmod, "home_for", lambda uid: users_root / uid)

    # Even naming bob's home outright does not open it.
    cfg = _cfg(tmp_path, [shared, bob])
    tb = Toolbox(cfg, None)
    out = await tb.read_file(str(bob / "agentos.db"))
    assert "[denied]" in out and "BOBSECRET" not in out
    # …while the genuinely shared folder does work for that same account.
    (shared / "note.txt").write_text("team note")
    assert "team note" in await tb.read_file(str(shared / "note.txt"))


# ------------------------------------------------------------ the shell jail

def test_bwrap_binds_the_safe_folders_after_the_tmpfs_that_hides_homes(tmp_path):
    """Ordering IS the mechanism: a bind is only visible if nothing blanks it
    afterwards, so the extra binds must come after every --tmpfs."""
    argv = bwrap_argv("/home/ada", ["/bin/bash", "-lc", "ls"],
                      hide=["/home/.agentos/users"], extra=["/data"])
    assert "--bind" in argv and "/data" in argv, argv
    last_tmpfs = max(i for i, a in enumerate(argv) if a == "--tmpfs")
    data_bind = argv.index("/data")
    assert data_bind > last_tmpfs, (
        "a safe folder is bound before a tmpfs that would blank it again")


def test_the_macos_profile_allows_the_safe_folders_after_the_denies():
    """SBPL takes the LAST matching rule. Swap these and the profile still loads,
    still looks right, and silently grants what it was written to refuse."""
    prof = toolsmod._sandbox_exec_profile("/home/ada", hide=["/home/users"],
                                          extra=["/data"])
    denied = prof.index('(deny file-read* (subpath "/home/users")')
    allowed = prof.index('(allow file-read* (subpath "/data")')
    assert denied < allowed, (
        "the safe-folder read allowance is written before the tenant deny, so the "
        "deny wins and the folder is unreadable from the shell:\n" + prof)
    # …and it is writable, which is the other half of "may work here".
    assert '(subpath "/data")' in prof.split("(allow file-write*")[1][:400], prof


# ------------------------------------------- shares: who, and how much

def _shared(tmp_path, entries):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return {"workspace": str(ws), "autonomy": "balanced", "policies": [],
            "default_model": "m",
            "sandbox": {"enabled": True, "root": str(ws), "folders": entries}}


@pytest.mark.asyncio
async def test_a_read_only_share_can_be_read_and_not_written(tmp_path):
    """The whole point of the mode. A ro share the tools let you overwrite is not
    read-only, whatever the setting says."""
    ro = tmp_path / "reference"
    ro.mkdir()
    (ro / "g.txt").write_text("reference")
    tb = Toolbox(_shared(tmp_path, [{"path": str(ro), "mode": "ro", "users": []}]), None)
    assert "reference" in await tb.read_file(str(ro / "g.txt"))
    out = await tb.write_file(str(ro / "new.txt"), "x")
    assert "[denied]" in out
    assert not (ro / "new.txt").exists(), "a read-only share was written to"


@pytest.mark.asyncio
async def test_the_read_only_refusal_says_which_problem_it_is(tmp_path):
    """"You cannot go there" and "you cannot do THAT there" send somebody to two
    different settings, and one of them is already correct."""
    ro = tmp_path / "reference"
    ro.mkdir()
    tb = Toolbox(_shared(tmp_path, [{"path": str(ro), "mode": "ro", "users": []}]), None)
    out = await tb.write_file(str(ro / "new.txt"), "x")
    assert "read-only" in out, out


def test_a_share_names_the_accounts_it_is_for(tmp_path, monkeypatch):
    mine = tmp_path / "mine"
    mine.mkdir()
    cfg = _shared(tmp_path, [{"path": str(mine), "mode": "rw", "users": ["bob"]}])
    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "users_root", lambda: tmp_path / "nowhere")
    assert safe_folders(cfg, uid="bob") == [str(mine)]
    assert safe_folders(cfg, uid="ada") == [], "a share reached an account it does not name"


def test_an_empty_user_list_means_everyone(tmp_path):
    """Including on a single-user machine, where current() is '' and there is
    nobody to distinguish."""
    shared = tmp_path / "all"
    shared.mkdir()
    cfg = _shared(tmp_path, [{"path": str(shared), "mode": "rw", "users": []}])
    for who in ("", "ada", "bob"):
        assert safe_folders(cfg, uid=who) == [str(shared)]


def test_the_old_flat_list_still_means_everyone_read_write(tmp_path):
    """Configs written before shares existed must not be quietly narrowed."""
    d = tmp_path / "legacy"
    d.mkdir()
    cfg = _shared(tmp_path, [str(d)])
    assert safe_folders(cfg, write=True) == [str(d)]
    assert folder_shares(cfg)[0]["users"] == []


def test_an_unrecognised_mode_narrows_rather_than_widens(tmp_path):
    """A typo must not be the thing that grants write access."""
    d = tmp_path / "typo"
    d.mkdir()
    cfg = _shared(tmp_path, [{"path": str(d), "mode": "read-write", "users": []}])
    assert folder_shares(cfg)[0]["mode"] == "ro"
    assert safe_folders(cfg, write=True) == []


def test_a_second_entry_cannot_widen_an_earlier_one(tmp_path):
    """Two lines for one folder keep the first, so a later rw cannot silently
    upgrade an ro share somebody wrote deliberately."""
    d = tmp_path / "twice"
    d.mkdir()
    cfg = _shared(tmp_path, [{"path": str(d), "mode": "ro", "users": []},
                             {"path": str(d), "mode": "rw", "users": []}])
    assert [s["mode"] for s in folder_shares(cfg)] == ["ro"]


def test_the_jail_binds_read_only_shares_read_only(tmp_path):
    """The mode has to mean the same thing at the shell as in the file tools, or
    write_file says no and run_command says yes about the same folder."""
    ro, rw = tmp_path / "ro", tmp_path / "rw"
    ro.mkdir(); rw.mkdir()
    cfg = _shared(tmp_path, [{"path": str(ro), "mode": "ro", "users": []},
                             {"path": str(rw), "mode": "rw", "users": []}])
    ro_paths, rw_paths = folder_binds(cfg)
    argv = bwrap_argv("/home/x", ["/bin/bash"], extra=rw_paths, ro_extra=ro_paths)
    assert argv[argv.index(str(ro)) - 1] == "--ro-bind", argv
    assert argv[argv.index(str(rw)) - 1] == "--bind", argv


@pytest.mark.asyncio
async def test_the_agent_gets_the_acting_accounts_shares_via_the_contextvar(
        tmp_path, monkeypatch):
    """The guarantee as the agent actually experiences it.

    Every other test here passes `uid=` by hand, which is not how a turn resolves
    it: the agent's tools read `users.current()`, the same contextvar the store and
    the config come through. Asserting only the explicit form would leave the wiring
    untested — and a scheduled job that inherited the machine's shares instead of its
    owner's would be exactly that bug, hours later and in the wrong home.
    """
    users_root = tmp_path / "agentos" / "users"
    for u in ("ada", "bob"):
        (users_root / u).mkdir(parents=True)
    finance, legal = tmp_path / "finance", tmp_path / "legal"
    finance.mkdir(); legal.mkdir()
    (finance / "q3.csv").write_text("EMEA,120000")
    (legal / "nda.txt").write_text("CONFIDENTIAL")

    monkeypatch.setattr(usersmod, "enabled", lambda: True)
    monkeypatch.setattr(usersmod, "users_root", lambda: users_root)
    monkeypatch.setattr(usersmod, "home_for", lambda uid: users_root / uid)
    # cfg_for() caches the composed config per uid, and the key is the uid alone —
    # so a previous test's machine dict is still in there under "ada". Harmless in
    # a running OS (one machine config per process) and lethal to a test that
    # composes a different one.
    usersmod._cfgs.clear()
    monkeypatch.setattr(usersmod, "cfg_path_for", lambda uid: users_root / uid / "config.json")

    cfg = _shared(tmp_path, [
        {"path": str(finance), "mode": "rw", "users": ["ada"]},
        {"path": str(legal), "mode": "ro", "users": ["bob"]}])
    tb = Toolbox(cfg, None)

    with usersmod.as_user("ada"):
        assert "EMEA" in await tb.read_file(str(finance / "q3.csv"))
        assert "[denied]" in await tb.read_file(str(legal / "nda.txt"))
    with usersmod.as_user("bob"):
        assert "CONFIDENTIAL" in await tb.read_file(str(legal / "nda.txt"))
        assert "[denied]" in await tb.read_file(str(finance / "q3.csv"))
        # …and the shell jail is built from the same answer, so the Terminal and
        # the file tools cannot disagree about who this is.
        ro_paths, rw_paths = folder_binds(cfg)
        assert ro_paths == [str(legal)] and rw_paths == []


# ------------------------------------------------ cautions, and where they live

def test_a_system_directory_read_write_is_cautioned():
    """The case this exists for: /etc rw is a different act from /data rw, and a
    path typed into a box gives no hint of that."""
    assert "operating system" in toolsmod.folder_risk("/etc", "rw")


def test_read_only_takes_the_caution_off_a_system_directory():
    """The caution has to be actionable — it names read-only as the way out, so
    read-only must actually be the quieter answer or the advice is noise."""
    assert toolsmod.folder_risk("/etc", "ro") == ""


def test_an_ordinary_data_folder_is_not_cautioned(tmp_path):
    """A warning on everything is a warning on nothing."""
    d = tmp_path / "reports"
    d.mkdir()
    assert toolsmod.folder_risk(str(d), "rw") == ""


def test_a_home_directory_says_home_not_system(monkeypatch, tmp_path):
    """On many machines HOME *is* a system directory (/root), and "this is part of
    the operating system" is the wrong sentence for somebody sharing their own
    home — so the home check runs first."""
    monkeypatch.setenv("HOME", "/root")
    assert "whole home directory" in toolsmod.folder_risk("/root", "rw")


def test_credentials_are_cautioned_even_read_only():
    """Reading an ssh key is the whole attack; it does not need to be written."""
    for mode in ("ro", "rw"):
        assert "credentials" in toolsmod.folder_risk("~/.ssh", mode)


def test_a_caution_is_never_a_refusal(tmp_path):
    """It is the admin's machine. An OS that refuses a deliberate decision teaches
    people to stop reading its warnings — the two hard refusals are the two that
    break somebody ELSE'S isolation, and they live in check_safe_folder."""
    p, why = check_safe_folder("/etc")
    assert p == "/etc" and not why
    assert toolsmod.folder_risk("/etc", "rw")

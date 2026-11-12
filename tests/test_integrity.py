"""The watcher: a changed security file stops the agents until a person clears it (integrity.py).

Asked for as "there should be a watcher if the file has been changed by the AI". Real files in a
throwaway tree and home. The suite's own checkout is never watched: `serve()` arms the watcher,
and nothing here does that against this repository."""
import asyncio
import base64
import json
import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import config as cfgmod                 # noqa: E402
from agentos import integrity, memory, policy, protected, secevents, updates  # noqa: E402
from agentos.memory import Store                     # noqa: E402
from agentos.policy import MAIN, PDP, Principal      # noqa: E402

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def box(tmp_path, monkeypatch):
    """A code tree and a home, both throwaway."""
    tree = tmp_path / "tree"
    (tree / "agentos").mkdir(parents=True)
    (tree / "agentos" / "policy.py").write_text("GATE = 1\n")
    (tree / "agentos" / "notes.py").write_text("X = 1\n")
    (tree / "agentos" / "__pycache__").mkdir()
    (tree / "agentos" / "__pycache__" / "policy.pyc").write_text("cache")
    (tree / "install.sh").write_text("#!/bin/sh\n")
    (tree / "pyproject.toml").write_text("[project]\n")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cfgmod, "AGENTOS_HOME", home)
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", home / "config.json")
    integrity.forget_for_tests()
    secevents.forget_for_tests()
    # a throwaway HOME has no git identity, and an annotated tag needs one
    for k in ("GIT_COMMITTER_NAME", "GIT_AUTHOR_NAME"):
        monkeypatch.setenv(k, "t")
    for k in ("GIT_COMMITTER_EMAIL", "GIT_AUTHOR_EMAIL"):
        monkeypatch.setenv(k, "t@t")
    yield tree, home
    integrity.forget_for_tests()
    secevents.forget_for_tests()


def _key(tmp_path, name="seal.key"):
    path, key_id, pub = integrity.keygen(tmp_path / name)
    return path, key_id, pub


def _flags(kind):
    return [e for e in secevents.recent(100) if e.get("kind") == kind]


def _touch(p: Path, text: str):
    p.write_text(text)


# ---------------------------------------------------------------- a change stops the agents

def test_a_changed_module_holds_and_names_the_file(box):
    tree, home = box
    w = integrity.start_watching(tree)
    assert integrity.held() is None
    assert w.tick() == [] and integrity.held() is None, "nothing changed, nothing happens"
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    w.tick()
    held = integrity.held()
    assert held and "agentos/policy.py" in held["files"]
    assert _flags("integrity.changed"), "the record names it"
    assert "agentos/policy.py" in _flags("integrity.changed")[0]["detail"]
    assert (home / integrity.HELD).exists(), "a restart must not clear it"


def test_a_cache_file_is_not_code(box):
    tree, _ = box
    w = integrity.start_watching(tree)
    (tree / "agentos" / "__pycache__" / "policy.pyc").write_text("again")
    (tree / "agentos" / "__pycache__" / "new.pyc").write_text("new")
    w.tick()
    assert integrity.held() is None


def test_an_edit_that_keeps_size_and_mtime_is_still_seen(box):
    """`touch -r` puts the mtime back. ctime can't be set from userspace."""
    tree, _ = box
    w = integrity.start_watching(tree)
    p = tree / "agentos" / "policy.py"
    st = p.stat()
    p.write_text("GATE = 0\n")
    assert p.stat().st_size == st.st_size
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    w.tick()
    assert integrity.held()


def test_a_new_file_and_a_removed_one_hold(box):
    tree, _ = box
    w = integrity.start_watching(tree)
    (tree / "agentos" / "sneaky.py").write_text("import os\n")
    w.tick()
    assert "agentos/sneaky.py" in integrity.held()["files"]
    integrity.forget_for_tests()
    w = integrity.start_watching(tree)
    (tree / "agentos" / "notes.py").unlink()
    w.tick()
    assert "agentos/notes.py" in integrity.held()["files"]


def test_an_agents_step_is_refused_by_the_gate_while_held(box, tmp_path):
    tree, _ = box
    pdp = PDP({"autonomy": "full"}, Store(tmp_path / "gate.db"))
    who = Principal("subagent", "researcher")
    assert pdp.decide(who, "tool.use", "tool:read_file", {"risk": "safe", "surface": "gui"}).effect != "deny"
    integrity.hold("test", ["agentos/policy.py"])
    for p in (who, MAIN, Principal("app", "notes")):
        d = pdp.decide(p, "tool.use", "tool:read_file", {"risk": "safe", "surface": "gui"})
        assert d.effect == "deny" and d.rule == "integrity-hold"
        assert "bento integrity accept" in d.reason
    # no grant lifts it, because it is read before any grant
    pdp.store.add_grant(who.kind, who.id, "tool.use", "tool:*", "allow")
    assert pdp.decide(who, "tool.use", "tool:read_file", {"risk": "safe", "surface": "gui"}).rule == "integrity-hold"
    assert policy.stage_of("integrity-hold") == "held"


def test_a_turn_is_refused_before_any_model_call(box, tmp_path):
    from agentos.agent import Agent

    class Boom:
        pdp = None

        def schemas(self):
            raise AssertionError("no tool list is read while held")

    integrity.hold("test", ["agentos/policy.py"])
    said = []

    async def emit(ev):
        said.append(ev)
    ag = Agent.__new__(Agent)
    ag.emit = emit
    ag.toolbox = Boom()
    got = asyncio.run(Agent.run(ag, [{"role": "user", "content": "hi"}]))
    assert "bento integrity accept" in got["content"]
    assert said[0]["type"] == "error"


def test_a_forwarded_cli_is_refused_before_it_starts(box, tmp_path):
    from agentos import executors
    integrity.hold("test", ["agentos/policy.py"])
    said = []

    async def emit(ev):
        said.append(ev)
    env = executors.Envelope(workspace=str(tmp_path / "ws"), engine="claude-code")
    run = asyncio.run(executors.run_task("hi", env, emit))
    assert run.proc is None, "no CLI was started"
    assert any("bento integrity accept" in e.get("message", "") for e in said)
    said.clear()
    run = asyncio.run(executors.run_on_bridge("hi", "", "http://x", "t", emit, cwd=str(tmp_path / "ws")))
    assert run.proc is None and said


def test_a_cli_already_running_is_stopped():
    from agentos import executors

    class P:
        returncode = None
        stopped = False

        def terminate(self):
            self.stopped = True
    r = executors.Run()
    r.proc = P()
    executors._LIVE_RUNS[id(r)] = r
    assert executors.stop_all() >= 1 and r.proc.stopped
    executors._LIVE_RUNS.clear()
    srv = (ROOT / "agentos/server.py").read_text()
    assert "execmod.stop_all()" in srv[srv.index("def _integrity_held"):srv.index("LEDGER_CHECK_S")]


def test_no_tool_or_route_names_the_door():
    """Only the terminal clears it. The card explains and has nothing to press."""
    srv = (ROOT / "agentos/server.py").read_text()
    tools = (ROOT / "agentos/tools.py").read_text()
    for needle in ("integrity.seal(", "integrity.trust(", "integrity._release", "rebaseline("):
        assert needle not in srv and needle not in tools, needle
    page = (ROOT / "agentos/ui/src/js/11j-security.js").read_text()
    assert "innerHTML" not in page, "an alert's detail is an attacker's words"
    assert "fetch(" not in page and "method:" not in page, "the card only reads"


# ----------------------------------------------------------------- only a person clears it

def test_only_the_persons_accept_clears_it(box):
    tree, home = box
    w = integrity.start_watching(tree)
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    w.tick()
    assert integrity.held()
    # Removing the file does nothing: the server's memory holds it.
    (home / integrity.HELD).unlink()
    w.tick()
    assert integrity.held()
    # An old record, or one the update path wrote, doesn't clear it.
    integrity.rebaseline(tree, by="update")
    w.tick()
    assert integrity.held(), "an update does not clear somebody else's change"
    integrity.seal(tree, by="accept")
    w.tick()
    assert integrity.held() is None
    assert not (home / integrity.HELD).exists()


def test_a_restart_keeps_the_hold_and_a_restart_never_rebaselines(box):
    tree, home = box
    integrity.seal(tree)
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    # the agent's restart_agentos: a new process, no person, no update
    integrity.forget_for_tests()
    integrity.start_watching(tree)
    held = integrity.held()
    assert held and "agentos/policy.py" in held["files"]
    assert "stopped" in held["reason"], "caught at start, against the record"
    integrity.forget_for_tests()
    integrity.start_watching(tree)
    assert integrity.held(), "and still after a second restart"


def test_a_person_door_refuses_a_pipe_and_a_child_of_the_server(box, monkeypatch):
    env = {**os.environ, "AGENTOS_HOME": str(box[1]), "HOME": str(box[1]), "AGENTOS_PORT": "18998"}
    r = subprocess.run([sys.executable, "-m", "agentos", "integrity", "accept", "--root", str(box[0])],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, input="accept\n", timeout=60)
    # nothing to accept is a fine answer; hold first so the door is what answers
    integrity.seal(box[0])
    _touch(box[0] / "agentos" / "policy.py", "GATE = 0\n")
    integrity.hold("x", ["agentos/policy.py"])
    r = subprocess.run([sys.executable, "-m", "agentos", "integrity", "accept", "--root", str(box[0])],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, input="accept\n", timeout=60)
    assert r.returncode == 1 and "person at a terminal" in r.stdout
    assert (box[1] / integrity.HELD).exists()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(integrity, "_ancestors", lambda: [["/usr/bin/python3", "-m", "agentos", "serve", "--port", "18999"]])
    assert "started by Bento" in integrity.person_problem()
    monkeypatch.setattr(integrity, "_ancestors", lambda: [["/bin/bash"], ["sshd: me"]])
    assert integrity.person_problem() == ""
    monkeypatch.setattr(integrity, "_ancestors", lambda: [["bash", "-c", "python -m agentos serve & wait"]])
    assert integrity.person_problem() == "", "a shell that only mentions it is not the server"


def test_the_terminal_door_works_for_a_person_typing(box):
    """A real pty, the phrase typed, as somebody at SSH would."""
    tree, home = box
    integrity.seal(tree)
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    integrity.hold("x", ["agentos/policy.py"])
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(str(ROOT))
        os.environ.update(AGENTOS_HOME=str(home), HOME=str(home), AGENTOS_PORT="18998")
        os.execv(sys.executable, [sys.executable, "-m", "agentos", "integrity", "accept", "--root", str(tree)])
    out = b""
    deadline = time.time() + 60
    typed = False
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 1)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if not typed and b"Type accept" in out:
                os.write(fd, b"accept\n")
                typed = True
    os.waitpid(pid, 0)
    assert b"agentos/policy.py" in out, out.decode(errors="replace")
    assert b"Accepted" in out, out.decode(errors="replace")
    assert not (home / integrity.HELD).exists()
    assert integrity.record_for(tree)["by"] == "accept"


# ---------------------------------------------------------------- the record can't be forged

def test_a_forged_record_is_refused(box, tmp_path):
    tree, home = box
    keyp, key_id, pub = _key(tmp_path)
    integrity.trust(pub)
    integrity.seal(tree, key_path=keyp)
    assert integrity.judge(integrity.record_for(tree), integrity.hash_tree(tree))["state"] == "match"
    assert integrity.judge(integrity.record_for(tree), integrity.hash_tree(tree))["signed"] == "signed"

    # An attacker changes the code and rewrites the hashes: the signature no longer covers them.
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    d = json.loads((home / integrity.RECORD).read_text())
    e = d["trees"][str(tree.resolve())]
    e["files"]["agentos/policy.py"] = integrity.sha_file(tree / "agentos" / "policy.py")
    e["digest"] = integrity.digest_of(e["files"])
    (home / integrity.RECORD).write_text(json.dumps(d))
    assert integrity.judge(integrity.record_for(tree), integrity.hash_tree(tree))["state"] == "forged"
    integrity.forget_for_tests()
    integrity.start_watching(tree)
    assert integrity.held(), "a signature that fails is a hold, not 'unsigned'"
    integrity.forget_for_tests()

    # Signed by a key nobody trusts here.
    other, _, _ = _key(tmp_path, "other.key")
    e = dict(e)
    e.pop("sig", None)
    kid, sig = integrity.sign_bytes(other, integrity._canonical(e))
    e["sig"] = {"key_id": kid, "sig": sig}
    assert integrity.signature_state(e) == "bad"

    # With the signature simply removed, on a machine that asked for signing.
    e.pop("sig")
    verdict = integrity.judge(e, integrity.hash_tree(tree))
    assert verdict["state"] == "unsigned"

    # A record that can't be read isn't the same as none.
    (home / integrity.RECORD).write_text("{ nonsense")
    assert integrity.judge(integrity.record_for(tree), {})["state"] == "forged"


def test_a_machine_with_a_key_cant_accept_without_it(box, tmp_path):
    tree, _ = box
    _, _, pub = _key(tmp_path)
    integrity.trust(pub)
    with pytest.raises(ValueError, match="--key"):
        integrity.seal(tree, by="accept")
    other, _, _ = _key(tmp_path, "other.key")
    with pytest.raises(ValueError, match="trust"):
        integrity.seal(tree, key_path=other, by="accept")


def test_unsigned_says_so_and_never_verified(box):
    tree, _ = box
    integrity.seal(tree)
    st = integrity.status(tree)
    assert st["sealed"] == "unsigned" and st["signed"] == "none"
    assert "unsigned" in st["line"] and "verified" not in st["line"]


def test_removing_the_record_while_running_holds(box):
    tree, home = box
    integrity.seal(tree)
    w = integrity.start_watching(tree)
    (home / integrity.RECORD).unlink()
    w.tick()
    assert integrity.held()


def test_a_trust_list_that_appears_by_itself_holds(box):
    tree, home = box
    (home / "config.json").write_text("{}")
    w = integrity.start_watching(tree)
    (home / integrity.KEYS).write_text(json.dumps({"keys": {"bento-x": "AAAA"}}))
    w.tick()
    assert "~/integrity.keys" in integrity.held()["files"]


# ------------------------------------------------------------ a git checkout gets no free pass

def test_a_git_folder_exempts_nothing(box):
    """An agent making a `.git` directory must not switch anything off."""
    tree, _ = box
    (tree / ".git").mkdir()
    (tree / ".git" / "HEAD").write_text("ref: refs/heads/master\n")
    w = integrity.start_watching(tree)
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    w.tick()
    assert integrity.held()


def test_dev_mode_warns_and_is_a_persons_act(box):
    tree, _ = box
    integrity.seal(tree, dev=True)
    w = integrity.start_watching(tree)
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    w.tick()
    assert integrity.held() is None, "it warns on a checkout a person marked"
    assert _flags("integrity.dev")
    assert "agentos/policy.py" in w.dev_changes
    assert "development checkout" in integrity.status(tree)["line"]
    # and a signing key means dev mode needs the key as well
    with pytest.raises(ValueError):
        keyp = integrity.keygen(Path(str(tree)) / "k.key")
        integrity.trust(keyp[2])
        integrity.seal(tree, dev=False)


# ------------------------------------------------------------------- the OS's own path

def _git_tree(tmp_path, name="repo"):
    src = tmp_path / name
    (src / "agentos").mkdir(parents=True)
    (src / "agentos" / "VERSION").write_text("1.0.0\n")
    (src / "agentos" / "policy.py").write_text("GATE = 1\n")
    (src / "install.sh").write_text("#!/bin/sh\n")
    (src / "pyproject.toml").write_text("[project]\n")
    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=src, check=True,
                       capture_output=True)
    g("init", "-q", "-b", "master")
    g("add", ".")
    g("commit", "-qm", "one")
    return src, g


def test_an_update_rebaselines_and_a_dirty_file_stays_a_change(box, tmp_path):
    _, home = box
    src, g = _git_tree(tmp_path)
    integrity.seal(src)
    w = integrity.start_watching(src)
    with integrity.updating():
        (src / "agentos" / "policy.py").write_text("GATE = 2\n")
        g("add", ".")
        g("commit", "-qm", "two")
        w.tick()
        assert integrity.held() is None, "the watcher waits while an update moves the code"
        integrity.rebaseline(src, by="update", update={"state": "unsigned", "commit": "x"})
    w.tick()
    assert integrity.held() is None, "the update path recorded this exact code"

    # Something else changed a file during an update: git calls it dirty, so it isn't adopted.
    with integrity.updating():
        (src / "agentos" / "policy.py").write_text("GATE = 3\n")
        integrity.rebaseline(src, by="update", update={"state": "unsigned", "commit": "y"})
    w.tick()
    assert integrity.held() and "agentos/policy.py" in integrity.held()["files"]


def test_a_marker_left_behind_or_faked_buys_nothing(box):
    tree, home = box
    w = integrity.start_watching(tree)
    (home / integrity.UPDATING).write_text(json.dumps({"pid": 2 ** 22 + 7, "at": time.time()}))
    _touch(tree / "agentos" / "policy.py", "GATE = 0\n")
    w.tick()
    assert integrity.held(), "no such process, so no update is running"
    integrity.forget_for_tests()
    w = integrity.start_watching(tree)
    (home / integrity.UPDATING).write_text(json.dumps({"pid": os.getpid(), "at": time.time() - 4000}))
    _touch(tree / "agentos" / "policy.py", "GATE = 9\n")
    w.tick()
    assert integrity.held(), "too old to be an update"


def test_the_os_noting_its_own_write_is_not_a_change(box, monkeypatch):
    tree, home = box
    cfgmod.save_config({"autonomy": "balanced", "sandbox": {"enabled": True}})
    w = integrity.start_watching(tree)
    cfgmod.save_config({"autonomy": "balanced", "sandbox": {"enabled": False}})
    w.tick()
    assert integrity.held() is None, "the settings screen saved it"
    # a window position written by anything is not a security fact
    d = json.loads((home / "config.json").read_text())
    d["theme"] = "other"
    (home / "config.json").write_text(json.dumps(d))
    w.tick()
    assert integrity.held() is None
    # the sandbox switched off by a hand that didn't go through the OS
    d["sandbox"] = {"enabled": False, "root": "/"}
    (home / "config.json").write_text(json.dumps(d))
    w.tick()
    assert "~/config.json" in integrity.held()["files"]


def test_a_replaced_key_file_holds_and_a_new_one_does_not(box):
    tree, home = box
    (home / "session.key").write_text("a" * 64)
    w = integrity.start_watching(tree)
    (home / "vault.key").write_text("first")
    w.tick()
    assert integrity.held() is None, "made for the first time"
    (home / "session.key").write_text("b" * 64)
    w.tick()
    assert "~/session.key" in integrity.held()["files"]


def test_a_deleted_account_is_not_an_attack(box):
    tree, home = box
    acct = home / "users" / "u1"
    acct.mkdir(parents=True)
    (acct / "config.json").write_text("{}")
    w = integrity.start_watching(tree)
    import shutil
    shutil.rmtree(acct)
    w.tick()
    assert integrity.held() is None


def test_a_standby_takes_the_home_it_is_sent(box):
    tree, home = box
    (home / "config.json").write_text(json.dumps({"autonomy": "balanced"}))
    w = integrity.start_watching(tree, passive=lambda: True)
    (home / "config.json").write_text(json.dumps({"autonomy": "full"}))
    w.tick()
    assert integrity.held() is None


def test_the_watcher_is_off_unless_serve_arms_it():
    srv = (ROOT / "agentos/server.py").read_text()
    assert "if integrity.armed():" in srv
    main = (ROOT / "agentos/__main__.py").read_text()
    serve = main[main.index("def serve("):main.index("def ask(prompt")]
    assert "_integrity.arm()" in serve


# ---------------------------------------------------------------- signed updates (S-74)

def test_updates_ship_with_no_key():
    assert updates.SIGNING_KEYS == {}, "only the owner mints one, and only they pin it"


def test_release_state_reads_a_signed_tag(box, tmp_path):
    src, g = _git_tree(tmp_path)
    keyp, key_id, pub = _key(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    assert integrity.release_state(src, head, {})["state"] == "unsigned"
    got = integrity.sign_release(keyp, src, "v1")
    assert got["ok"] and got["key_id"] == key_id
    st = integrity.release_state(src, head, {key_id: pub})
    assert st["state"] == "verified" and st["tag"] == "bento-v1"
    assert st["digest"] == integrity.digest_of(integrity.hash_tree(src))
    assert integrity.release_state(src, head, {"bento-other": pub})["state"] == "unsigned", "someone else's key"
    # a tag that points elsewhere can't vouch for this commit
    (src / "install.sh").write_text("#!/bin/sh\nevil\n")
    g("add", ".")
    g("commit", "-qm", "two")
    head2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    assert integrity.release_state(src, head2, {key_id: pub})["state"] == "unsigned"


def test_a_tampered_signature_reads_as_bad(box, tmp_path):
    src, g = _git_tree(tmp_path)
    keyp, key_id, pub = _key(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=src, capture_output=True, text=True).stdout.strip()
    fake = base64.b64encode(b"\0" * 64).decode()
    g("tag", "-a", "bento-v1", "-m", f"x\n\nbento-signature: {key_id} {fake} {'0' * 64}\n")
    assert integrity.release_state(src, head, {key_id: pub})["state"] == "bad-signature"


@pytest.fixture()
def clone(box, tmp_path, monkeypatch):
    """A machine whose checkout tracks `origin`, with updates.apply pointed at it."""
    origin, g = _git_tree(tmp_path, "origin")
    subprocess.run(["git", "config", "receive.denyCurrentBranch", "ignore"], cwd=origin, check=True)
    mine = tmp_path / "mine"
    subprocess.run(["git", "clone", "-q", str(origin), str(mine)], check=True)
    monkeypatch.setattr(updates, "install_dir", lambda: mine)
    monkeypatch.setattr(updates, "ensure_remote", lambda cfg, root=None: (True, ""))
    monkeypatch.setattr(updates, "remote_name", lambda cfg: "origin")
    monkeypatch.setattr(updates, "repo_of", lambda cfg: "test/repo")
    monkeypatch.setattr(updates, "_python", lambda root: sys.executable)
    real = updates._run

    def run(args, cwd=None, timeout=60, env=None):
        if len(args) > 2 and args[1:3] == ["-m", "agentos"]:
            return True, "no migrate in a toy tree"
        return real(args, cwd, timeout, env)
    monkeypatch.setattr(updates, "_run", run)
    return origin, g, mine


def _push_commit(origin, g, text="GATE = 2\n"):
    (origin / "agentos" / "policy.py").write_text(text)
    g("add", ".")
    g("commit", "-qm", "next")


CFG = {"updates": {"branch": "master"}}


def test_an_unsigned_update_works_for_a_person_and_says_unsigned(clone):
    origin, g, mine = clone
    integrity.seal(mine)
    w = integrity.start_watching(mine)
    _push_commit(origin, g)
    said = []
    res = asyncio.run(updates.apply(CFG, run_tests=False, log=said.append))
    assert res["ok"] and res["release"] == "unsigned"
    assert any("not signed" in m for m in said)
    assert integrity.record_for(mine)["by"] == "update"
    w.tick()
    assert integrity.held() is None, "the update path re-baselined, so it doesn't trip the watcher"


def test_automatic_needs_a_signed_one_and_a_person_may_override_only_with_a_word(clone, monkeypatch):
    origin, g, mine = clone
    keyp, key_id, pub = _key(origin.parent)
    _push_commit(origin, g)
    res = asyncio.run(updates.apply(CFG, run_tests=False, need_verified=True))
    assert not res["ok"] and res["needs_person"], "a Zero's auto mode asks instead"

    monkeypatch.setattr(updates, "SIGNING_KEYS", {key_id: pub})
    res = asyncio.run(updates.apply(CFG, run_tests=False))
    assert not res["ok"] and "not signed" in res["error"], "with a key pinned, unsigned needs a word"
    res = asyncio.run(updates.apply(CFG, run_tests=False, allow_unsigned=True))
    assert res["ok"] and res["release"] == "unsigned"


def test_a_signed_update_is_verified_recorded_and_believed(clone, monkeypatch):
    origin, g, mine = clone
    keyp, key_id, pub = _key(origin.parent)
    monkeypatch.setattr(updates, "SIGNING_KEYS", {key_id: pub})
    _push_commit(origin, g)
    assert integrity.sign_release(keyp, origin, "v2")["ok"]
    res = asyncio.run(updates.apply(CFG, run_tests=False, need_verified=True))
    assert res["ok"] and res["release"] == "verified"
    e = integrity.record_for(mine)
    assert e["update"]["state"] == "verified" and e["update"]["key_id"] == key_id
    v = integrity.judge(e, integrity.hash_tree(mine))
    assert v["state"] == "match" and v["signed"] == "release"
    assert integrity.status(mine)["sealed"] == "signed"


def test_a_bad_signature_is_refused_whoever_asks(clone, monkeypatch):
    origin, g, mine = clone
    keyp, key_id, pub = _key(origin.parent)
    monkeypatch.setattr(updates, "SIGNING_KEYS", {key_id: pub})
    _push_commit(origin, g)
    fake = base64.b64encode(b"\0" * 64).decode()
    g("tag", "-a", "bento-v9", "-m", f"x\n\nbento-signature: {key_id} {fake} {'0' * 64}\n")
    res = asyncio.run(updates.apply(CFG, run_tests=False, allow_unsigned=True))
    assert not res["ok"] and "does not check" in res["error"]
    assert (mine / "agentos" / "policy.py").read_text() == "GATE = 1\n", "nothing moved"


def test_code_that_doesnt_match_its_signature_rolls_back(clone, monkeypatch):
    """The tag signs a digest. If the commit it names holds other code, it doesn't count."""
    origin, g, mine = clone
    keyp, key_id, pub = _key(origin.parent)
    monkeypatch.setattr(updates, "SIGNING_KEYS", {key_id: pub})
    _push_commit(origin, g)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=origin, capture_output=True, text=True).stdout.strip()
    wrong = "f" * 64
    kid, sig = integrity.sign_bytes(keyp, integrity.release_message(head, wrong))
    g("tag", "-a", "bento-v3", "-m", f"x\n\nbento-signature: {kid} {sig} {wrong}\n")
    res = asyncio.run(updates.apply(CFG, run_tests=False))
    assert not res["ok"] and res.get("rolled_back")
    assert (mine / "agentos" / "policy.py").read_text() == "GATE = 1\n"


def test_the_terminal_has_the_word_for_unsigned():
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"--allow-unsigned"' in main and 'extra["allow_unsigned"] = True' in main
    srv = (ROOT / "agentos/server.py").read_text()
    assert 'allow_unsigned=bool(body.get("allow_unsigned"))' in srv


def test_a_zero_on_auto_answers_needs_person_before_starting():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def _zero_update_from_hub"):srv.index("async def _team_on_ask")]
    assert h.index("tip_release") < h.index('_ZERO_UPDATING["on"] = True')
    assert "needs_person" in h and "need_verified=auto" in h
    k = srv[srv.index("async def _zeros_keep_current"):srv.index("async def _zero_update_from_hub")]
    assert "auto=True" in k and "needs_person" in k


def test_a_rollback_rebaselines_too():
    src = (ROOT / "agentos/updates.py").read_text()
    body = src[src.index("def _rollback("):src.index("def _failed_nodes")]
    assert 'integrity.rebaseline(root, by="rollback"' in body


# --------------------------------------------------------------------------- the root lock

def test_lock_is_what_was_shown_and_the_ladder_is_sessions(box):
    tree, _ = box
    script = integrity.lock_script(tree)
    assert "chown -R root:root" in script and str(tree) in script
    ran = []

    def runner(argv, why):
        ran.append((argv, why))
        return False, "no sudo here"
    ok, out = integrity.run_as_root(script, "why", runner=runner)
    assert not ok and ran[0][0] == ["sh", "-c", script]
    assert script.split()[0] in integrity.hand_back(script)
    assert not integrity.is_locked(tree), "this user can write it, so it isn't locked"
    u = integrity.unlock_script(tree)
    assert f"chown -R {os.getuid()}:{os.getgid()}" in u


def test_a_locked_tree_says_so_to_the_updater(box, monkeypatch, tmp_path):
    src, _ = _git_tree(tmp_path)
    monkeypatch.setattr(updates, "install_dir", lambda: src)
    monkeypatch.setattr(integrity, "is_locked", lambda root=None: True)
    ok, why = updates.can_apply({})
    assert not ok and "bento integrity unlock" in why
    assert "bento integrity unlock" in asyncio.run(updates.rollback({}))["error"]


# ------------------------------------------------------------------------- the ledger (S-47)

def _rows(store, n=6):
    for i in range(n):
        store.audit_add(principal_kind="user", action="a", resource=f"r{i}", effect="allow", rule="d")


@pytest.fixture()
def led(tmp_path):
    s = Store(tmp_path / "agentos.db")
    _rows(s)
    return s


def test_rewriting_and_recomputing_the_old_way_is_detected(led):
    """The audit's proof: flip an effect and recompute every hash with the public formula."""
    assert led.audit_verify()["ok"]
    db = led.db
    rows = db.execute("SELECT * FROM audit WHERE seq>0 ORDER BY seq").fetchall()
    prev = ""
    for n, r in enumerate(rows, 1):
        eff = "deny" if n == 2 else r["effect"]
        h = Store._audit_hash(prev, (n, round(r["ts"], 6), r["uid"] or "", r["principal_kind"] or "",
                                     r["principal_id"] or "", r["surface"] or "", r["space_id"] or "",
                                     r["conversation_id"] or "", r["run_id"] or "", r["action"] or "",
                                     r["resource"] or "", eff, r["rule"] or "", r["risk"] or "", r["reason"] or ""))
        db.execute("UPDATE audit SET seq=?,prev_hash=?,row_hash=?,effect=? WHERE id=?", (n, prev, h, eff, r["id"]))
        prev = h
    db.commit()
    v = led.audit_verify()
    assert not v["ok"] and v["at_seq"] == 1


def test_deleting_the_newest_row_is_detected(led):
    led.db.execute("DELETE FROM audit WHERE seq=(SELECT MAX(seq) FROM audit)")
    led.db.commit()
    v = led.audit_verify()
    assert not v["ok"] and "newest" in v["reason"]


def test_deleting_the_oldest_row_is_detected(led):
    led.db.execute("DELETE FROM audit WHERE seq=(SELECT MIN(seq) FROM audit)")
    led.db.commit()
    assert not led.audit_verify()["ok"]


def test_editing_outcome_or_detail_is_detected(led):
    aid = led.db.execute("SELECT id FROM audit WHERE seq=3").fetchone()["id"]
    led.audit_finish(aid, "ok", "ran fine", 12)
    assert led.audit_verify()["ok"], "the OS stamping an outcome is not tampering"
    for col, val in (("outcome", "error"), ("detail", "something else"), ("duration_ms", 9999)):
        was = led.db.execute(f"SELECT {col} FROM audit WHERE id=?", (aid,)).fetchone()[0]
        led.db.execute(f"UPDATE audit SET {col}=? WHERE id=?", (val, aid))
        led.db.commit()
        v = led.audit_verify()
        assert not v["ok"] and "happened" in v["reason"], col
        led.db.execute(f"UPDATE audit SET {col}=? WHERE id=?", (was, aid))
        led.db.commit()
    assert led.audit_verify()["ok"]
    led.db.execute("UPDATE audit SET out_mac='' WHERE id=?", (aid,))
    led.db.commit()
    assert not led.audit_verify()["ok"], "blanking the mark doesn't leave the check"


def test_a_row_inserted_or_reordered_is_detected(led):
    led.db.execute("UPDATE audit SET seq=99 WHERE seq=3")
    led.db.commit()
    assert not led.audit_verify()["ok"]


def test_an_anchor_naming_a_different_row_is_a_rewrite(led, tmp_path):
    """An anchor naming a row whose hash has changed is a rewrite."""
    memory.write_anchor(led.path, 3, "0" * 64)
    v = led.audit_verify()
    assert not v["ok"] and "anchor" in v["reason"]


def test_a_power_cut_is_a_note_and_a_deletion_in_the_same_boot_is_not(led):
    head = led.audit_verify()["head_seq"]
    led.db.execute("DELETE FROM audit WHERE seq=?", (head,))
    led.db.commit()
    assert not led.audit_verify()["ok"], "same boot: somebody deleted it"
    a = memory.read_anchor(led.path)
    a["boot"] = "an-earlier-boot"
    memory._ledger_files(led.path)[1].write_text(json.dumps(a))
    v = led.audit_verify()
    assert v["ok"] and "stopped without warning" in v["note"]
    a["seq"] = head + memory.ANCHOR_SLACK + 5
    memory._ledger_files(led.path)[1].write_text(json.dumps(a))
    assert not led.audit_verify()["ok"], "more than a power cut can lose"


def test_a_key_that_went_missing_is_a_break(led):
    memory._ledger_files(led.path)[0].unlink()
    v = Store(led.path).audit_verify()
    assert not v["ok"] and "key" in v["reason"]


def test_old_rows_keep_verifying_by_the_old_scheme_up_to_the_boundary(tmp_path):
    """A ledger written before this code: an unkeyed chain, no key file."""
    s = Store(tmp_path / "agentos.db")
    db = s.db
    prev = ""
    for n in range(1, 5):
        now = 1000.0 + n
        fields = (n, round(now, 6), "", "user", "", "", "", "", "", "a", f"r{n}", "allow", "d", "", "")
        h = Store._audit_hash(prev, fields)
        db.execute("INSERT INTO audit (id, ts, uid, principal_kind, principal_id, surface, space_id, "
                   "conversation_id, run_id, action, resource, effect, rule, risk, reason, outcome, detail, "
                   "duration_ms, seq, prev_hash, row_hash, created_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"o{n}", now, "", "user", "", "", "", "", "", "a", f"r{n}", "allow", "d", "", "", "old", "old",
                    0, n, prev, h, now))
        prev = h
    db.commit()
    s = Store(tmp_path / "agentos.db")
    assert s.audit_verify()["ok"], "nothing keyed yet"
    assert s.audit_add(principal_kind="user", action="a", resource="new", effect="allow", rule="d")
    v = s.audit_verify()
    assert v["ok"] and v["boundary"] == 4 and v["head_seq"] == 5
    led = memory.load_ledger_key(s.path)
    assert led["boundary_seq"] == 4 and led["boundary_hash"] == prev and led["legacy_break"] is None

    # the old rows can't be rewritten and recomputed either: the boundary's hash is out of the database
    rows = db.execute("SELECT * FROM audit WHERE seq>0 AND seq<=4 ORDER BY seq").fetchall()
    p = ""
    for r in rows:
        eff = "deny" if r["seq"] == 2 else r["effect"]
        fields = list(memory._old_fields(r))
        fields[11] = eff
        h = Store._audit_hash(p, tuple(fields))
        db.execute("UPDATE audit SET prev_hash=?, row_hash=?, effect=? WHERE id=?", (p, h, eff, r["id"]))
        p = h
    db.commit()
    v = s.audit_verify()
    assert not v["ok"] and v["at_seq"] == 4


def test_an_old_break_is_said_once_and_isnt_a_new_alarm(tmp_path):
    """A `bento` verb and the server used to fork the old chain by accident."""
    s = Store(tmp_path / "agentos.db")
    db = s.db
    for n in (1, 2, 2, 3):
        db.execute("INSERT INTO audit (id, ts, seq, prev_hash, row_hash) VALUES (?,?,?,?,?)",
                   (uuid_(), 1.0, n, "", "x"))
    db.commit()
    assert s.audit_add(principal_kind="user", action="a", resource="new", effect="allow", rule="d")
    v = s.audit_verify()
    assert v["ok"] and "already" in v["note"]
    db.execute("UPDATE audit SET row_hash='y' WHERE seq=3")
    db.commit()
    assert not s.audit_verify()["ok"], "the boundary's hash still pins them"


def uuid_():
    import uuid
    return uuid.uuid4().hex[:12]


def test_two_writers_on_one_ledger_dont_fork_it(tmp_path):
    """The server and a `bento` verb: found building this. The old chain forked on ordinary use."""
    a, b = Store(tmp_path / "agentos.db"), Store(tmp_path / "agentos.db")
    for i in range(10):
        (a if i % 2 else b).audit_add(principal_kind="user", action="x", resource=str(i), effect="allow", rule="d")
    v = a.audit_verify()
    assert v["ok"] and v["head_seq"] == 10


def test_threads_on_one_store_dont_fork_it(tmp_path):
    import threading
    s = Store(tmp_path / "agentos.db")
    ts = [threading.Thread(target=lambda: [s.audit_add(principal_kind="user", action="x", resource="r",
                                                       effect="allow", rule="d") for _ in range(20)])
          for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    v = s.audit_verify()
    assert v["ok"] and v["head_seq"] == 80


def test_the_timer_walks_only_new_rows_and_flags_a_break(box):
    tree, home = box
    s = Store(home / "agentos.db")
    _rows(s, 3)
    assert integrity.verify_ledgers(full=True)[0]["ok"]
    _rows(s, 2)
    v = integrity.verify_ledgers()[0]
    assert v["ok"] and v["checked"] == 2 and v["head_seq"] == 5
    s.db.execute("UPDATE audit SET effect='deny' WHERE seq=2")
    s.db.commit()
    assert integrity.verify_ledgers()[0]["ok"], "an incremental look only reads new rows"
    assert not integrity.verify_ledgers(full=True)[0]["ok"], "the daily walk reads them all"
    assert _flags("ledger.broken")


def test_a_head_that_moved_backwards_is_a_break_on_the_timer(box):
    _, home = box
    s = Store(home / "agentos.db")
    _rows(s, 5)
    assert integrity.verify_ledgers(full=True)[0]["ok"]
    s.db.execute("DELETE FROM audit WHERE seq>=4")
    s.db.commit()
    # the same (seq, hash) still names row 5, so the incremental look says so in one read
    v = integrity.verify_ledgers()[0]
    assert not v["ok"] and _flags("ledger.broken")


def test_one_break_is_one_alert_however_often_the_timer_looks(box, monkeypatch):
    """Reported as the same Telegram alert every 20 minutes all night: the check runs on a timer,
    the break stays broken, and the alert's cooldown (15 min) was shorter than the timer. One break
    alerts once; a different break alerts again, and so does one after the ledger verified clean."""
    _, home = box
    s = Store(home / "agentos.db")
    _rows(s, 4)
    assert integrity.verify_ledgers(full=True)[0]["ok"]
    s.db.execute("UPDATE audit SET effect='deny' WHERE seq=2")
    s.db.commit()
    for k in range(5):
        monkeypatch.setattr(secevents.time, "time", lambda k=k: 1e9 + k * 1200)   # 20 minutes apart
        v = integrity.verify_ledgers(full=bool(k % 2))[0]
        assert not v["ok"] or k == 0
    alerts = [e for e in _flags("ledger.broken") if e.get("alert")]
    assert len(alerts) == 1, "the same break, told once"
    s.db.execute("UPDATE audit SET effect='deny' WHERE seq=1")
    s.db.commit()
    monkeypatch.setattr(secevents.time, "time", lambda: 1e9 + 99999)
    integrity.verify_ledgers(full=True)
    assert len([e for e in _flags("ledger.broken") if e.get("alert")]) == 2, "a new break is new news"


def test_a_factory_reset_starts_a_new_chain(led):
    led.factory_reset()
    assert led.audit_verify()["ok"]
    assert led.audit_add(principal_kind="user", action="a", resource="r", effect="allow", rule="d")
    assert led.audit_verify()["ok"]


def test_the_key_and_anchor_are_no_agents(box):
    _, home = box
    for name in ("ledger.key", "ledger.anchor", "integrity.json", "integrity.keys", "integrity.held",
                 "integrity.writes", "integrity.updating"):
        assert protected.secret(home / name), name
        assert protected.write_refused(home / name), name
    assert protected.secret(home / "users" / "u1" / "ledger.key")


def test_a_backup_carries_the_key_and_leaves_the_anchor(box):
    from agentos import backup
    _, home = box
    s = Store(home / "agentos.db")
    _rows(s, 2)
    names = {rel for rel, _ in backup._walk(home)}
    assert "ledger.key" in names and "ledger.anchor" not in names
    (home / integrity.RECORD).write_text("{}")
    names = {rel for rel, _ in backup._walk(home)}
    assert integrity.RECORD not in names, "which code is sealed is a fact about this computer"


# ------------------------------------------------------------------- surfaces and awareness

def test_one_quiet_line_when_nothing_is_wrong(box):
    tree, _ = box
    integrity.start_watching(tree)
    line = integrity.status(tree)["line"]
    assert line.startswith("Watching 4 files") and "not sealed" in line
    assert "\n" not in line


def test_the_status_route_is_admin_only_and_read_only():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def api_security_status"):srv.index('@app.get("/api/security/events")')]
    assert "_require_admin()" in h
    assert not [ln for ln in srv.splitlines() if "/api/security" in ln and ".post(" in ln], "no route clears it"


def test_the_phones_hear_one_line_with_only_the_os_words():
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("def _security_alert"):srv.index("def _integrity_held")]
    assert "_security_phone" in h and "alert['words']" in h
    assert "alert['detail']" not in h and "alert['source']" not in h


def test_a_forwarded_lead_hears_the_note(box):
    from agentos import executors
    secevents.flag("integrity.changed", "agentos/policy.py")
    ctx = executors.context_for("")
    assert "Security notice from this OS" in ctx and "agentos/policy.py" not in ctx


def test_the_watcher_is_cheap_measured(box):
    tree, _ = box
    w = integrity.start_watching(tree)
    t = time.perf_counter()
    for _ in range(50):
        w.tick()
    assert (time.perf_counter() - t) / 50 < 0.05

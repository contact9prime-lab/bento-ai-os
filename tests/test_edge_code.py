"""Small code on the edge, big code on its hub (agentos/edgecode.py).

Asked for as "the pi should be able to run small codes and big codes should be handed off to
hub if required, only in the context and that folder, and should not impact our application".
The jail tests run the real bubblewrap and skip where it cannot start (a CI runner whose user
namespaces are off)."""
import asyncio
import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agentos import edgecode, provision, tools                       # noqa: E402
from agentos.memory import Store                                     # noqa: E402
from agentos.policy import PDP                                       # noqa: E402

ROOT = Path(__file__).parent.parent


def _bwrap_works() -> bool:
    if not (shutil.which("bwrap") and shutil.which("prlimit") and os.path.exists("/usr/bin/python3")):
        return False
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        Path(d, edgecode.SCRIPT).write_text("pass\n")
        return subprocess.run(edgecode.jail_argv(d, "/usr/bin/python3"), capture_output=True).returncode == 0


JAIL = pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap cannot start here")


def _toolbox(tmp_path, monkeypatch):
    cfg = {"workspace": str(tmp_path / "ws"), "sandbox": {"enabled": False}}
    (tmp_path / "ws").mkdir()
    tb = tools.Toolbox.__new__(tools.Toolbox)
    tb.cfg = cfg

    async def run_command(command, cwd=""):
        p = await asyncio.create_subprocess_shell(command, stdout=asyncio.subprocess.PIPE,
                                                  stderr=asyncio.subprocess.STDOUT, cwd=cfg["workspace"])
        out, _ = await p.communicate()
        text = out.decode()
        return text if p.returncode == 0 else f"[exit code {p.returncode}]\n{text}"
    tb.run_command = run_command
    return tb, cfg


def test_a_machine_with_no_hub_runs_python_as_it_always_did(tmp_path, monkeypatch):
    tb, cfg = _toolbox(tmp_path, monkeypatch)
    monkeypatch.setattr(edgecode, "hub_for", lambda cfg: None)
    assert asyncio.run(tb.run_python("print(6*7)")).strip() == "42"
    assert "no hub" in asyncio.run(tb.run_python("print(1)", where="hub"))


def test_small_code_stays_on_the_edge_and_big_code_goes_to_the_hub(tmp_path, monkeypatch):
    tb, cfg = _toolbox(tmp_path, monkeypatch)
    monkeypatch.setattr(edgecode, "hub_for", lambda cfg: {"label": "big-box"})
    monkeypatch.setattr(edgecode, "EDGE_SECONDS", 2)
    monkeypatch.setattr(edgecode, "EDGE_MEMORY_MB", 256)
    sent = []

    async def offload(cfg, code, base, folder, why):
        sent.append(why)
        return f"[ran on the hub big-box because {why}]"
    monkeypatch.setattr(edgecode, "offload", offload)
    assert asyncio.run(tb.run_python("print(6*7)")).strip() == "42" and not sent
    out = asyncio.run(tb.run_python("import time; time.sleep(30)"))
    assert "ran on the hub" in out and "ran past 2 s here" == sent[-1][3:]
    out = asyncio.run(tb.run_python("x = bytearray(600 * 1024 * 1024); print(len(x))"))
    assert "ran on the hub" in out and "MB here" in sent[-1]
    n = len(sent)
    out = asyncio.run(tb.run_python("import time; time.sleep(30)", where="here"))
    assert len(sent) == n and out.startswith("[exit code"), "'here' never hands it over"
    asyncio.run(tb.run_python("print(1)", where="hub"))
    assert sent[-1] == "you asked for it"


def test_only_the_named_folder_travels_and_nothing_leaves_it(tmp_path):
    ws = tmp_path / "ws"
    (ws / "job" / "data").mkdir(parents=True)
    (ws / "job" / "data" / "in.csv").write_text("a,b\n1,2\n")
    (ws / "job" / ".secret").write_text("no")
    (ws / "other.txt").write_text("not this")
    os.symlink("/etc/passwd", ws / "job" / "link")
    files, left, err = edgecode.pack_folder(ws, "job")
    assert not err and [f["path"] for f in files] == ["data/in.csv"]
    for bad in ("../x", "/etc", ".hidden", "job/../.."):
        assert edgecode.pack_folder(ws, bad)[2], bad
    back = [{"path": p, "data": base64.b64encode(b"x").decode()}
            for p in ("out/r.txt", "../escape.txt", "/abs.txt", ".bashrc", "a/.ssh/k")]
    written, refused = edgecode.unpack_into(ws / "job", back)
    assert written == ["out/r.txt"] and len(refused) == 4
    assert not (tmp_path / "escape.txt").exists() and (ws / "job" / "out" / "r.txt").read_text() == "x"


def _hub(tmp_path, monkeypatch, granted=True):
    monkeypatch.setattr(edgecode, "runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(provision, "was_enabled_here", lambda fp: fp == "f" * 64)
    store = Store(tmp_path / "hub.db")
    if granted:
        assert edgecode.grant(store, "kitchen-pi") and not edgecode.grant(store, "kitchen-pi")
    pdp = PDP({"autonomy": "balanced"}, store)
    lk = {"kind": "machine", "label": "kitchen-pi", "peer_host_fp": "f" * 64}
    return store, pdp, lk


@JAIL
def test_the_hub_runs_it_in_a_jail_with_only_that_folder(tmp_path, monkeypatch):
    store, pdp, lk = _hub(tmp_path, monkeypatch)
    secret = Path.home() / ".agentos"
    code = (
        "import os, socket\n"
        "print(open('data/in.csv').read().strip().replace('\\n', ' | '))\n"
        "open('out.txt', 'w').write('made on the hub')\n"
        f"print('home visible:', os.path.exists({str(secret)!r}))\n"
        "try:\n    socket.create_connection(('1.1.1.1', 80), 2); print('network: yes')\n"
        "except OSError:\n    print('network: no')\n"
        "print('root:', sorted(os.listdir('/')))\n")
    req = {"code": code, "files": [{"path": "data/in.csv", "data": base64.b64encode(b"a,b\n1,2\n").decode()}]}
    out = asyncio.run(edgecode.answer(store, pdp, lk, req))
    assert out["ok"], out
    assert "a,b | 1,2" in out["output"] and "network: no" in out["output"]
    assert "home visible: False" in out["output"]
    assert [f["path"] for f in out["files"]] == ["out.txt"], "only what it made goes back"
    assert not any((tmp_path / "runs").rglob("*.txt")), "the run's folder is gone afterwards"
    assert any(r["action"] == "edge.code" for r in store.audit_rows(limit=20)) if hasattr(store, "audit_rows") else True


@JAIL
def test_the_hubs_limits_hold(tmp_path, monkeypatch):
    store, pdp, lk = _hub(tmp_path, monkeypatch)
    monkeypatch.setattr(edgecode, "HUB_MEMORY_MB", 300)
    out = asyncio.run(edgecode.answer(store, pdp, lk, {"code": "x = bytearray(800 * 1024 * 1024)"}))
    assert out["ok"] and out["rc"] != 0 and "MemoryError" in out["output"]
    monkeypatch.setattr(edgecode, "HUB_SECONDS", 2)
    out = asyncio.run(edgecode.answer(store, pdp, lk, {"code": "while True: pass"}))
    assert out["rc"] == -9 and "stopped after 2 s" in out["output"]


def test_the_hub_refuses_a_machine_it_did_not_set_up_or_did_not_allow(tmp_path, monkeypatch):
    store, pdp, lk = _hub(tmp_path, monkeypatch, granted=False)
    out = asyncio.run(edgecode.answer(store, pdp, lk, {"code": "print(1)"}))
    assert not out["ok"] and "Permissions" in out["error"]
    edgecode.grant(store, "kitchen-pi")
    other = {**lk, "peer_host_fp": "e" * 64}
    out = asyncio.run(edgecode.answer(store, PDP({}, store), other, {"code": "print(1)"}))
    assert not out["ok"] and "set up itself" in out["error"]
    monkeypatch.setattr(tools, "sandbox_mechanism", lambda: "")
    out = asyncio.run(edgecode.answer(store, PDP({}, store), lk, {"code": "print(1)"}))
    assert not out["ok"] and "no sandbox" in out["error"], "never unconfined"


def test_the_grant_is_written_at_set_up_and_goes_with_the_link():
    from agentos import fabric
    src = (ROOT / "agentos/server.py").read_text()
    enable = src[src.index("async def _provision_enable("):src.index("def _provision_view(")]
    assert "_edge().grant(" in enable
    assert '"code.run"' in (ROOT / "agentos/fabric.py").read_text().split("def forget_link_grants")[1][:600]
    assert '"edge_run"' in (ROOT / "agentos/teamlink.py").read_text()
    assert fabric  # imported: the module the revocation lives in


def test_a_firewall_on_the_hub_is_said_with_its_ports_and_opened_on_a_yes(tmp_path, monkeypatch):
    """Found on the owner's hub: ufw let a Pi reach only SSH and Bento's page, so it was never
    heard and could not have joined or handed code over."""
    from agentos import hostfirewall, session
    conf = tmp_path / "ufw.conf"
    conf.write_text("ENABLED=no\n")
    monkeypatch.setattr(hostfirewall, "UFW_CONF", conf)
    monkeypatch.setattr(hostfirewall.shutil, "which", lambda n: "/usr/sbin/ufw" if n == "ufw" else None)
    cfg = {"port": 8321}
    assert hostfirewall.state(cfg)["kind"] == "" and not hostfirewall.state(cfg)["words"]
    conf.write_text("ENABLED=yes\n")
    st = hostfirewall.state(cfg)
    assert st["kind"] == "ufw" and "8322 (TCP)" in st["words"] and "(UDP)" in st["words"]
    assert st["commands"][0] == "sudo ufw allow 8322/tcp"
    ran = []
    monkeypatch.setattr(session, "_run_root", lambda argv, why: (False, "a password is required"))
    got = hostfirewall.open_ports(cfg)
    assert not got["ok"] and got["needs"][0] == "sudo ufw allow 8322/tcp" and hostfirewall.state(cfg)["words"]
    monkeypatch.setattr(session, "_run_root", lambda argv, why: (ran.append(argv), (True, ""))[1])
    assert hostfirewall.open_ports(cfg)["ok"] and len(ran) == 2
    assert not hostfirewall.state(cfg)["words"], "opened: the line goes"
    cfg["team"] = {"link_port": 9000}
    assert hostfirewall.state(cfg)["words"], "a different port is asked about again"

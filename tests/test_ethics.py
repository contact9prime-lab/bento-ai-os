"""Ethics: whether a step should be done at all, whoever said yes (agentos/ethics.py).

Asked for as "while the user may authorize rm -rf *, the AI's ethics filter has picked it up as
a cautionary command", "asking how to hack a third party site … the vision of the operator is
skewed", and "ethics has to be calculated by the system in the most deterministic way, so the AI
doesn't circumvent it". What these defend:

- only the party who would be hurt can consent: harm to someone else's machine and wiping this
  one are refused whatever a grant, the autonomy level or a person says;
- harm to your own things is measured by Bento (files, bytes, where) and confirmed by TYPING a
  phrase at a screen: a tap, a remembered grant, full autonomy or a phone never answers it, and
  an approver that never asked for the phrase leaves the step refused (fail closed);
- the one switch is the person's own-data check; the others have none, and no agent can reach it;
- a machine is "yours" by a fact Bento checks (this machine, one it set up, a proved site),
  never by a sentence.
"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))
os.environ.setdefault("AGENTOS_VAULT_KEYRING", "0")

from agentos import config as cfgmod                                     # noqa: E402
from agentos import ethics, policy, tools                                # noqa: E402
from agentos.agent import Agent                                          # noqa: E402
from agentos.memory import Store                                         # noqa: E402
from agentos.policy import MAIN, PDP, Principal, STAGES, person_rule     # noqa: E402
from agentos.tools import Toolbox                                        # noqa: E402

ROOT = Path(__file__).parent.parent


def _world(tmp_path, **cfg):
    c = cfgmod.load_config()
    c.update({"workspace": str(tmp_path / "ws"), "autonomy": "full", "policies": []})
    c.update(cfg)
    (tmp_path / "ws").mkdir(exist_ok=True)
    store = Store(tmp_path / "t.db")
    tb = Toolbox(c, store)
    tb.pdp = PDP(c, store)
    return c, store, tb


def _files(d: Path, n: int):
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (d / f"f{i}").write_text("x")
    return d


def _decide(tb, p, name, args):
    lvl, why = tb.risk_of(name, args)
    dec = tb.pdp.decide_tool(p, name, args, lvl, reason=why, surface="gui",
                             autonomy=tb.cfg.get("autonomy"), base_risk=tb.base_risk(name, args))
    must = person_rule(p, name, args, dec, tb.pdp)
    return dec, must


def _grant_shell(store, p=MAIN):
    store.add_grant(p.kind, p.id, "tool.use", "tool:run_command", effect="allow", source="user")


# ---- the rules -------------------------------------------------------------------------

def test_every_rule_a_verdict_names_is_in_the_table_and_only_your_own_can_be_switched():
    src = (ROOT / "agentos" / "ethics.py").read_text()
    named = set(re.findall(r'Verdict\("(?:caution|refuse)", "(\w+)"', src))
    assert named and named <= set(ethics.RULE), named - set(ethics.RULE)
    assert [r[0] for r in ethics.RULES if r[3]] == ["own"]
    assert {r[0] for r in ethics.RULES if r[1] in ("others", "everyone")} >= {"wreck", "attack", "range"}
    assert ("ethics" in [s[0] for s in STAGES]) and policy.stage_of("ethics") == "ethics"


@pytest.mark.parametrize("line,rule", [
    ("rm -rf /", "wreck"), ("rm -rf ~", "wreck"), ("rm -rf ~/*", "wreck"), ("sudo rm -rf /etc", "wreck"),
    ("mkfs.ext4 /dev/sdb1", "wreck"), ("dd if=/dev/zero of=/dev/sda bs=1M", "wreck"),
    ("chmod -R 777 /", "wreck"), ("bash -c 'rm -rf /usr'", "wreck"),
    ("nmap -sV example.com", "attack"), ("sqlmap -u https://shop.example.org/?id=1 --dbs", "attack"),
    ("hydra -l admin -P rockyou.txt ssh://203.0.113.5", "attack"),
    ("ab -n 100000 -c 500 https://example.com/", "attack"), ("timeout 60 nikto -h victim.example", "attack"),
    ("nmap 192.168.1.0/24", "range"), ("masscan 10.0.0.0/8 -p80", "range"),
])
def test_refused_whoever_asks(tmp_path, line, rule):
    v = ethics.judge("run_command", {"command": line, "cwd": str(tmp_path)}, {"workspace": str(tmp_path)})
    assert v.level == "refuse" and v.rule == rule, (line, v)
    assert v.harmed in ("others", "everyone")


def test_a_target_that_is_yours_is_left_to_the_rest_of_the_gate(tmp_path):
    c = {"workspace": str(tmp_path)}
    for line in ("nmap -sV 127.0.0.1", "nmap localhost", "curl https://example.com", "ls -la",
                 "git push origin main", "rm -rf build"):
        assert ethics.judge("run_command", {"command": line, "cwd": str(tmp_path)}, c).level == "ok", line
    # a site becomes yours by the proof file, recorded, never by being named
    c["ethics"] = {"sites": [{"host": "example.com", "how": "proof file"}]}
    assert ethics.judge("run_command", {"command": "nmap -sV api.example.com"}, c).level == "ok"
    assert ethics.judge("run_command", {"command": "nmap -sV example.net"}, c).level == "refuse"


def test_your_own_things_are_measured_and_typed(tmp_path):
    ws = tmp_path / "ws"
    _files(ws / "big", ethics.OWN_FILES + 5)
    _files(ws / "small", 3)
    _files(tmp_path / "elsewhere", 1)
    c = {"workspace": str(ws)}
    big = ethics.judge("run_command", {"command": "rm -rf big", "cwd": str(ws)}, c)
    assert big.level == "caution" and big.rule == "own" and big.harmed == "you"
    assert big.confirm == f"delete {ethics.OWN_FILES + 5} files"
    assert any(f.startswith(f"{ethics.OWN_FILES + 5} files") for f in big.facts)
    assert ethics.judge("run_command", {"command": "rm -rf small", "cwd": str(ws)}, c).level == "ok"
    out = ethics.judge("run_command", {"command": f"rm -rf {tmp_path / 'elsewhere'}", "cwd": str(ws)}, c)
    assert out.level == "caution" and "outside your workspace" in out.facts
    # yours to switch off
    c["ethics"] = {"own": False}
    assert ethics.judge("run_command", {"command": "rm -rf big", "cwd": str(ws)}, c).level == "ok"


def test_what_it_cant_read_or_rewrites_others_history_is_typed(tmp_path):
    c = {"workspace": str(tmp_path), "ethics": {"own": False}}
    for line, rule in (("rm -rf $(cat list)", "unread"), ('rm -rf "$DIR"/*', "unread"),
                       ("ls | xargs rm -f", "unread"), ("git push --force origin main", "history"),
                       ("git push origin +main", "history"), ("nmap -iL targets.txt", "unread")):
        v = ethics.judge("run_command", {"command": line, "cwd": str(tmp_path)}, c)
        assert v.level == "caution" and v.rule == rule, (line, v)


def test_code_that_imports_an_attack_library_is_read_too():
    v = ethics.judge("run_python", {"code": "from scapy.all import *\nsend(IP(dst='198.51.100.7')/TCP())"}, {})
    assert v.level == "refuse" and v.rule == "attack"
    assert ethics.judge("run_python", {"code": "print(1+1)"}, {}).level == "ok"


def test_a_reader_that_breaks_never_waves_a_step_through(monkeypatch):
    monkeypatch.setattr(ethics, "judge_command", lambda *a, **k: 1 / 0)
    v = ethics.judge("run_command", {"command": "rm -rf x"}, {})
    assert v.level == "caution"


def test_no_model_is_asked():
    src = (ROOT / "agentos" / "ethics.py").read_text()
    imports = set(re.findall(r"from \. import (\w+)|from \.(\w+) import", src))
    imported = {a or b for a, b in imports}
    assert not imported & {"executors", "providers", "agent", "fabric", "llm"}, imported
    for word in ("ask_brain", "ask_once", "complete(", "chat("):
        assert word not in src, word


# ---- the gate --------------------------------------------------------------------------

def test_a_grant_and_full_autonomy_do_not_reach_past_a_refusal(tmp_path):
    c, store, tb = _world(tmp_path)
    _grant_shell(store)
    dec, _ = _decide(tb, MAIN, "run_command", {"command": "nmap -A scanme.nmap.org"})
    assert dec.effect == "deny" and dec.rule == "ethics" and "scanme.nmap.org" in dec.reason
    # a specialist, an app: the same
    for p in (Principal("subagent", "researcher"), Principal("app", "a1")):
        assert _decide(tb, p, "run_command", {"command": "rm -rf ~"})[0].rule in ("ethics", "hard-block", "builtin-deny")


def test_a_caution_is_a_typed_question_that_nothing_remembers(tmp_path):
    c, store, tb = _world(tmp_path)
    _files(tmp_path / "ws" / "big", ethics.OWN_FILES + 1)
    _grant_shell(store)
    dec, must = _decide(tb, MAIN, "run_command", {"command": "rm -rf big", "cwd": str(tmp_path / "ws")})
    assert dec.effect == "ask" and dec.rule == "ethics" and dec.grant_offer is None
    assert dec.ethics["confirm"] == f"delete {ethics.OWN_FILES + 1} files"
    assert must and "type" in must
    # a later deny still stands: ethics never widens
    store.add_grant("user", "", "tool.use", "tool:run_command", effect="deny", source="user")
    assert _decide(tb, MAIN, "run_command", {"command": "rm -rf big", "cwd": str(tmp_path / "ws")})[0].effect == "deny"


def _agent(c, tb, approver):
    ran = []

    async def emit(ev):
        pass

    async def execute(name, args):
        ran.append((name, dict(args)))
        return f"ran {name}"
    tb.execute = execute
    return Agent(c, tb, "ollama/x", emit, approver, principal=MAIN, surface="gui"), ran


def test_a_yes_without_the_typed_words_is_refused(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    monkeypatch.setattr(tools, "jail_gap", lambda cfg: "")
    _files(tmp_path / "ws" / "big", ethics.OWN_FILES + 1)
    seen = []

    async def taps_yes(name, args, reason, offer=None):
        seen.append((ethics.pending(), policy.needs_person()))
        return True                                  # a phone tap, a scheduler, an old page
    a, ran = _agent(c, tb, taps_yes)
    out, ok, *_ = asyncio.run(a.call_tool("run_command", {"command": "rm -rf big", "cwd": str(tmp_path / "ws")}, "c"))
    assert not ran and not ok and "type" in out and seen[0][0] and seen[0][1]
    assert ethics.pending() is None                  # the question is closed once answered


def test_the_typed_words_let_it_run(tmp_path, monkeypatch):
    c, store, tb = _world(tmp_path)
    monkeypatch.setattr(tools, "jail_gap", lambda cfg: "")
    _files(tmp_path / "ws" / "big", ethics.OWN_FILES + 1)

    async def types_it(name, args, reason, offer=None):
        p = ethics.pending()
        assert "token" in p and p["confirm"]
        return ethics.confirm(p["token"], p["confirm"], p["confirm"].upper() + "  ")
    a, ran = _agent(c, tb, types_it)
    out, ok, *_ = asyncio.run(a.call_tool("run_command", {"command": "rm -rf big", "cwd": str(tmp_path / "ws")}, "c"))
    assert ran and ok


def test_wrong_words_and_a_reused_token_do_nothing():
    v = ethics.Verdict("caution", "own", "w", [], "delete 9 files", "you")
    tok, ctx = ethics.ask(v)
    ethics.done(ctx)
    assert not ethics.confirm(tok, v.confirm, "delete 8 files")
    assert ethics.confirm(tok, v.confirm, "Delete 9 files")
    assert ethics.consume(tok) and not ethics.consume(tok)


# ---- the faces and the switch ----------------------------------------------------------

def test_the_server_checks_the_words_and_phones_are_never_asked():
    src = (ROOT / "agentos" / "server.py").read_text()
    body = src[src.index("async def resolve_approval"):src.index("async def _approval_send")]
    assert "ethics_mod.confirm(" in body and "remember = False" in body
    req = src[src.index("async def request_approval"):src.index("async def _desk_approval")]
    assert req.index("ethics_mod.pending()") < req.index("_phone_asks(")
    desk = src[src.index("async def _desk_approval"):src.index("def _ethics_public")]
    assert "_ethics_public(eth)" in desk, "the token never goes to a page"
    tg = (ROOT / "agentos" / "telegram_admin.py").read_text()
    assert 'dec.rule == "ethics"' in tg


def test_every_screen_asks_for_the_words():
    js = (ROOT / "agentos" / "ui" / "src" / "js" / "09-websocket.js").read_text()
    assert "function apEthics" in js and "allow.disabled=true" in js and "typed" in js
    assert "innerHTML" not in js[js.index("function apEthics"):js.index("/* The price card.")]
    assert "ApprovalScreen(" in (ROOT / "agentos" / "tui_app.py").read_text()
    assert 'ev.get("ethics")' in (ROOT / "agentos" / "tui_app.py").read_text()
    assert 'ev.get("ethics")' in (ROOT / "agentos" / "clitui.py").read_text()
    main = (ROOT / "agentos" / "__main__.py").read_text()
    assert "ethics_mod.pending()" in main and '"typed": args.type' in main


def test_no_agent_can_reach_the_switch():
    from agentos import users
    assert "ethics" in users.USER_KEYS
    assert "ethics" not in tools.CONFIG_SAFE_KEYS
    assert "agentos/ethics.py" in __import__("agentos.protected", fromlist=["x"]).SECURITY_MODULES
    s = (ROOT / "agentos" / "server.py").read_text()
    put = s[s.index('@app.put("/api/ethics")'):s.index('@app.post("/api/ethics/prove")')]
    assert '"ethics.write"' in put, "a switch is a ledger row"
    assert "only `own` can be switched" in put


def test_the_settings_card_and_the_cli(tmp_path, capsys, monkeypatch):
    js = (ROOT / "agentos" / "ui" / "src" / "js" / "11m-ethics.js").read_text()
    assert "/api/ethics" in js and "innerHTML" not in js
    from agentos.__main__ import _ethics_cli
    monkeypatch.setenv("AGENTOS_PORT", "1")

    class A:
        action, rest = "check", ["nmap", "-sV", "example.org"]
    _ethics_cli(A())
    assert "refused (attack)" in capsys.readouterr().out


def test_a_site_is_proved_by_its_file(tmp_path, monkeypatch):
    c = {}
    got = ethics.prove_start(c, "Example.com.")
    assert got["host"] == "example.com" and got["token"].startswith("bento-proof-")
    from agentos import netguard

    async def fake(url, cap, **k):
        assert url == "https://example.com" + ethics.PROOF_PATH
        return 200, "text/plain", f"{got['token']}\n".encode()
    monkeypatch.setattr(netguard, "read_capped", fake)
    ok, said = asyncio.run(ethics.prove_check(c, "example.com"))
    assert ok and ethics.owned("www.example.com", c)
    assert ethics.forget_site(c, "example.com") and not ethics.owned("example.com", c)
    with pytest.raises(ValueError):
        ethics.prove_start(c, "not a site")


def test_a_refusal_is_not_pushed_to_try_again():
    """Found live: after the person denied an ethics card, the loop's "you ended without
    delivering … do it NOW with your tools" nudge fired, asking the model to find a way round."""
    steps = [{"type": "tool", "name": "run_command", "ok": False,
              "output": "[denied] Bento's ethics check needs a person to type it, and nobody did."}]
    assert not Agent._looks_unfinished("I didn't delete anything. The folder is still there.", steps)

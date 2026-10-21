"""Files across a linked team's hand-over, both ways, under permissions.

Asked for as "in teams mode, where permissions are defined and agents hand off tasks, the
blobs should be sent back to the main agent: if the main agent asks an agent on another
machine to build a ppt, the file has to come back once done; and files on one computer
may be what the other acts on". Two machines, 'office' and 'home', linked over real mTLS.
What these defend:

- home's lead hands a task to analyst@office with a file; the file is decided as its own
  step (`file.send` on `team:office`), lands on office in from-home/, the analyst makes the
  deck in for-home/, and the deck comes back to home in from-office/;
- only what was MADE for the task comes back: a file the answer names that existed before
  stays where it is, and the answer says so;
- office can switch files back off, and then its agents can't make files for that team
  either (the folder permission goes with it);
- below full autonomy the send is asked; after untrusted content it is a person's; a file
  outside the folders this machine shares with its agents, or a hidden one, never goes.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("AGENTOS_HOME", tempfile.mkdtemp(prefix="agentos-test-home-"))

from agentos import fabric, linkfiles, providers, teamlink              # noqa: E402
from agentos.agent import Agent                                         # noqa: E402
from agentos.policy import MAIN, PDP, needs_person                       # noqa: E402
from test_teamlink import pair                                          # noqa: E402,F401

ROOT = Path(__file__).parent.parent


def _scripted(seen):
    """home's lead hands the deck to analyst@office with data.csv; the analyst writes the
    deck where it was told to, and answers naming it and an older file."""
    def chat(cfg, model, messages, tools, options=None):
        async def gen():
            sys_txt = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            done = [m["content"] for m in messages if m["role"] == "tool"]
            if "SOUL-analyst" in sys_txt:
                seen["analyst_task"] = user
                import re
                folder = re.search(r"write them in (/\S+) \(or", user)
                if not done:
                    yield {"type": "tool_call", "id": "w1", "name": "write_file",
                           "args": {"path": f"{folder.group(1) if folder else 'nowhere'}/deck.pptx",
                                    "content": "SLIDES built from data.csv"}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                seen["analyst_tool"] = done[-1]
                yield {"type": "text", "text": f"Made it: `{folder.group(1) if folder else ''}/deck.pptx`. "
                                               f"I also looked at `{seen['old']}`."}
            else:
                if not done:
                    send = seen.get("send", ["data.csv"])
                    yield {"type": "tool_call", "id": "d1", "name": "delegate",
                           "args": {"subagent": "analyst@office", "task": "build the deck from the data",
                                    **({"files": send} if send else {})}}
                    yield {"type": "finish", "reason": "tool_calls"}
                    return
                seen["lead_tool"] = done[-1]
                yield {"type": "text", "text": "LEAD done"}
            yield {"type": "finish", "reason": "stop"}
        return gen()
    return chat


def _setup(pair, monkeypatch, autonomy="full", files_back=None):
    A, B, inv, loop = pair
    A["store"].save_subagent({"name": "analyst", "soul": "SOUL-analyst", "tools": ["write_file"]})
    fabric.set_link_access(A["store"], "home", ["analyst"])
    B["store"].add_grant("user", "", "agent.message", "agent:subagent/analyst@office")
    B["cfg"]["autonomy"] = autonomy
    (B["home"] / "data.csv").write_text("month,revenue\nOct,12\n")
    old = A["home"] / "old-notes.txt"
    old.write_text("written before the task")
    os.utime(old, (1, 1))
    if files_back is not None:
        linkfiles.set_back(A["store"], "home", files_back, A["cfg"])
    seen = {"old": str(old)}
    monkeypatch.setattr(providers, "chat", _scripted(seen))
    return A, B, loop, seen


def _lead_run(B, loop, approver=None, taint=None):
    async def em(ev):
        pass

    async def yes(*a, **k):
        return True
    agent = Agent(B["cfg"], B["tb"], "openai/gpt-4o", em, approver or yes)
    if taint:
        agent.taint = list(taint)

    async def go():
        with teamlink.at(B["home"]):
            return await agent.run([{"role": "user", "content": "make me the deck"}])
    return loop.run_until_complete(go())


def test_a_file_goes_with_the_task_and_the_deck_comes_back(pair, monkeypatch):
    A, B, loop, seen = _setup(pair, monkeypatch)
    _lead_run(B, loop)
    got = A["home"] / "from-home" / "data.csv"
    assert got.read_text().startswith("month,revenue"), "the file arrived on the other machine"
    assert str(got) in seen["analyst_task"], "and the task names where it is"
    assert "for-home" in seen["analyst_task"], "the worker is told where to make what goes back"
    assert "written" in seen["analyst_tool"].lower() or "wrote" in seen["analyst_tool"].lower(), seen["analyst_tool"]
    back = B["home"] / "from-office" / "deck.pptx"
    assert back.read_text() == "SLIDES built from data.csv", "the deck came back"
    assert str(back) in seen["lead_tool"], "and the lead's answer names it here"
    assert "old-notes.txt" in seen["lead_tool"] and "not made for this task" in seen["lead_tool"]
    assert not (B["home"] / "from-office" / "old-notes.txt").exists(), "an older file stays where it is"
    a_rows = [(r["action"], (r.get("reason") or "") + (r.get("detail") or "")) for r in A["store"].audit_list(limit=80)]
    b_rows = [(r["action"], (r.get("reason") or "") + (r.get("detail") or "")) for r in B["store"].audit_list(limit=80)]
    assert any(a == "link.files" and "received 1 file" in d for a, d in a_rows)
    assert any(a == "link.files" and "sent 1 file(s) back" in d for a, d in a_rows)
    assert any(a == "link.files" and "sent 1 file(s) to office" in d for a, d in b_rows)
    assert any(a == "file.send" for a, _ in b_rows), "the send was a gate decision, in the ledger"
    assert any(a == "file.send" for a, _ in a_rows), "and so was sending it back"


def test_switching_files_back_off_keeps_them_here_and_the_folder_closed(pair, monkeypatch):
    A, B, loop, seen = _setup(pair, monkeypatch, files_back=False)
    _lead_run(B, loop)
    assert not (B["home"] / "from-office").exists()
    assert "for-home" not in seen["analyst_task"]
    assert seen["analyst_tool"].startswith("[denied]"), "no folder to make it in: a person is needed"
    with teamlink.at(A["home"]):
        assert not linkfiles.back_state(A["store"], "home")
    linkfiles.set_back(A["store"], "home", True, A["cfg"])
    assert linkfiles.back_state(A["store"], "home")
    rows = [g for g in A["store"].list_grants(principal_kind="team", principal_id="home/*")
            if g["source"] == "files"]
    assert len(rows) == 1 and "for-home" in rows[0]["resource"]


def test_below_full_autonomy_the_send_is_asked_and_a_no_keeps_the_file(pair, monkeypatch):
    A, B, loop, seen = _setup(pair, monkeypatch, autonomy="balanced")
    asked = []

    async def no(name, args, reason, offer=None):
        asked.append((name, args, offer))
        return False
    _lead_run(B, loop, approver=no)
    sends = [a for a in asked if a[0] == "send_files"]
    assert sends and sends[0][1]["files"] == ["data.csv"] and sends[0][1]["to"] == "office"
    assert sends[0][2], "Allow & remember is offered: a standing yes for that team"
    assert not (A["home"] / "from-home").exists()
    assert "were not sent" in seen["lead_tool"]


def test_after_untrusted_content_the_send_is_a_persons(pair, monkeypatch):
    A, B, loop, seen = _setup(pair, monkeypatch)
    who = []

    async def ask(name, args, reason, offer=None):
        if name == "send_files":
            who.append(needs_person())
            return False
        return True
    _lead_run(B, loop, approver=ask, taint=[{"tool": "fetch_url", "source": "example.com"}])
    assert who == ["after untrusted content"]
    assert not (A["home"] / "from-home").exists()


def test_a_leads_hand_overs_are_budgeted_per_turn_not_forever(pair, monkeypatch):
    """Found by running these files together: the lead's hand-overs to a linked team were all
    budgeted under its own name, so after six of them, in any chats, every later one was
    refused until the server restarted."""
    A, B, loop, seen = _setup(pair, monkeypatch)
    seen["send"] = []
    for _ in range(fabric.team_limits(B["cfg"])["budget"] + 1):
        _lead_run(B, loop)
        assert "[analyst@office" in seen["lead_tool"] and "[refused]" not in seen["lead_tool"], seen["lead_tool"]


def test_only_shared_folders_and_never_a_hidden_file(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".ssh").mkdir(parents=True)
    (ws / ".ssh" / "id_ed25519").write_text("KEY")
    (ws / "ok.txt").write_text("fine")
    (tmp_path / "outside.txt").write_text("nope")
    cfg = {"workspace": str(ws)}
    ok, refused = linkfiles.resolve_out(cfg, ["ok.txt", ".ssh/id_ed25519", str(tmp_path / "outside.txt"),
                                              "../outside.txt", "missing.txt"])
    assert [p.name for p in ok] == ["ok.txt"]
    assert any("hidden" in r for r in refused) and sum("not a file" in r for r in refused) == 3


def test_the_permission_is_an_ordinary_grant_and_defaults_with_the_cells(tmp_path):
    from agentos.memory import Store
    store = Store(tmp_path / "s.db")
    cfg = {"workspace": str(tmp_path / "ws")}
    assert not linkfiles.back_state(store, "office"), "no cell, nothing goes back"
    fabric.set_link_access(store, "office", [fabric.LEAD])
    assert linkfiles.back_state(store, "office")
    assert linkfiles.ensure_back(store, cfg, "office")
    pdp = PDP({"autonomy": "balanced"}, store)
    assert linkfiles.may_send_back(store, pdp, "office")
    linkfiles.set_back(store, "office", False, cfg)
    assert not linkfiles.may_send_back(store, PDP({"autonomy": "balanced"}, store), "office")
    assert pdp.decide(MAIN, "file.send", "team:office", {"risk": "risky", "autonomy": "full"}).effect == "allow"


def test_every_face_has_it():
    s = (ROOT / "agentos/ui/src/js/11-settings.js").read_text()
    assert "data-link-files" in s and "files_back" in s
    assert "file.send" in (ROOT / "agentos/ui/src/js/20c-permmap.js").read_text()
    main = (ROOT / "agentos/__main__.py").read_text()
    assert '"files"])' in main and "linkfiles.set_back" in main
    assert '"send_files"' in (ROOT / "agentos/approvalcard.py").read_text()
    tools = (ROOT / "agentos/tools.py").read_text()
    assert '"files": {"type": "array"' in tools, "the model can name files for a hand-over"

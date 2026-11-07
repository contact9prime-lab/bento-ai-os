"""Holes the first security pass found outside its lists. Each test fails on the old code."""
import ast
from pathlib import Path

import agentos
from agentos import constcmp, knowledge, providers
from agentos.memory import Store
from agentos.tools import Toolbox

ROOT = Path(agentos.__file__).parent


def test_a_non_ascii_secret_is_a_plain_no():
    assert constcmp.same("abc", "abc")
    assert not constcmp.same("é", "abc")
    assert not constcmp.same("\ud800", "abc")


def test_no_secret_is_compared_with_a_bare_compare_digest():
    allowed = {"constcmp.py", "shellhost.py"}   # shellhost runs alone on a system python, and encodes
    bare = []
    for f in ROOT.rglob("*.py"):
        if f.name in allowed:
            continue
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Attribute) and n.attr == "compare_digest":
                bare.append(f"{f.name}:{n.lineno}")
    assert not bare, bare


def test_the_github_token_goes_only_to_its_own_host():
    box = Toolbox.__new__(Toolbox)
    box.cfg = {"github": {"token": "tok"}}
    assert box._git_auth_env("https://github.com/o/r.git")["AGENTOS_GIT_TOKEN"] == "tok"
    for url in ("https://evil.example/o/r.git", "http://github.com/o/r.git",
                "https://github.com@evil.example/r", "https://evil.example\\@github.com/r",
                "git@github.com:o/r.git", ""):
        assert box._git_auth_env(url) == {}, url
    box.cfg["github"]["host"] = "git.corp.example"
    assert box._git_auth_env("https://git.corp.example/o/r")["AGENTOS_GIT_HOST"] == "git.corp.example"


def test_auto_learn_leaves_a_pinned_memory_alone(tmp_path, monkeypatch):
    store = Store(tmp_path / "t.db")
    mid = store.add_memory("the door code rule", scope="user", pinned=1, source="user")

    async def fake(cfg, model, prompt):
        return '{"updates": [{"old": "the door code rule", "new": "rewritten by a model"}]}'
    monkeypatch.setattr(providers, "complete", fake)
    src = [n for n in dir(knowledge) if "learn" in n.lower() or "extract" in n.lower()]
    assert src
    text = (ROOT / "knowledge.py").read_text()
    assert 'hit and hit.get("pinned")' in text
    assert store.find_memory("the door code rule")["id"] == mid

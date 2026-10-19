"""Permissions → Map (20c-permmap.js): every rule says what it does in a sentence and lands
on one place of the map. The page's own functions are run in Node."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
JS = (ROOT / "agentos/ui/src/js/20c-permmap.js").read_text()


def _run(expr: str):
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = JS + "\nconsole.log(JSON.stringify(" + expr + "));"
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_each_rule_reads_as_a_sentence():
    cases = [
        ({"action": "tool.use", "resource": "tool:run_command git status*", "effect": "allow"},
         "may run git status…"),
        ({"action": "tool.use", "resource": "tool:fetch_url*", "effect": "allow"}, "may use fetch_url"),
        ({"action": "fs.write", "resource": "fs:/etc/*", "effect": "deny"}, "may not write files in /etc/…"),
        ({"action": "net.fetch", "resource": "net:*", "effect": "allow"}, "may fetch any web address"),
        ({"action": "agent.message", "resource": "agent:subagent/writer", "effect": "allow"}, "may ask writer"),
        ({"action": "agent.invoke", "resource": "agent:main", "effect": "allow"}, "may start your agent"),
        ({"action": "memory.write", "resource": "memory:*", "effect": "deny"}, "may not write memory"),
        ({"action": "mcp.use", "resource": "mcp:github/*", "effect": "allow"}, "may use every tool of github"),
        ({"action": "*", "resource": "*", "effect": "allow"}, "may do anything"),
    ]
    said = _run("[" + ",".join(f"pmSay({json.dumps(g)})" for g, _ in cases) + "]")
    assert said == [want for _, want in cases]


def test_every_action_the_gate_names_has_a_place():
    """An action that fell to 'Other' would be a line to nowhere anybody recognises."""
    actions = ["*", "tool.use", "fs.read", "fs.write", "net.fetch", "agent.invoke", "agent.message",
               "team.act", "pool.work", "memory.read", "memory.write", "kg.write", "mcp.use",
               "skill.use", "plugin.run", "mail.read", "calendar.read", "model.use",
               "app.data.read", "app.data.*", "browser.act", "legacy policy"]
    places = _run("[" + ",".join(f"pmArea({json.dumps(a)})" for a in actions) + "]")
    assert "Other" not in places, dict(zip(actions, places))


def test_where_a_rule_came_from_is_said_in_words():
    got = _run('[pmSource({source:"definition",source_ref:"flow:daily-briefing"}),'
               'pmSource({source:"matrix"}),pmSource({source:"user",source_ref:"conv:abc"}),'
               'pmSource({source:"manifest"})]')
    assert got == ["mission daily-briefing", "team matrix", "remembered in a chat", "its manifest"]


def test_the_map_replaced_the_cards():
    perm = (ROOT / "agentos/ui/src/js/20-permissions.js").read_text()
    assert "function permMap" not in perm and "perm-card" not in perm, "one map, in 20c"
    assert "['map','Map']" in perm
    assert "function permMap(box)" in JS and "pmLines" in JS

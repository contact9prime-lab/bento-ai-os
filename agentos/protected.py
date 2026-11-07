"""What no agent may write: one list, in code, read by everything that guards a path.

Asked for as "AI should not be able to touch the security file". There used to be no such list:
`policy.py`, `vault.key` and `config.json` got no refusal of their own, and only the jail stood in
front of them where a jail existed.

A grant, a Rule, autonomy or a person's click cannot widen this: the answer does not read any of
them. It holds for every principal that is an agent. A person edits these from their own terminal,
outside this OS, which is where changing the gate belongs.

Two things it is not. It is not the whole defence, because a process outside the jail with the same
Unix user can write a file whatever this says (`integrity.py` notices that, and `bento integrity
lock` puts the code out of that user's reach). And it is not a read ban on code: an agent may read
the source. `SECRET_FILES` are refused for reads as well, because reading those is the attack.
"""

from __future__ import annotations

import os
from pathlib import Path

# The modules that decide who may do what. The whole code tree is refused for an agent's writes;
# this narrower list is what is refused even to a person's approved `develop_agentos`, and what
# a change to raises the loudest alert.
SECURITY_MODULES = frozenset({
    "agentos/agent.py",
    "agentos/approvalcard.py",
    "agentos/edgecode.py",
    "agentos/executors.py",
    "agentos/fabric.py",
    "agentos/hands.py",
    "agentos/integrity.py",
    "agentos/mcpbridge.py",
    "agentos/mcp_client.py",
    "agentos/migrate.py",
    "agentos/peercheck.py",
    "agentos/policy.py",
    "agentos/protected.py",
    "agentos/provision.py",
    "agentos/remote.py",
    "agentos/secevents.py",
    "agentos/server.py",
    "agentos/standby.py",
    "agentos/teamlink.py",
    "agentos/tools.py",
    "agentos/toolscope.py",
    "agentos/updates.py",
    "agentos/users.py",
    "agentos/vault.py",
    "install.sh",
    "pyproject.toml",
})

# In any home (the machine's or an account's): never read or written by an agent. Reading a
# vault key is reading every password; writing a database is writing your own grants.
SECRET_FILES = frozenset({
    "session.key", "vault.key", "vault.json", "users.json",
    "security-events.jsonl", "integrity.json", "integrity.keys", "integrity.held",
    "integrity.writes", "integrity.updating", "integrity.lock", "ledger.key", "ledger.anchor",
})
WRITE_LOCKED_FILES = frozenset({
    "config.json", "agentos.db", "agentos.db-wal", "agentos.db-shm", "provision.json",
    "inventory.json", "update-history.json",
})
SECRET_DIRS = frozenset({"pki", ".standby", ".keep"})

# A CLI runs what these say on its next start, outside the gate (a SessionStart hook, an MCP
# server), so writing one into a workspace is writing a program.
AGENT_CONFIG_NAMES = frozenset({".claude", ".gemini", ".codex", ".mcp.json", ".cursor", ".vscode"})


def _code_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _homes() -> list[Path]:
    """The machine's home, read at call time because tests and a restore move it."""
    from . import config as cfgmod
    return [Path(cfgmod.AGENTOS_HOME).resolve()]


def _real(path) -> Path:
    return Path(os.path.realpath(os.path.expanduser(str(path))))


def _home_relative(real: Path) -> tuple[str, ...] | None:
    """The parts of `real` under a home, with `users/<id>/` taken off, or None when outside."""
    for home in _homes():
        try:
            parts = real.relative_to(home).parts
        except ValueError:
            continue
        if len(parts) >= 2 and parts[0] == "users":
            parts = parts[2:]
        return parts
    return None


def secret(path) -> str:
    """Why an agent may not READ this path, or ''. Worded for the tool's refusal."""
    parts = _home_relative(_real(path))
    if parts is None or not parts:
        return ""
    if parts[-1] in SECRET_FILES or parts[0] in SECRET_DIRS:
        return f"{parts[-1]} is a security file. No agent can read it."
    return ""


def write_refused(path) -> str:
    """Why an agent may not WRITE this path, or ''. No grant or autonomy level changes it."""
    why = secret(path)
    if why:
        return why
    real = _real(path)
    try:
        rel = real.relative_to(_code_root())
    except ValueError:
        rel = None
    if rel is not None and rel.parts and rel.parts[0] in ("agentos", "install.sh", "pyproject.toml",
                                                          "packaging", "tests", ".github"):
        return f"{rel} is this OS's own code. No agent can change it."
    parts = _home_relative(real)
    if parts and parts[-1] in WRITE_LOCKED_FILES:
        return f"{parts[-1]} holds this machine's settings and permissions. No agent can change it."
    for part in real.parts:
        if part in AGENT_CONFIG_NAMES:
            return f"{part} tells an agent CLI what to run on its next start. No agent can change it."
        if part == ".git":
            return "A git folder holds hooks git runs by itself. No agent can write into it directly."
    return ""


def is_security_module(rel_path: str) -> bool:
    """`develop_agentos` refuses these even with a person's yes."""
    return str(rel_path).replace(os.sep, "/").lstrip("./") in SECURITY_MODULES

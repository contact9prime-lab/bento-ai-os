"""Executor profiles: an agent's hands.

The model this OS is built on, in the words it was asked for:

- a **brain** is where the thinking comes from — a provider and one of its models,
  or another agent installed here (`executors.brains()`, Settings → AI providers);
- **hands** are what an agent can physically reach — which tools, which folders and
  whether it may write there, which web addresses, which MCP servers. That is an
  executor PROFILE, defined here, shown as Settings → Executors;
- **authority** is what an agent is ALLOWED to do with those hands — its grants in
  the permission gate (`policy.PDP`), unchanged;
- an **agent** is the one that gets a brain, a profile, grants, skills and a soul.

So a profile is a CEILING, not a permission. It is checked by the gate before
grants (`policy.PDP._decide`, step 2a) and no grant can reach past it: a
"read-only" agent granted `fs.write` everywhere still cannot write, because the
hands it was given do not reach. And it is audited like every other refusal
(rule `reach`), so "why could it not?" has the same answer on every surface.

Three things to keep true:

- **Folders are matched on the real path**, never the text the model wrote
  (`policy._fs_real`: `~`, the workspace for a relative path, `..` and symlinks
  resolved). A glob is not a path.
- **A shell is a tool, and the profile says so honestly.** `run_command` reaches
  whatever the machine's folder jail allows, not only this profile's folders — so
  the editor says that out loud next to the switch rather than implying the folder
  list bounds a shell. Leave it out of a profile to keep the folders a real limit.
- **The default profile is today's behaviour** (every tool, anywhere the machine
  allows, any web, every MCP server), so installing this changes nothing until
  somebody narrows an agent. Built-ins can be edited but not deleted, and an agent
  whose profile was deleted falls back to default — it is never left with no hands
  and a stale name.

Kept free of HTTP and asyncio, like `jobs.py`: `bento hands` reads and writes the same
rows with the server down.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import time

DEFAULT = "default"

#: How the editor groups the tool catalogue. Presentation only: a tool not listed
#: here appears under "Other", and nothing is allowed or refused because of a group.
GROUPS = {
    "Files": ["read_file", "write_file", "list_dir", "search_files", "list_folders", "share_folder",
              "save_report"],
    "Web": ["fetch_url"],
    "Shell & code": ["run_command", "run_python", "run_tests", "run_evals"],
    "Git": ["git_status", "git_log", "git_diff", "git_init", "git_commit", "git_branch",
            "git_remote_set", "git_push", "git_pull", "git_clone", "export_app_to_git"],
    "Memory": ["remember", "recall", "forget", "kg_add", "kg_query", "timeline"],
    "Mail & calendar": ["mail_search", "mail_read", "mail_send", "calendar_events"],
    "Messages": ["notify", "telegram_send", "whatsapp_send", "brief_item"],
    "Images & assets": ["generate_image", "list_assets", "get_asset", "save_asset", "delete_asset",
                        "generate_wallpaper"],
    "Desktop": ["open_app", "launch_native_app", "list_windows", "focus_window", "manage_window",
                "desktop_state", "control_desktop", "take_screenshot", "set_wallpaper",
                "create_theme", "list_themes", "pin_widget", "list_notifications", "system_info",
                "system_control", "wifi", "bluetooth", "set_brightness", "audio", "power_profile",
                "lock_screen", "power_action"],
    "Apps & missions": ["create_app", "read_app_data", "create_flow", "enable_flow", "list_flows",
                        "run_flow", "schedule_task", "create_trigger", "list_automations",
                        "run_automation", "save_automation"],
    "Team": ["delegate", "huddle", "ask_agent", "create_subagent", "set_agent_brain", "set_avatar", "set_office"],
    "Skills & tools": ["use_skill", "save_skill", "delete_skill", "find_tools", "search_docs",
                       "add_mcp_server", "discover_mcp_servers", "install_mcp_server", "llm_generate"],
}

#: The tools a shell-shaped reach comes from: said out loud in the editor, because a
#: profile's folders bound the FILE tools and not a command line.
SHELL_TOOLS = ("run_command", "run_python", "run_tests")

READ_ONLY_TOOLS = ["read_file", "list_dir", "search_files", "list_folders", "fetch_url", "recall",
                   "kg_query", "timeline", "list_assets", "get_asset", "system_info", "search_docs",
                   "git_status", "git_log", "git_diff", "mail_search", "mail_read", "calendar_events",
                   "list_flows", "brief_item", "notify", "ask_agent", "use_skill"]

BUILTINS = {
    DEFAULT: {"description": "Everything this machine allows: every tool, any folder the "
                             "machine's own sandbox lets through, the web, every MCP server. "
                             "What your agent had before profiles existed.",
              "spec": {"tools": ["*"], "folders": [{"path": "*", "mode": "rw"}],
                       "web": "any", "mcp": ["*"]}},
    "read-only": {"description": "Looks, never touches: reading tools only, the workspace "
                                 "read-only, the web, no MCP servers.",
                  "spec": {"tools": READ_ONLY_TOOLS,
                           "folders": [{"path": "@workspace", "mode": "ro"}],
                           "web": "any", "mcp": []}},
}

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")
_GEN = [0]          # bumped on every write; the gate's cache keys on it


def generation() -> int:
    return _GEN[0]


def _audit(store, action: str, resource: str, detail: str):
    try:
        from . import users as _users
        uid = _users.current() or ""
    except Exception:
        uid = ""
    store.audit_add(uid=uid, principal_kind="user", principal_id="", action=action,
                    resource=resource, effect="allow", rule="person", outcome="ok",
                    detail=detail[:1000])


# ---- the spec --------------------------------------------------------------------------

def normalize(spec: dict | None) -> dict:
    """A profile's spec in its one shape, refusing what cannot be one. Folders are
    `*` (anywhere the machine allows), `@workspace`, or a full path (`~` allowed)."""
    s = dict(spec or {})
    tools = [str(t).strip() for t in (s.get("tools") if s.get("tools") is not None else ["*"]) if str(t).strip()]
    folders = []
    for f in (s.get("folders") if s.get("folders") is not None else [{"path": "*", "mode": "rw"}]):
        f = f if isinstance(f, dict) else {"path": str(f), "mode": "rw"}
        path = str(f.get("path") or "").strip()
        mode = "ro" if str(f.get("mode") or "rw") == "ro" else "rw"
        if not path:
            continue
        if path not in ("*", "@workspace") and not os.path.isabs(os.path.expanduser(path)):
            raise ValueError(f"'{path}' is not a full path — write ~/projects or /srv/data "
                             f"(or @workspace for the workspace)")
        folders.append({"path": path, "mode": mode})
    web = s.get("web", "any")
    if isinstance(web, str):
        web = web if web in ("any", "none") else "any"
    else:
        web = [str(w).strip() for w in (web or []) if str(w).strip()] or "none"
    mcp = [str(m).strip() for m in (s.get("mcp") if s.get("mcp") is not None else ["*"]) if str(m).strip()]
    return {"tools": tools, "folders": folders, "web": web, "mcp": mcp}


def summary(spec: dict) -> str:
    """One line a person reads: what these hands reach."""
    s = normalize(spec)
    tools = "every tool" if "*" in s["tools"] else f"{len(s['tools'])} tool{'s' if len(s['tools']) != 1 else ''}"
    if any(f["path"] == "*" for f in s["folders"]):
        folders = "any folder the machine allows"
    elif not s["folders"]:
        folders = "no folders"
    else:
        folders = ", ".join(f"{f['path']} ({'read-write' if f['mode'] == 'rw' else 'read-only'})"
                            for f in s["folders"][:3]) + (" …" if len(s["folders"]) > 3 else "")
    web = {"any": "the web", "none": "no web"}.get(s["web"], "") if isinstance(s["web"], str) \
        else f"{len(s['web'])} web address pattern(s)"
    mcp = "every MCP server" if "*" in s["mcp"] else (f"MCP: {', '.join(s['mcp'])}" if s["mcp"] else "no MCP")
    shell = " · a shell" if ("*" in s["tools"] or any(t in s["tools"] for t in SHELL_TOOLS)) else ""
    return f"{tools}{shell} · {folders} · {web} · {mcp}"


# ---- the rows --------------------------------------------------------------------------

def ensure_builtins(store) -> None:
    now = time.time()
    for name, b in BUILTINS.items():
        store.db.execute("INSERT OR IGNORE INTO executor_profiles (name, description, spec, builtin, "
                         "created_at, updated_at) VALUES (?,?,?,1,?,?)",
                         (name, b["description"], json.dumps(b["spec"]), now, now))
    store.db.commit()


def _row(r) -> dict:
    d = dict(r)
    try:
        d["spec"] = normalize(json.loads(d.get("spec") or "{}"))
    except (ValueError, TypeError):
        d["spec"] = normalize(BUILTINS["read-only"]["spec"])   # an unreadable row fails narrow
    d["builtin"] = bool(d.get("builtin"))
    d["summary"] = summary(d["spec"])
    return d


def list_profiles(store) -> list[dict]:
    ensure_builtins(store)
    rows = store.db.execute("SELECT * FROM executor_profiles ORDER BY builtin DESC, name COLLATE NOCASE"
                            ).fetchall()
    return [_row(r) for r in rows]


def get(store, name: str) -> dict | None:
    ensure_builtins(store)
    r = store.db.execute("SELECT * FROM executor_profiles WHERE name=? COLLATE NOCASE",
                         ((name or DEFAULT).strip(),)).fetchone()
    return _row(r) if r else None


def save(store, name: str, spec: dict, description: str = "") -> dict:
    name = (name or "").strip()
    if not _NAME.fullmatch(name):
        raise ValueError("a profile's name is letters, digits, dot, dash or underscore (up to 40)")
    s = normalize(spec)
    ensure_builtins(store)
    now = time.time()
    old = get(store, name)
    store.db.execute(
        "INSERT INTO executor_profiles (name, description, spec, builtin, created_at, updated_at) "
        "VALUES (?,?,?,0,?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description, "
        "spec=excluded.spec, updated_at=excluded.updated_at",
        (name, (description or "")[:300], json.dumps(s), now, now))
    store.db.commit()
    _GEN[0] += 1
    _audit(store, "executor.write", f"executor:{name}",
           ("changed" if old else "created") + f" — {summary(s)}")
    return get(store, name)


def delete(store, name: str) -> int:
    """Delete a profile; every agent on it goes back to default (and says so)."""
    p = get(store, name)
    if not p:
        raise ValueError(f"no executor called '{name}'")
    if p["builtin"]:
        raise ValueError(f"'{p['name']}' is built in — change it, but it cannot be deleted")
    moved = [a["name"] for a in store.list_subagents() if (a.get("profile") or "").lower() == p["name"].lower()]
    for a in moved:
        store.db.execute("UPDATE subagents SET profile='' WHERE name=? COLLATE NOCASE", (a,))
    store.db.execute("DELETE FROM executor_profiles WHERE name=? COLLATE NOCASE", (p["name"],))
    store.db.commit()
    _GEN[0] += 1
    _audit(store, "executor.delete", f"executor:{p['name']}",
           "deleted" + (f"; {', '.join(moved)} moved to {DEFAULT}" if moved else ""))
    return len(moved)


def assign(store, cfg: dict, agent: str, name: str) -> str:
    """Give an agent hands. `agent` is '@agent' (the master) or a specialist's name.
    Returns the profile name it now has. The caller saves config for the master."""
    p = get(store, name or DEFAULT)
    if not p:
        raise ValueError(f"no executor called '{name}'")
    if agent in ("@agent", "", "master"):
        cfg["agent_profile"] = p["name"]
        who = "your agent"
    else:
        d = store.get_subagent(agent)
        if not d:
            raise ValueError(f"no agent called '{agent}'")
        store.db.execute("UPDATE subagents SET profile=? WHERE id=?",
                         ("" if p["name"] == DEFAULT else p["name"], d["id"]))
        store.db.commit()
        who = d["name"]
    _GEN[0] += 1
    _audit(store, "agent.hands", f"agent:{'@agent' if who == 'your agent' else who}",
           f"{who} now works with the '{p['name']}' executor — {p['summary']}")
    return p["name"]


def profile_name(store, cfg: dict, kind: str, ident: str) -> str | None:
    """Which profile a principal works with, or None when profiles do not apply
    (apps, flows' masters, peers, linked teams have their own ceilings)."""
    if kind == "user":
        return (cfg or {}).get("agent_profile") or DEFAULT
    if kind == "subagent":
        d = store.get_subagent(ident)
        return (d or {}).get("profile") or DEFAULT
    return None


# ---- the ceiling -----------------------------------------------------------------------

def _root(path: str, workspace: str) -> str:
    if path == "@workspace":
        path = workspace or "~"
    return os.path.realpath(os.path.expanduser(path))


def refusal(spec: dict, cfg: dict, tool: str, action: str, resource: str) -> str:
    """Why these hands cannot do this ('' when they can). Only reach is judged here —
    whether the agent is ALLOWED is the grants' question, answered after."""
    s = spec if "tools" in spec and "folders" in spec else normalize(spec)
    ws = (cfg or {}).get("workspace", "")
    if tool and not tool.startswith(("mcp_", "ocp_")) and \
            not any(fnmatch.fnmatchcase(tool, p) for p in s["tools"]):
        return f"'{tool}' is not one of this executor's tools"
    if action == "mcp.use" and resource not in ("mcp:*", "mcp:"):
        server = resource[4:].split("/", 1)[0]
        if not any(fnmatch.fnmatchcase(server, p) for p in s["mcp"]):
            return f"the MCP server '{server}' is not one this executor reaches"
    if action == "plugin.tool" and "*" not in s["tools"] and not any(p.startswith("ocp_") for p in s["tools"]):
        return "plugin tools are not among this executor's tools"
    if action in ("fs.read", "fs.write") and resource not in ("fs:*", "fs:"):
        # anywhere, with the mode this needs: no path to resolve (the default profile)
        if any(f["path"] == "*" and (action == "fs.read" or f["mode"] == "rw") for f in s["folders"]):
            return ""
        from .policy import _fs_real
        real = _fs_real(resource, ws)[3:]
        ro_hit = False
        for f in s["folders"]:
            if f["path"] == "*":
                if action == "fs.read" or f["mode"] == "rw":
                    return ""
                ro_hit = True
                continue
            root = _root(f["path"], ws)
            if real == root or real.startswith(root.rstrip("/") + "/"):
                if action == "fs.read" or f["mode"] == "rw":
                    return ""
                ro_hit = True
        if ro_hit:
            return f"{real} is read-only for this executor"
        return f"{real} is outside this executor's folders"
    if action == "net.fetch" and resource not in ("net:*", "net:"):
        url = resource[4:]
        web = s["web"]
        if web == "none":
            return "this executor has no web access"
        if isinstance(web, list) and not any(fnmatch.fnmatchcase(url, w) for w in web):
            return f"{url} is not one of this executor's web addresses"
    return ""


def tools_allowed(spec: dict, names: list[str]) -> list[str]:
    """The subset of tool names these hands can pick up (MCP and plugin tools are
    judged per call by server, so they pass here)."""
    s = normalize(spec)
    if "*" in s["tools"]:
        return list(names)
    return [n for n in names if n.startswith(("mcp_", "ocp_"))
            or any(fnmatch.fnmatchcase(n, p) for p in s["tools"])]

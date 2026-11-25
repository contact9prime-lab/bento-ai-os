"""Bring the connectors set up in Claude into Bento, where every call is gated.

Asked for as "Claude is just the middleware … what it needs to act on is what Bento should be
controlling" and "Bento is the ultimate truth for execution if executed from its environment".
A connector added at claude.ai (Supermetrics, Gmail, Canva…) was reachable from a Bento chat
on Claude Code and from nowhere else, and its calls never passed Bento's vault, permissions,
ethics or ledger. So every Claude Code run Bento starts is now `--strict-mcp-config` (measured
on 2.1.331: without it the claude.ai connectors load a few seconds in; with it, none do), and
this module is the way to carry each one across: read the list, then add each server to
Bento's own `mcp_servers`, where a sign-in is Bento's and its tokens are in Bento's vault.

Three rules:
- **Names and addresses only.** `claude mcp list` prints them; Claude's own sign-ins are not
  readable here and are never asked for. Each server is signed in to again, in Bento.
- **An address that carries a secret goes into the vault** (`private`): some connectors are a
  URL with a token in its path or query (a personal server, a CRM's per-user address). Config
  holds `vault:mcp.<key>.url`, mcp_client opens it at connect time, and every listing masks it.
- **A program is not brought in.** A local server is a command that runs on this machine;
  adding one is the MCP app's own form (or install_mcp_server's card), where the command is
  shown before it runs. It is listed with that sentence, never added silently.

Stdlib only, no HTTP or asyncio, so `bento mcp claude` and the route share it.
"""

from __future__ import annotations

import re
import subprocess
from urllib.parse import urlsplit, urlunsplit

LIST_TIMEOUT_S = 90       # `claude mcp list` checks each server's health; 17 took ~10 s here

_LINE = re.compile(r"^(?P<name>[^\n:]+?): (?P<target>\S.*?) - (?P<status>.+)$")
_KIND = re.compile(r"\s+\((?:HTTP|SSE|stdio)\)$", re.I)
# A path segment or query value long and random enough to be a credential.
_SECRETISH = re.compile(r"^(?=.*[0-9])(?=.*[A-Za-z])[A-Za-z0-9_\-]{20,}$")


def key_of(name: str) -> str:
    """A server name for Bento's config: lower case words joined by dashes."""
    k = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("claude.ai ", "")).strip("-")
    return k[:40] or "server"


def private(url: str) -> bool:
    """Does this address carry a secret of its own (a token in the path or the query)?"""
    u = urlsplit(url)
    if u.query or u.username or u.password:
        return True
    # a personal host (Zoho's is <person>-mcp-claude-<number>.zohomcp.in) is an address too
    return any(_SECRETISH.match(seg) for seg in u.path.split("/") + (u.hostname or "").split(".") if seg)


def masked(url: str) -> str:
    """The address as it may be shown: secret-looking parts replaced, no query, no user."""
    u = urlsplit(url)
    path = "/".join("…" if _SECRETISH.match(s) else s for s in u.path.split("/"))
    host = ".".join("…" if _SECRETISH.match(s) else s for s in (u.hostname or "").split("."))
    return urlunsplit((u.scheme, host, path, "", ""))


def parse(text: str) -> list[dict]:
    """`claude mcp list`'s lines as items. Lines that aren't a server are skipped."""
    out = []
    for line in (text or "").splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        name, target, status = m["name"].strip(), _KIND.sub("", m["target"].strip()), m["status"].strip()
        is_url = target.startswith(("https://", "http://"))
        st = ("connected" if "✔" in status or "Connected" in status else
              "needs-auth" if "authentication" in status.lower() else "failed")
        out.append({"name": name.replace("claude.ai ", "", 1), "from": "claude.ai" if name.startswith("claude.ai ")
                    else "claude-code", "kind": "url" if is_url else "program", "url": target if is_url else "",
                    "command": "" if is_url else target, "claude_status": st})
    return out


def listed(run=subprocess.run) -> dict:
    """What Claude Code has, read from its own CLI on this machine. {"ok", "items", "why"}."""
    from . import executors
    exe = executors._find_bin(("claude",))
    if not exe:
        return {"ok": False, "items": [], "why": "Claude Code isn't installed on this machine."}
    try:
        r = run([exe, "mcp", "list"], capture_output=True, text=True, timeout=LIST_TIMEOUT_S,
                env=executors.child_env("claude-code"), cwd="/")
    except subprocess.TimeoutExpired:
        return {"ok": False, "items": [], "why": "Claude Code took too long to list its connectors."}
    except OSError as e:
        return {"ok": False, "items": [], "why": f"Claude Code couldn't be asked: {e}"}
    items = parse(r.stdout)
    if not items and r.returncode:
        return {"ok": False, "items": [], "why": (r.stderr or r.stdout or "it gave no answer").strip()[:300]}
    return {"ok": True, "items": items, "why": ""}


def plan(items: list[dict], have: dict) -> list[dict]:
    """Each item with what bringing it in would do: `state` is ready, in-bento, program or
    not-answering, and `why` says it in words. `have` is the account's `mcp_servers`."""
    from . import mcp_catalog
    curated = {c["remote_url"].rstrip("/"): c["key"] for c in mcp_catalog.all_candidates()}
    have_urls = {str((c or {}).get("url") or "").rstrip("/"): k for k, c in (have or {}).items()}
    out, used = [], set(have or {})
    for it in items:
        it = dict(it)
        url = it["url"].rstrip("/")
        it["private"] = bool(url) and private(url)
        it["shown"] = masked(url) if url else it["command"][:80]
        it["key"] = curated.get(url) or key_of(it["name"])
        if url and url in have_urls:
            it.update(state="in-bento", key=have_urls[url], why="Already connected in Bento.")
        elif it["kind"] == "program":
            it.update(state="program", why="Runs a program on this machine. Add it in MCP Servers, where the "
                                           "command is shown before it runs.")
        elif url.endswith("/sse"):
            it.update(state="not-answering", why="Uses the older SSE connection, which Bento doesn't speak.")
        elif it["claude_status"] == "failed":
            it.update(state="not-answering", why="Doesn't answer in Claude either right now.")
        else:
            while it["key"] in used:
                it["key"] = it["key"] + "-2"
            it.update(state="ready", why=("Its address holds a private token, so it goes into your vault."
                                          if it["private"] else "Sign in once in your browser."))
        used.add(it["key"])
        out.append(it)
    return out


def conf_for(item: dict) -> dict:
    """Bento's config for one ready item. A private address is put in the vault here."""
    conf: dict = {"transport": "http", "enabled": True, "from": "claude"}
    if item.get("private"):
        from . import vault
        conf["url"] = vault.put(f"mcp.{item['key']}.url", item["url"])
    else:
        conf["url"] = item["url"]
        conf["auth"] = "oauth"
    return conf


def bring(cfg: dict, store, keys: list[str] | None, items: list[dict]) -> dict:
    """Add the ready items named by `keys` (None = every ready one) to `cfg['mcp_servers']`.
    The caller has checked who is asking, saves the config and reloads the servers."""
    from . import mcp_client
    servers = cfg.setdefault("mcp_servers", {})
    added, skipped = [], []
    for it in plan(items, servers):
        if keys is not None and it["key"] not in keys and it["name"] not in keys:
            continue
        if it["state"] != "ready":
            skipped.append({"key": it["key"], "name": it["name"], "why": it["why"]})
            continue
        conf = conf_for(it)
        why = mcp_client.refusal({**conf, "url": it["url"]})
        if why:
            skipped.append({"key": it["key"], "name": it["name"], "why": why})
            continue
        servers[it["key"]] = conf
        try:
            store.mcp_reg_upsert(it["key"], title=it["name"], source="claude", origin=it["shown"],
                                 status="installed")
        except Exception:
            pass
        added.append({"key": it["key"], "name": it["name"], "oauth": conf.get("auth") == "oauth"})
    return {"added": added, "skipped": skipped}

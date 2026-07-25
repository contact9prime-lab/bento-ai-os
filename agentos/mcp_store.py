"""MCP discovery store: find MCP servers published to the public MCP registry,
turn them into AgentOS server configs, record every install in the local MCP
Registry (mcp_registry table), and generate documentation for each one.

The store never installs silently — discovery returns candidates, and installing
is a separate, user-consented step (an approval-gated tool call from the agent,
or an explicit click in the Store app).
"""

import asyncio
import json
import re
import time
from pathlib import Path

import httpx

from . import config as cfgmod

# The official community registry (registry.modelcontextprotocol.io, v0 API).
REGISTRY_API = "https://registry.modelcontextprotocol.io/v0/servers"
USER_DOCS_DIR = cfgmod.AGENTOS_HOME / "docs"

# The public API routinely takes 15-25s PER REQUEST, so live queries are unusable for
# as-you-type search. Instead the whole catalog is synced into a local index in the
# background (saved progressively, page by page) and searches run locally in ~0ms.
INDEX_PATH = cfgmod.AGENTOS_HOME / "mcp_index.json"
INDEX_TTL = 24 * 3600          # refresh the catalog daily
PAGE_LIMIT = 100
MAX_PAGES = 300                # safety backstop, far above the registry's real size

_slug_rx = re.compile(r"[^a-z0-9-]+")


def _slug(name: str) -> str:
    """'io.github.owner/repo-mcp' -> 'repo-mcp' — a friendly local config key."""
    tail = (name or "").split("/")[-1] or name or "server"
    return _slug_rx.sub("-", tail.lower()).strip("-")[:40] or "server"


def _get(d: dict, *keys, default=None):
    """Tolerant field access: the registry has shipped both snake_case and camelCase."""
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def _normalize(item: dict) -> dict:
    """One public-registry entry -> a flat candidate the UI/agent can reason about."""
    srv = item.get("server") if isinstance(item.get("server"), dict) else item
    name = srv.get("name", "")
    packages = srv.get("packages") or []
    remotes = srv.get("remotes") or []
    pkg = packages[0] if packages else {}
    env_vars = []
    for ev in (_get(pkg, "environment_variables", "environmentVariables", default=[]) or []):
        if isinstance(ev, dict) and ev.get("name"):
            env_vars.append({"name": ev["name"],
                             "required": bool(_get(ev, "is_required", "isRequired", default=False)),
                             "secret": bool(_get(ev, "is_secret", "isSecret", default=False)),
                             "description": ev.get("description", "")})
    repo = srv.get("repository") or {}
    remote = next((r for r in remotes if r.get("url")), {})
    headers = []
    for h in (remote.get("headers") or []):
        if isinstance(h, dict) and h.get("name"):
            headers.append({"name": h["name"], "value": h.get("value", ""),
                            "required": bool(_get(h, "is_required", "isRequired", default=False)),
                            "secret": bool(_get(h, "is_secret", "isSecret", default=False)),
                            "description": h.get("description", "")})
    return {
        "key": _slug(name),
        "registry_name": name,
        "description": (srv.get("description") or "").strip(),
        "version": _get(srv, "version", "versionDetail", default="") or "",
        "homepage": repo.get("url", "") if isinstance(repo, dict) else "",
        "registry_type": _get(pkg, "registry_type", "registryType", default=""),
        "identifier": _get(pkg, "identifier", "name", default=""),
        "runtime_hint": _get(pkg, "runtime_hint", "runtimeHint", default=""),
        "remote_url": remote.get("url", ""),
        "remote_type": remote.get("type", ""),
        "remote_headers": headers,
        "env": env_vars,
    }


async def search(query: str, limit: int = 20) -> list[dict]:
    """Search the public MCP registry UPSTREAM (slow: the API takes 15-25s). Only used
    as a fallback while the local index is still empty — everything else goes through
    search_local()."""
    params = {"limit": max(1, min(int(limit), 50))}
    if (query or "").strip():
        params["search"] = query.strip()
    async with httpx.AsyncClient(timeout=40, follow_redirects=True,
                                 headers={"User-Agent": "AgentOS/0.1"}) as client:
        r = await client.get(REGISTRY_API, params=params)
    r.raise_for_status()
    data = r.json()
    items = data.get("servers") or data.get("data") or []
    out, seen = [], set()
    for it in items:
        c = _normalize(it)
        if not (c["registry_name"] and (c["identifier"] or c["remote_url"])):
            continue
        if c["registry_name"] in seen:  # the registry lists every published version
            continue
        seen.add(c["registry_name"])
        out.append(c)
    return out


# ---- local index: background sync + instant search ------------------------------

_index: dict | None = None      # {"updated_at": ts, "complete": bool, "servers": [...]}
_syncing = False


def _load_index() -> dict:
    global _index
    if _index is None:
        try:
            _index = json.loads(INDEX_PATH.read_text())
            assert isinstance(_index.get("servers"), list)
        except Exception:
            _index = {"updated_at": 0.0, "complete": False, "servers": []}
    return _index


def _save_index(idx: dict):
    global _index
    _index = idx
    try:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        INDEX_PATH.write_text(json.dumps(idx))
    except Exception:
        pass  # in-memory index still works this session


def index_status() -> dict:
    idx = _load_index()
    return {"count": len(idx["servers"]), "complete": bool(idx.get("complete")),
            "syncing": _syncing, "updated_at": idx.get("updated_at", 0)}


def ensure_index(store=None) -> bool:
    """Kick off a background catalog sync if the index is missing, incomplete, or
    stale. Returns True when a sync was started. Safe to call on every search."""
    idx = _load_index()
    stale = time.time() - (idx.get("updated_at") or 0) > INDEX_TTL
    if _syncing or (idx.get("complete") and not stale):
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False  # no loop (tests / sync context): searches fall back upstream
    asyncio.create_task(_sync_index(store))
    return True


async def _sync_index(store=None):
    """Page the whole public catalog into the local index. Each page is saved as it
    arrives, so searches see a growing index instead of waiting minutes for the end."""
    global _syncing
    if _syncing:
        return
    _syncing = True
    servers, seen, cursor, pages = [], set(), None, 0
    try:
        if store:
            store.log("system", "mcp index: sync started (public registry is slow — "
                                "results appear as pages arrive)")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True,
                                     headers={"User-Agent": "AgentOS/0.1"}) as client:
            while pages < MAX_PAGES:
                # version=latest collapses the per-version listing server-side:
                # 100 unique servers per page instead of ~20 after local dedupe
                params = {"limit": PAGE_LIMIT, "version": "latest"}
                if cursor:
                    params["cursor"] = cursor
                r = await client.get(REGISTRY_API, params=params)
                r.raise_for_status()
                data = r.json()
                for it in (data.get("servers") or data.get("data") or []):
                    c = _normalize(it)
                    if (c["registry_name"] and (c["identifier"] or c["remote_url"])
                            and c["registry_name"] not in seen):
                        seen.add(c["registry_name"])
                        servers.append(c)
                pages += 1
                _save_index({"updated_at": time.time(), "complete": False,
                             "servers": servers})
                meta = data.get("metadata") or {}
                cursor = meta.get("nextCursor") or meta.get("next_cursor")
                if not cursor:
                    break
        _save_index({"updated_at": time.time(), "complete": True, "servers": servers})
        if store:
            store.log("system", f"mcp index: synced {len(servers)} servers "
                                f"({pages} pages)")
    except Exception as e:
        # keep whatever was indexed; the next ensure_index() retries
        if store:
            store.log("error", f"mcp index sync failed after {pages} pages: "
                               f"{type(e).__name__}: {e}"[:300])
    finally:
        _syncing = False


def search_local(query: str, limit: int = 30) -> list[dict]:
    """Instant search over the local index: every query word must appear in the
    name+description; exact/prefix name matches rank first."""
    idx = _load_index()
    q = (query or "").strip().lower()
    words = q.split()
    scored = []
    for c in idx["servers"]:
        hay = (c["registry_name"] + " " + (c.get("description") or "")).lower()
        if not all(w in hay for w in words):
            continue
        name = c["registry_name"].lower()
        tail = name.split("/")[-1]
        score = (0 if tail == q else
                 1 if q and tail.startswith(q) else
                 2 if q and q in tail else
                 3 if q and q in name else 4)
        scored.append((score, c))
    scored.sort(key=lambda t: (t[0], t[1]["registry_name"]))
    return [c for _, c in scored[:max(1, int(limit))]]


# ---- deep discovery: when the registry isn't enough, widen the net ---------------
#
# The public registry misses plenty of real servers. Deep discovery sweeps npm and
# GitHub for MCP servers matching the query: npm hits become normally-installable
# candidates (registry_name "npm:<pkg>"); repo-only hits can't be auto-derived, so
# they're flagged agentic=True — the agent reads the repo and configures the server
# itself (add_mcp_server) with the user in the loop.

NPM_SEARCH = "https://registry.npmjs.org/-/v1/search"
GITHUB_SEARCH = "https://api.github.com/search/repositories"


def _npm_candidates(data: dict, query: str) -> list[dict]:
    """Parse an npm search response into candidates — only packages that plausibly
    ARE MCP servers (name/keywords say so), not everything mentioning the word."""
    out = []
    q = (query or "").lower()
    for o in data.get("objects") or []:
        pkg = o.get("package") or {}
        name = pkg.get("name", "")
        kw = [k.lower() for k in (pkg.get("keywords") or [])]
        namehit = "mcp" in name.lower() or "modelcontextprotocol" in name.lower()
        if not (namehit or "mcp" in kw or "model-context-protocol" in kw):
            continue
        hay = (name + " " + (pkg.get("description") or "") + " " + " ".join(kw)).lower()
        if q and not all(w in hay for w in q.split()):
            continue
        links = pkg.get("links") or {}
        out.append({
            "key": _slug(name),
            "registry_name": f"npm:{name}",
            "description": (pkg.get("description") or "").strip(),
            "version": pkg.get("version", ""),
            "homepage": links.get("repository") or links.get("homepage") or links.get("npm", ""),
            "registry_type": "npm", "identifier": name, "runtime_hint": "",
            "remote_url": "", "remote_type": "", "remote_headers": [], "env": [],
            "origin_source": "npm",
        })
    return out


def _github_candidates(data: dict) -> list[dict]:
    """Parse a GitHub repo search into agentic candidates: no package to run directly,
    so the agent has to read the repo and derive the config."""
    out = []
    for repo in data.get("items") or []:
        full = repo.get("full_name", "")
        if not full or repo.get("archived"):
            continue
        stars = repo.get("stargazers_count", 0)
        out.append({
            "key": _slug(full.split("/")[-1]),
            "registry_name": f"github:{full}",
            "description": ((repo.get("description") or "").strip()
                            + (f" · ★{stars}" if stars else "")).strip(" ·"),
            "version": "", "homepage": repo.get("html_url", ""),
            "registry_type": "", "identifier": "", "runtime_hint": "",
            "remote_url": "", "remote_type": "", "remote_headers": [], "env": [],
            "origin_source": "github", "agentic": True,
        })
    return out


async def search_deep(query: str, limit: int = 12,
                      exclude: set[str] | None = None) -> list[dict]:
    """Widen discovery beyond the registry: npm + GitHub, swept in parallel and
    deduped (against each other and against `exclude` — the identifiers/repos the
    registry already returned). Best-effort per source: one failing doesn't kill it."""
    q = (query or "").strip()
    if not q:
        return []
    exclude = {e.lower() for e in (exclude or set())}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": "AgentOS/0.1"}) as client:
        async def npm():
            r = await client.get(NPM_SEARCH, params={"text": f"mcp {q}", "size": 25})
            r.raise_for_status()
            return _npm_candidates(r.json(), q)

        async def github():
            r = await client.get(GITHUB_SEARCH,
                                 params={"q": f"mcp server {q} in:name,description,topics",
                                         "sort": "stars", "per_page": 10})
            r.raise_for_status()
            return _github_candidates(r.json())

        results = await asyncio.gather(npm(), github(), return_exceptions=True)
    out, seen = [], set(exclude)
    for group in results:
        if isinstance(group, BaseException):
            continue
        for c in group:
            # an npm hit and a github hit for the same project collapse on repo URL;
            # registry overlap collapses on the npm identifier
            keys = {c["registry_name"].lower()}
            if c.get("identifier"):
                keys.add(c["identifier"].lower())
            if c.get("homepage"):
                keys.add(c["homepage"].lower().rstrip("/"))
            if keys & seen:
                continue
            seen |= keys
            out.append(c)
    # runnable packages before repos-needing-the-agent; within each group keep the
    # source ranking (GitHub results arrive star-sorted — stable sort preserves that)
    out.sort(key=lambda c: bool(c.get("agentic")))
    return out[:max(1, int(limit))]


async def search_any(query: str, limit: int = 30, store=None) -> list[dict]:
    """The search everything should use: local index when it has anything (instant),
    upstream only as a first-run fallback. Always nudges the background sync."""
    ensure_index(store)
    if index_status()["count"]:
        return search_local(query, limit=limit)
    return await search(query, limit=min(int(limit), 50))


async def lookup(registry_name: str, store=None) -> dict | None:
    """Resolve an installable candidate by name: an exact public-registry name, or a
    deep-discovery 'npm:<package>' (verified against the npm registry at install time)."""
    name = (registry_name or "").strip()
    if name.startswith("npm:"):
        pkg = name[4:].strip()
        async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                     headers={"User-Agent": "AgentOS/0.1"}) as client:
            r = await client.get(f"https://registry.npmjs.org/{pkg}/latest")
        if r.status_code != 200:
            return None
        meta = r.json()
        repo = meta.get("repository") or {}
        home = (repo.get("url", "") if isinstance(repo, dict) else str(repo)) \
            .removeprefix("git+").removesuffix(".git") or meta.get("homepage", "")
        return {"key": _slug(pkg), "registry_name": name,
                "description": (meta.get("description") or "").strip(),
                "version": meta.get("version", ""), "homepage": home,
                "registry_type": "npm", "identifier": pkg, "runtime_hint": "",
                "remote_url": "", "remote_type": "", "remote_headers": [], "env": []}
    for c in _load_index()["servers"]:
        if c["registry_name"] == name:
            return c
    for c in await search(name, limit=50):  # not indexed (yet) — ask upstream
        if c["registry_name"] == name:
            return c
    return None


def to_conf(cand: dict, env_values: dict | None = None) -> tuple[dict, list[str]]:
    """Derive an AgentOS mcp_servers config from a candidate.
    Returns (conf, missing_env): missing_env lists required keys the user must still
    fill in — the server is written disabled until they do."""
    env_values = env_values or {}
    conf: dict
    missing: list[str] = []
    if cand.get("remote_url"):
        conf = {"transport": "http", "url": cand["remote_url"]}
        headers = {}
        for h in cand.get("remote_headers", []):
            tpl = h.get("value") or "{" + h["name"] + "}"
            # '{smithery_api_key}'-style variables become fillable placeholders,
            # substituted from env_values when the user already supplied them
            vars_ = re.findall(r"\{([\w.-]+)\}", tpl)
            val = tpl
            for v in vars_:
                sub = str(env_values.get(v, "") or env_values.get(h["name"], "")).strip()
                val = val.replace("{" + v + "}", sub or f"<YOUR_{v}>")
            headers[h["name"]] = val
            if "<YOUR_" in val and h.get("required"):
                missing += [v for v in vars_ if f"<YOUR_{v}>" in val]
        if headers:
            conf["headers"] = headers
    else:
        rt = cand.get("registry_type", "")
        ident = cand.get("identifier", "")
        hint = cand.get("runtime_hint", "")
        if rt == "npm":
            conf = {"transport": "stdio", "command": hint or "npx", "args": f"-y {ident}"}
        elif rt == "pypi":
            conf = {"transport": "stdio", "command": hint or "uvx", "args": ident}
        elif rt == "oci":
            conf = {"transport": "stdio", "command": "docker", "args": f"run -i --rm {ident}"}
        else:  # unknown package type: fall back to the runtime hint verbatim
            conf = {"transport": "stdio", "command": hint or ident, "args": ""}
    env = {}
    for ev in cand.get("env", []):
        val = str(env_values.get(ev["name"], "")).strip()
        if val:
            env[ev["name"]] = val
        else:
            env[ev["name"]] = f"<YOUR_{ev['name']}>"
            if ev.get("required"):
                missing.append(ev["name"])
    if env:
        conf["env"] = env
    conf["enabled"] = not missing
    return conf, missing


def package_info(cand: dict) -> dict:
    """What the registry row remembers about how this server is obtained/run."""
    return {k: cand.get(k, "") for k in
            ("registry_type", "identifier", "runtime_hint", "remote_url", "remote_type",
             "version")} | {"env": cand.get("env", []),
                            "remote_headers": cand.get("remote_headers", [])}


# ---------------------------------------------------------------------------
# Documentation: every registry entry gets a generated manual page, served into
# the Docs app alongside the built-in manual.
# ---------------------------------------------------------------------------

def write_doc(name: str, reg: dict, conf: dict | None = None,
              live: dict | None = None) -> str:
    """Generate (or refresh) the markdown doc for one registry entry. Returns the
    doc path relative to the user docs dir (e.g. 'mcp/github.md')."""
    conf = conf or {}
    live = live or {}
    lines = [f"# MCP: {reg.get('title') or name}", ""]
    if reg.get("description"):
        lines += [reg["description"], ""]
    lines += ["## At a glance", "",
              f"- **Local name:** `{name}` — tools appear to the agent as `mcp_{name}_*`",
              f"- **Source:** {reg.get('source') or 'manual'}"
              + (f" · discovered from `{reg['origin']}`" if reg.get("origin") else ""),
              f"- **Status:** {live.get('status') or reg.get('status') or 'installed'}"]
    if reg.get("homepage"):
        lines.append(f"- **Homepage:** {reg['homepage']}")
    pkg = reg.get("package") or {}
    if pkg.get("identifier"):
        lines.append(f"- **Package:** `{pkg['identifier']}` ({pkg.get('registry_type') or '?'}"
                     + (f", v{pkg['version']}" if pkg.get("version") else "") + ")")
    if pkg.get("remote_url"):
        lines.append(f"- **Remote:** {pkg['remote_url']} ({pkg.get('remote_type') or 'http'})")
    lines.append("")
    run = conf.get("url") or " ".join(
        x for x in (conf.get("command", ""), conf.get("args", "")) if x)
    if run:
        lines += ["## How it runs", "", f"```\n{run}\n```", ""]
    env_specs = pkg.get("env") or []
    if env_specs or conf.get("env"):
        lines += ["## Configuration", "",
                  "Set these in the MCP app (Settings → MCP Servers) — placeholders like "
                  "`<YOUR_KEY>` must be replaced before the server is enabled:", ""]
        specs = {e.get("name"): e for e in env_specs if isinstance(e, dict)}
        for k in (conf.get("env") or {k: {} for k in specs}):
            s = specs.get(k, {})
            note = " *(required)*" if s.get("required") else ""
            note += " · secret" if s.get("secret") else ""
            desc = f" — {s['description']}" if s.get("description") else ""
            lines.append(f"- `{k}`{note}{desc}")
        lines.append("")
    tools = live.get("tools") or []
    if tools:
        lines += ["## Tools", ""]
        for t in tools:
            desc = (t.get("description") or "").split("\n")[0][:160]
            lines.append(f"- **`{t.get('name')}`**" + (f" — {desc}" if desc else ""))
        lines.append("")
    if live.get("instructions"):
        lines += ["## Usage notes (from the server)", "", live["instructions"][:2000], ""]
    lines += ["## Permissions", "",
              "Calls to this server are governed by the permission framework: the action is "
              f"`mcp.use` on resources `mcp:{name}/<tool>`. The main agent asks for approval "
              "on first use (\"allow & remember\" writes a grant); apps must declare "
              f"`mcp.use` / `mcp:{name}/*` in their manifest, and every grant can be scoped "
              "to IO surfaces (GUI, TUI, Telegram) in the Permissions app.", "",
              f"*Generated by AgentOS on {time.strftime('%Y-%m-%d %H:%M')}.*", ""]
    rel = f"mcp/{name}.md"
    p = USER_DOCS_DIR / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines))
    return rel


def delete_doc(rel: str):
    if not rel:
        return
    p = (USER_DOCS_DIR / rel).resolve()
    if str(p).startswith(str(USER_DOCS_DIR.resolve())) and p.is_file():
        p.unlink(missing_ok=True)


def record_install(store, name: str, *, title: str = "", description: str = "",
                   source: str = "manual", origin: str = "", package: dict | None = None,
                   homepage: str = "", conf: dict | None = None, live: dict | None = None):
    """Upsert the registry row for an installed server and (re)generate its doc.
    The single entry point every install path goes through — Store UI, agent tools,
    package imports — so the MCP Registry stays complete."""
    store.mcp_reg_upsert(name, title=title, description=description, source=source,
                         origin=origin, package=package, homepage=homepage,
                         status="installed")
    reg = store.mcp_reg_get(name) or {}
    try:
        rel = write_doc(name, reg, conf=conf, live=live)
        store.mcp_reg_upsert(name, doc_file=rel)
    except Exception as e:  # docs are best-effort; never fail an install over them
        store.log("error", f"mcp doc generation failed for '{name}': {e}"[:300])


def refresh_doc(store, name: str, conf: dict | None = None, live: dict | None = None) -> bool:
    """Regenerate one entry's doc (e.g. once the server connects and its tools are known)."""
    reg = store.mcp_reg_get(name)
    if not reg:
        return False
    rel = write_doc(name, reg, conf=conf, live=live)
    store.mcp_reg_upsert(name, doc_file=rel)
    return True

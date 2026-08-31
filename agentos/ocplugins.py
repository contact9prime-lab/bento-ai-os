"""OpenClaw plugins, installed through this OS's review — scan, consent, hold.

OpenClaw is already an EXECUTOR here (`executors.py`): if the `openclaw` CLI is on
the PATH, AgentOS hands it turns. What it could not do was extend it. OpenClaw's
own extension surface is plugins — tools, providers, channels, hooks, MCP servers
— and the way you get one is `openclaw plugins install <spec>`, which is a
sentence a person types into a terminal that this OS never sees.

That is the gap. A plugin is third-party code that runs beside the agent this
machine answers with, and every other way code arrives here — an app from the
store, an MCP server, a flow — goes past a scan, a consent screen, a grant and a
quarantine. Plugins should not be the one door with no lock on it just because
somebody else's CLI owns the door.

So this module is that door, and it is deliberately NOT a reimplementation of
OpenClaw's plugin system. It shells out to the real `openclaw plugins ...` verbs
for everything OpenClaw owns — resolution, download, dependency install, the
manifest registry — and adds the four things this OS has that OpenClaw's install
path does not know about:

    scan        this machine re-reads the plugin's own `openclaw.plugin.json`
                off disk and says what enabling it would let it reach. Same
                shape, same severities and the same `verdict_of` as the app
                registry, because a second definition of "is this alarming?"
                is how one of them stops being read.
    consent     `preview()` is the screen, and `enable()` is the save. They run
                ONE computation (`capabilities` + `declared_grants`), for the
                same reason jobs.py insists on it: describing a permission
                separately from granting it is how the sentence somebody agreed
                to stops matching the permission they got.
    grants      real `grants` rows, `source='openclaw-plugin'`,
                `source_ref='ocplugin:<id>'` — the same provenance shape flow
                definitions use, so the Permissions app lists them, and revoking
                one is not a note in a file: `reconcile()` turns a revoked grant
                back into `openclaw plugins disable <id>` plus a `plugins.deny`
                entry, which OpenClaw itself enforces.
    quarantine  `principal_kind='ocplugin'` in the existing quarantine table, so
                a held plugin appears in the same list, with the same
                once/forever/deleted release, as a runaway app.

WHAT THIS DOES NOT DO, said plainly because the honesty rules require it and
because pretending otherwise would be worse than having nothing: an OpenClaw
plugin runs inside OpenClaw's own process. Its individual calls do not pass
through this PDP and AgentOS cannot gate them one at a time the way it gates an
app's `appTool`. What AgentOS gates is the LIFECYCLE — install, enable, update,
uninstall — and what it enforces afterwards is enablement, through the one lever
OpenClaw documents as absolute: `plugins.deny` wins over allow and over
per-plugin enablement. That is a real boundary and it is the whole of it.
`docs/openclaw-plugins.md` says the same thing to a user.

INSTALL LEAVES IT DISABLED, and that is the load-bearing decision here. Scanning
a package before it exists would mean re-implementing OpenClaw's resolver for
npm, ClawHub, git, archives and marketplaces — five ways to be subtly wrong about
which bytes are about to land. Instead the bytes land first, disabled, and the
scan reads the real manifest on disk. This is the same rule flows already run on
("a disabled flow holds nothing — Enable is the act of granting"), which is the
strongest argument for it: one idea, twice, rather than two half-ideas.

Facts about OpenClaw pinned here come from its own documentation (`docs/cli/
plugins.md`, `docs/plugins/manifest.md`, `docs/tools/plugin.md` in the openclaw
repository). What is NOT pinned is the exact shape of `--json` output: that is
not documented field-by-field, so every reader below is tolerant — it accepts the
plausible key spellings and degrades to an empty answer rather than raising. A
plugin surface that crashes on an unfamiliar key is worse than one that says it
could not read the list.

HTTP-free and asyncio-free on purpose, like `jobs.py` and `appregistry.py`: the
same catalogue has to work from `bento openclaw` on a headless Pi with the server
down, and the server reaches it through `asyncio.to_thread`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

# ONE definition of "how bad is this?", shared with the app registry. Two copies
# would drift, and the half that drifted would be whichever one nobody demoed.
from .appregistry import verdict_of

#: The manifest a native OpenClaw plugin ships at its root. Bundle-format plugins
#: (`Format: bundle` in `plugins list`) carry their own manifest instead; those are
#: scanned on what we can read and SAY so, rather than reported as clean.
MANIFEST_NAME = "openclaw.plugin.json"

#: Where OpenClaw keeps installed plugins. Both are documented; the state dir wins
#: when `OPENCLAW_STATE_DIR` is set, which is how a container deployment moves it.
def state_dir() -> Path:
    return Path(os.environ.get("OPENCLAW_STATE_DIR")
                or os.path.expanduser("~/.openclaw")).expanduser()


def extensions_root() -> Path:
    return state_dir() / "extensions"


#: Grant provenance. Mirrors `flows.DEFINITION_SOURCE` deliberately: one filter
#: (`source` + `source_ref`) is what lets reconciliation regenerate its own rows
#: without ever touching one a person wrote by hand.
GRANT_SOURCE = "openclaw-plugin"
PRINCIPAL_KIND = "ocplugin"


def source_ref(pid: str) -> str:
    return f"ocplugin:{(pid or '').strip().lower()}"


TIMEOUT_READ = 30.0        # list / inspect / doctor — local, but node starts slowly
TIMEOUT_SEARCH = 45.0      # ClawHub, over the network
TIMEOUT_INSTALL = 900.0    # npm dependency install on a Pi's SD card


# ---------------------------------------------------------------------------
# Is OpenClaw here at all
# ---------------------------------------------------------------------------

def cli() -> str:
    """The `openclaw` executable, resolved over the EXTENDED path.

    `shutil.which` alone is the wrong question for a server started by systemd or
    a LaunchAgent — neither sources a login shell, so ~/.local/bin is simply
    absent. `executors._find_bin` already solved this once; use it rather than
    solving it differently here.
    """
    try:
        from .executors import _find_bin
        found = _find_bin(("openclaw",))
        if found:
            return found
    except Exception:                                              # noqa: BLE001
        pass
    return shutil.which("openclaw") or ""


def available() -> bool:
    return bool(cli())


def problem() -> str:
    """'' if plugins can be managed here, else the sentence saying why not.

    The sentence names the component and stops. AgentOS does not ship an OpenClaw
    installer — `executors.EXECUTOR_CATALOGUE` records the same refusal for the
    same reason — so this must not end in a command we made up.
    """
    if available():
        return ""
    return ("OpenClaw is not installed here. AgentOS uses the `openclaw` CLI if it is on "
            "your PATH and deliberately does not install it for you — install it yourself "
            "and this surface comes to life.")


# ---------------------------------------------------------------------------
# Where a plugin comes from, and whether that is a source OpenClaw itself trusts
# ---------------------------------------------------------------------------
# OpenClaw's own rule: ClawHub packages and its bundled/official catalog are
# trusted install sources; an arbitrary npm, npm-pack, git, local path/archive or
# marketplace source warns and asks before continuing, and a non-interactive
# install of one must pass `--force` after the person has reviewed it.
#
# AgentOS mirrors that judgement rather than inventing a second one, and passes
# `--force` ONLY when the user has actually been shown the source and said yes.
# `--force` travelling with every install would quietly answer OpenClaw's own
# provenance question on the user's behalf, which is the whole thing it exists
# to ask.

_SPEC_SCHEMES = ("clawhub:", "npm:", "npm-pack:", "git:")


def parse_spec(spec: str) -> dict:
    """What kind of source this is, in the terms the consent screen needs.

    Returns {spec, scheme, package, ref, trusted, origin} where `trusted` is
    OpenClaw's notion of a trusted source, not ours — see above.
    """
    s = (spec or "").strip()
    out = {"spec": s, "scheme": "", "package": s, "ref": "", "trusted": False, "origin": ""}
    if not s:
        return out
    for sch in _SPEC_SCHEMES:
        if s.lower().startswith(sch):
            out["scheme"] = sch[:-1]
            out["package"] = s[len(sch):]
            break
    else:
        # A local path or archive is anything that exists on disk, or looks like one.
        if s.startswith((".", "/", "~")) or Path(os.path.expanduser(s)).exists():
            out["scheme"] = "path"
        elif "@" in s[1:] and not s.startswith("@") and _looks_like_marketplace(s):
            out["scheme"] = "marketplace"
            out["package"], _, out["market"] = s.partition("@")
        else:
            # A bare name. OpenClaw resolves it against its official catalog first
            # and falls back to npm — so this is trusted only when it names an
            # official package, which we cannot know from the string alone. Say
            # npm, which is the cautious half of a genuine ambiguity.
            out["scheme"] = "npm"

    pkg = out["package"]
    if out["scheme"] in ("clawhub", "npm") and "@" in pkg[1:]:
        out["package"], _, out["ref"] = pkg.rpartition("@")
    if out["scheme"] == "git":
        for sep in ("@", "#"):
            if sep in pkg.rsplit("/", 1)[-1]:
                base, _, ref = pkg.rpartition(sep)
                if base:
                    out["package"], out["ref"] = base, ref
                break

    out["trusted"] = (out["scheme"] == "clawhub"
                      or out["package"].startswith("@openclaw/"))
    out["origin"] = {
        "clawhub": "ClawHub", "npm": "npm", "npm-pack": "a local npm tarball",
        "git": "a git repository", "path": "a path on this machine",
        "marketplace": f"the '{out.get('market') or '?'}' marketplace",
    }.get(out["scheme"], out["scheme"] or "an unrecognised source")
    return out


def _looks_like_marketplace(s: str) -> bool:
    """`plugin@marketplace` shorthand, distinguished from `pkg@1.2.3`."""
    _, _, tail = s.rpartition("@")
    return bool(tail) and not re.fullmatch(r"[0-9v][\w.\-+]*|latest|beta|rc|dev", tail)


def source_sentence(info: dict) -> str:
    """One line for the consent screen. Says WHERE, and whether that is trusted."""
    if info.get("trusted"):
        return (f"from {info['origin']} — a source OpenClaw treats as trusted, so it "
                f"installs without a provenance warning")
    return (f"from {info['origin']} — OpenClaw does not treat this as a trusted source, "
            f"so installing it is you vouching for {info.get('package') or 'it'}")


# ---------------------------------------------------------------------------
# Talking to the CLI
# ---------------------------------------------------------------------------

def _run(args: list[str], timeout: float, env: dict | None = None) -> tuple[int, str]:
    exe = cli()
    if not exe:
        return 127, problem()
    e = dict(os.environ)
    e.update(env or {})
    # Nothing here is ever interactive: every verb that would prompt is called
    # with the flag that makes it not, and a prompt with nobody in front of it is
    # a hang, not a question. stdin is closed so a missed one fails fast.
    try:
        p = subprocess.run([exe, "plugins", *args], capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL, env=e)
    except subprocess.TimeoutExpired:
        return 1, f"`openclaw plugins {' '.join(args)}` timed out after {int(timeout)}s"
    except Exception as ex:                                        # noqa: BLE001
        return 1, str(ex)
    return p.returncode or 0, (p.stdout or "") + (p.stderr or "")


def _json_run(args: list[str], timeout: float) -> tuple[dict | list | None, str]:
    """Run with --json and parse. Returns (parsed, error_sentence).

    Tolerant on purpose: OpenClaw may print a lifecycle trace or a warning line
    before the object, and the JSON shape is not documented field-by-field. The
    first balanced JSON value in the output is the answer; anything else is an
    honest failure sentence rather than a traceback.
    """
    rc, out = _run([*args, "--json"], timeout)
    for start in (out.find("{"), out.find("[")):
        if start < 0:
            continue
        try:
            parsed, _ = json.JSONDecoder().raw_decode(out[start:])
            return parsed, ""
        except ValueError:
            continue
    tail = (out or "").strip().splitlines()
    return None, (tail[-1][:300] if tail else f"`openclaw plugins {args[0]}` failed (exit {rc})")


def _rows(parsed, *keys: str) -> list[dict]:
    """A list of dicts out of whatever shape came back."""
    if isinstance(parsed, list):
        return [r for r in parsed if isinstance(r, dict)]
    if isinstance(parsed, dict):
        for k in keys:
            v = parsed.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _first(row: dict, *names, default=""):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return default


# ---------------------------------------------------------------------------
# Reading what is installed
# ---------------------------------------------------------------------------

def installed() -> tuple[list[dict], str]:
    """Every plugin OpenClaw knows about here, normalised. (rows, error).

    `plugins list` reads the persisted local registry — it is not a live probe of
    a running Gateway, and this surface must not imply that it is. A plugin whose
    code or enablement changed needs the Gateway restarted before the change is
    real, which `doctor()` and the docs both say.
    """
    if not available():
        return [], problem()
    parsed, err = _json_run(["list"], TIMEOUT_READ)
    if parsed is None:
        return [], err
    out = []
    for r in _rows(parsed, "plugins", "entries", "items"):
        pid = str(_first(r, "id", "pluginId", "name"))
        if not pid:
            continue
        out.append({
            "id": pid,
            "name": str(_first(r, "displayName", "title", "name", default=pid)),
            "version": str(_first(r, "version")),
            "enabled": bool(_first(r, "enabled", "isEnabled", default=False)),
            "format": str(_first(r, "format", default="")),
            "bundled": bool(_first(r, "bundled", "isBundled", default=False)),
            "source": str(_first(r, "source", "spec", "installSpec")),
            "origin": str(_first(r, "origin", "sourceKind")),
            "path": str(_first(r, "path", "dir", "installPath", "root")),
        })
    return sorted(out, key=lambda p: p["id"]), ""


def inspect(pid: str) -> tuple[dict, str]:
    """One plugin's record, WITHOUT `--runtime`.

    `--runtime` imports the plugin's module to list what it registers. That is
    exactly the code the review exists to decide about, so running it to produce
    the review would answer the question by doing the thing. The manifest is a
    static declaration and it is what we read; `contracts.tools` is required to
    match what the runtime registers, so the manifest is not a weaker answer, it
    is the answer that does not execute anything.
    """
    if not available():
        return {}, problem()
    parsed, err = _json_run(["inspect", pid], TIMEOUT_READ)
    if parsed is None:
        return {}, err
    if isinstance(parsed, list):
        parsed = next((r for r in parsed if isinstance(r, dict)
                       and str(_first(r, "id", "pluginId")) == pid), {})
    return parsed if isinstance(parsed, dict) else {}, ""


def _manifest_from(record: dict) -> dict:
    for k in ("manifest", "pluginManifest", "openclawPlugin"):
        v = (record or {}).get(k)
        if isinstance(v, dict):
            return v
    return {}


def manifest_of(pid: str, record: dict | None = None) -> tuple[dict, str]:
    """The plugin's own `openclaw.plugin.json`, read off THIS machine's disk.

    In federation the receiving machine always re-reads the bytes — the same rule
    `appregistry.scan_drift` exists for. An inspect record that already carries the
    manifest is used as-is; otherwise the file is read from the recorded install
    path, and failing that from the extensions root.
    """
    rec = record if record is not None else inspect(pid)[0]
    man = _manifest_from(rec)
    if man:
        return man, ""
    cands = []
    p = str(_first(rec, "path", "dir", "installPath", "root"))
    if p:
        cands.append(Path(p).expanduser() / MANIFEST_NAME)
    cands.append(extensions_root() / pid / MANIFEST_NAME)
    for c in cands:
        try:
            if c.is_file():
                return json.loads(c.read_text()), ""
        except Exception as e:                                     # noqa: BLE001
            return {}, f"{c} could not be read: {e}"
    fmt = str(_first(rec, "format", default="")).lower()
    if fmt and fmt != "openclaw":
        return {}, (f"this is a '{fmt}'-format plugin, which carries its own bundle manifest "
                    f"rather than {MANIFEST_NAME} — what is shown below is only what "
                    f"OpenClaw reported about it, not a read of its declarations")
    return {}, f"no {MANIFEST_NAME} found for '{pid}' — nothing was scanned"


def package_json_of(pid: str, record: dict | None = None) -> dict:
    """The plugin's package.json, if it has one. Read for install scripts only."""
    rec = record if record is not None else inspect(pid)[0]
    p = str(_first(rec, "path", "dir", "installPath", "root"))
    for c in ([Path(p).expanduser() / "package.json"] if p else []) + \
             [extensions_root() / pid / "package.json"]:
        try:
            if c.is_file():
                return json.loads(c.read_text())
        except Exception:                                          # noqa: BLE001
            pass
    return {}


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------
# Deterministic, needs no model and no server, and reads the manifest rather than
# the code — which is a real limitation and is stated as one. A manifest is a
# DECLARATION: OpenClaw enforces some of it (a runtime `api.registerTool` must
# match `contracts.tools`; an installed plugin registering an undeclared trusted
# policy id is rejected before registration), and the rest is the plugin telling
# you what it is for. So this scan answers "what has it declared it will reach?",
# which is the question a consent screen needs, and does not pretend to answer
# "is this code malicious?", which reading a manifest cannot.
#
# Severities match appregistry's, because the same words end up on the same kind
# of screen: `high` is a capability whose misuse is unbounded, `medium` is real
# reach worth naming, `info` is what the thing is.

def _nonempty(seq) -> list:
    return [x for x in (seq or []) if x]


def static_scan(manifest: dict, package: dict | None = None,
                spec: dict | None = None) -> list[dict]:
    """Findings over a plugin's declarations. Same output everywhere it runs."""
    m = manifest or {}
    pkg = package or {}
    contracts = m.get("contracts") if isinstance(m.get("contracts"), dict) else {}
    out: list[dict] = []

    def add(sev, rule, note):
        out.append({"severity": sev, "rule": rule, "note": note})

    # --- high: the tiers whose whole point is bypassing a check -----------
    if _nonempty(contracts.get("trustedToolPolicies")):
        ids = ", ".join(str(x) for x in contracts["trustedToolPolicies"][:6])
        add("high", "trusted-tool-policies",
            f"registers host-trusted pre-tool policies ({ids}) — code that runs BEFORE a "
            f"tool call is checked and can decide the answer. Legitimate for a budget or "
            f"guardrail plugin; there is no smaller thing it could be asking for")
    if contracts.get("gatewayMethodDispatch"):
        add("high", "gateway-dispatch",
            "dispatches Gateway control-plane methods in-process from its own HTTP routes. "
            "OpenClaw's own documentation says this is an API-hygiene gate and NOT a "
            "sandbox against a malicious native plugin")
    if _nonempty(contracts.get("agentToolResultMiddleware")):
        add("high", "tool-result-middleware",
            "rewrites tool results before the model sees them — it sits between what "
            "actually happened and what the agent is told happened")
    kinds = m.get("kind")
    kinds = [kinds] if isinstance(kinds, str) else list(kinds or [])
    for k in kinds:
        if k in ("memory", "context-engine"):
            add("high", f"slot-{k}",
                f"claims the '{k}' slot — while it holds it, every {k} read and write goes "
                f"through this plugin instead of OpenClaw's own")
    hooks = _hook_names(m)
    conv = sorted(set(hooks) & CONVERSATION_HOOKS)
    if conv:
        add("high", "conversation-hooks",
            f"declares conversation hooks ({', '.join(conv)}) — these read and can rewrite "
            f"prompts and replies. OpenClaw will not start them until "
            f"plugins.entries.{m.get('id') or '<id>'}.hooks.allowConversationAccess is true, "
            f"so this stays off unless somebody turns it on deliberately")

    # --- medium: real reach, named ---------------------------------------
    mcp = m.get("mcpServers")
    if isinstance(mcp, dict) and mcp:
        add("medium", "mcp-servers",
            f"contributes {len(mcp)} MCP server(s) ({', '.join(sorted(mcp)[:6])}) — each one "
            f"is another program with its own reach, started because this plugin is enabled")
    cmds = _nonempty(m.get("cliCommands")) + _nonempty(m.get("commandAliases"))
    if cmds:
        names = ", ".join(str(c.get("name") if isinstance(c, dict) else c) for c in cmds[:6])
        add("medium", "cli-commands",
            f"adds commands to the `openclaw` CLI ({names}) — after this, typing one of "
            f"those runs plugin code")
    scripts = (pkg.get("scripts") or {}) if isinstance(pkg.get("scripts"), dict) else {}
    hooky = [s for s in ("preinstall", "install", "postinstall", "prepare") if s in scripts]
    if hooky:
        add("medium", "install-scripts",
            f"its package.json declares npm lifecycle scripts ({', '.join(hooky)}). OpenClaw "
            f"installs plugin dependencies with --ignore-scripts, so these did not run here "
            f"— but they are what the author expects to run somewhere")
    for key, what in (("channels", "messaging channels"), ("providers", "model providers")):
        vals = _nonempty(m.get(key))
        if vals:
            add("medium", f"owns-{key}",
                f"owns {what}: {', '.join(str(v) for v in vals[:6])} — turns become that "
                f"plugin's traffic when one is selected")
    if _nonempty(m.get("backupResources")):
        add("medium", "backup-resources",
            "declares state directories to be included in backups — check they are its own")
    if spec and not spec.get("trusted"):
        add("medium", "untrusted-source", source_sentence(spec))

    # --- info: what it is ------------------------------------------------
    tools = _nonempty(contracts.get("tools"))
    if tools:
        add("info", "tools",
            f"adds {len(tools)} tool(s) the agent can call: "
            f"{', '.join(str(t) for t in tools[:8])}"
            + (" …" if len(tools) > 8 else ""))
    quiet = sorted(set(hooks) - CONVERSATION_HOOKS)
    if quiet:
        add("info", "hooks", f"runs on these events: {', '.join(quiet[:8])}")

    # --- what it did NOT say ---------------------------------------------
    oc = m.get("openclaw") if isinstance(m.get("openclaw"), dict) else {}
    if not ((oc.get("install") or {}).get("minHostVersion")
            or (oc.get("compat") or {}).get("pluginApi")):
        add("info", "no-compat-floor",
            "declares no minimum host version or plugin-API floor, so nothing here can "
            "check it against this OpenClaw before it loads")
    return out


#: The hooks OpenClaw itself gates behind `hooks.allowConversationAccess` for a
#: non-bundled plugin. Pinned from its docs — a hook that reaches the conversation
#: is categorically different from one that reaches a file.
CONVERSATION_HOOKS = frozenset({
    "before_model_resolve", "agent_turn_prepare", "before_prompt_build",
    "before_agent_reply", "llm_input", "llm_output", "before_agent_run",
    "before_agent_finalize", "agent_end",
})


def _hook_names(manifest: dict) -> list[str]:
    """Hook ids a manifest declares, across the spellings it may use."""
    m = manifest or {}
    contracts = m.get("contracts") if isinstance(m.get("contracts"), dict) else {}
    found: list[str] = []
    for src in (m.get("hooks"), contracts.get("hooks")):
        if isinstance(src, dict):
            found += [str(k) for k in src]
        elif isinstance(src, list):
            found += [str(h.get("event") if isinstance(h, dict) else h) for h in src]
    act = m.get("activation") if isinstance(m.get("activation"), dict) else {}
    found += [str(h) for h in (act.get("onHooks") or [])]
    return sorted({f for f in found if f})


def scan(manifest: dict, package: dict | None = None, spec: dict | None = None) -> dict:
    """The security block for a plugin: findings + verdict + when + by what."""
    findings = static_scan(manifest, package, spec)
    return {"scanner": "ocplugin-static/1", "scanned_at": time.time(),
            "verdict": verdict_of(findings), "findings": findings}


# ---------------------------------------------------------------------------
# What enabling would grant — the consent computation
# ---------------------------------------------------------------------------
# `capabilities()` is the sentence list a person reads; `declared_grants()` is the
# rows that get written. They are computed from the SAME manifest in the same
# call (`preview`) and the save re-derives them rather than trusting anything the
# screen sent back, which is what keeps the two from drifting apart.

def capabilities(pid: str, manifest: dict) -> list[str]:
    """Plain sentences: what this plugin will be able to reach, once enabled."""
    m = manifest or {}
    contracts = m.get("contracts") if isinstance(m.get("contracts"), dict) else {}
    out = []
    tools = _nonempty(contracts.get("tools"))
    if tools:
        out.append(f"give the agent {len(tools)} new tool(s): "
                   f"{', '.join(str(t) for t in tools[:8])}")
    mcp = m.get("mcpServers")
    if isinstance(mcp, dict) and mcp:
        out.append(f"start {len(mcp)} MCP server(s): {', '.join(sorted(mcp))}")
    for key, verb in (("providers", "answer turns as model provider"),
                      ("channels", "carry messages on channel")):
        vals = _nonempty(m.get(key))
        if vals:
            out.append(f"{verb} {', '.join(str(v) for v in vals[:6])}")
    cmds = _nonempty(m.get("cliCommands"))
    if cmds:
        out.append("add `openclaw` commands: " + ", ".join(
            str(c.get("name") if isinstance(c, dict) else c) for c in cmds[:6]))
    hooks = _hook_names(m)
    if hooks:
        conv = sorted(set(hooks) & CONVERSATION_HOOKS)
        out.append(f"run on {len(hooks)} event(s)" + (
            f", including {len(conv)} that read the conversation itself "
            f"(off until you set hooks.allowConversationAccess)" if conv else ""))
    if not out:
        out.append("declare nothing this scan can name — read its own documentation "
                   "before enabling it")
    return out


def declared_grants(pid: str, manifest: dict, surfaces: str = "*") -> list[dict]:
    """The exact grant rows enabling this plugin implies. Pure — no database.

    One row per thing it declared, plus the row that IS the enablement
    (`plugin.run`). That last one is not decoration: `reconcile()` reads it back,
    and a revoked `plugin.run` is what turns into `openclaw plugins disable`. It
    is the binding that makes the Permissions app a real control over a plugin
    running in somebody else's process.
    """
    m = manifest or {}
    contracts = m.get("contracts") if isinstance(m.get("contracts"), dict) else {}
    ref, rows = source_ref(pid), []

    def add(action, resource, note):
        rows.append({"principal_kind": PRINCIPAL_KIND, "principal_id": pid,
                     "action": action, "resource": resource, "effect": "allow",
                     "surfaces": surfaces, "note": note[:300]})

    add("plugin.run", ref,
        f"the OpenClaw plugin '{pid}' is enabled. Revoke this and AgentOS disables it.")
    for t in _nonempty(contracts.get("tools")):
        add("tool.use", f"tool:{t}", f"a tool the '{pid}' plugin owns")
    for name in sorted((m.get("mcpServers") or {}) if isinstance(m.get("mcpServers"), dict) else {}):
        add("mcp.use", f"mcp:{name}", f"an MCP server the '{pid}' plugin contributes")
    for p in _nonempty(m.get("providers")):
        add("model.use", f"model:{p}/*", f"a model provider the '{pid}' plugin owns")
    return rows


def reconcile_grants(store, pid: str, manifest: dict, enabled: bool) -> dict:
    """Regenerate this plugin's grants, leaving anything a human wrote alone.

    Same filter and same argument as `flows.reconcile_grants`: `source` +
    `source_ref` is what a definition wrote, so editing or disabling a plugin
    never quietly undoes a permission somebody deliberately gave it. A DISABLED
    plugin holds nothing — enabling is the act of granting.
    """
    ref = source_ref(pid)
    want = declared_grants(pid, manifest) if enabled else []
    have = [g for g in store.list_grants()
            if g.get("source") == GRANT_SOURCE and (g.get("source_ref") or "") == ref]

    def key(g):
        return (g["principal_kind"], g["principal_id"], g["action"], g["resource"],
                g.get("effect") or "allow")

    wk = {key(w): w for w in want}
    hk = {key(h): h for h in have}
    revoked = sum(1 for k, h in hk.items() if k not in wk and store.revoke_grant(h["id"]))
    added = 0
    for k, w in wk.items():
        if k not in hk:
            store.add_grant(w["principal_kind"], w["principal_id"], w["action"], w["resource"],
                            effect=w["effect"], source=GRANT_SOURCE, note=w["note"],
                            surfaces=w.get("surfaces", "*"), source_ref=ref)
            added += 1
    return {"added": added, "revoked": revoked, "kept": len(set(wk) & set(hk))}


def revoke_grants(store, pid: str) -> int:
    """Everything an uninstalled plugin was granted goes with it."""
    ref, n = source_ref(pid), 0
    for g in store.list_grants():
        if g.get("source") == GRANT_SOURCE and (g.get("source_ref") or "") == ref:
            n += int(bool(store.revoke_grant(g["id"])))
    return n


def consented(store, pid: str) -> bool:
    """Is the enablement grant still live? The one question `reconcile` asks."""
    ref = source_ref(pid)
    return any(g.get("source") == GRANT_SOURCE and (g.get("source_ref") or "") == ref
               and g.get("action") == "plugin.run" for g in store.list_grants())


# ---------------------------------------------------------------------------
# Trust on first use — same model as the app registry, different bytes
# ---------------------------------------------------------------------------
# The question an update has to answer is not "is this signed?" — most plugins
# are not — but "is this the same thing I decided about last time?". That is what
# SSH's known_hosts answers, and `appregistry.tofu_check` already answers it for
# apps. Here the pin is (source, version), because an OpenClaw plugin's identity
# on the wire is its install spec: a plugin that was ClawHub yesterday and a git
# URL today is either a legitimate move or a namesquat, and the person decides.
#
# Pins live in cfg["registry"]["openclaw"] — inside the existing `registry`
# USER_KEY, which is already documented as personal: whom I trust costs nothing
# machine-wide and reconfigures nothing.

def pins(cfg: dict) -> dict:
    return ((cfg or {}).get("registry") or {}).get("openclaw") or {}


def pin_check(cfg: dict, pid: str, source: str) -> tuple[str, str]:
    """(status, sentence) for a plugin about to be enabled or updated."""
    pin = pins(cfg).get((pid or "").strip().lower())
    if not pin:
        return "first-install", "first time — its source will be remembered"
    was = pin.get("source") or ""
    if was and source and was != source:
        return "changed-source", (f"it now comes from '{source}' but it was '{was}' when you "
                                  f"enabled it — a plugin changing origin is either the author "
                                  f"moving or somebody else taking the name")
    return "match", f"same source as when you enabled it ({was or 'unrecorded'})"


def record_pin(cfg: dict, pid: str, source: str, version: str = "",
               verdict: str = "") -> dict:
    """Remember what was agreed to: where it came from AND how it scanned.

    The verdict is pinned as well as the source because the before/after of an
    `update` is the weaker question. AgentOS does not own the `openclaw` CLI — a
    person can and will run `openclaw plugins update` in a terminal, or edit a
    linked plugin's own source — so a comparison made only across OUR update call
    misses every change that did not go through it. The pinned verdict is what the
    person actually consented to, and `drift_check` measures against that.
    """
    reg = cfg.setdefault("registry", {})
    oc = reg.setdefault("openclaw", {})
    oc[(pid or "").strip().lower()] = {"source": source or "", "version": version or "",
                                       "verdict": verdict or "", "pinned_at": time.time()}
    return cfg


def drift_check(cfg: dict, pid: str, verdict: str) -> str:
    """'' if a fresh scan still agrees with what was consented to, else the sentence.

    Only an ESCALATION is drift. A plugin that got quieter is good news, and
    holding it would teach people that the hold means nothing.
    """
    pinned = (pins(cfg).get((pid or "").strip().lower()) or {}).get("verdict") or ""
    if not pinned or pinned == verdict:
        return ""
    if pinned == "pass" and verdict == "caution":
        return (f"its declarations now scan as '{verdict}' but you enabled it when they "
                f"scanned as '{pinned}' — it is asking for more than you agreed to")
    return ""


def forget_pin(cfg: dict, pid: str) -> dict:
    ((cfg.get("registry") or {}).get("openclaw") or {}).pop((pid or "").strip().lower(), None)
    return cfg


# ---------------------------------------------------------------------------
# Quarantine — the ceiling, expressed in the one lever OpenClaw enforces
# ---------------------------------------------------------------------------
# A held plugin is DISABLED and named in `plugins.deny`, which OpenClaw documents
# as winning over allow and over per-plugin enablement. That is why the hold is
# real rather than a note: the enforcement is not ours to keep, it is OpenClaw's,
# and we are writing the one thing it obeys unconditionally.
#
# It uses the existing quarantine table with `principal_kind='ocplugin'`, so a
# held plugin shows up in the same list, with the same once/forever/deleted
# release, as a runaway app. A second quarantine surface would be a second set of
# bugs in something a person only ever looks at when they are already worried.

def hold(store, pid: str, reason: str, kind: str = "supply-chain",
         evidence: dict | None = None) -> str:
    """Quarantine a plugin, turn it off, and take back what it was granted.

    All three, here, rather than at each call site: a hold that left the grants
    standing would be undone by the next `reconcile()`, which reads exactly those
    rows to decide the plugin is still allowed. Doing it in one place is also why
    the CLI, the route and an update-triggered hold cannot end up meaning three
    different things.

    The disable and the revoke run whether or not the ROW was new — the row being
    there already means a previous hold, not that the plugin is off.
    """
    qid = store.quarantine_add(PRINCIPAL_KIND, pid, reason, label=f"OpenClaw plugin '{pid}'",
                               kind=kind, evidence=evidence or {})
    disable(pid)
    revoke_grants(store, pid)
    return qid


def held(store, pid: str) -> dict | None:
    return store.quarantined(PRINCIPAL_KIND, pid)


def exempt(store, pid: str) -> bool:
    return store.quarantine_exempt(PRINCIPAL_KIND, pid)


def reconcile(store, cfg: dict) -> dict:
    """Make OpenClaw's enablement agree with this OS's decisions.

    Three things can disagree, and each is a decision that has stopped being true:
      · the `plugin.run` grant was revoked (Permissions app, or `bento openclaw disable`)
      · the plugin is quarantined and not released
      · a fresh scan of its manifest is worse than the one it was enabled on

    That third one is the case AgentOS could not otherwise see, and it is not a
    corner: this OS does not own the `openclaw` CLI. Somebody updating a plugin in
    a terminal, or editing a linked plugin's own source, changes what it can reach
    without ever passing through the consent screen. Re-reading the bytes is the
    only thing that catches it — the same argument `appregistry.scan_drift` makes
    for apps, where the receiving machine always re-scans.

    The answer is the same in all three cases and it is enforceable: disable it.
    Nothing here ENABLES anything — re-enabling is a person's act, the same
    asymmetry `flows.reconcile_grants` has.
    """
    rows, err = installed()
    if err:
        return {"checked": 0, "disabled": [], "error": err}
    off = []
    for r in rows:
        if r.get("bundled"):
            continue                    # bundled plugins are OpenClaw itself, not an install
        if not r["enabled"]:
            continue
        pid, why, drifted = r["id"], "", False
        if held(store, pid) and not exempt(store, pid):
            why = "quarantined"
        elif not consented(store, pid):
            why = "its permission was revoked"
        else:
            man, _ = manifest_of(pid, r)
            fresh = scan(man, package_json_of(pid, r), parse_spec(r.get("source") or ""))
            if d := drift_check(cfg, pid, fresh["verdict"]):
                why, drifted = d, True
        if not why:
            continue
        if drifted and not exempt(store, pid):
            hold(store, pid, why, kind="supply-chain", evidence={"verdict": fresh["verdict"]})
        rc, out = disable(pid)
        off.append({"id": pid, "why": why, "held": drifted,
                    "ok": rc == 0, "detail": out[-200:]})
    return {"checked": len(rows), "disabled": off, "error": ""}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def search(query: str, limit: int = 20) -> tuple[list[dict], str]:
    """ClawHub, through OpenClaw's own search. Reads a catalogue and nothing else."""
    if not available():
        return [], problem()
    parsed, err = _json_run(["search", query, "--limit", str(max(1, min(int(limit or 20), 100)))],
                            TIMEOUT_SEARCH)
    if parsed is None:
        return [], err
    out = []
    for r in _rows(parsed, "results", "packages", "plugins", "items"):
        name = str(_first(r, "name", "package", "id"))
        if not name:
            continue
        out.append({"name": name,
                    "version": str(_first(r, "version")),
                    "summary": str(_first(r, "summary", "description"))[:300],
                    "family": str(_first(r, "family", "kind")),
                    "channel": str(_first(r, "channel")),
                    "spec": f"clawhub:{name}"})
    return out, ""


def install(spec: str, pin: bool = True, force: bool = False) -> tuple[bool, str]:
    """Install a plugin. It lands DISABLED — see the module docstring.

    `--pin` by default: an unpinned npm install is a different set of bytes every
    time the registry's default line moves, and a review of bytes that get
    replaced without another review is not a review. `--force` is passed only
    when the caller says the user was shown the source and agreed, because it is
    the answer to OpenClaw's own provenance question.
    """
    info = parse_spec(spec)
    if not info["spec"]:
        return False, "which plugin? a ClawHub name, npm:…, git:… or a path"
    args = ["install", info["spec"]]
    if pin and info["scheme"] in ("npm", "clawhub") and not info["ref"]:
        args.append("--pin")            # --pin is npm-only; a ref is already a pin
    if force:
        args.append("--force")
    rc, out = _run(args, TIMEOUT_INSTALL)
    return rc == 0, out.strip()[-2000:]


def installed_id(spec: str, install_output: str = "") -> str:
    """Which plugin id an install actually produced. '' when it cannot be known.

    A plugin id is NOT its package name — a scoped npm package installs as
    whatever its manifest `id` says — so this asks the registry rather than
    guessing from the string. There is ONE of these because reviewing the wrong
    plugin is worse than saying nothing, and three surfaces (CLI, route, agent
    tool) each guessing differently is how two of them end up wrong.
    """
    rows, err = installed()
    if err:
        return ""
    ids = {r["id"] for r in rows}
    for pat in (r"[Ii]nstalled\s+(?:plugin\s+)?['\"`]?([\w.@/-]+)['\"`]?",
                r"plugin\s+id[:=]\s*['\"`]?([\w.@/-]+)"):
        m = re.search(pat, install_output or "")
        if m and m.group(1) in ids:
            return m.group(1)
    stem = parse_spec(spec)["package"].rsplit("/", 1)[-1].removesuffix(".tgz")
    if stem in ids:
        return stem
    near = [i for i in ids if stem and (stem in i or i in stem)]
    return near[0] if len(near) == 1 else ""


def enable(pid: str) -> tuple[int, str]:
    rc, out = _run(["enable", pid], TIMEOUT_READ)
    return rc, out.strip()[-1000:]


def disable(pid: str) -> tuple[int, str]:
    rc, out = _run(["disable", pid], TIMEOUT_READ)
    return rc, out.strip()[-1000:]


def uninstall(pid: str, dry_run: bool = False) -> tuple[int, str]:
    # `--force` here means "do not require an interactive TTY to confirm", which is
    # the only sense in which a server can uninstall anything. The decision was
    # already made by whoever called this; the prompt would have nobody at it.
    args = ["uninstall", pid] + (["--dry-run"] if dry_run else ["--force"])
    rc, out = _run(args, TIMEOUT_INSTALL)
    return rc, out.strip()[-2000:]


def update(pid: str, dry_run: bool = False) -> tuple[int, str]:
    args = ["update", pid] + (["--dry-run"] if dry_run else [])
    rc, out = _run(args, TIMEOUT_INSTALL)
    return rc, out.strip()[-2000:]


def doctor() -> tuple[dict, str]:
    if not available():
        return {}, problem()
    parsed, err = _json_run(["doctor"], TIMEOUT_READ)
    return (parsed if isinstance(parsed, dict) else {}), err


# ---------------------------------------------------------------------------
# The consent screen, and the save that must agree with it
# ---------------------------------------------------------------------------

def preview(pid: str, cfg: dict, store=None) -> dict:
    """Everything a person needs to decide about ONE installed plugin.

    This is the screen AND the input to the save: `enable_plugin` calls it again
    rather than trusting anything handed back, so the permission somebody agreed
    to is the permission they get.
    """
    rec, err = inspect(pid)
    if err and not rec:
        return {"id": pid, "error": err}
    man, man_err = manifest_of(pid, rec)
    pkg = package_json_of(pid, rec)
    src = str(_first(rec, "source", "spec", "installSpec"))
    info = parse_spec(src) if src else {"spec": "", "scheme": "", "package": pid,
                                        "ref": "", "trusted": False, "origin": "unrecorded"}
    sec = scan(man, pkg, info if src else None)
    tofu, tofu_note = pin_check(cfg, pid, src)
    out = {
        "id": pid,
        "name": str(_first(rec, "displayName", "title", "name", default=pid)),
        "version": str(_first(rec, "version")),
        "enabled": bool(_first(rec, "enabled", "isEnabled", default=False)),
        "bundled": bool(_first(rec, "bundled", "isBundled", default=False)),
        "format": str(_first(rec, "format")),
        "source": src,
        "source_note": source_sentence(info) if src else
                       "OpenClaw recorded no install source for this one — it is either "
                       "bundled with OpenClaw or was loaded from a path",
        "manifest_note": man_err,
        "security": sec,
        "capabilities": capabilities(pid, man),
        "grants": declared_grants(pid, man),
        "tofu": tofu,
        "tofu_note": tofu_note,
    }
    # What will NOT work here, and the offer to build it properly instead. Carried
    # on the preview so the CLI, the GUI and the agent all show the same sentences
    # — a disclaimer that differs by surface is one somebody has already got wrong.
    from . import ocnative
    out["compatibility"] = ocnative.compatibility(man, hosted=False)
    out["native"] = ocnative.brief(pid, man, src)
    if store is not None:
        q = held(store, pid)
        out["quarantined"] = bool(q)
        out["quarantine"] = {"id": q["id"], "reason": q["reason"]} if q else None
        out["consented"] = consented(store, pid)
    return out


def enable_plugin(store, cfg: dict, pid: str) -> dict:
    """The save. Consent has happened by the time this is called.

    Order matters: a quarantined plugin is refused before anything is written, the
    grants are derived from a FRESH read of the manifest on disk, and the pin is
    recorded last so a failed enable does not leave a pin claiming a decision
    nobody completed.
    """
    q = held(store, pid)
    if q and not exempt(store, pid):
        return {"ok": False, "error": f"'{pid}' is held: {q['reason']}. Release it in "
                                      f"Permissions → Quarantine first."}
    rec, err = inspect(pid)
    if err and not rec:
        return {"ok": False, "error": err}
    man, _ = manifest_of(pid, rec)
    src = str(_first(rec, "source", "spec", "installSpec"))
    rc, out = enable(pid)
    if rc != 0:
        return {"ok": False, "error": out or f"`openclaw plugins enable {pid}` failed"}
    res = reconcile_grants(store, pid, man, enabled=True)
    record_pin(cfg, pid, src, str(_first(rec, "version")),
               scan(man, package_json_of(pid, rec), parse_spec(src))["verdict"])
    return {"ok": True, "grants": res, "capabilities": capabilities(pid, man),
            "restart_note": "OpenClaw loads plugin code at Gateway start — restart the "
                            "OpenClaw gateway before expecting this to be live."}


def disable_plugin(store, pid: str) -> dict:
    """Off, and everything it was granted goes with it."""
    rc, out = disable(pid)
    revoked = revoke_grants(store, pid)
    return {"ok": rc == 0, "error": "" if rc == 0 else out, "revoked": revoked}


def uninstall_plugin(store, cfg: dict, pid: str) -> dict:
    rc, out = uninstall(pid)
    revoked = revoke_grants(store, pid)
    forget_pin(cfg, pid)
    return {"ok": rc == 0, "error": "" if rc == 0 else out, "revoked": revoked}


def update_plugin(store, cfg: dict, pid: str) -> dict:
    """Update, then re-decide. An update is a new set of bytes, so it is re-scanned.

    Two things can turn an update into a hold rather than an upgrade, and both are
    the supply-chain case this exists for: the source moved (TOFU), or the fresh
    scan of the new manifest is worse than what was consented to. Either way the
    plugin is quarantined and disabled, with the reason recorded, instead of
    silently running with capabilities nobody agreed to.
    """
    was_enabled = bool(preview(pid, cfg, store).get("enabled"))
    rc, out = update(pid)
    if rc != 0:
        return {"ok": False, "error": out or f"`openclaw plugins update {pid}` failed"}
    after = preview(pid, cfg, store)
    now = (after.get("security") or {}).get("verdict") or "pass"

    # Measured against the PIN — what was consented to — rather than against a
    # reading taken moments earlier. See `record_pin`.
    why = ""
    if after.get("tofu") == "changed-source":
        why = f"update changed where it comes from — {after.get('tofu_note')}"
    elif drift := drift_check(cfg, pid, now):
        highs = [f["note"] for f in (after["security"]["findings"]) if f["severity"] == "high"]
        why = drift + (": " + "; ".join(highs[:2]) if highs else "")
    if why and was_enabled:
        hold(store, pid, why, kind="supply-chain",
             evidence={"consented": (pins(cfg).get(pid) or {}).get("verdict"),
                       "now": now, "source": after.get("source")})
        return {"ok": True, "held": True, "reason": why, "preview": after}

    if was_enabled:
        man, _ = manifest_of(pid)
        reconcile_grants(store, pid, man, enabled=True)
        record_pin(cfg, pid, after.get("source") or "", after.get("version") or "", now)
    return {"ok": True, "held": False, "preview": after}

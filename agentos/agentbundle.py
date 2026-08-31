"""Fork my agent: the agent itself as the unit of distribution — with nothing personal in it.

Everything this OS produces that is worth having — a persona, skills, specialist
subagents, standing flows, apps, the MCP servers that power them — lived on one
machine and could not travel. The app registry moved APPS; the agent, the thing
people would actually share ("mine runs my whole invoicing — here, fork it"),
had no door. This module is that door, in both directions:

    bento agent share            write bento.agent.json — the well-known file a
                                 repo hosts, exactly as apps use bento.agentapp.json
    bento agent fork <source>    a file, a URL, or owner/repo — reviewed, then
                                 created HERE, everything landing disabled

THE VITAL DROP: no data and no credentials, structurally. Two mechanisms, and
the order matters:

  1. **The bundle is built from a WHITELIST, never "config minus secrets".**
     `export()` constructs the manifest field by field from things it names —
     the soul (opt-in), skills, subagents, flow definitions, chosen apps,
     sanitized MCP shapes. Memory rows, the knowledge graph, conversations,
     usage, audit, provider keys, channel tokens, webhook secrets and the
     signing key are not filtered out; they are simply never reached for. A
     blacklist leaks the first time somebody adds a key it has not heard of; a
     whitelist cannot, which is the same argument that made users directories
     instead of WHERE clauses.
  2. **A tripwire on the finished bytes.** `leak_scan()` runs over the
     serialized bundle looking for anything key-shaped — vendor prefixes, PEM
     blocks, a Telegram token's silhouette — because a secret can be SMUGGLED
     into whitelisted prose: pasted into a soul, hardcoded in an app's HTML,
     written into a flow's mission. Export REFUSES on a finding and names where
     it is; there is no --force, because "ship my key anyway" is not a decision
     this OS will help anyone make quickly. Remove it and export again.

A FORK GRANTS NOTHING. Import writes zero grant rows: flows arrive disabled
(and a disabled flow holds nothing — enabling is the act of granting, the rule
everything here runs on), MCP servers arrive disabled with placeholder env for
you to fill, apps go through the same permission staging every app does, and
the soul is adopted only when explicitly asked. Forking a stranger's agent is
safe not because the stranger is trusted but because nothing they sent is live
until each piece passes the door it always had.

Trust is the registry's trust, reused rather than re-invented: the checksum is
`appregistry.canonical` over the manifest, the signature is the same Ed25519
keypair `bento registry keygen` mints, verification runs against the same
`trusted_keys`, and first-fork pins use the same `tofu_check` — the SSH model,
where the loudest alarm is the SIGNER changing under a name you know.

Nothing an existing machine has is ever overwritten: a skill, subagent, flow,
app or MCP server whose name is taken is SKIPPED and said so. A fork must not
be a way to replace what somebody already built. HTTP-free like jobs.py: a
headless box shares and forks with the server down.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import flows as flowsmod
from .appregistry import (canonical, static_scan, tofu_check, trusted_keys,
                          verdict_of)

FORMAT = "agentos-agent/1"

#: Where a shared agent lives in its author's repo, mirroring the app registry's
#: WELL_KNOWN, and the GitHub topic that makes it discoverable with nobody
#: hosting a directory.
WELL_KNOWN = ("bento.agent.json", ".bento/agent.agent.json")
DISCOVERY_TOPIC = "bento-agent"

#: The pins bucket, inside the existing `registry` USER_KEY — whom I trust is
#: personal, the same reasoning as app pins and OpenClaw plugin pins.
PINS_KEY = "agents"


# ---------------------------------------------------------------------------
# The tripwire
# ---------------------------------------------------------------------------
#: (label, pattern). Deliberately NAMED shapes rather than a generic entropy
#: hunt: an entropy scan cries wolf on every checksum and base64 icon, and a
#: tripwire people silence is no tripwire. Each row is a form a real credential
#: takes on this OS or arrives in.
_LEAK_RULES: tuple[tuple[str, str], ...] = (
    ("an Anthropic API key", r"sk-ant-[A-Za-z0-9_-]{10,}"),
    ("an OpenAI-style API key", r"sk-[A-Za-z0-9]{20,}"),
    ("a GitHub token", r"gh[pousr]_[A-Za-z0-9]{20,}"),
    ("a Slack token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("an AWS access key id", r"AKIA[0-9A-Z]{16}"),
    ("a Google API key", r"AIza[0-9A-Za-z_-]{30,}"),
    ("a private key block", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("a Telegram bot token", r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),
    ("a bearer credential", r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    # A field that CALLS itself a secret and carries a real-looking value. The
    # whitelist never emits such fields, so one in the bytes means smuggled prose.
    ("a field named like a credential",
     r"(?i)\"(api_key|apikey|secret|token|password|passwd|private_key)\"\s*:\s*\"[^\"<>{}]{8,}\""),
)


def leak_scan(text: str) -> list[dict]:
    """Anything key-shaped in the bytes about to travel. [] is the only pass."""
    out = []
    for label, pat in _LEAK_RULES:
        m = re.search(pat, text or "")
        if m:
            at = text[:m.start()].count("\n") + 1
            out.append({"looks_like": label, "line": at,
                        "excerpt": m.group(0)[:12] + "…"})
    return out


class LeakRefusal(ValueError):
    """Export stopped because the bundle contained something key-shaped.

    Deliberately not overridable: there is no flag that ships it anyway. The fix
    is to remove the credential from the soul, skill, app or flow it was pasted
    into and export again — which is also the fix the person actually wants,
    they just have not noticed the paste yet.
    """

    def __init__(self, findings: list[dict]):
        self.findings = findings
        lines = "; ".join(f"{f['looks_like']} at line {f['line']} ({f['excerpt']})"
                          for f in findings)
        super().__init__(
            f"this bundle will not be written: it contains {lines}. Nothing that looks "
            f"like a credential leaves this machine — remove it from wherever it was "
            f"pasted (a soul, a skill, an app, a flow) and share again.")


def sanitize_mcp_conf(name: str, conf: dict) -> dict:
    """A shareable MCP server: connection SHAPE only — secrets become placeholders
    the forking user fills in themselves. Real env/header values never leave.

    One implementation; server.py's app export imports this rather than keeping
    its own, because two definitions of "what may an MCP config share?" is how
    one of them starts sharing the key.
    """
    out = {"name": name}
    for k in ("transport", "command", "args", "url"):
        if conf.get(k):
            out[k] = conf[k]
    if conf.get("env"):
        out["env_template"] = {k: f"<YOUR_{k}>" for k in conf["env"]}
    if conf.get("headers"):
        out["headers_template"] = {k: "<your value>" for k in conf["headers"]}
    return out


# ---------------------------------------------------------------------------
# Export — the whitelist, field by field
# ---------------------------------------------------------------------------

def _flow_export(store, f: dict) -> dict:
    """One flow as it may travel: the definition, never the machinery.

    Triggers carry kind + config with the webhook SECRET dropped — the secret is
    this machine's credential, minted fresh on the forking machine when (if) the
    flow is enabled there. `enabled` is forced False in the bundle so even a
    tampered file cannot claim a flow arrives live.
    """
    trigs = []
    for t in store.flow_triggers(f["name"]):
        conf = {k: v for k, v in (t.get("config") or {}).items()
                if k not in ("secret", "token")}
        trigs.append({"kind": t["kind"], "config": conf,
                      "cooldown_secs": t.get("cooldown_secs", 60)})
    return {"name": f["name"], "mission": f.get("mission") or "",
            "description": f.get("description") or "",
            "roster": f.get("roster") or [],
            "permissions": f.get("permissions") or {},
            "sinks": f.get("sinks") or [], "triggers": trigs,
            "enabled": False}


def export(store, cfg: dict, *, name: str = "", description: str = "",
           apps: list[str] | str = "none", with_soul: bool = False,
           mcp: list[str] | str = "used") -> tuple[dict, dict]:
    """Build the bundle. Returns (bundle, report) or raises LeakRefusal.

    `apps` — "none" (default), "all", or names: SHIPPING AN APP IS A CHOICE the
    exporter makes per app, never a default, because an app is the piece most
    likely to have something personal built into its HTML.
    `with_soul` — the soul is learned from the owner's life as much as written,
    so it is opt-in and the report carries its full text for a last read.
    `mcp` — "used" ships only servers a shipped flow/app plausibly needs — here,
    all configured names, shapes only; "none" ships none; or explicit names.

    The report is the honest half: exactly what traveled, what was deliberately
    left behind, and the sentence for each. An export whose owner cannot say
    what it contains is a leak with a checksum.
    """
    from . import config as cfgmod

    skills = [{"name": s["name"], "description": s.get("description") or "",
               "content": s.get("content") or ""}
              for s in store.list_skills()]
    subagents = [{"name": a["name"], "soul": a.get("soul") or "",
                  "model": "",                    # a model is this machine's choice
                  "tools": a.get("tools") or [], "skills": a.get("skills") or [],
                  "autonomy_cap": a.get("autonomy_cap") or "balanced",
                  "max_steps": a.get("max_steps", 12)}
              for a in store.list_subagents() if not a.get("builtin")]
    flows = [_flow_export(store, f) for f in (store.list_flows() or [])]

    all_apps = store.list_apps(with_html=True)
    if apps == "all":
        chosen = all_apps
    elif apps == "none" or not apps:
        chosen = []
    else:
        want = {a.strip().lower() for a in apps}
        chosen = [a for a in all_apps if a["name"].lower() in want]
    app_docs = [{"name": a["name"], "icon": a.get("icon") or "",
                 "description": a.get("description") or "", "html": a.get("html") or ""}
                for a in chosen]

    mcp_names = sorted((cfg.get("mcp_servers") or {}))
    if mcp == "none":
        mcp_names = []
    elif isinstance(mcp, list):
        mcp_names = [n for n in mcp_names if n in set(mcp)]
    mcp_docs = [sanitize_mcp_conf(n, (cfg.get("mcp_servers") or {})[n]) for n in mcp_names]

    soul = cfgmod.load_soul() if with_soul else ""

    manifest = {
        "name": name or cfg.get("agent_name") or "Aria",
        "description": description or "",
        "created_at": time.time(),
        "soul": soul,
        "skills": skills,
        "subagents": subagents,
        "flows": flows,
        "apps": app_docs,
        "mcp_servers": mcp_docs,
        # Disclosure, not authority: what enabling EVERY flow would grant, so a
        # forking user reads the ceiling before anything exists. The import
        # writes none of these — enabling each flow later does, through
        # flows.reconcile_grants exactly as if it had been written by hand here.
        "permissions": [g for f in flows for g in flowsmod.declared_grants(
            {**f, "enabled": True})],
        "security": {"scanner": "static/1", "scanned_at": time.time(),
                     "verdict": verdict_of([x for a in app_docs
                                            for x in static_scan(a["html"])]),
                     "apps_scanned": len(app_docs)},
    }
    bundle = {"format": FORMAT, "manifest": manifest,
              "checksum": bundle_checksum(manifest), "signature": None}

    # indent=1 so a finding's line number points INTO the bundle rather than
    # every finding being "line 1 of one very long line".
    findings = leak_scan(json.dumps(bundle, indent=1))
    if findings:
        raise LeakRefusal(findings)

    report = {
        "traveled": {"skills": len(skills), "subagents": len(subagents),
                     "flows": len(flows), "apps": [a["name"] for a in app_docs],
                     "mcp_servers": mcp_names, "soul": bool(soul)},
        "withheld": [
            "your memory, knowledge graph and conversations — never exported",
            "every API key, channel token and webhook secret — never reached for",
            "MCP env/header values — shapes travel, placeholders replace values",
            ("the soul — off by default; --with-soul shares it and shows you the "
             "text first" if not soul else
             "NOTE: the soul IS included — read it below before publishing"),
        ] + ([] if apps != "none" else
             ["your apps — shipping an app is a per-app choice (--apps)"]),
        "soul_text": soul,
        "leak_scan": "clean",
    }
    return bundle, report


def bundle_checksum(manifest: dict) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(canonical(manifest).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Signatures — the registry's identity, reused
# ---------------------------------------------------------------------------

def signing_key_exists() -> bool:
    """Whether `--sign` can work here — so a share screen offers signing as a
    real choice or explains the one command that would make it one, never a
    dead checkbox."""
    from .appregistry import SIGNING_KEY_PATH
    return SIGNING_KEY_PATH.is_file()


def sign_bundle(bundle: dict, key_path: Path | None = None) -> dict:
    """Ed25519 over the checksum, with the same key `bento registry keygen`
    mints. The checksum is recomputed rather than trusted from the file —
    signing a stale one would vouch for bytes nobody looked at."""
    import base64
    import hashlib

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    from .appregistry import SIGNING_KEY_PATH
    key_path = key_path or SIGNING_KEY_PATH
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key_path.read_bytes()))
    raw_pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    out = dict(bundle)
    out["checksum"] = bundle_checksum(bundle.get("manifest") or {})
    out["signature"] = {
        "alg": "ed25519",
        "key_id": "reg-" + hashlib.sha256(raw_pub).hexdigest()[:8],
        "sig": base64.b64encode(priv.sign(out["checksum"].encode())).decode(),
        "signed_at": time.time(),
    }
    return out


def verify_bundle(bundle: dict, cfg: dict | None = None) -> tuple[str, str]:
    """(status, sentence): checksum-mismatch | unsigned | unknown-key |
    bad-signature | verified. `unsigned` is not hostile — your own shares are
    unsigned; only mismatch and bad-signature mean do-not-fork."""
    import base64
    man = (bundle or {}).get("manifest") or {}
    if bundle.get("checksum") != bundle_checksum(man):
        return "checksum-mismatch", ("the content does not match its checksum — it was "
                                     "modified after being shared, or corrupted in transit")
    sig = bundle.get("signature")
    if not sig:
        return "unsigned", "no signature — fine for your own shares; identity unproven"
    keys = trusted_keys(cfg)
    pub = keys.get(sig.get("key_id") or "")
    if not pub:
        return "unknown-key", (f"signed by '{sig.get('key_id')}', a key this machine does "
                               f"not trust — add it deliberately or treat as unsigned")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub)).verify(
            base64.b64decode(sig["sig"]), bundle["checksum"].encode())
    except Exception as e:                                         # noqa: BLE001
        return "bad-signature", f"the signature does not verify: {e}"
    return "verified", f"signed by {sig.get('key_id')}"


# ---------------------------------------------------------------------------
# The consent screen, and the fork it must agree with
# ---------------------------------------------------------------------------

def _pins(cfg: dict) -> dict:
    return ((cfg or {}).get("registry") or {}).get(PINS_KEY) or {}


def fork_preview(bundle: dict, store, cfg: dict, source: str = "") -> dict:
    """Everything a person decides on before a single row exists.

    The same computation `fork()` re-derives — the jobs.py rule — so the sentence
    agreed to is what happens. Collisions are found HERE so 'this will be
    skipped' is read before the fork, not discovered after it.
    """
    man = (bundle or {}).get("manifest") or {}
    status, status_note = verify_bundle(bundle, cfg)
    tofu, tofu_note = tofu_check(_pins(cfg), man.get("name") or "", source,
                                 ((bundle or {}).get("signature") or {}).get("key_id") or "")

    have_skills = {s["name"].lower() for s in store.list_skills()}
    have_agents = {a["name"].lower() for a in store.list_subagents()}
    have_flows = {f["name"].lower() for f in (store.list_flows() or [])}
    have_apps = {a["name"].lower() for a in store.list_apps()}
    have_mcp = {n.lower() for n in (cfg.get("mcp_servers") or {})}

    def rows(items, key, have, what):
        return [{"name": i[key], "kind": what,
                 "skipped": i[key].lower() in have,
                 "note": "a name this machine already uses — never overwritten"
                         if i[key].lower() in have else ""}
                for i in items]

    items = (rows(man.get("skills") or [], "name", have_skills, "skill")
             + rows(man.get("subagents") or [], "name", have_agents, "subagent")
             + rows(man.get("flows") or [], "name", have_flows, "flow")
             + rows(man.get("apps") or [], "name", have_apps, "app")
             + rows(man.get("mcp_servers") or [], "name", have_mcp, "mcp server"))

    app_findings = [dict(f, app=a["name"]) for a in (man.get("apps") or [])
                    for f in static_scan(a.get("html") or "")]
    return {
        "name": man.get("name") or "?",
        "description": man.get("description") or "",
        "verify": {"status": status, "note": status_note},
        "tofu": {"status": tofu, "note": tofu_note},
        "items": items,
        "security": {"verdict": verdict_of(app_findings), "findings": app_findings},
        "permissions_ceiling": man.get("permissions") or [],
        "grants_written_now": 0,       # a constant, and the whole point
        "soul_included": bool(man.get("soul")),
        "soul_text": man.get("soul") or "",
        "mcp_needs": [{"name": m["name"],
                       "fill": sorted((m.get("env_template") or {}))
                               + sorted((m.get("headers_template") or {}))}
                      for m in man.get("mcp_servers") or []],
    }


def fork(bundle: dict, store, cfg: dict, source: str = "",
         adopt_soul: bool = False) -> dict:
    """Create everything, all of it DISABLED, none of it granted, nothing
    overwritten. Returns what was created and what was skipped, by name.

    Refuses a checksum-mismatch or bad-signature outright — those are the two
    verdicts that mean the bytes are not what the sharer shared. `unsigned` and
    `unknown-key` fork fine: the consent screen already said so.
    """
    status, note = verify_bundle(bundle, cfg)
    if status in ("checksum-mismatch", "bad-signature"):
        return {"ok": False, "error": f"refusing to fork: {note}"}
    man = bundle.get("manifest") or {}
    pv = fork_preview(bundle, store, cfg, source)
    created, skipped = [], [i for i in pv["items"] if i["skipped"]]
    skip = {(i["kind"], i["name"].lower()) for i in skipped}

    for s in man.get("skills") or []:
        if ("skill", s["name"].lower()) not in skip:
            store.save_skill(s["name"], s.get("description") or "",
                             s.get("content") or "", source=f"fork:{man.get('name')}")
            created.append({"kind": "skill", "name": s["name"]})
    for a in man.get("subagents") or []:
        if ("subagent", a["name"].lower()) not in skip:
            store.save_subagent({**a, "builtin": 0})
            created.append({"kind": "subagent", "name": a["name"]})
    for f in man.get("flows") or []:
        if ("flow", f["name"].lower()) not in skip:
            body = {**f, "enabled": False}        # forced, whatever the file claims
            try:
                flowsmod.save(store, body)
                created.append({"kind": "flow", "name": f["name"], "enabled": False})
            except ValueError as e:
                skipped.append({"kind": "flow", "name": f["name"],
                                "skipped": True, "note": f"did not validate: {e}"})
    for a in man.get("apps") or []:
        if ("app", a["name"].lower()) not in skip:
            store.save_app(a["name"], a.get("icon") or "", a.get("description") or "",
                           a.get("html") or "", note=f"forked from '{man.get('name')}'")
            created.append({"kind": "app", "name": a["name"]})
    for m in man.get("mcp_servers") or []:
        if ("mcp server", m["name"].lower()) not in skip:
            conf = {k: m[k] for k in ("transport", "command", "args", "url") if m.get(k)}
            conf["enabled"] = False               # placeholders are not credentials
            if m.get("env_template"):
                conf["env"] = dict(m["env_template"])
            if m.get("headers_template"):
                conf["headers"] = dict(m["headers_template"])
            cfg.setdefault("mcp_servers", {})[m["name"]] = conf
            created.append({"kind": "mcp server", "name": m["name"], "enabled": False})

    soul_note = ""
    if man.get("soul"):
        if adopt_soul:
            from . import config as cfgmod
            cfgmod.save_soul(man["soul"])
            soul_note = "adopted — this agent's identity is now the shared one"
        else:
            soul_note = ("included but NOT adopted — your agent keeps its own identity; "
                         "re-run with the adopt option after reading it")

    reg = cfg.setdefault("registry", {}).setdefault(PINS_KEY, {})
    reg[(man.get("name") or "").strip().lower()] = {
        "source": source or "", "checksum": bundle.get("checksum") or "",
        "key_id": (bundle.get("signature") or {}).get("key_id") or "",
        "at": time.time()}

    return {"ok": True, "created": created, "skipped": skipped,
            "grants_written": 0, "soul": soul_note,
            "next": ("nothing is live yet: enable each flow in Workflows (that is when "
                     "its permissions are granted), fill the MCP placeholders and switch "
                     "the servers on, and open each app to review what it may do")}


# ---------------------------------------------------------------------------
# Where a shared agent lives
# ---------------------------------------------------------------------------

def resolve_source(src: str) -> list[str]:
    """Candidate URLs for owner/repo[@ref] or a URL — the app registry's
    resolver pointed at the agent well-known names. Same two CDNs, same Merkle
    argument for @commit pins, one implementation."""
    from .appregistry import resolve_source as _resolve
    return _resolve(src, well_known=WELL_KNOWN)

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
            "arrival": _arrival(man.get("name") or "?", created, skipped, soul_note),
            "next": ("nothing is live yet: enable each flow in Workflows (that is when "
                     "its permissions are granted), fill the MCP placeholders and switch "
                     "the servers on, and open each app to review what it may do")}


def _arrival(name: str, created: list[dict], skipped: list[dict],
             soul_note: str) -> dict:
    """The moment after a fork, as one computation every face shows.

    An import is disorienting in a specific way: eleven things just appeared and
    nothing on screen says which parts of your machine were touched and which
    were not. So the arrival answers exactly two questions — WHAT CHANGED (by
    name) and WHAT DID NOT (the things a forker worries about, said as facts) —
    and ends with the one action that turns a pile of definitions into an agent
    you believe in: talk to it. The suggested first message is part of the
    computation so chat, the wizard, the CLI and Settings all offer the same
    test, not four drifting paraphrases.
    """
    by_kind: dict = {}
    for c in created:
        by_kind.setdefault(c["kind"], []).append(c["name"])
    changed = [{"kind": k, "names": v,
                "note": {"flow": "arrived DISABLED — enabling is when its permissions "
                                 "are granted",
                         "mcp server": "arrived OFF, credentials are <placeholders> "
                                       "for you to fill",
                         "app": "opens from the desktop and App Studio; its "
                                "permissions stage like any app's"}.get(k, "")}
               for k, v in by_kind.items()]
    unchanged = [
        "your memory, conversations and knowledge graph — untouched, and none of "
        "the sharer's came: a bundle never carries data",
        "your brain and API keys — the fork answers with THIS machine's model and "
        "spends nothing of theirs",
        "your permissions — 0 rows were written by the import",
    ]
    if soul_note and "NOT adopted" in soul_note:
        unchanged.append("your agent's identity — the shared soul came along but was "
                         "not adopted; adopt it deliberately or leave it")
    for s in skipped:
        note = s.get("note") or ""
        if note.startswith("did not validate"):
            # Not a collision: the item failed to arrive, and saying "your
            # existing X" about it would claim a thing that is not there.
            unchanged.append(f"the {s['kind']} '{s['name']}' did not arrive — {note}")
        else:
            unchanged.append(f"your existing {s['kind']} '{s['name']}' — "
                             f"{note or 'kept, never overwritten'}")
    return {
        "changed": changed, "unchanged": unchanged,
        "try_message": (f"I just forked you from the shared agent '{name}'. "
                        f"Introduce yourself: what arrived — skills, teammates, "
                        f"flows, apps — what is still disabled, and what should I "
                        f"enable or fill in first?"),
    }


# ---------------------------------------------------------------------------
# Where a shared agent lives
# ---------------------------------------------------------------------------

def resolve_source(src: str) -> list[str]:
    """Candidate URLs for owner/repo[@ref] or a URL — the app registry's
    resolver pointed at the agent well-known names. Same two CDNs, same Merkle
    argument for @commit pins, one implementation."""
    from .appregistry import resolve_source as _resolve
    return _resolve(src, well_known=WELL_KNOWN)


# ---------------------------------------------------------------------------
# Hosted share — "it stays with me, take it", over an authenticated MCP door
# ---------------------------------------------------------------------------
#
# Share and fork are two different intentions and they get two different doors.
# A FORK is "you have my everything": a copy the taker now owns, which no later
# decision of mine can reach. A hosted SHARE is "it is hosted with me — take
# it": the bundle is served live by MY machine, so it is always the CURRENT
# agent, every take is authenticated with a key I minted, and revoking that key
# ends the arrangement. Publishing a file to a repo cannot express that second
# intention; this can.
#
# The door speaks MCP (JSON-RPC over HTTP), so the caller does not have to be a
# Bento machine: another agent adds it as an MCP server and calls `fetch_agent`.
# What travels through it is EXACTLY the export above — same whitelist, same
# placeholder credentials, and the leak scan runs on every single take, so a
# key pasted into a skill yesterday refuses today's fetch too.
#
# A peer is a real PRINCIPAL. Minting a key writes a `peer:<name> may
# agent.share` grant row (source='peer'); every fetch goes through PDP.decide,
# which writes the ledger row and honours a revocation made in the Permissions
# app — the same load-bearing binding as plugin.run. A peer's defaults deny
# everything else (policy._default), so the grant IS the whole reach.

SHARE_KEY = "agent_share"
PEER_GRANT_SOURCE = "peer"


def share_conf(cfg: dict) -> dict:
    c = cfg.setdefault(SHARE_KEY, {})
    c.setdefault("enabled", False)
    c.setdefault("peers", {})
    c.setdefault("include", {"apps": "none", "with_soul": False})
    return c


def hosting(cfg: dict) -> bool:
    return bool(share_conf(cfg).get("enabled"))


def mint_peer(cfg: dict, store, name: str, days: float = 0) -> tuple[str, str]:
    """(key, error). Minting is the act of granting: the key is the credential,
    and the grant row is the permission the Permissions app can later revoke.
    The key does NOT expire unless asked to — a key that dies on its own
    silently strands a standing arrangement — but --days sets a lifetime, and
    the refusal after that date says *expired*, not *bad key*."""
    import secrets
    name = (name or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", name or ""):
        return "", "a peer needs a simple name (letters, digits, . _ -)"
    ps = share_conf(cfg)["peers"]
    if name in ps and not ps[name].get("revoked_at"):
        return "", f"'{name}' already has a live key — revoke or rotate it instead"
    key = "bap_" + secrets.token_urlsafe(24)
    ps[name] = {"key": key, "created_at": time.time(),
                "expires_at": (time.time() + days * 86400) if days else 0,
                "revoked_at": 0, "last_fetch": 0}
    store.add_grant("peer", name, "agent.share", "agent:bundle",
                    source=PEER_GRANT_SOURCE, source_ref=f"peer:{name}",
                    note=f"may fetch this agent's shared bundle (key minted "
                         f"{time.strftime('%Y-%m-%d')})")
    return key, ""


def revoke_peer(cfg: dict, store, name: str) -> bool:
    """The end of the arrangement: the key stops opening the door AND the grant
    is revoked, so neither half can be forgotten. The record is kept, not
    deleted — a refusal that can say 'revoked' beats one that says 'unknown'."""
    name = (name or "").strip().lower()
    p = share_conf(cfg)["peers"].get(name)
    if not p or p.get("revoked_at"):
        return False
    p["revoked_at"] = time.time()
    for g in store.list_grants():
        if g.get("source") == PEER_GRANT_SOURCE and \
                (g.get("source_ref") or "") == f"peer:{name}":
            store.revoke_grant(g["id"])
    return True


def rotate_peer(cfg: dict, store, name: str, days: float = 0) -> tuple[str, str]:
    """A new key for the same arrangement — the grant stays, the old key dies."""
    name = (name or "").strip().lower()
    p = share_conf(cfg)["peers"].get(name)
    if not p or p.get("revoked_at"):
        return "", f"no live peer called '{name}'"
    import secrets
    p["key"] = "bap_" + secrets.token_urlsafe(24)
    p["expires_at"] = (time.time() + days * 86400) if days else 0
    return p["key"], ""


def list_peers(cfg: dict) -> list[dict]:
    out = []
    for name, p in sorted(share_conf(cfg)["peers"].items()):
        out.append({"name": name, "created_at": p.get("created_at") or 0,
                    "expires_at": p.get("expires_at") or 0,
                    "revoked": bool(p.get("revoked_at")),
                    "last_fetch": p.get("last_fetch") or 0})
    return out


def peer_for_key(cfg: dict, key: str) -> tuple[str, str]:
    """(peer_name, problem). Three refusals with three different sentences,
    because they call for three different actions: 'unknown key' is a caller to
    distrust, 'revoked' is an arrangement that ended, and 'expired' means
    rotate it — hunting a leak that never happened is the failure mode a vague
    refusal buys."""
    import hmac as _hmac
    key = (key or "").strip()
    if not key:
        return "", "no key presented"
    for name, p in share_conf(cfg)["peers"].items():
        if _hmac.compare_digest(str(p.get("key") or "\0"), key):
            if p.get("revoked_at"):
                return "", f"the key for '{name}' was revoked — this share has ended"
            exp = float(p.get("expires_at") or 0)
            if exp and time.time() > exp:
                return "", (f"the key for '{name}' expired — its owner can rotate it "
                            f"(`bento agent peers --rotate {name}`); this is not a leak")
            return name, ""
    return "", "unknown key"


def share_tools() -> list[dict]:
    """What the MCP door offers. Two tools, deliberately: discovery that costs
    the host nothing to answer honestly, and the take itself."""
    return [
        {"name": "agent_card",
         "description": "What this machine shares: the agent's name, description "
                        "and what a fetch would contain — counts and checksum, "
                        "never the content. Cheap, call it first.",
         "inputSchema": {"type": "object", "properties": {}}},
        {"name": "fetch_agent",
         "description": "The shared agentos-agent/1 bundle, built fresh from the "
                        "live agent: skills, subagents, flows (disabled), chosen "
                        "apps, MCP server shapes with placeholder credentials. "
                        "No memory, no conversations, no keys — a leak scan runs "
                        "on every fetch and refuses rather than serves. Fork it "
                        "with `bento agent fork` — everything lands disabled and "
                        "nothing is granted.",
         "inputSchema": {"type": "object", "properties": {}}},
    ]


def build_hosted(store, cfg: dict, *, name: str = "") -> tuple[dict, str]:
    """(bundle, error) — the export, with the host's stored include choices.
    One computation with `export()`, so what a peer takes is exactly what the
    owner's own share screen would build, leak scan included."""
    inc = share_conf(cfg).get("include") or {}
    try:
        bundle, _report = export(store, cfg, name=name,
                                 apps=inc.get("apps", "none"),
                                 with_soul=bool(inc.get("with_soul")))
    except LeakRefusal as e:
        return {}, str(e)
    if signing_key_exists():
        try:
            bundle = sign_bundle(bundle)     # hosting IS publishing; sign if we can
        except Exception:                                          # noqa: BLE001
            pass                             # unsigned is honest, a crash is not
    return bundle, ""


def fetch_peer(url: str, key: str, timeout: int = 30) -> tuple[dict, str]:
    """(bundle, error) — take a hosted share from another machine, as a client.
    Speaks the same MCP door `/api/agent/mcp`; a bare host[:port] is completed."""
    import urllib.request
    u = (url or "").strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "http://" + u
    if not u.endswith("/api/agent/mcp"):
        u += "/api/agent/mcp"

    def rpc(method: str, params: dict, rid: int):
        req = urllib.request.Request(
            u, data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                                "params": params}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    try:
        rpc("initialize", {"protocolVersion": "2025-06-18",
                           "clientInfo": {"name": "bento-agent", "version": "1"},
                           "capabilities": {}}, 1)
        res = rpc("tools/call", {"name": "fetch_agent", "arguments": {}}, 2)
    except urllib.error.HTTPError as e:
        # The door's refusals are sentences worth relaying — "revoked" and
        # "expired — rotate it" call for different actions than a bare 401.
        try:
            detail = json.loads(e.read()).get("error") or ""
        except Exception:                                          # noqa: BLE001
            detail = ""
        return {}, f"the host refused ({e.code}): {detail or e.reason}"
    except Exception as e:                                         # noqa: BLE001
        return {}, f"could not reach the share at {u}: {e}"
    if res.get("error"):
        return {}, str(res["error"].get("message") or res["error"])
    result = res.get("result") or {}
    if result.get("isError"):
        parts = result.get("content") or []
        return {}, "; ".join(p.get("text", "") for p in parts) or "the host refused"
    try:
        text = (result.get("content") or [{}])[0].get("text") or ""
        bundle = json.loads(text)
    except Exception:                                              # noqa: BLE001
        return {}, "the host answered, but not with a bundle"
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        return {}, f"the host answered, but not with an {FORMAT} bundle"
    return bundle, ""

"""The ethics library: what Bento knows about harm, built from public catalogues.

Asked for as "auto populate the ethics library, refer to some big source to begin with". Three
sources, each named on screen with its licence:

- **MITRE ATT&CK (Enterprise)**: the catalogue of attack techniques and of the tools and malware
  seen using them. It gives the programs whose job is attacking (and which tactic they serve), the
  technique names people use when they ask for one ("password spraying", "kerberoasting"), and the
  malware families. Royalty-free with MITRE's copyright notice kept (`SOURCES["attack"]`).
- **MITRE ATLAS**: the same for attacks on AI systems ("poison training data", "LLM jailbreak").
  Apache-2.0.
- **The MIT AI Risk Repository**: its domain taxonomy is how every flag is sorted (privacy, fraud,
  cyberattacks, surveillance…). CC BY 4.0; only the category names are used, with the citation.
  Its database is a spreadsheet, not a download, so the risks themselves are not imported, and the
  library says so.

Bento's own phrases about harm to people (doxxing, stalking a partner, a phishing email) are
written here, sorted by that taxonomy, because neither MITRE catalogue covers people.

Deterministic by construction: `build()` is a pure function of the two files, the result is
checked into the repo (`ethics_library.json`) and read at start, and nothing is fetched while a
step is being judged. An admin's Update fetches the same two files and may only ADD to what is
shipped (`load()` merges the overlay: new names, higher weights, never fewer or lower). The
overlay lives in the machine's home and is write-locked to agents (protected.WRITE_LOCKED_FILES).
This file is a SECURITY_MODULE.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
SHIPPED = HERE / "ethics_library.json"
OVERLAY_NAME = "ethics-library.json"

ATTACK_URL = ("https://raw.githubusercontent.com/mitre-attack/attack-stix-data/master/"
              "enterprise-attack/enterprise-attack.json")
ATLAS_URL = "https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml"

SOURCES = {
    "attack": {"name": "MITRE ATT&CK (Enterprise)", "url": "https://attack.mitre.org",
               "data": ATTACK_URL,
               "licence": "ATT&CK licence: royalty-free for research, development and commercial use, "
                          "with MITRE's copyright line and the licence kept (ethics_library_NOTICE.md)",
               "notice": "© 2026 The MITRE Corporation. This work is reproduced and distributed with the "
                         "permission of The MITRE Corporation."},
    "atlas": {"name": "MITRE ATLAS", "url": "https://atlas.mitre.org", "data": ATLAS_URL,
              "licence": "Apache-2.0", "notice": "Copyright 2021-2026 MITRE. Licensed under the Apache License 2.0."},
    "mit": {"name": "MIT AI Risk Repository (domain taxonomy)", "url": "https://airisk.mit.edu",
            "licence": "CC BY 4.0",
            "notice": "Slattery et al. (2024), The AI Risk Repository, arXiv:2408.12622. Category "
                      "names only; the risk database itself is not imported."},
    "bento": {"name": "Bento's phrases about harm to people", "url": "",
              "licence": "this project's licence",
              "notice": "Written for Bento and sorted by the MIT AI Risk Repository's categories."},
}

# The MIT AI Risk Repository's domains and subdomains: how every flag is sorted.
CATEGORIES = {
    "1.1": "Unfair discrimination and misrepresentation",
    "1.2": "Exposure to toxic content",
    "1.3": "Unequal performance across groups",
    "2.1": "Compromise of privacy",
    "2.2": "AI system security vulnerabilities and attacks",
    "3.1": "False or misleading information",
    "3.2": "Pollution of the information ecosystem",
    "4.1": "Disinformation, surveillance and influence at scale",
    "4.2": "Cyberattacks, weapons and mass harm",
    "4.3": "Fraud, scams and targeted manipulation",
    "5.1": "Overreliance and unsafe use",
    "5.2": "Loss of human agency and autonomy",
    "6.6": "Environmental harm",
    "7.1": "AI pursuing its own goals against people's interests",
    "7.2": "AI with dangerous capabilities",
    "7.3": "Lack of capability or robustness",
}

# ATT&CK lists the operating system's own tools because attackers use them too. Bento's own agents
# use them every day, so they carry no weight here; a target they name is still judged by owner.
DUAL_USE = frozenset({
    "arp", "bitsadmin", "diskpart", "expand", "forfiles", "net", "nltest", "ping", "reg",
    "systeminfo", "tasklist", "wevtutil", "at", "attrib", "certutil", "cipher", "cmd", "dsquery",
    "esentutl", "ftp", "ifconfig", "ipconfig", "nbtstat", "netsh", "netstat", "route", "schtasks",
    "tor", "ngrok", "rclone", "connectwise", "quick assist", "remoteutilities", "trufflehog",
    "sdelete", "adfind", "meek", "frp",
})
# Technique names too ordinary to say anything about intent when a person uses them.
GENERIC = frozenset({
    "valid accounts", "cloud accounts", "default accounts", "domain accounts", "local accounts",
    "service stop", "system shutdown/reboot", "data manipulation", "chat messages", "keychain",
    "private keys", "proc filesystem", "web cookies", "container api", "hybrid identity",
    "multi-factor authentication", "network device authentication", "pluggable authentication modules",
    "group policy preferences", "conditional access policies", "cloud instance metadata api",
    "domain controller authentication", "shell history", "password managers", "input capture",
    "reversible encryption", "ccache files", "security account manager", "unsecured credentials",
    "credentials in files", "scheduled transfer", "data transfer size limits", "trusted relationship",
    "hardware additions", "wi-fi networks", "content injection", "external remote services",
    "replication through removable media", "lifecycle-triggered deletion", "data", "model",
    "hardware", "ai software", "datasets", "models", "software tools", "verify attack",
    "establish accounts", "user execution", "ai model inference api access", "cost harvesting",
    "ai artifact collection", "data from local system", "data from information repositories",
    "discover ai artifacts", "use pre-trained model", "full ai model access", "account access removal",
    "transfer data to cloud account", "traffic duplication", "automated exfiltration",
    "network provider dll", "password filter dll", "modify authentication process", "ntds",
    "lsa secrets", "web portal capture", "gui input capture", "credential api hooking",
    "windows credential manager", "securityd memory", "saml tokens", "/etc/passwd and /etc/shadow",
    "steal or forge authentication certificates", "forced authentication",
    "exploitation for credential access", "cloud secrets management stores",
})
# The ATT&CK tactics a person's words are read for, and what saying one adds to the score.
TACTIC_WEIGHT = {"impact": 3, "credential-access": 3, "exfiltration": 2, "initial-access": 2}
ATLAS_TACTIC_WEIGHT = {"AML.TA0011": 3, "AML.TA0010": 3, "AML.TA0001": 2, "AML.TA0007": 2,
                       "AML.TA0004": 2, "AML.TA0013": 2, "AML.TA0003": 2}
TACTIC_CATEGORY = {"impact": "4.2", "credential-access": "2.1", "exfiltration": "2.1",
                   "initial-access": "4.3", "command-and-control": "4.2", "discovery": "4.2",
                   "lateral-movement": "4.2", "reconnaissance": "4.2", "collection": "2.1"}
# What a tool from ATT&CK does when it runs here, from the tactic it serves most.
TOOL_KIND = {"credential-access": "credentials", "command-and-control": "remote-control",
             "lateral-movement": "probe", "discovery": "probe", "reconnaissance": "probe",
             "execution": "probe"}

# Harm to PEOPLE, which neither MITRE catalogue covers. Each is a regex over the person's words,
# its MIT category and what it adds to the score. Saying one is context, never a refusal.
CURATED = (
    (r"\b(dox|doxx|doxxing|doxing)\b", "2.1", 3),
    (r"\b(home address|phone number|social security number|passport number) of\b", "2.1", 2),
    (r"\bwhere (does|do|did) [a-z][a-z .'-]{1,40} live\b", "2.1", 2),
    (r"\bwithout (them|him|her|anyone) knowing\b", "5.2", 3),
    (r"\b(track|spy on|monitor|read|follow) (my |his |her |their )?(wife|husband|girlfriend|boyfriend|partner|ex|"
     r"employee|employees|neighbou?r|kid|child|daughter|son)('?s)?\b", "4.1", 3),
    (r"\b(stalk|stalking|stalkerware|spyware)\b", "4.1", 4),
    (r"\bhack(ing)? into\b", "4.2", 3),
    (r"\bbreak into (a |the |their |his |her |my )?(account|server|site|website|network|wifi|wi-fi|phone|email)\b", "4.2", 3),
    (r"\b(ddos|dos attack)\b", "4.2", 4),
    (r"\btake (it|them|their site|the site|the server|their server|their website) down\b", "4.2", 3),
    (r"\bbypass (the )?(login|authentication|2fa|mfa|captcha|paywall)\b", "4.2", 3),
    (r"\b(ransomware|keylogger|botnet|rootkit|zero[- ]day exploit)\b", "4.2", 3),
    (r"\bcrack (the |a |their |his |her )?(password|wifi|wi-fi|hash)", "4.2", 3),
    (r"\bsteal (their |his |her |the |someone'?s )?(password|passwords|credentials|cookies|session|identity|data)\b", "2.1", 4),
    (r"\bphishing (email|page|site|kit|link|campaign)\b", "4.3", 4),
    (r"\bfake (invoice|review|reviews|receipt|id|identity|login page|bank statement)\b", "4.3", 3),
    (r"\bimpersonat(e|ing)\b", "4.3", 2),
    (r"\bpretend(ing)? to be (from )?(the |a |my |their )?(bank|police|irs|tax office|support|ceo|boss|manager)\b", "4.3", 4),
    (r"\b(scam|scamming|con them)\b", "4.3", 2),
    (r"\bdeepfake\b", "4.3", 2),
    (r"\bharass(ment|ing)?\b", "1.2", 3),
    (r"\b(threatening|threat) (message|letter|email|note)\b", "1.2", 3),
    (r"\b(fake news|disinformation|astroturf(ing)?)\b", "3.1", 2),
    (r"\b(spread|write|generate) (misinformation|propaganda)\b", "3.1", 3),
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[-_]", " ", str(text or "").lower())).strip()


def _distinct_malware(name: str) -> bool:
    """A malware family's name is a phrase worth matching only when nobody says it by accident:
    a digit, a capital after a small letter (TrickBot), or seven or more capitals (BLINDINGCAN)."""
    n = str(name or "").strip()
    if len(n) < 4:
        return False
    if re.search(r"\d", n) or re.search(r"[a-z][A-Z]", n):
        return True
    return n.isupper() and len(n) >= 7 and " " not in n


# --- building it from the sources ---------------------------------------------------------

def build(attack: dict, atlas: dict | None, fetched_at: float | None = None) -> dict:
    """The library, from ATT&CK's STIX bundle and ATLAS's YAML. Pure: the same two files give the
    same library, so a review of the change is a review of the sources."""
    objs = [o for o in (attack or {}).get("objects", [])
            if not o.get("revoked") and not o.get("x_mitre_deprecated")]
    by_id = {o["id"]: o for o in objs if o.get("id")}
    ext = lambda o: next((r.get("external_id") for r in o.get("external_references", [])   # noqa: E731
                          if r.get("source_name") == "mitre-attack"), "")
    tactics_of = {o["id"]: [k["phase_name"] for k in o.get("kill_chain_phases", [])]
                  for o in objs if o["type"] == "attack-pattern"}
    uses: dict = defaultdict(list)
    for r in objs:
        if r.get("type") == "relationship" and r.get("relationship_type") == "uses" \
                and r.get("target_ref") in tactics_of and r.get("source_ref") in by_id:
            uses[r["source_ref"]].append(r["target_ref"])
    version = next((o.get("x_mitre_version") for o in objs if o["type"] == "x-mitre-collection"), "")

    programs: dict = {}
    for o in objs:
        if o["type"] != "tool":
            continue
        name = o["name"]
        key = _norm(name)
        tac = Counter(t for ap in uses.get(o["id"], []) for t in tactics_of.get(ap, []))
        main = next((t for t, _ in tac.most_common() if t in TOOL_KIND), "")
        kind = "dual-use" if key in DUAL_USE or key.split(".")[0] in DUAL_USE else TOOL_KIND.get(main, "probe")
        techs = sorted({ext(by_id[ap]) for ap in uses.get(o["id"], []) if ap in by_id})[:6]
        entry = {"name": name, "kind": kind, "weight": 0 if kind == "dual-use" else 3,
                 "category": TACTIC_CATEGORY.get(main, "4.2"), "source": "attack", "ref": ext(o),
                 "techniques": techs}
        for alias in {key, *(_norm(a) for a in o.get("x_mitre_aliases") or [])}:
            for form in {alias, alias.replace(" ", ""), alias.replace(" ", "-")}:
                if form and len(form) >= 2:
                    programs.setdefault(form, entry)

    phrases: dict = {}
    for o in objs:
        if o["type"] != "attack-pattern":
            continue
        tac = [t for t in tactics_of.get(o["id"], []) if t in TACTIC_WEIGHT]
        if not tac:
            continue
        name = _norm(o["name"])
        if name in GENERIC or (" " not in name and len(name) < 6):
            continue
        w = max(TACTIC_WEIGHT[t] for t in tac)
        phrases.setdefault(name, {"phrase": name, "weight": w, "category": TACTIC_CATEGORY[tac[0]],
                                  "source": "attack", "ref": ext(o), "title": o["name"]})
    for o in objs:
        if o["type"] != "malware" or not _distinct_malware(o["name"]):
            continue
        for alias in [o["name"], *(o.get("x_mitre_aliases") or [])]:
            if _distinct_malware(alias):
                phrases.setdefault(_norm(alias), {"phrase": _norm(alias), "weight": 1, "category": "4.2",
                                                  "source": "attack", "ref": ext(o),
                                                  "title": f"{o['name']} (malware)"})

    atlas_version = ""
    if atlas:
        atlas_version = str(atlas.get("version") or "")
        for m in atlas.get("matrices") or []:
            for t in m.get("techniques") or []:
                tw = [ATLAS_TACTIC_WEIGHT[x] for x in t.get("tactics") or [] if x in ATLAS_TACTIC_WEIGHT]
                name = _norm(t.get("name"))
                if not tw or name in GENERIC or (" " not in name and len(name) < 6):
                    continue
                phrases.setdefault(name, {"phrase": name, "weight": max(tw), "category": "2.2",
                                          "source": "atlas", "ref": t.get("id", ""), "title": t.get("name")})

    curated = [{"pattern": p, "category": c, "weight": w, "source": "bento"} for p, c, w in CURATED]
    return {"format": "bento-ethics-library/1", "built_at": int(fetched_at or time.time()),
            "versions": {"attack": version, "atlas": atlas_version},
            "sources": SOURCES, "categories": CATEGORIES,
            "programs": dict(sorted(programs.items())), "phrases": dict(sorted(phrases.items())),
            "curated": curated}


def write_shipped(lib: dict, path: Path = SHIPPED) -> None:
    path.write_text(json.dumps(lib, indent=0, sort_keys=True, ensure_ascii=False) + "\n")


# --- reading it -------------------------------------------------------------------------

_CACHE: dict = {"key": None, "lib": None, "rx": None}


def _overlay_path() -> Path:
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME) / OVERLAY_NAME


def _merge(base: dict, extra: dict) -> dict:
    """The overlay may only ADD: new names, and a higher weight for a name already there."""
    out = json.loads(json.dumps(base))
    for section in ("programs", "phrases"):
        for k, v in (extra.get(section) or {}).items():
            have = out[section].get(k)
            if have is None:
                out[section][k] = v
            elif (v.get("weight") or 0) > (have.get("weight") or 0):
                have["weight"] = v["weight"]
    out["versions"] = {**base.get("versions", {}), **{f"{k} (update)": v for k, v in
                                                      (extra.get("versions") or {}).items() if v}}
    out["updated_at"] = extra.get("built_at")
    return out


def load() -> dict:
    """The shipped library with the machine's overlay merged in, read once per change."""
    try:
        ov = _overlay_path()
        key = (SHIPPED.stat().st_mtime, ov.stat().st_mtime if ov.exists() else 0)
    except OSError:
        key = None
    if _CACHE["lib"] is not None and _CACHE["key"] == key:
        return _CACHE["lib"]
    try:
        lib = json.loads(SHIPPED.read_text())
    except (OSError, ValueError):
        lib = {"programs": {}, "phrases": {}, "curated": [], "sources": SOURCES, "categories": CATEGORIES,
               "versions": {}, "missing": True}
    try:
        ov = _overlay_path()
        if ov.exists():
            lib = _merge(lib, json.loads(ov.read_text()))
    except (OSError, ValueError):
        pass
    _CACHE.update(key=key, lib=lib, rx=None)
    return lib


def _matcher():
    lib = load()
    if _CACHE["rx"] is None:
        names = sorted(lib.get("phrases", {}), key=len, reverse=True)
        big = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(n) for n in names) + r")(?![a-z0-9])") \
            if names else None
        cur = [(re.compile(c["pattern"], re.I), c) for c in lib.get("curated", [])]
        _CACHE["rx"] = (big, cur)
    return _CACHE["rx"]


def program(name: str) -> dict | None:
    """What the library knows about a program a command runs ('impacket-secretsdump',
    'mimikatz.exe', 'crackmapexec'), or None."""
    base = _norm(re.sub(r"\.(exe|py|ps1|sh)$", "", str(name or "").lower().rsplit("/", 1)[-1]))
    progs = load().get("programs", {})
    for form in (base, base.replace(" ", ""), base.split(" ")[0], base.split("-")[0]):
        if form in progs:
            return progs[form]
    return None


def mentions(text: str, limit: int = 8) -> list[dict]:
    """The library's phrases in a person's (or a task's) words. Saying one is context: it adds to
    the conversation's score and is shown with its source, and it never refuses anything."""
    t = _norm(text)[:6000]
    if not t:
        return []
    big, cur = _matcher()
    out, seen = [], set()
    for rx, c in cur:
        m = rx.search(t)
        if m and c["pattern"] not in seen:
            seen.add(c["pattern"])
            out.append({"phrase": m.group(0), "weight": c["weight"], "category": c["category"],
                        "source": "bento", "ref": "", "title": m.group(0)})
            # a phrase inside one already counted is not counted again ("phishing" in "phishing email")
            t = t[:m.start()] + " " * (m.end() - m.start()) + t[m.end():]
    if big is not None:
        phrases = load().get("phrases", {})
        for m in big.finditer(t):
            p = phrases.get(m.group(1))
            if p and m.group(1) not in seen:
                seen.add(m.group(1))
                out.append(dict(p))
    out.sort(key=lambda x: -x["weight"])
    return out[:limit]


def summary() -> dict:
    lib = load()
    progs = lib.get("programs", {})
    kinds = Counter(v.get("kind") for v in {v.get("name"): v for v in progs.values()}.values())
    by_src = Counter(p.get("source") for p in lib.get("phrases", {}).values())
    return {"versions": lib.get("versions", {}), "built_at": lib.get("built_at"),
            "updated_at": lib.get("updated_at"), "missing": bool(lib.get("missing")),
            "sources": list(lib.get("sources", SOURCES).values()),
            "categories": lib.get("categories", CATEGORIES),
            "programs": len({v.get("name") for v in progs.values()}), "kinds": dict(kinds),
            "phrases": len(lib.get("phrases", {})), "by_source": dict(by_src),
            "curated": len(lib.get("curated", []))}


async def update() -> dict:
    """Fetch the two catalogues again and write what they ADD to the machine's overlay. An admin's
    act (the route checks); it changes nothing that is shipped and lowers nothing."""
    import yaml
    from . import netguard
    st, _, body = await netguard.read_capped(ATTACK_URL, 160 * 1024 * 1024, timeout=300)
    if st != 200:
        raise RuntimeError(f"MITRE ATT&CK answered {st}")
    attack = json.loads(body)
    st2, _, body2 = await netguard.read_capped(ATLAS_URL, 16 * 1024 * 1024, timeout=120)
    atlas = yaml.safe_load(body2) if st2 == 200 else None
    fresh = build(attack, atlas)
    shipped = json.loads(SHIPPED.read_text()) if SHIPPED.exists() else {"programs": {}, "phrases": {}}
    add = {"built_at": fresh["built_at"], "versions": fresh["versions"],
           "programs": {k: v for k, v in fresh["programs"].items() if k not in shipped.get("programs", {})},
           "phrases": {k: v for k, v in fresh["phrases"].items() if k not in shipped.get("phrases", {})}}
    _overlay_path().write_text(json.dumps(add, sort_keys=True))
    _CACHE.update(key=None, lib=None, rx=None)
    return {"added_programs": len(add["programs"]), "added_phrases": len(add["phrases"]),
            "versions": fresh["versions"], "atlas": atlas is not None}


if __name__ == "__main__":       # python -m agentos.ethicslib ATTACK.json ATLAS.yaml  → rebuild the shipped file
    import sys
    import yaml
    a = json.loads(Path(sys.argv[1]).read_text())
    b = yaml.safe_load(Path(sys.argv[2]).read_text()) if len(sys.argv) > 2 else None
    lib = build(a, b)
    write_shipped(lib)
    print(json.dumps(summary(), indent=1)[:2000])

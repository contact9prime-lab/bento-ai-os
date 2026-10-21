"""The inventory: every machine on this network that Bento knows, one row each.

Asked for with the Network tab: "it should install and also make sure it maintains the
inventory and secures the box too". Four places already knew about machines, each its own
half: the devices a scan or mDNS heard (provision.load()["devices"]), Bento machines heard
waiting or set up (provision seen/enabled), machines linked by hand (teamlink) and the
community's members. `rows()` folds them into one list keyed by MAC when known, else by
address, so a Pi that was heard without Bento, installed, set up and linked is one row
whose story moves, not four rows that each tell part of it.

What the inventory adds of its own is small and kept in `inventory.json`: the security
state each machine was last MEASURED at (harden.check, never "the run finished"), when, by
whom, the SSH user that worked, and a label a person gave it. Everything else is read from
its source every time, so the list cannot disagree with the screens it summarises.

Kept free of HTTP and asyncio, like jobs.py: `bento network` reads the same rows with the
server down.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MAX_ROWS = 256
STALE_S = 7 * 24 * 3600          # "not heard for a week" is said, never hidden


def _home() -> Path:
    from . import teamlink
    return teamlink.home()


def path() -> Path:
    return _home() / "inventory.json"


def load() -> dict:
    try:
        d = json.loads(path().read_text())
        if isinstance(d, dict) and isinstance(d.get("devices"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"devices": {}}


def save(d: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if len(d["devices"]) > MAX_ROWS:
        for k, _ in sorted(d["devices"].items(), key=lambda kv: kv[1].get("at", 0))[:len(d["devices"]) - MAX_ROWS]:
            d["devices"].pop(k, None)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(p)


def _key_for(ip: str, mac: str = "") -> str:
    return (mac or ip or "").lower()


def record(ip: str, mac: str = "", **fields) -> dict:
    """Write what Bento itself learned about a machine (its security, the user that worked, a
    label). Keyed as `rows()` keys it, so the note lands on the same row."""
    d = load()
    key = _key_for(ip, mac)
    if not key:
        raise ValueError("a machine needs an address")
    # a row first noted by address and later learned by MAC is one machine
    if mac and mac.lower() not in d["devices"]:
        for k, e in list(d["devices"].items()):
            if e.get("ip") == ip and not e.get("mac"):
                d["devices"][mac.lower()] = d["devices"].pop(k)
                break
    e = d["devices"].setdefault(key, {})
    e.update({k: v for k, v in fields.items() if v is not None})
    e["ip"], e["at"] = ip, time.time()
    if mac:
        e["mac"] = mac.lower()
    save(d)
    return e


def note_security(ip: str, mac: str, done: dict, user: str, by: str = "") -> dict:
    from . import harden
    clean = {s: bool(done.get(s)) for s in harden.IDS}
    return record(ip, mac, security={"done": clean, "at": time.time(), "by": by}, user=user)


def set_label(ip: str, mac: str, label: str) -> dict:
    from . import teamlink
    return record(ip, mac, label=teamlink.plain(label, 40, newlines=False).strip())


def forget(key: str) -> bool:
    d = load()
    if d["devices"].pop(str(key).lower(), None) is None:
        return False
    save(d)
    return True


def _security_words(sec: dict | None) -> tuple[str, int]:
    from . import harden
    if not sec:
        return "not checked", -1
    n = sum(1 for s in harden.IDS if (sec.get("done") or {}).get(s))
    total = len(harden.IDS)
    return ("secured" if n == total else f"{n} of {total} in place"), n


def rows(cfg: dict | None = None) -> list[dict]:
    """Every machine Bento knows on this network, newest heard first."""
    from . import netscan, provision, teamlink
    pd = provision.load()
    mine = load()["devices"]
    out: dict[str, dict] = {}
    by_ip: dict[str, str] = {}

    def row(ip: str, mac: str = "") -> dict:
        key = _key_for(ip, mac)
        if ip and ip in by_ip and by_ip[ip] != key:
            old = by_ip[ip]
            if mac and not out[old].get("mac"):
                out[key] = out.pop(old)
                by_ip[ip] = key
            else:
                key = old
        r = out.setdefault(key, {"key": key, "ip": ip, "mac": mac, "name": "", "maker": "", "board": "",
                                 "os": "", "bento": "none", "ssh": False, "owner": "", "via": "",
                                 "last": 0, "first": 0, "sources": []})
        if ip:
            by_ip[ip] = key
            r["ip"] = r["ip"] or ip
        if mac:
            r["mac"] = r["mac"] or mac
        return r

    for e in pd.get("devices", {}).values():           # heard or scanned, Bento or not
        r = row(e.get("ip") or "", (e.get("mac") or "").lower())
        r.update({k: e[k] for k in ("name", "maker", "os") if e.get(k) and not r.get(k)})
        r["ssh"] = r["ssh"] or bool(e.get("ssh"))
        r["ports"] = e.get("ports") or []
        r["pi"] = bool(e.get("pi"))
        r["seen_by"] = e.get("seen_by") or r.get("seen_by") or ""
        r["ignored"] = e.get("state") == "ignored"
        if e.get("state") == "installed" and r["bento"] == "none":
            r["bento"] = "installed"
        r["last"] = max(r["last"], e.get("last", 0))
        r["first"] = min(x for x in (r["first"], e.get("first", 0)) if x) if r["first"] else e.get("first", 0)
        r["sources"].append("scan")
    for m in provision.seen_list():                    # Bento waiting or set up
        r = row(m.get("addr") or "")
        hw = m.get("hw") or {}
        r["name"] = m.get("name") or r["name"]
        r["board"] = hw.get("board") or hw.get("arch") or r["board"]
        r["ram_mb"] = hw.get("ram_mb") or r.get("ram_mb", 0)
        r["bento"] = "set up" if m.get("state") == "enabled" else "waiting"
        r["version"] = m.get("version") or ""
        r["owner"] = m.get("owner") or ""
        r["via"] = m.get("via") or ""
        r["fp"] = m.get("fp")
        r["last"] = max(r["last"], m.get("last", 0))
        r["sources"].append("setup")
    by_fp = {r["fp"]: r for r in out.values() if r.get("fp")}
    for lk in teamlink.links(pool=True):               # linked by hand, or a community member
        if lk.get("kind") not in ("machine", "pool") or not lk.get("host"):
            continue
        r = by_fp.get(lk.get("peer_host_fp") or "") or row(str(lk["host"]))
        r["name"] = r["name"] or lk.get("label", "")
        if r["bento"] in ("none", "installed"):
            r["bento"] = "linked"
        if lk.get("peer_host_fp"):
            r["fp"] = r.get("fp") or lk["peer_host_fp"]
            by_fp[r["fp"]] = r
        r.setdefault("links", []).append({"label": lk.get("label", ""), "owner": lk.get("owner") or "",
                                          "kind": lk.get("kind")})
        r["sources"].append("link")
    try:
        from . import pool
        members = pool.load().get("members") or {}
    except Exception:
        members = {}
    for fp, m in members.items():                       # this machine leads them
        if m.get("state") != "member":
            continue
        host = m.get("host") or m.get("addr")
        r = by_fp.get(fp) or (row(str(host)) if host else None)
        if r is None:
            continue
        r["community"] = m.get("name") or fp[:12]
        r["fp"] = r.get("fp") or fp
    for key, e in mine.items():                        # what Bento measured itself
        r = out.get(key) or (out.get(by_ip.get(e.get("ip") or "", "")) if e.get("ip") else None)
        if r is None:
            r = row(e.get("ip") or "", e.get("mac") or "")
            r["sources"].append("kept")
        if e.get("label"):
            r["label"] = e["label"]
        r["user"] = e.get("user", "")
        r["security"] = e.get("security")
    now = time.time()
    for r in out.values():
        r["security_words"], r["secured_n"] = _security_words(r.get("security"))
        # a Pi that is there with SSH shut: say how to open it, rather than offer a button
        # that cannot log in (a machine running Bento is reached another way)
        r["ssh_off"] = netscan.ssh_off_words(r) if r["bento"] == "none" else ""
        r["display"] = r.get("label") or r["name"] or r["ip"]
        r["stale"] = bool(r["last"]) and now - r["last"] > STALE_S
        r["links"] = [lk for lk in r.get("links", []) if lk["kind"] == "machine"]
        r["connections"] = connections(r)
        r["age"] = int(now - r["last"]) if r["last"] else None
    return sorted(out.values(), key=lambda r: (-(r["last"] or 0), r["ip"]))


def connections(r: dict) -> list[dict]:
    """What ties this machine to that one, each a thing Disconnect can undo: a link (its
    agents may ask ours, and it may be a Zero answered here), its place in the community
    this machine leads, and this machine's SSH key in its authorized_keys (which is what
    lets Bento log in with no password)."""
    out = [{"id": "link:" + lk["label"], "kind": "link", "label": lk["label"], "owner": lk["owner"],
            "words": f"the link “{lk['label']}”"} for lk in r.get("links", [])]
    if r.get("community"):
        out.append({"id": "community", "kind": "community", "words": "its place in your community"})
    if ((r.get("security") or {}).get("done") or {}).get("key"):
        out.append({"id": "key", "kind": "key", "words": "this machine’s SSH key on it"})
    return out


def find(rows_: list[dict], what: str) -> dict | None:
    w = str(what or "").strip().lower()
    for r in rows_:
        if w and w in (r["key"], (r["ip"] or "").lower(), (r.get("mac") or "").lower(),
                       (r["name"] or "").lower(), (r.get("label") or "").lower()):
            return r
    return None


def summary(rows_: list[dict]) -> dict:
    return {"machines": len(rows_), "bento": sum(1 for r in rows_ if r["bento"] != "none"),
            "secured": sum(1 for r in rows_ if r["security_words"] == "secured"),
            "unchecked": sum(1 for r in rows_ if r["secured_n"] < 0)}

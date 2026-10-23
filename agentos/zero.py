"""A Zero: a small machine (a Pi Zero, any Pi, an old laptop) that runs no brain and keeps
no agents of its own, set up by one command and run from the hub.

Asked for as "another download to make a zero agent pi using curl on the repo, that would
install the zero agent and Tailscale and connect to the main hub … zero touch on the same
network … it should broadcast over Tailscale or the local network, that gets captured … and
this agent gets a provisioning profile which is always standardized … and when the main hub
becomes the point of execution, the pi may need files shipped back to it".

It is provisioning (provision.py) with four things added, and nothing beside it:

  * THE ONE LINE. `bento pool zero` (and Settings → New machines) prints a curl command for
    install.sh with `--zero`: Light mode, no questions, the hub's automatic enrolment key,
    the hub's addresses, and optionally a Tailscale auth key. The Tailscale key is put in the
    line and NEVER stored here; a person pasting it chose to.
  * HEARD WHERE IT IS. Tailscale carries no broadcasts, so a Zero announces to each hub
    address as well as to its LAN's broadcast. The hub says which way it arrived (`via`),
    read from the address it came FROM, never from what the beacon says about itself.
  * ONE STANDARD PROFILE. The hub keeps one (provision.standard): name, agent name, Light
    mode, kiosk, where work runs, and the agents with their executors. Every machine it sets
    up gets it, under whatever a key or a person adds; an automatic key sets a heard Zero up
    with no question asked, which is still a ledger row and a toast.
  * THE HUB WORKS, THE FILES COME BACK. With `execution: hub` the Zero's lead hands tasks to
    the hub's lead (both cells written at the claim, so nobody is asked on a machine nobody
    sits at), and files the hub's answer names travel back with it into the Zero's workspace
    (`from-<hub>/`), capped, a ledger row on both sides.

Kept free of HTTP and asyncio, like provision.py's file half.
"""
from __future__ import annotations

import base64
import ipaddress
import os
import re
import shutil
import subprocess
from pathlib import Path

#: Tailscale's addresses: the CGNAT range it hands out, and its IPv6 prefix.
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
MAX_HUBS = 4                     # addresses a Zero announces to
SHIP_FILES = 8                   # files one answer may carry back
SHIP_FILE_CAP = 1_500_000        # bytes, one file
SHIP_TOTAL_CAP = 2_500_000       # bytes, all of them (base64 fits a pinned peer's 4 MiB line)
EXECUTIONS = ("hub", "here")
#: What the hub's lead may do with its own Zero's task without a card: hand it to one of
#: this machine's specialists or departments (fabric._lead_for_link).
HUB_HANDOVERS = ("delegate", "department_task")


# ---- where it came from ------------------------------------------------------------------

def via(addr: str) -> str:
    """'tailscale' for an address in Tailscale's ranges, else 'local network'. Read from the
    address a beacon ARRIVED from: a beacon's own words are a stranger's."""
    try:
        ip = ipaddress.ip_address(str(addr or "").split("%")[0])
    except ValueError:
        return "local network"
    if (ip.version == 4 and ip in TAILNET_V4) or (ip.version == 6 and ip in TAILNET_V6):
        return "tailscale"
    return "local network"


def via_words(v: str) -> str:
    return "over Tailscale" if v == "tailscale" else "on the local network"


_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[?[0-9A-Fa-f:]{2,39}\]?")


def clean_hubs(items) -> list[str]:
    """Hub addresses a Zero announces to: host names or IP addresses, no ports, no schemes,
    at most MAX_HUBS. Anything else is dropped."""
    if isinstance(items, str):
        items = [items]
    flat = [x for it in (items or []) for x in re.split(r"[,\s]+", str(it or ""))]
    out: list[str] = []
    for a in flat:
        a = str(a or "").strip().strip("[]")
        if a and _HOST.fullmatch(a) and a not in out:
            out.append(a)
    return out[:MAX_HUBS]


# ---- this hub's addresses, for the one line -----------------------------------------------

def tailscale_ip() -> str:
    """This machine's Tailscale IPv4 address, or '' (not installed, not up)."""
    exe = shutil.which("tailscale")
    if not exe:
        return ""
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for ln in out.splitlines():
        if via(ln.strip()) == "tailscale":
            return ln.strip()
    return ""


def lan_ips() -> list[str]:
    """This machine's private IPv4 addresses, read without asking anything outside."""
    import socket
    out: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))   # no packet leaves: it only picks the route
            out.append(s.getsockname()[0])
        finally:
            s.close()
    except OSError:
        pass
    try:
        for a in socket.gethostbyname_ex(socket.gethostname())[2]:
            if a not in out:
                out.append(a)
    except OSError:
        pass
    keep = []
    for a in out:
        try:
            ip = ipaddress.ip_address(a)
        except ValueError:
            continue
        if ip.is_private and not ip.is_loopback and via(a) != "tailscale":
            keep.append(a)
    return keep


def hub_addresses() -> list[dict]:
    """Where a Zero can find this hub: the Tailscale address first (it works from anywhere
    on the tailnet), then the local ones."""
    out = []
    ts = tailscale_ip()
    if ts:
        out.append({"addr": ts, "via": "tailscale"})
    out += [{"addr": a, "via": "local network"} for a in lan_ips()]
    return out[:MAX_HUBS]


_TSKEY = re.compile(r"tskey-[A-Za-z0-9_-]{8,200}")


def one_line(cfg: dict, key_text: str, hubs: list[str], tailscale_key: str = "") -> str:
    """The command a person pastes on the Pi. `tailscale_key` goes into the line only; it is
    never written anywhere on this machine."""
    from . import updates
    if tailscale_key and not _TSKEY.fullmatch(tailscale_key.strip()):
        raise ValueError("that is not a Tailscale auth key (it starts with tskey-)")
    url = f"{updates.raw_base(cfg)}/master/install.sh"
    parts = ["--zero", f"--enroll={key_text}"]
    hubs = clean_hubs(hubs)
    if hubs:
        parts.append("--hub=" + ",".join(hubs))
    if tailscale_key:
        parts.append(f"--tailscale-key={tailscale_key.strip()}")
    return f"curl -fsSL {url} | sh -s -- " + " ".join(parts)


# ---- the machine it became ----------------------------------------------------------------

def state(cfg: dict) -> dict:
    """{'hub': link label, 'execution': 'hub'|'here'} on a Zero, {} elsewhere."""
    z = (cfg or {}).get("zero")
    return z if isinstance(z, dict) and z.get("hub") else {}


def runs_on_hub(cfg: dict) -> bool:
    return state(cfg).get("execution") == "hub"


def note(cfg: dict, prefix: str = "mcp__bento__") -> str:
    """What the lead of a Zero is told: where its work runs and how to send it there."""
    z = state(cfg)
    if not z or z.get("execution") != "hub":
        return ""
    hub = z["hub"]
    return (f"\n\nTHIS MACHINE IS A ZERO. Its work runs on {hub}, the hub that set it up. For "
            f"anything that needs more than a short answer, hand the whole task to the hub's lead "
            f"with {prefix}delegate {{\"subagent\": \"lead@{hub}\", \"task\": ...}} and pass on what "
            f"comes back. Files the hub makes arrive in this machine's workspace, in from-{hub}/, "
            f"and the answer names them.")


def ships_to(lk: dict | None) -> bool:
    """Does this hub send files back to the machine behind `lk`? Only to a machine it set up
    itself to run its work here (provision `enabled[fp].execution == 'hub'`): your own
    devices. Another person's linked team gets words, never this machine's files."""
    from . import provision
    if not lk or lk.get("kind") != "machine":
        return False
    e = provision.load()["enabled"].get(str(lk.get("peer_host_fp") or ""))
    return bool(e) and e.get("execution") == "hub"


def is_my_hub(cfg: dict, lk: dict | None) -> bool:
    """Is `lk` the link to the hub that set this machine up?"""
    from . import provision
    if not lk or lk.get("kind") != "machine":
        return False
    c = provision.load().get("claimed") or {}
    return bool(c.get("leader_fp")) and c.get("leader_fp") == lk.get("peer_host_fp")


# ---- what the hub may do for it -------------------------------------------------------------

def folder_for(cfg: dict, label: str) -> Path:
    """Where the hub's agents put what they make for one Zero: `<workspace>/for-<label>`."""
    return Path(os.path.realpath(os.path.expanduser(str((cfg or {}).get("workspace") or "~/AgentOS")))) \
        / f"for-{safe_name(label)}"


def zero_standing(store, cfg: dict, label: str) -> list[str]:
    """The hub's half of a Zero that runs its work here. Every task from it is a linked
    team's, so it is untrusted, and a step that writes would wait for a person who is not
    there. This row lets ANY of this machine's agents write into that Zero's own folder
    without asking (a report through save_report needs nothing: it is safe already). It is
    an ordinary standing permission (policy._standing reads agent '*' only on a provision
    row), shown in Permissions, and revoked with the link (fabric.forget_link_grants)."""
    from .policy import standing_refusal, standing_resource
    folder = folder_for(cfg, label)
    folder.mkdir(parents=True, exist_ok=True)
    want = [("fs.write", f"fs:{folder}/*")]
    have = {g.get("resource") for g in store.list_grants(principal_kind="team", principal_id=f"{label}/*")
            if g.get("action") == "team.act" and g.get("source") == "provision"}
    made = []
    for action, scope in want:
        if standing_refusal(action, scope):
            continue
        res = standing_resource("*", action, scope)
        if res in have:
            continue
        store.add_grant("team", f"{label}/*", "team.act", res, source="provision",
                        note=f"the Zero {label} may have any agent here {action} {scope} without asking")
        made.append(f"{action} {scope}")
    return made


def hub_side(store, cfg: dict, label: str) -> list[str]:
    """Everything the hub writes when it sets up a Zero whose work runs here, in one place
    for the desktop and the terminal: its lead may hand whole tasks to this machine's lead
    (the link's cell, written now because nobody sits at a Zero to answer the first card),
    and the standing permission above."""
    from . import fabric as fabricmod
    acc = fabricmod.link_access(store, label)
    fabricmod.set_link_access(store, label, sorted(set(acc["theirs_may_ask"]) | {fabricmod.LEAD}))
    return ["its lead may hand tasks to this machine's lead"] + zero_standing(store, cfg, label)


def hub_note(cfg: dict, lk: dict | None) -> str:
    """What the hub's lead is told about a task from one of its own Zeros."""
    if not ships_to(lk):
        return ""
    return (f"\n\n{lk['label']} is a Zero this machine set up, and its work runs here. Files you "
            f"made for it go in {folder_for(cfg, lk['label'])} or through save_report (tell whoever "
            f"you hand it to); name each one by its full path in your answer and it is sent back "
            f"to {lk['label']} with it.")


# ---- files going back ------------------------------------------------------------------------

def pack(text: str, roots: list[Path]) -> tuple[list[dict], list[str]]:
    """The files `text` names under `roots`, as they travel: ([{name, size, data}], [left]).
    `left` names what was too big or one too many, said in the answer rather than dropped."""
    from . import outputs
    files, left, total = [], [], 0
    for f in outputs.mentioned(text, roots, limit=SHIP_FILES * 2):
        p = Path(f["path"])
        size = int(f.get("size") or 0)
        if len(files) >= SHIP_FILES or size > SHIP_FILE_CAP or total + size > SHIP_TOTAL_CAP:
            left.append(f"{f['name']} ({outputs.size_words(size)})")
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        total += len(data)
        files.append({"name": p.name, "size": len(data), "data": base64.b64encode(data).decode()})
    return files, left


_SAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(name: str) -> str:
    n = _SAFE.sub("_", os.path.basename(str(name or "")).strip()).strip(" .")[:80]
    return n or "file"


def unpack(files, workspace: Path, hub: str) -> list[Path]:
    """Write files that came back from the hub into `<workspace>/from-<hub>/`. A name is
    reduced to a plain basename, a clash gets a number, and anything over the caps or not
    base64 is skipped: what arrives is the other machine's bytes."""
    if not isinstance(files, list):
        return []
    dest = Path(workspace) / f"from-{safe_name(hub)}"
    out: list[Path] = []
    total = 0
    for f in files[:SHIP_FILES]:
        if not isinstance(f, dict):
            continue
        try:
            data = base64.b64decode(str(f.get("data") or ""), validate=True)
        except (ValueError, TypeError):
            continue
        if len(data) > SHIP_FILE_CAP or total + len(data) > SHIP_TOTAL_CAP:
            continue
        total += len(data)
        dest.mkdir(parents=True, exist_ok=True)
        name = safe_name(f.get("name"))
        p, n = dest / name, 2
        while p.exists():
            stem, dot, ext = name.rpartition(".")
            p = dest / (f"{stem}-{n}.{ext}" if dot and stem else f"{name}-{n}")
            n += 1
        p.write_bytes(data)
        out.append(p)
    return out


def files_line(paths: list[Path], hub: str, left: list[str] | None = None) -> str:
    """The sentence added to an answer that brought files: the local paths, so Chat's chips,
    Telegram's send_files and the next turn all find them."""
    s = ""
    if paths:
        s += f"\n\nFiles from {hub}, saved on this machine: " + ", ".join(f"`{p}`" for p in paths)
    if left:
        s += f"\n\nLeft on {hub} (too big to send back): " + ", ".join(left)
    return s



# ---- a Zero's chat runs on its hub -------------------------------------------------------

def chat_on_hub(cfg: dict) -> bool:
    """Does a person's chat on this machine run on its hub? On a Zero set to work there,
    unless `zero.chat: here` keeps it local (a hub that is away for good)."""
    from . import zeromind
    return runs_on_hub(cfg) and state(cfg).get("chat", "hub") != "here" and zeromind.on_hub(cfg)


async def hub_turn(cfg: dict, conversation_id: str, text: str, emit) -> dict:
    """One turn of a person's chat, worked on the hub (fabric.zero_chat there). What comes
    back is the reply, which the caller saves here as the screen's copy. A hub that cannot
    be reached is said in a sentence; nothing is answered locally in its place."""
    from . import teamlink, zeromind, linkfiles, executors as execmod
    lk = zeromind.hub_link(cfg)
    hub = (lk or {}).get("label") or state(cfg).get("hub") or "the hub"
    if not lk:
        return {"content": f"[error] this machine has no link to {hub}, where its chats run",
                "steps": [], "tokens": {"input": 0, "output": 0}}

    async def progress(t: str, secs: int):
        if t and t != "received":
            await emit({"type": "status", "message": f"{hub}: {t}"})
    await emit({"type": "status", "message": f"thinking on {hub}"})
    try:
        got = await teamlink.call(lk, {"op": "zero_chat", "text": text, "conversation": conversation_id,
                                       "agent": str(cfg.get("agent_name") or "")[:40],
                                       "progress": 1}, on_progress=progress, limit=teamlink.POOL_LINE)
    except Exception as e:
        got = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if not got.get("ok"):
        why = teamlink.plain(got.get("error") or "no answer", 300, newlines=False)
        if "unknown request" in why:
            return {"fallback": f"{hub} runs an older Bento, so this machine answers itself until it is updated"}
        return {"content": f"[error] {hub} could not answer: {why}", "steps": [],
                "tokens": {"input": 0, "output": 0}}
    out = teamlink.plain(got.get("text") or "(no answer)", 6000)
    if got.get("files"):
        from pathlib import Path
        paths = linkfiles.receive(got.get("files"), Path(execmod.default_workspace(cfg)), lk["label"])
        out += files_line(paths, lk["label"], got.get("left"))
    await emit({"type": "text_delta", "text": out})
    return {"content": out, "steps": [{"type": "text", "text": out}],
            "tokens": {"input": 0, "output": 0}, "engine": f"hub:{hub}",
            "engine_model": teamlink.plain(got.get("model", ""), 80, newlines=False)}

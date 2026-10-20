"""Files across a linked team's hand-over, both ways.

Asked for as "in teams mode, where permissions are defined and agents hand off tasks, the
blobs should be sent back to the main agent: if the main agent asks an agent on another
machine to build a ppt, the file has to come back once done; and files on one computer
may be what the other acts on".

Two directions, each its own consent:

  * OUT, with the task. The lead's `delegate` to `name@team` may carry `files`. Sending
    this machine's files to another team is `file.send` on `team:<label>`, a decision of
    its own in the agent loop beside the matrix's `agent.message` (agent._files_out): it
    asks at the usual autonomy, "Allow & remember" makes it standing for that team, and
    after untrusted content it is a person's. Only files under this machine's own roots
    (outputs.roots), never a hidden one, capped.
  * BACK, with the answer. What the other side's agents MADE for the task (written during
    it, named in the answer, under its roots) comes back. That is the answering side's
    `file.send` on `files:made` for principal `team:<label>/*`: on with the link's cells
    (written the first time it is needed, an ordinary grant), switched off per link in
    Settings or `bento link files`, which writes a deny. With it, any of this machine's
    agents may write into `for-<label>/` for that team (a standing permission, source
    `files`): their task is untrusted here, and without somewhere to make the file there
    would be nothing to send. A file the answer names but that
    existed before the task is NOT sent, and the answer says so: a hand-over must not be a
    way to fetch whatever the other machine has.

Everything that arrives is somebody else's bytes: plain names, `from-<team>/` in the
workspace, capped, never executable, and a ledger row on both sides. A Zero's own hub
keeps its own, wider rule (zero.ships_to).
"""
from __future__ import annotations

import os
from pathlib import Path

from . import zero as zeromod

ACTION = "file.send"
MADE = "files:made"            # the answering side's resource: files made for their task


def team_resource(label: str) -> str:
    return f"team:{label}"


def resolve_out(cfg: dict, paths) -> tuple[list[Path], list[str]]:
    """The files a hand-over may carry: real files under this machine's roots, not hidden,
    within the caps. Returns (paths, refused-with-why)."""
    from . import outputs
    roots = outputs.roots(cfg)
    ok, refused, total = [], [], 0
    for raw in (paths if isinstance(paths, list) else [paths])[: zeromod.SHIP_FILES * 2]:
        raw = str(raw or "").strip()
        if not raw:
            continue
        p = outputs.reachable(raw, roots)
        if p is None:
            refused.append(f"{raw} (not a file in a folder you share with your agents)")
            continue
        root = next((r for r in roots if r == p or r in p.parents), p.parent)
        if any(part.startswith(".") for part in p.relative_to(root).parts):
            # judged inside its folder: a workspace under ~/.agentos is not hidden, .ssh is
            refused.append(f"{p.name} (a hidden file)")
            continue
        size = p.stat().st_size
        if len(ok) >= zeromod.SHIP_FILES or size > zeromod.SHIP_FILE_CAP or total + size > zeromod.SHIP_TOTAL_CAP:
            refused.append(f"{p.name} (too big to send, or one too many)")
            continue
        if p not in ok:
            ok.append(p)
            total += size
    return ok, refused


def encode(paths: list[Path]) -> list[dict]:
    import base64
    out = []
    for p in paths:
        try:
            data = p.read_bytes()
        except OSError:
            continue
        out.append({"name": p.name, "size": len(data), "data": base64.b64encode(data).decode()})
    return out


def made_for_task(text: str, roots: list[Path], since: float) -> tuple[list[dict], list[str], list[str]]:
    """What an answer may carry back: files it names that were made or changed during the
    task. Returns (files, left: too big, kept: named but older than the task)."""
    from . import outputs
    named = outputs.mentioned(text, roots, limit=zeromod.SHIP_FILES * 2)
    fresh, kept = [], []
    for f in named:
        p = Path(f["path"])
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m + 1 < since or any(part.startswith(".") for part in Path(f.get("rel") or p.name).parts):
            kept.append(p.name)
        else:
            fresh.append(str(p))
    files, left = zeromod.pack(" ".join(f"`{x}`" for x in fresh), roots) if fresh else ([], [])
    return files, left, kept


# ---- the answering side's permission ---------------------------------------------------------

def _rows(store, label: str) -> list[dict]:
    return [g for g in store.list_grants(principal_kind="team", principal_id=f"{label}/*")
            if g.get("action") == ACTION and g.get("resource") == MADE]


def folder_for(cfg: dict, label: str) -> Path:
    """Where this machine's agents make files for one linked team: `<workspace>/for-<label>`."""
    return zeromod.folder_for(cfg, label)


def _folder_rows(store, label: str) -> list[dict]:
    return [g for g in store.list_grants(principal_kind="team", principal_id=f"{label}/*")
            if g.get("action") == "team.act" and g.get("source") == "files"]


def _set_folder(store, cfg: dict, label: str, on: bool) -> None:
    """A linked team's task is untrusted here, so a write waits for a person. Sending back
    what is made for them needs somewhere to make it: any of my agents may write into
    `for-<label>/` for that team, and nothing else (policy._standing, agent '*' only on a
    `files` row). On and off with the files-back switch."""
    from .policy import standing_refusal, standing_resource
    for g in _folder_rows(store, label):
        store.revoke_grant(g["id"])
    if not on:
        return
    folder = folder_for(cfg, label)
    folder.mkdir(parents=True, exist_ok=True)
    scope = f"fs:{folder}/*"
    if not standing_refusal("fs.write", scope):
        store.add_grant("team", f"{label}/*", "team.act", standing_resource("*", "fs.write", scope),
                        source="files", note=f"your agents may make files for {label} in {folder}")


def back_state(store, label: str) -> bool:
    """Do files made for this team's tasks go back to them? On with the link's cells
    unless somebody switched it off."""
    rows = _rows(store, label)
    if any(g.get("effect") == "deny" for g in rows):
        return False
    if rows:
        return True
    from . import fabric as fabricmod
    return bool(fabricmod.link_access(store, label)["theirs_may_ask"])


def ensure_back(store, cfg: dict, label: str) -> bool:
    """Before their task is worked: write the rows the first time they are needed, when the
    link lets their team ask one of ours and nobody switched files off. Ordinary grants:
    Permissions lists them. Returns whether files go back."""
    on = back_state(store, label)
    if on and not _rows(store, label):
        store.add_grant("team", f"{label}/*", ACTION, MADE, source="matrix",
                        note=f"files your agents make for {label}'s tasks go back with the answer")
    if on and not _folder_rows(store, label):
        _set_folder(store, cfg, label, True)
    return on


def set_back(store, label: str, on: bool, cfg: dict | None = None) -> bool:
    for g in _rows(store, label):
        store.revoke_grant(g["id"])
    if cfg is not None:
        _set_folder(store, cfg, label, on)
    if on:
        store.add_grant("team", f"{label}/*", ACTION, MADE, source="user",
                        note=f"files your agents make for {label}'s tasks go back with the answer")
    else:
        store.add_grant("team", f"{label}/*", ACTION, MADE, effect="deny", source="user",
                        note=f"files your agents make for {label}'s tasks stay here; words only")
    return on


def may_send_back(store, pdp, label: str) -> bool:
    """The gate's answer, so the ledger has the row: team:<label>/* file.send files:made."""
    from .policy import Principal
    if pdp is None:
        return False
    dec = pdp.decide(Principal("team", f"{label}/*"), ACTION, MADE,
                     {"surface": "team", "risk": "safe", "reason": "files made for their task"})
    return dec.effect == "allow"


# ---- what arrives ------------------------------------------------------------------------------

def receive(files, workspace: Path, label: str) -> list[Path]:
    """Files another team sent: plain names in `<workspace>/from-<label>/`, capped, and
    never executable (write_bytes gives the umask's 0644)."""
    paths = zeromod.unpack(files, Path(workspace), label)
    for p in paths:
        try:
            os.chmod(p, 0o644)
        except OSError:
            pass
    return paths


def sent_line(paths: list[Path], label: str) -> str:
    return (f"\n\nFiles they sent with it, saved here: " + ", ".join(f"`{p}`" for p in paths)
            if paths else "")


def kept_line(kept: list[str], where: str) -> str:
    return (f"\n\nNamed but not sent, because they were not made for this task: "
            + ", ".join(kept[:8]) + f" (they stay on {where})." if kept else "")

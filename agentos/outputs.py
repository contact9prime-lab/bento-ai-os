"""What your agents made: the files a reply names, and the ones made lately.

Reported as: "it created the deck but I can't open it from the chat, and it isn't in
Files". A reply that names a file is only half an answer if the file cannot be reached
from where the reply is read. This module is the one answer to two questions every
surface asks:

- **Which files does this text name?** (`mentioned`) Chat turns them into a chip with
  Open and Download, Telegram and WhatsApp send them as documents after the reply.
- **What has been made lately?** (`recent`) The Office's filing cabinet and
  `bento files` list them.

A path is honoured only inside the folders this person may reach (`roots`): their own
workspace always, and the machine's folders (the shared workspace, the folder set in
Settings → Executors) only on a machine without accounts or for an admin. A reply is
text a model wrote, and a model can be talked into naming /etc/shadow; a name outside
those folders is left as text.

Stdlib only, no HTTP, so the server, the bridges and the CLI all call it directly.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

#: How many files one reply may hand over (a reply listing a folder is not a request
#: to send forty documents to a phone).
MAX_PER_REPLY = 5
#: Folders a person never means when they say "the files": tools' caches and VCS.
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache", ".mypy_cache",
             ".pytest_cache", ".next", "dist", "build", ".idea", ".DS_Store"}
#: A walk of the workspace stops after this many entries, so a checkout of a large
#: repository in the workspace cannot make the Office's cabinet a disk scan.
WALK_CAP = 6000

# a path-looking token in running text: absolute, home-relative or relative, ending in an
# extension. No spaces here (a sentence would read as one long name); a file whose name
# has spaces is found through the code span a reply puts it in.
_PATH = re.compile(r"(?:~|/|\.{1,2}/)?(?:[\w.@+-]+/)*[\w.@()+-]+\.[A-Za-z0-9]{1,8}")


def roots(cfg: dict, admin: bool = True) -> list[Path]:
    """The folders a file may be handed over from, most personal first."""
    out: list[Path] = []

    def add(p):
        if not p:
            return
        try:
            r = Path(os.path.expanduser(str(p))).resolve()
        except OSError:
            return
        if r.is_dir() and r not in out:
            out.append(r)

    add((cfg or {}).get("workspace"))
    if admin:
        from . import config as _cfgmod
        add(_cfgmod.AGENTOS_HOME / "workspace")
        add((((cfg or {}).get("executors") or {}).get("claude_code") or {}).get("workspace"))
    return out


def reachable(path: str, rts: list[Path]) -> Path | None:
    """`path` as a real file inside one of `rts`, or None. Relative paths are tried
    against each root in turn; symlinks are resolved before the check."""
    raw = str(path or "").strip().strip("`'\"").rstrip(".,;:)")
    if not raw or "\x00" in raw:
        return None
    cands = []
    exp = os.path.expanduser(raw)
    if os.path.isabs(exp):
        cands.append(Path(exp))
    else:
        cands.extend(r / exp for r in rts)
    for c in cands:
        try:
            p = c.resolve()
        except OSError:
            continue
        if p.is_file() and any(p == r or r in p.parents for r in rts):
            return p
    return None


def describe(p: Path, rts: list[Path]) -> dict:
    st = p.stat()
    root = next((r for r in rts if r in p.parents), p.parent)
    return {"name": p.name, "path": str(p), "rel": str(p.relative_to(root)),
            "root": str(root), "size": st.st_size, "mtime": st.st_mtime,
            "ext": p.suffix.lower().lstrip(".")}


def mentioned(text: str, rts: list[Path], limit: int = MAX_PER_REPLY) -> list[dict]:
    """The files `text` names that exist in `rts`, in the order they are named."""
    seen: set[str] = set()
    out: list[dict] = []
    spans = re.findall(r"`([^`\n]{3,400})`", text or "")
    for tok in spans + _PATH.findall(text or ""):
        p = reachable(tok, rts)
        if p is None or str(p) in seen:
            continue
        seen.add(str(p))
        out.append(describe(p, rts))
        if len(out) >= limit:
            break
    return out


def recent(rts: list[Path], limit: int = 30, since: float = 0.0) -> list[dict]:
    """Files in `rts`, newest first. Hidden files and tool caches are skipped, and the
    walk stops at WALK_CAP entries."""
    found: list[tuple[float, Path]] = []
    walked = 0
    for r in rts:
        for dirpath, dirnames, filenames in os.walk(r):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for f in filenames:
                walked += 1
                if walked > WALK_CAP:
                    break
                if f.startswith("."):
                    continue
                p = Path(dirpath) / f
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m >= since:
                    found.append((m, p))
            if walked > WALK_CAP:
                break
    found.sort(key=lambda x: -x[0])
    out, seen = [], set()
    for _, p in found:
        rp = p.resolve()
        if str(rp) in seen:
            continue
        seen.add(str(rp))
        out.append(describe(rp, rts))
        if len(out) >= limit:
            break
    return out


def size_words(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1e6 else f"{n / 1e6:.1f} MB"


def since_minutes(m: float) -> float:
    return time.time() - m * 60

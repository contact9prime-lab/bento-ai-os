"""The version number moves with the code, or CI says why not.

`agentos/VERSION` was written by hand at a release, and between releases nobody
wrote it. So a machine that ran `bento update` and pulled forty commits still said
0.4.0 afterwards — the code had moved and the one number a person reads had not,
which reads as "the update did nothing". `updates.check()` already learned to ask
git how far behind a checkout is; this closes the other half: the number itself.

Three pieces, one rule — **a change that ships moves the version**:

- `bump(kind)` is the one way to write it: VERSION, pyproject.toml and the top
  changelog heading together (`tests/test_updates.py` already fails if the first
  two disagree). `bento version bump [patch|minor|major]`.
- `needs_bump(base)` is the check: did anything that ships change since `base`
  without the version moving past `base`'s? CI runs it on every pull request
  (`bento version check origin/master`) and refuses with the command to run.
- The safety net for a push straight to the branch: CI runs the same check against
  the previous tip and, when it fails, commits a patch bump itself
  (`.github/workflows/version.yml`). A person's bump is always preferred — it
  comes with notes — but the number never stays behind the code.

Kept free of HTTP and asyncio, like `jobs.py`: it is a few file writes and git reads,
and the release machine, CI and a headless box all run it the same way.
"""
from __future__ import annotations

import datetime as _dt
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: What ships. A change under any of these reaches somebody's machine through
#: `bento update`, so it has to arrive under a new number. Docs, tests and CI
#: configuration do not change what runs, and demanding a bump for a typo in a
#: guide is how a rule gets bypassed rather than followed.
SHIPPED = ("agentos/", "pyproject.toml", "uv.lock", "install.sh", "packaging/")
KINDS = ("patch", "minor", "major")


def _git(args: list[str], root: Path) -> tuple[bool, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                           timeout=60)
        return p.returncode == 0, p.stdout.strip()
    except Exception as e:                       # no git at all
        return False, f"{type(e).__name__}: {e}"


def parse(v: str) -> tuple[int, int, int]:
    nums = [int(n) for n in re.findall(r"\d+", (v or "").split("-")[0].split("+")[0])[:3]]
    return tuple((nums + [0, 0, 0])[:3])          # type: ignore[return-value]


def read(root: Path | None = None) -> str:
    try:
        return ((root or ROOT) / "agentos" / "VERSION").read_text().strip()
    except OSError:
        return ""


def next_version(v: str, kind: str = "patch") -> str:
    if kind not in KINDS:
        raise ValueError(f"a bump is one of {', '.join(KINDS)}, not '{kind}'")
    major, minor, patch = parse(v)
    if kind == "major":
        return f"{major + 1}.0.0"
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def bump(kind: str = "patch", root: Path | None = None, to: str = "",
         today: str = "") -> dict:
    """Move the version: VERSION, pyproject.toml and the changelog, in one go.

    The changelog's top heading, when it is an "Unreleased" one, becomes this
    version's heading — its notes are what `updates._notes` shows a machine that
    is about to install it. With no unreleased notes a heading is still written,
    saying so: an update card with a version and nothing under it reads as broken.
    """
    root = root or ROOT
    old = read(root)
    if not old:
        raise ValueError(f"no agentos/VERSION under {root}")
    new = to.strip() or next_version(old, kind)
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        raise ValueError(f"'{new}' is not a version like 1.2.3")
    if parse(new) <= parse(old):
        raise ValueError(f"{new} is not newer than {old}")
    day = today or _dt.date.today().isoformat()
    (root / "agentos" / "VERSION").write_text(new + "\n")
    pp = root / "pyproject.toml"
    text = pp.read_text()
    text, n = re.subn(r'(?m)^version\s*=\s*"[^"]*"', f'version = "{new}"', text, count=1)
    if not n:
        raise ValueError("pyproject.toml has no version line to move")
    pp.write_text(text)
    files = ["agentos/VERSION", "pyproject.toml"]
    lock = root / "uv.lock"
    if lock.exists():
        # The lockfile records this package's own version; left behind, the next
        # `uv sync` rewrites it and the checkout looks edited (updates.DERIVED).
        lt, n = re.subn(r'(\[\[package\]\]\nname = "agentos"\nversion = )"[^"]*"',
                        rf'\g<1>"{new}"', lock.read_text(), count=1)
        if n:
            lock.write_text(lt)
            files.append("uv.lock")
    cl = root / "CHANGELOG.md"
    if cl.exists():
        lines = cl.read_text().splitlines(keepends=True)
        head = next((i for i, ln in enumerate(lines) if re.match(r"^#{2,}\s", ln)), None)
        title = f"## {new} — {day}"
        if head is not None and re.match(r"^#{2,}\s+Unreleased\b", lines[head]):
            rest = re.sub(r"^#{2,}\s+Unreleased\s*(—|-)?\s*", "", lines[head]).strip()
            lines[head] = title + (f" — {rest}" if rest else "") + "\n"
        else:
            at = head if head is not None else len(lines)
            lines[at:at] = [title + "\n", "\n",
                            f"No release notes were written for this one; the commits since "
                            f"{old} are what changed (`bento update` lists them).\n", "\n"]
        cl.write_text("".join(lines))
        files.append("CHANGELOG.md")
    return {"from": old, "to": new, "files": files}


def version_at(ref: str, root: Path | None = None) -> str:
    ok, out = _git(["show", f"{ref}:agentos/VERSION"], root or ROOT)
    return out.strip() if ok else ""


def needs_bump(base: str, head: str = "HEAD", root: Path | None = None) -> dict:
    """Did something that ships change between `base` and `head` while the version
    stayed put? `{"needed": bool, "shipped": [...], "base_version", "head_version",
    "error"}` — an unreadable base is an error, never a pass."""
    root = root or ROOT
    out = {"needed": False, "shipped": [], "base_version": "", "head_version": "", "error": ""}
    ok, mb = _git(["merge-base", base, head], root)
    if not ok:
        out["error"] = f"cannot find where {head} left {base}: {mb[:200]}"
        return out
    ok, names = _git(["diff", "--name-only", mb, head], root)
    if not ok:
        out["error"] = f"cannot diff {base}..{head}: {names[:200]}"
        return out
    out["shipped"] = sorted(p for p in names.splitlines()
                            if p.startswith(SHIPPED) and p != "agentos/VERSION")
    out["base_version"] = version_at(mb, root)
    out["head_version"] = version_at(head, root)
    moved = bool(out["head_version"]) and parse(out["head_version"]) > parse(out["base_version"])
    out["needed"] = bool(out["shipped"]) and not moved
    return out


def build(root: Path | None = None) -> str:
    """The commit this copy runs, short — '' when it is not a git checkout. Shown
    next to the number, so even two copies of one version say which code each is."""
    root = root or ROOT
    if not (root / ".git").exists():
        return ""
    ok, out = _git(["rev-parse", "--short", "HEAD"], root)
    return out if ok else ""


def label(root: Path | None = None) -> str:
    """'0.5.0 (d2717b0)' — the number and the build, or just the number."""
    b = build(root)
    return read(root) + (f" ({b})" if b else "")

"""Small code on the edge, big code on its hub.

Asked for as "the pi should be able to run small codes and big codes should be handed off to
hub if required, only in the context and that folder, and should not impact our application".

The edge's side: `run_python` on a machine a hub set up runs here first, inside `EDGE_SECONDS`
and `EDGE_MEMORY_MB`. A run those limits stop, or one asked for with where="hub", goes to the
hub over the link that set this machine up (wire op `edge_run`): the code, and one folder of
the workspace if it names one. What comes back is the output and the files the run made or
changed, written into that same folder.

The hub's side (`answer`): only for a machine this hub set up, only with the `code.run` grant
written when it was set up (Permissions can revoke it), and only in a jail of its own:
bubblewrap with no network, nothing of the hub visible but /usr and a fresh folder holding
what was sent, its own memory, CPU and file-size limits, a lower priority, one run at a time,
and the folder deleted afterwards. A hub without bubblewrap refuses rather than run unconfined.

Free of HTTP, like provision.py: the server and the tools call into it.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import shutil
import signal
import time
import uuid
from pathlib import Path

ACTION = "code.run"
RESOURCE = "code:sandbox"
OP = "edge_run"

# a run on the edge longer than this goes to the hub (AGENTOS_EDGE_SECONDS: a test's short clock)
EDGE_SECONDS = int(os.environ.get("AGENTOS_EDGE_SECONDS") or 60)
EDGE_MEMORY_MB = 512            # and one that needs more memory than this
HUB_SECONDS = 900               # what the hub gives one run, wall clock
HUB_CPU_SECONDS = 900
HUB_MEMORY_MB = 2048
HUB_FILE_MB = 200               # no one file the run writes may grow past this
OUT_CAP = 64_000                # characters of output sent back
SEND_FILES = 64                 # files one folder may carry to the hub
SEND_FILE_CAP = 1_500_000       # bytes, one file
SEND_TOTAL_CAP = 2_500_000      # bytes, all of them (base64 fits a pinned link's 4 MiB line)
BACK_FILES = 16
SCRIPT = ".bento-run.py"

_SLOT: dict = {}                # one asyncio.Semaphore per loop: one run at a time on the hub


# ---- the edge -------------------------------------------------------------------------------

def hub_for(cfg: dict) -> dict | None:
    """The link to the hub that set this machine up, or None (then nothing changes)."""
    from . import zeromind
    try:
        return zeromind.hub_link(cfg)
    except Exception:
        return None


def local_command(py: str, path: str, cwd: str = "") -> str:
    """The edge's run, held to the edge's limits. `ulimit -v` is the memory, `timeout`
    the clock (GNU's says 124, uutils' 125, a KILL 137); `stopped_by_limit` reads them."""
    import shlex
    lead = f"cd {shlex.quote(cwd)} && " if cwd else ""
    # TERM at the limit and KILL two seconds on: uutils' timeout (Ubuntu 25.10) ignored a bare
    # `-s KILL` and let the run go on to its end
    clock = f"timeout -k 2 {EDGE_SECONDS} " if shutil.which("timeout") else ""
    return f"{lead}ulimit -v {EDGE_MEMORY_MB * 1024}; exec {clock}{shlex.quote(py)} {shlex.quote(path)}"


def stopped_by_limit(out: str) -> str:
    """Why the edge's limits stopped a run, in words, or '' when they did not."""
    head = (out or "")[:40]
    if head.startswith(("[exit code 124]", "[exit code 125]")):
        return f"it ran past {EDGE_SECONDS} s here"
    if head.startswith(("[exit code 137]", "[exit code -9]")):
        return "it was stopped here, out of time or memory"
    if "MemoryError" in (out or "") or "Cannot allocate memory" in (out or ""):
        return f"it needed more than {EDGE_MEMORY_MB} MB here"
    if (out or "").startswith("[error] command timed out"):
        return "it ran too long here"
    return ""


def _inside(base: Path, rel: str) -> Path | None:
    """`rel` under `base`, or None: no absolute path, no '..', no hidden part, no link out."""
    rel = str(rel or "").strip()
    if rel.startswith(("/", "~")):
        return None
    rel = rel.rstrip("/")
    if not rel:
        return base
    parts = Path(rel).parts
    if any(p in ("..", "") or p.startswith(".") for p in parts):
        return None
    p = (base / rel)
    try:
        real = Path(os.path.realpath(p))
    except OSError:
        return None
    b = Path(os.path.realpath(base))
    return p if real == b or b in real.parents else None


def pack_folder(base: Path, folder: str) -> tuple[list[dict], list[str], str]:
    """The files of one folder as they travel: ([{path, data}], [left behind], error)."""
    root = _inside(Path(base), folder)
    if root is None:
        return [], [], f"'{folder}' is not a folder inside the workspace"
    if not folder:
        return [], [], ""
    if not root.is_dir():
        return [], [], f"there is no folder '{folder}' in the workspace"
    files, left, total = [], [], 0
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
        for n in sorted(names):
            p = Path(dirpath) / n
            if n.startswith(".") or p.is_symlink() or not p.is_file():
                continue
            rel = str(p.relative_to(root))
            size = p.stat().st_size
            if len(files) >= SEND_FILES or size > SEND_FILE_CAP or total + size > SEND_TOTAL_CAP:
                left.append(rel)
                continue
            total += size
            files.append({"path": rel, "data": base64.b64encode(p.read_bytes()).decode()})
    return files, left, ""


def unpack_into(root: Path, files) -> tuple[list[str], list[str]]:
    """Write files under `root` by their relative paths, refusing any path that would leave it.
    Returns (written, refused). Never executable: they are another machine's bytes."""
    written, refused, total = [], [], 0
    if not isinstance(files, list):
        return written, refused
    for f in files[:max(SEND_FILES, BACK_FILES)]:
        if not isinstance(f, dict):
            continue
        rel = str(f.get("path") or "")
        dest = _inside(root, rel) if rel else None
        try:
            data = base64.b64decode(str(f.get("data") or ""), validate=True)
        except (ValueError, TypeError):
            refused.append(rel or "?")
            continue
        if dest is None or dest == root or len(data) > SEND_FILE_CAP or total + len(data) > SEND_TOTAL_CAP:
            refused.append(rel or "?")
            continue
        total += len(data)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        dest.write_bytes(data)
        with contextlib.suppress(OSError):
            os.chmod(dest, 0o644)
        written.append(rel)
    return written, refused


async def offload(cfg: dict, code: str, base: Path, folder: str, why: str) -> str:
    """Send one run to the hub and bring its answer back into `folder`."""
    from . import teamlink
    lk = hub_for(cfg)
    if not lk:
        return "[error] this machine has no hub to hand code to"
    files, left, err = pack_folder(Path(base), folder)
    if err:
        return f"[error] {err}"
    req = {"op": OP, "code": code, "files": files, "folder": folder}
    t0 = time.time()
    try:
        out = await teamlink.call(lk, req, timeout=HUB_SECONDS + 90, limit=teamlink.POOL_LINE)
    except Exception as e:      # an answer is always a sentence, never a traceback
        return f"[error] could not reach the hub {lk.get('label')}: {type(e).__name__}: {e}"
    if not isinstance(out, dict) or not out.get("ok"):
        return f"[error] the hub {lk.get('label')} did not run it: {(out or {}).get('error') or 'no answer'}"
    dest = _inside(Path(base), folder) if folder else Path(base) / f"from-{_safe(lk.get('label'))}"
    written, refused = unpack_into(dest, out.get("files")) if dest is not None else ([], [])
    lines = [f"[ran on the hub {lk.get('label')} because {why}, in {time.time() - t0:.0f} s"
             + (f", exit code {out.get('rc')}" if out.get("rc") else "") + "]"]
    lines.append(str(out.get("output") or "(no output)"))
    if written:
        lines.append(f"[files back in {dest}: {', '.join(written)}]")
    if refused or out.get("left"):
        lines.append(f"[not brought back: {', '.join(list(refused) + list(out.get('left') or []))}]")
    if left:
        lines.append(f"[not sent, over the size limit: {', '.join(left)}]")
    return "\n".join(lines)


def _safe(name) -> str:
    from . import zero
    return zero.safe_name(str(name or "hub"))


# ---- the hub --------------------------------------------------------------------------------

def set_up_here(lk: dict | None) -> bool:
    """A machine this hub set up itself: the only ones it runs code for."""
    from . import provision
    return bool(lk) and lk.get("kind") == "machine" and provision.was_enabled_here(str(lk.get("peer_host_fp") or ""))


def grant(store, label: str) -> bool:
    """The hub's consent, written when it sets a machine up: an ordinary grant, shown in
    Permissions and revoked with the link (fabric.forget_link_grants)."""
    have = [g for g in store.list_grants(principal_kind="team", principal_id=f"{label}/*")
            if g.get("action") == ACTION and g.get("effect") == "allow"]
    if have:
        return False
    store.add_grant("team", f"{label}/*", ACTION, RESOURCE, source="provision",
                    note=f"{label} may hand code too big for it to this machine, run in a sandbox")
    return True


def _python() -> str:
    for p in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if os.path.exists(p):
            return p
    return ""


def jail_argv(run: str, py: str) -> list[str]:
    """No network, nothing of this machine but /usr (and its library links) read-only, and
    the run's own folder as /work. Not tools.bwrap_argv: that binds the whole filesystem
    read-only, which is right for this machine's own agents and wrong for another's code."""
    argv = ["bwrap", "--unshare-all", "--hostname", "sandbox", "--die-with-parent", "--new-session", "--clearenv",
            "--ro-bind", "/usr", "/usr"]
    for p in ("/bin", "/sbin", "/lib", "/lib64", "/lib32"):
        if os.path.islink(p):
            argv += ["--symlink", os.readlink(p), p]
        elif os.path.isdir(p):
            argv += ["--ro-bind", p, p]
    for p in ("/etc/alternatives", "/etc/ld.so.cache", "/etc/ssl", "/etc/localtime"):
        argv += ["--ro-bind-try", p, p]
    return argv + ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                   "--bind", run, "/work", "--chdir", "/work",
                   "--setenv", "HOME", "/work", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
                   "--setenv", "PYTHONDONTWRITEBYTECODE", "1", "--setenv", "MPLBACKEND", "Agg",
                   py, f"/work/{SCRIPT}"]


def limited(argv: list[str]) -> list[str]:
    """Memory, CPU and file-size limits and a lower priority, set by prlimit and nice on the
    command line (a preexec_fn is not safe in a server that runs threads)."""
    mb = 1024 * 1024
    return ["prlimit", f"--as={HUB_MEMORY_MB * mb}", f"--cpu={HUB_CPU_SECONDS}",
            f"--fsize={HUB_FILE_MB * mb}", "nice", "-n", "10", *argv]


def runs_dir() -> Path:
    from . import config as cfgmod
    return Path(cfgmod.AGENTOS_HOME) / "edge-runs"


async def answer(store, pdp, lk: dict, req: dict) -> dict:
    """Run one piece of code for a machine this hub set up, in the jail, and send back what it
    printed and the files it made or changed."""
    from . import fabric as fabricmod
    from .policy import Principal
    from .tools import sandbox_mechanism
    label = str(lk.get("label") or "")
    if not set_up_here(lk):
        return {"ok": False, "error": "this hub runs code only for machines it set up itself"}
    dec = pdp.decide(Principal("team", f"{label}/code"), ACTION, RESOURCE, {"surface": "team"})
    if dec.effect != "allow":
        return {"ok": False, "error": f"this hub does not run code for {label} (allow it in Permissions)"}
    if sandbox_mechanism() != "bwrap" or not _python() or not shutil.which("prlimit"):
        return {"ok": False, "error": "this hub has no sandbox to run other machines' code in "
                                      "(it needs bubblewrap, prlimit and python3), so it runs none"}
    code = str(req.get("code") or "")
    if not code.strip():
        return {"ok": False, "error": "nothing to run"}
    run = runs_dir() / _safe(label) / uuid.uuid4().hex[:12]
    run.mkdir(parents=True, exist_ok=True)
    try:
        got, refused = unpack_into(run, req.get("files"))
        (run / SCRIPT).write_text(code)
        before = {str(p.relative_to(run)): p.stat().st_mtime_ns for p in run.rglob("*") if p.is_file()}
        slot = _SLOT.setdefault(id(asyncio.get_running_loop()), asyncio.Semaphore(1))
        t0 = time.time()
        async with slot:
            proc = await asyncio.create_subprocess_exec(
                *limited(jail_argv(str(run), _python())), stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, start_new_session=True)
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=HUB_SECONDS)
                rc = proc.returncode
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
                out, rc = f"[stopped after {HUB_SECONDS} s on the hub]".encode(), -9
        text = out.decode(errors="replace")
        if len(text) > OUT_CAP:
            text = text[:OUT_CAP // 2] + f"\n… {len(text) - OUT_CAP} characters cut …\n" + text[-OUT_CAP // 2:]
        back, left, total = [], [], 0
        for p in sorted(run.rglob("*")):
            rel = str(p.relative_to(run))
            if not p.is_file() or p.is_symlink() or rel == SCRIPT or any(x.startswith(".") for x in Path(rel).parts):
                continue
            if before.get(rel) == p.stat().st_mtime_ns:
                continue                       # sent and untouched: it is already there
            size = p.stat().st_size
            if len(back) >= BACK_FILES or size > SEND_FILE_CAP or total + size > SEND_TOTAL_CAP:
                left.append(rel)
                continue
            total += size
            back.append({"path": rel, "data": base64.b64encode(p.read_bytes()).decode()})
        fabricmod.audit_team(store, "edge.code", f"link:{label}",
                             f"ran code for {label} in the sandbox: {len(code)} characters, {len(got)} files in, "
                             f"{len(back)} back, exit {rc}, {time.time() - t0:.0f} s")
        return {"ok": True, "output": text, "rc": rc, "files": back, "left": left + refused}
    finally:
        shutil.rmtree(run, ignore_errors=True)

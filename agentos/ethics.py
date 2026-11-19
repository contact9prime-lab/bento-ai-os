"""Ethics: whether a step should be done at all, whoever said yes.

The gate (policy.py) answers "may this agent do it, and did a person agree?". It never asked
whether the thing should be done, so a person could approve harm with one tap, and an agent at
full autonomy could reach somebody else's machine. Asked for as "ethics is the most important
evaluator, calculated by the system in the most deterministic way, so the AI doesn't
circumvent it" (docs/design/ethics.md).

One rule underneath it all: **only the party who would be hurt can consent.**

- Harm to YOU (your files): you may say yes, but informed. The damage is measured here (files,
  bytes, where) and confirmed by typing a phrase at a screen. A grant, a remembered approval,
  the autonomy level or a phone tap never counts. This is the one part a person may switch off,
  because it is theirs.
- Harm to OTHERS (a machine nobody here has shown is theirs) and to EVERYONE (wiping the
  system): refused. Nobody's yes covers it, so there is no switch. A machine becomes "yours" by
  a fact Bento checks (this machine, one Bento set up or logged into, or a site that served the
  proof file), never by a sentence a model or a person types.

Deterministic by construction: plain code over facts this module works out itself (the parsed
command, real paths, measured counts, the targets' owners). No model is asked. A verdict can only
be made stricter by anything else; nothing lowers it. This file is in protected.SECURITY_MODULES.

What it cannot do, said in the docs and on screen: judge intent, see a CLI's own native tools,
stop a person running the command themselves, or follow a socket a program opens itself (the
jail keeps the network, so the checks are on what a step names).
"""
from __future__ import annotations

import contextvars
import fnmatch
import glob as _glob
import ipaddress
import os
import re
import secrets
import shlex
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

# --- the rules -------------------------------------------------------------------------

# (id, who would be hurt, verdict, can the person switch it off, what it covers). Settings,
# `bento ethics` and the docs list this table; the test checks every rule a verdict names is here.
RULES = (
    ("wreck", "everyone", "refuse", False,
     "Wiping the system, a disk, or a whole home folder."),
    ("attack", "others", "refuse", False,
     "Scanning, breaking into or flooding a machine nobody here has shown is theirs."),
    ("range", "others", "refuse", False,
     "Scanning a whole range of addresses."),
    ("history", "others", "caution", False,
     "Rewriting history other people may share (a force push)."),
    ("unread", "you", "caution", False,
     "A destructive command Bento can't read fully, so it can't tell what it would hit."),
    ("own", "you", "caution", True,
     "Deleting a lot of your own files, or files outside your workspace."),
    # phase 2: the library, where a target came from, and what a conversation has been doing
    ("credentials", "others", "caution", False,
     "Dumping the passwords and keys saved on a machine (a tool MITRE ATT&CK lists for it)."),
    ("untraced", "others", "caution", False,
     "Sending to, or acting on, a host or address nobody named: the agent chose it itself."),
    ("leak", "others", "caution", False,
     "Sending anything out after reading a secret, like a key or a password file."),
    ("context", "everyone", "caution", False,
     "A conversation whose ethics score has built up: risky steps are typed, and past the hold line none run."),
    ("evaluator", "others", "caution", False,
     "A second reading by the machine's brain with no tools found a concern. It can only ask for typing."),
)
RULE = {r[0]: r for r in RULES}
HARMED_WORDS = {"you": "you", "others": "someone else", "everyone": "everyone on this machine"}

# A delete inside the workspace is your agent's own working area: under these it is the ordinary
# gate's question. Outside it, or over these, it is measured and typed.
OWN_FILES = 200
OWN_BYTES = 200 * 1024 * 1024
MEASURE_ENTRIES = 200_000          # a walk stops here and says "at least"
MEASURE_S = 1.5

# Programs whose job is to probe, break into or flood another machine. Their target decides.
ATTACK_PROGRAMS = frozenset({
    "nmap", "masscan", "zmap", "rustscan", "unicornscan", "sqlmap", "hydra", "medusa", "ncrack",
    "patator", "nikto", "wpscan", "joomscan", "gobuster", "dirb", "dirbuster", "feroxbuster", "ffuf",
    "wfuzz", "msfconsole", "msfvenom", "crackmapexec", "netexec", "nxc", "responder", "bettercap",
    "ettercap", "arpspoof", "aireplay-ng", "aircrack-ng", "mdk3", "mdk4", "hping3", "slowloris",
    "goldeneye", "xerxes", "commix", "xsstrike", "dnsenum", "fierce", "enum4linux", "smbmap",
    "evil-winrm", "kerbrute", "nuclei", "zap-cli", "theharvester",
    # load generators: pointed at somebody else, a flood
    "ab", "siege", "wrk", "hey", "vegeta", "locust", "bombardier", "h2load",
})
# Python libraries for the same jobs, read in run_python's code
ATTACK_MODULES = frozenset({"scapy", "impacket", "pwn", "pwntools", "nmap", "paramiko_brute"})
# Wiping a disk or the system: refused whatever the target
WRECK_PROGRAMS = frozenset({"mkfs", "wipefs", "sgdisk", "fdisk", "parted", "sfdisk", "blkdiscard"})
# Programs that only run another program
RUNNERS = frozenset({"sudo", "doas", "env", "nice", "ionice", "nohup", "timeout", "time", "stdbuf",
                     "setsid", "command", "exec", "builtin", "busybox", "chrt", "taskset"})
SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "fish"})
DESTROY_PROGRAMS = frozenset({"rm", "shred", "srm", "wipe", "unlink", "find", "git", "dd",
                              "truncate", "chmod", "chown"}) | WRECK_PROGRAMS
# A word that looks like a host name but is a file
_FILE_ENDINGS = frozenset({"txt", "json", "xml", "csv", "log", "lst", "list", "py", "sh", "conf", "cfg",
                           "yaml", "yml", "html", "htm", "js", "md", "gz", "zip", "tar", "pcap", "out",
                           "nmap", "gnmap", "ini", "toml", "pem", "key", "crt", "db", "sql", "bak"})
_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{1,62}$", re.I)


@dataclass
class Verdict:
    level: str = "ok"            # ok | caution | refuse
    rule: str = ""               # an id from RULES
    why: str = ""                # one sentence a person reads
    facts: list = field(default_factory=list)   # what was measured or found, in words
    confirm: str = ""            # the phrase to type, for a caution
    harmed: str = ""             # you | others | everyone

    def to_dict(self) -> dict:
        return {"level": self.level, "rule": self.rule, "why": self.why, "facts": list(self.facts),
                "confirm": self.confirm, "harmed": self.harmed,
                "harmed_words": HARMED_WORDS.get(self.harmed, "")}


OK = Verdict()


# --- settings ----------------------------------------------------------------------------

def conf(cfg: dict | None) -> dict:
    """The person's ethics settings (`ethics`, a USER_KEY). Only `own` is a switch."""
    e = (cfg or {}).get("ethics") if isinstance((cfg or {}).get("ethics"), dict) else {}
    ev = str(e.get("evaluator") or "flagged")
    return {"own": e.get("own", True) is not False,
            "evaluator": ev if ev in ("off", "flagged", "risky") else "flagged",
            "sites": [s for s in (e.get("sites") or []) if isinstance(s, dict) and s.get("host")],
            "pending": dict(e.get("pending") or {})}


# --- whose is it -------------------------------------------------------------------------

def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))


def _agentos_home() -> str:
    from . import config as cfgmod
    return os.path.realpath(str(cfgmod.AGENTOS_HOME))


def _workspaces(cfg: dict) -> list[str]:
    out = []
    for w in ((cfg or {}).get("workspace"),
              (((cfg or {}).get("executors") or {}).get("claude_code") or {}).get("workspace")):
        if w:
            out.append(os.path.realpath(os.path.expanduser(str(w))))
    return out


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _wreck_roots() -> set[str]:
    roots = {"/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/boot", "/var",
             "/sys", "/proc", "/dev", "/root", "/home", "/opt", "/srv", "/Users", "/System",
             "/Library", "/Applications", _home(), _agentos_home()}
    return {os.path.realpath(r) for r in roots}


def _norm_host(host: str) -> str:
    return str(host or "").strip().strip("[]").rstrip(".").lower()


def owned(host: str, cfg: dict | None = None) -> str:
    """Why `host` counts as yours ('' when nothing shows it is). A fact Bento checks, never a
    claim: this machine, a machine Bento set up, linked or logged into, or a site that served
    the proof file (prove/check)."""
    h = _norm_host(host)
    if not h:
        return ""
    if h in ("localhost", "ip6-localhost") or h.endswith(".localhost"):
        return "this machine"
    try:
        ip = ipaddress.ip_address(h)
        if ip.is_loopback:
            return "this machine"
    except ValueError:
        ip = None
    try:
        import socket
        if h in (socket.gethostname().lower(), socket.getfqdn().lower()):
            return "this machine"
        from . import netscan
        if ip is not None and str(ip) in netscan.my_addresses():
            return "this machine"
    except Exception:
        pass
    try:
        from . import inventory
        for r in inventory.rows(cfg):
            if r.get("ignored"):
                continue
            if r.get("bento") in ("installed", "set up", "linked") or r.get("user"):
                names = {str(r.get("ip") or "").lower(), str(r.get("name") or "").lower()}
                names |= {n + ".local" for n in list(names) if n and "." not in n}
                if h in names - {""}:
                    return "a machine Bento set up or logs into"
    except Exception:
        pass
    for s in conf(cfg)["sites"]:
        root = _norm_host(s.get("host"))
        if h == root or h.endswith("." + root):
            return f"you proved {root} is yours"
    return ""


# --- reading a command ---------------------------------------------------------------------

_SEP = re.compile(r"\|\||&&|;|\||&|\n|\$\(|`|\)|\(")


def _segments(line: str) -> tuple[list[list[str]], bool]:
    """The commands in a shell line as word lists, and whether the line was read fully.
    Looser than tools.shell_parse on purpose: that one gives up on anything it can't be sure
    of, which is right for "is this read-only?", and wrong here, where a line we can't be sure
    of still has to be looked at."""
    from .tools import DANGEROUS_META, shell_parse
    exact = shell_parse(line.strip()) is not None and not DANGEROUS_META.search(line)
    out = []
    for part in _SEP.split(line):
        part = part.strip()
        if not part:
            continue
        try:
            words = shlex.split(part, comments=False, posix=True)
        except ValueError:
            words = part.split()
            exact = False
        # a redirect target is not an argument
        words = [w for w in words if not re.fullmatch(r"\d*[<>]{1,2}&?\d*", w)]
        if words:
            out.append(words)
    return out, exact


def _unwrap(words: list[str]) -> list[str]:
    """`sudo -u x env A=1 timeout 5 rm -rf d` → `rm -rf d`."""
    i = 0
    while i < len(words):
        w = os.path.basename(words[i])
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[i]):
            i += 1
            continue
        if w in RUNNERS:
            i += 1
            while i < len(words) and words[i].startswith("-"):
                i += 2 if words[i] in ("-u", "-g", "-n", "-c", "-s", "-k") else 1
            if w == "timeout" and i < len(words) and re.fullmatch(r"[\d.]+[smhd]?", words[i]):
                i += 1
            continue
        break
    return words[i:]


def _expand(word: str, cwd: str) -> list[str]:
    p = os.path.expanduser(word)
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    if any(c in word for c in "*?["):
        return sorted(_glob.glob(p))
    return [p]


def _measure(paths: list[str]) -> tuple[int, int, bool]:
    """(files, bytes, complete) under these paths, never following a link."""
    files = size = seen = 0
    t0 = time.monotonic()
    for top in paths:
        if os.path.islink(top) or os.path.isfile(top):
            files += 1
            try:
                size += os.lstat(top).st_size
            except OSError:
                pass
            continue
        for root, dirs, names in os.walk(top, followlinks=False):
            for n in names:
                files += 1
                seen += 1
                try:
                    size += os.lstat(os.path.join(root, n)).st_size
                except OSError:
                    pass
            seen += len(dirs)
            if seen > MEASURE_ENTRIES or time.monotonic() - t0 > MEASURE_S:
                return files, size, False
    return files, size, True


def _size_words(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _targets(prog: str, args: list[str], cfg: dict | None = None) -> list[str]:
    """The words of an attack program that name where it points: hosts, addresses, URLs,
    ranges. A wordlist or an output file is not a target."""
    out = []
    for a in args:
        val = a.split("=", 1)[1] if a.startswith("--") and "=" in a else a
        if val.startswith("-") or not val:
            continue
        if "@" in val and "://" not in val:          # user@host, DOMAIN/user:pass@host
            val = val.rsplit("@", 1)[1]
        if "://" in val:
            out.append(val)
            continue
        if re.fullmatch(r"[\d.]+/\d{1,2}|[0-9a-f:]+/\d{1,3}", val, re.I) or re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}-\d{1,3}", val):
            out.append(val)
            continue
        try:
            ipaddress.ip_address(val.strip("[]"))
            out.append(val)
            continue
        except ValueError:
            pass
        hostpart = val.split(":")[0]
        if re.fullmatch(r"[a-z][a-z0-9-]{0,62}", hostpart, re.I) and owned(hostpart, cfg):
            out.append(val)          # a one-word name only counts when it is known to be yours
            continue
        if _HOST_RE.match(hostpart) and hostpart.rsplit(".", 1)[-1].lower() not in _FILE_ENDINGS \
                and "/" not in val:
            out.append(val)
    return out


def _judge_targets(prog: str, targets: list[str], cfg: dict) -> Verdict | None:
    if not targets:
        return Verdict("caution", "unread",
                       f"{prog} probes or floods machines, and Bento couldn't tell which one this "
                       f"points at.", [f"program: {prog}"], "run it anyway", "you")
    for t in targets:
        if re.search(r"/\d{1,3}$", t) and "://" not in t or re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}-\d{1,3}", t):
            return Verdict("refuse", "range",
                           f"{prog} would scan the whole range {t}. Bento only points tools like "
                           f"this at single machines that are shown to be yours.",
                           [f"program: {prog}", f"target: {t}"], "", "others")
        host = urlsplit(t).hostname if "://" in t else t.split(":")[0] if t.count(":") == 1 else t
        if not owned(host or "", cfg):
            return Verdict("refuse", "attack",
                           f"{prog} would probe or attack {host}, and nothing shows {host} is yours. "
                           f"Your yes can't cover someone else's machine.",
                           [f"program: {prog}", f"target: {host}",
                            "a machine counts as yours when it is this one, one Bento set up or logs "
                            "into, or a site that served Bento's proof file (bento ethics prove)"],
                           "", "others")
    return None


def _judge_delete(words: list[str], cwd: str, cfg: dict, exact: bool) -> Verdict | None:
    prog = os.path.basename(words[0])
    args = words[1:]
    flags = [a for a in args if a.startswith("-") and a != "-"]
    if "--" in args:
        k = args.index("--")
        plain = [a for a in args[:k] if not a.startswith("-")] + args[k + 1:]
    else:
        plain = [a for a in args if not a.startswith("-")]
    letters = "".join(f[1:] for f in flags if not f.startswith("--"))
    longs = {f for f in flags if f.startswith("--")}
    recursive = "r" in letters.lower() or "--recursive" in longs

    if prog in WRECK_PROGRAMS:
        return Verdict("refuse", "wreck", f"{prog} rewrites disks and partitions.",
                       [f"program: {prog}"], "", "everyone")
    if prog == "dd":
        dest = next((a[3:] for a in args if a.startswith("of=")), "")
        if dest.startswith("/dev/"):
            return Verdict("refuse", "wreck", f"dd would write straight over {dest}.",
                           [f"writes: {dest}"], "", "everyone")
        return None
    if prog in ("chmod", "chown"):
        if not recursive:
            return None
        hit = [p for w in plain[1:] for p in _expand(w, cwd) if os.path.realpath(p) in _wreck_roots()]
        if hit:
            return Verdict("refuse", "wreck", f"{prog} -R on {hit[0]} changes every file in it.",
                           [f"target: {hit[0]}"], "", "everyone")
        return None
    if prog == "git":
        sub = next((a for a in args if not a.startswith("-")), "")
        if sub == "push" and ({"--force", "--force-with-lease", "--mirror", "--delete"} & longs
                              or "f" in letters or "d" in letters
                              or any(a.startswith("+") or a.startswith(":") for a in plain[1:])):
            return Verdict("caution", "history",
                           "A force push rewrites history on the remote. Anyone who already has those "
                           "commits is left with history that no longer exists there.",
                           [f"in: {cwd}", "command: " + " ".join(words)[:200]], "force push", "others")
        if sub == "clean" and "f" in letters:
            files, size, done = _measure([cwd])
            return _own_verdict(cfg, "git clean deletes files git doesn't track, and they can't be "
                                     "got back from git.", [cwd], files, size, done, force=True)
        return None
    if prog == "find":
        if "-delete" not in args and not ("-exec" in args and any(
                os.path.basename(a) in ("rm", "shred") for a in args[args.index("-exec") + 1:])):
            return None
        tops = []
        for a in args:
            if a.startswith("-") or a in ("!", "(", ")"):
                break
            tops += _expand(a, cwd)
        return _paths_verdict("find with -delete removes what it finds", tops or [cwd], cfg,
                              upto=True)
    if prog in ("rm", "unlink", "shred", "srm", "wipe", "truncate"):
        if prog == "truncate":
            return None
        if prog == "rm" and not recursive and not plain:
            return None
        tops = [p for w in plain for p in _expand(w, cwd)]
        if any("$" in w or "`" in w for w in plain):
            return Verdict("caution", "unread",
                           f"{prog} with a target Bento can't read ({' '.join(plain)[:80]}), so it can't "
                           f"tell what would be deleted.", ["command: " + " ".join(words)[:200]],
                           "run it anyway", "you")
        wreck = _wreck_of(plain, tops, cwd)
        if wreck:
            return Verdict("refuse", "wreck", f"{prog} would delete {wreck}.", [f"target: {wreck}"],
                           "", "everyone")
        what = "shred overwrites files so nothing can bring them back" if prog in ("shred", "srm", "wipe") \
            else "rm deletes for good, with no bin to restore from"
        return _paths_verdict(what, tops, cfg, force=prog != "rm" and prog != "unlink")
    return None


def _wreck_of(words: list[str], tops: list[str], cwd: str) -> str:
    """A delete that takes out the system, a disk or a whole home: the root itself, or a
    wildcard over everything in one (`/*`, `~/*`, `~/.*`)."""
    roots = _wreck_roots()
    for t in tops:
        if os.path.realpath(t) in roots:
            return t
    for w in words:
        p = os.path.expanduser(w)
        if not os.path.isabs(p):
            p = os.path.join(cwd, p)
        head, tail = os.path.split(p)
        if tail and re.fullmatch(r"[.*?]+|\.\[.*", tail) and "*" in tail \
                and os.path.realpath(head) in roots:
            return f"everything in {head}"
    return ""


def _paths_verdict(what: str, tops: list[str], cfg: dict, upto: bool = False,
                   force: bool = False) -> Verdict | None:
    tops = [t for t in tops if os.path.lexists(t)]
    if not tops:
        return None
    files, size, done = _measure(tops)
    return _own_verdict(cfg, what + ".", tops, files, size, done and not upto, force=force)


def _own_verdict(cfg: dict, what: str, tops: list[str], files: int, size: int, done: bool,
                 force: bool = False) -> Verdict | None:
    real = [os.path.realpath(t) for t in tops]
    ws = _workspaces(cfg)
    outside = [r for r in real if not any(_under(r, w) for w in ws)]
    big = files >= OWN_FILES or size >= OWN_BYTES
    if not (outside or big or force):
        return None
    if not conf(cfg)["own"]:
        return None
    n = f"{files:,}" if done else f"at least {files:,}"
    facts = [f"{n} file{'' if files == 1 else 's'}, {_size_words(size)}"]
    facts += [f"in {p}" for p in real[:3]] + ([f"and {len(real) - 3} more places"] if len(real) > 3 else [])
    if outside:
        facts.append("outside your workspace" if len(outside) == len(real) else "partly outside your workspace")
    return Verdict("caution", "own", f"{what} It's your data, so it's your call, made knowing what goes.",
                   facts, f"delete {files} files" if files != 1 else "delete 1 file", "you")


def judge_command(line: str, cfg: dict, cwd: str = "") -> Verdict:
    """The verdict on one shell line: the strictest of its commands'."""
    line = str(line or "")
    if not line.strip():
        return OK
    cwd = os.path.realpath(os.path.expanduser(cwd)) if cwd else (_workspaces(cfg) or [os.getcwd()])[0]
    segs, exact = _segments(line)
    found: list[Verdict] = []
    hidden = False                 # a delete whose arguments a substitution or variable hides
    for words in segs:
        words = _unwrap(words)
        if not words:
            continue
        prog = os.path.basename(words[0])
        if re.fullmatch(r"(mkfs|mke2fs|mkswap)(\..+)?", prog):     # mkfs.ext4, mkfs.vfat…
            prog, words = "mkfs", ["mkfs", *words[1:]]
        if prog in SHELLS and "-c" in words:
            inner = words[words.index("-c") + 1] if words.index("-c") + 1 < len(words) else ""
            found.append(judge_command(inner, cfg, cwd))
            continue
        if prog in ATTACK_PROGRAMS:
            v = _judge_targets(prog, _targets(prog, words[1:], cfg), cfg)
            if v:
                found.append(v)
            continue
        lib = _library_program(prog)
        if lib:
            v = _judge_library(prog, lib, words[1:], cfg)
            if v:
                found.append(v)
            continue
        if prog in DESTROY_PROGRAMS:
            v = _judge_delete(words, cwd, cfg, exact)
            if v:
                found.append(v)
            elif not exact and prog in ("rm", "shred", "srm", "wipe", "find", "unlink"):
                hidden = True
        elif prog == "xargs" and any(os.path.basename(w) in ("rm", "shred") for w in words[1:]):
            found.append(Verdict("caution", "unread",
                                 "xargs feeds a delete with names from elsewhere, so Bento can't tell "
                                 "what would go.", ["command: " + " ".join(words)[:200]],
                                 "run it anyway", "you"))
    if hidden and not any(v.level == "refuse" for v in found):
        # `rm -rf $(cat list)`, `rm -rf "$DIR"/*`: the reader can't see what it would hit
        found.append(Verdict("caution", "unread",
                             "This deletes something a substitution or variable names, so Bento "
                             "can't tell what would go.", ["command: " + line[:200]],
                             "run it anyway", "you"))
    return strictest(found) if found else OK


def strictest(vs: list[Verdict]) -> Verdict:
    order = {"ok": 0, "caution": 1, "refuse": 2}
    return max(vs, key=lambda v: order.get(v.level, 0)) if vs else OK


def judge_python(code: str, cfg: dict) -> Verdict:
    """run_python: the attack libraries it imports and the attack programs it names, with the
    hosts in its strings. Deletes in code aren't read; the jail keeps the code to its folder."""
    code = str(code or "")
    mods = set(re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w]*)", code, re.M))
    progs = {w for w in re.findall(r"[\"']([\w.-]+)[\"'\s]", code) if w in ATTACK_PROGRAMS - {"ab", "hey", "wrk"}}
    hits = (mods & ATTACK_MODULES) | progs
    if not hits:
        return OK
    strings = re.findall(r"[\"']([^\"'\n]{3,200})[\"']", code)
    targets = []
    for s in strings:
        targets += _targets("", s.split())
    return _judge_targets(sorted(hits)[0], targets, cfg) or OK


def _library_program(prog: str) -> dict | None:
    """A program the ethics library (MITRE ATT&CK) lists as an attack tool; dual-use tools of
    the operating system carry no weight here."""
    try:
        from . import ethicslib
        e = ethicslib.program(prog)
    except Exception:
        return None
    return e if e and e.get("kind") in ("probe", "credentials", "remote-control") else None


def _judge_library(prog: str, lib: dict, args: list[str], cfg: dict) -> Verdict | None:
    ref = f"MITRE ATT&CK {lib.get('ref')}" if lib.get("ref") else "MITRE ATT&CK"
    targets = _targets(prog, [a.lstrip("\\") for a in args], cfg)
    if lib["kind"] == "remote-control":
        return Verdict("refuse", "attack",
                       f"{prog} is a framework for remote control of other machines ({ref} lists it as "
                       f"{lib.get('name')}).", [f"program: {prog}", f"source: {ref}"], "", "others")
    if targets:
        v = _judge_targets(prog, targets, cfg)
        if v:
            v.facts.append(f"source: {ref}")
            return v
    if lib["kind"] == "credentials":
        return Verdict("caution", "credentials",
                       f"{prog} dumps saved passwords and keys ({ref} lists {lib.get('name')} for it). "
                       f"Those belong to everyone who signs in here, not only you.",
                       [f"program: {prog}", f"source: {ref}"], "dump the passwords", "others")
    if not targets:
        return Verdict("caution", "unread",
                       f"{prog} probes machines ({ref}), and Bento couldn't tell which one this points at.",
                       [f"program: {prog}", f"source: {ref}"], "run it anyway", "you")
    return None


# --- what a step sends out, and what it read ------------------------------------------------

_SECRETISH = re.compile(r"(^|/)(\.env(\.[\w-]+)?|id_(rsa|ed25519|ecdsa|dsa)|[^/]*\.(pem|key|p12|pfx|kdbx)|"
                        r"credentials(\.json)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|wallet\.dat|"
                        r"cookies\.sqlite|login data|keychain[^/]*|secrets?(\.\w+)?|token(s)?(\.\w+)?)$|"
                        r"(^|/)\.(ssh|aws|gnupg|docker)/", re.I)
_READERS = frozenset({"cat", "less", "more", "head", "tail", "base64", "xxd", "od", "strings", "cp", "scp",
                      "tar", "zip", "gpg", "openssl", "python", "python3", "jq", "sed", "awk", "grep"})
_SENDERS = frozenset({"curl", "wget", "http", "https", "nc", "ncat", "netcat", "socat", "telnet", "ssh",
                      "scp", "sftp", "rsync", "ftp", "mail", "sendmail", "mutt"})


def secret_read(tool: str, args: dict) -> str:
    """The secret-looking file a step reads ('' when it reads none)."""
    args = args or {}
    if tool == "read_file":
        p = str(args.get("path") or "")
        return p if _SECRETISH.search(p) else ""
    if tool in ("run_command", "terminal_send"):
        line = str(args.get("command") or args.get("text") or "")
        segs, _ = _segments(line)
        for words in segs:
            words = _unwrap(words)
            if words and os.path.basename(words[0]) in _READERS:
                for w in words[1:]:
                    if not w.startswith("-") and _SECRETISH.search(w):
                        return w
    return ""


def outward(tool: str, args: dict) -> list[str]:
    """The hosts or addresses a step SENDS to or acts on: a POST, an upload, a remote shell, a
    copy to another machine, a mail. Reading a page is not sending."""
    args = args or {}
    out: list[str] = []
    if tool == "mail_send":
        to = args.get("to") or ""
        to = to if isinstance(to, list) else re.split(r"[,;\s]+", str(to))
        out += [t.strip().lower() for t in to if "@" in str(t)]
    elif tool in ("browser_type", "browser_click") and (tool == "browser_click" or args.get("submit")):
        if args.get("_site"):
            out.append(str(args["_site"]).lower())
    elif tool in ("run_command", "terminal_send"):
        line = str(args.get("command") or args.get("text") or "")
        segs, _ = _segments(line)
        for words in segs:
            words = _unwrap(words)
            if not words:
                continue
            prog = os.path.basename(words[0])
            if prog not in _SENDERS:
                continue
            rest = words[1:]
            sends = prog not in ("curl", "wget", "http", "https") or any(
                a in ("-d", "-F", "-T", "--form", "--json", "--upload-file", "--post-data", "--post-file")
                or a.startswith(("--data", "--form", "--json", "--post", "-d", "-F", "-T"))
                or (a in ("-X", "--request", "--method") and i + 1 < len(rest)
                    and rest[i + 1].upper() in ("POST", "PUT", "PATCH", "DELETE"))
                or re.fullmatch(r"(-X|--request=|--method=)(POST|PUT|PATCH|DELETE)", a, re.I)
                for i, a in enumerate(rest))
            if not sends:
                continue
            for a in rest:
                if "://" in a:
                    h = urlsplit(a).hostname
                    if h:
                        out.append(h.lower())
                elif prog in ("ssh", "scp", "sftp", "rsync") and not a.startswith("-"):
                    m = re.fullmatch(r"(?:[\w.-]+@)?([a-z0-9][\w.-]*):?.*", a, re.I)
                    if m and ("@" in a or ":" in a or prog == "ssh") and "/" not in m.group(1):
                        out.append(m.group(1).lower())
                        if prog == "ssh":
                            break
                elif prog in ("nc", "ncat", "netcat", "telnet", "socat") and not a.startswith("-") \
                        and (_HOST_RE.match(a) or re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", a)):
                    out.append(a.lower())
    elif tool == "run_python":
        code = str(args.get("code") or "")
        if re.search(r"\.(post|put|patch|delete)\(|method\s*=\s*['\"](POST|PUT|PATCH|DELETE)|sendall\(|smtplib",
                     code, re.I):
            out += [urlsplit(u).hostname.lower() for u in re.findall(r"https?://[^\s'\"]+", code)
                    if urlsplit(u).hostname]
    seen, uniq = set(), []
    for h in out:
        if h and h not in seen:
            seen.add(h)
            uniq.append(h)
    return uniq[:12]


def _judge_outward(tool: str, args: dict, cfg: dict, store=None, ctx: str = "") -> Verdict | None:
    """Where a step's targets came from (ethicsctx.PURPOSE), and whether it sends after a secret."""
    targets = outward(tool, args)
    if not targets:
        return None
    from . import ethicsctx
    if store is not None and ctx and ethicsctx.has_recent(store, ctx, "secret_read"):
        return Verdict("caution", "leak",
                       "This sends something out after this conversation read a secret (a key or a "
                       "password file). That is how keys leave a machine.",
                       [f"sends to: {', '.join(targets[:4])}"], "send it anyway", "others")
    untraced = []
    for t in targets:
        host = t.split("@", 1)[1] if "@" in t else t
        if owned(host, cfg) or ethicsctx.traced(host):
            continue
        untraced.append(t)
    if untraced:
        return Verdict("caution", "untraced",
                       f"This sends to {', '.join(untraced[:3])}, which you never named. The agent chose "
                       f"it itself, so you confirm it.",
                       [f"not in your request: {', '.join(untraced[:4])}"],
                       f"send to {untraced[0]}", "others")
    return None


def judge(tool: str, args: dict, cfg: dict, store=None, ctx: str = "") -> Verdict:
    """The one entry: the verdict on a tool call. Only the tools that can reach these harms are
    read; everything else is OK here and decided by the rest of the gate as before. With the
    person's store and the conversation (`ctx`), where its targets came from is judged too."""
    args = args or {}
    try:
        v = OK
        if tool == "run_command":
            v = judge_command(str(args.get("command") or ""), cfg, str(args.get("cwd") or ""))
        elif tool == "terminal_send" and not args.get("_fg"):
            v = judge_command(str(args.get("text") or ""), cfg, "")
        elif tool == "run_python":
            v = judge_python(str(args.get("code") or ""), cfg)
        if v.level != "refuse":
            o = _judge_outward(tool, args, cfg, store, ctx)
            if o:
                v = strictest([v, o]) if v.level != "ok" else o
        return v
    except Exception as e:                              # noqa: BLE001
        # a reader that broke is not a reason to wave a step through
        return Verdict("caution", "unread", f"Bento's ethics check couldn't read this step ({type(e).__name__}).",
                       [], "run it anyway", "you")


# --- the typed confirmation ----------------------------------------------------------------

# The caution a step is waiting on, set by the agent loop around its approver (as
# policy._NEEDS_PERSON is): the desk card reads it and asks for the phrase.
_PENDING: contextvars.ContextVar = contextvars.ContextVar("ethics_pending", default=None)
_CONFIRMED: dict = {}
CONFIRM_TTL = 900


def ask(verdict) -> tuple:
    """Open a confirmation for this caution (a Verdict or its dict); returns (token, the
    contextvar's reset token)."""
    d = verdict.to_dict() if isinstance(verdict, Verdict) else dict(verdict or {})
    tok = secrets.token_hex(8)
    return tok, _PENDING.set({**d, "token": tok})


def pending() -> dict | None:
    return _PENDING.get()


def done(ctx_token) -> None:
    _PENDING.reset(ctx_token)


def typed_ok(phrase: str, typed: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", str(s or "").strip().lower().replace(",", ""))   # noqa: E731
    return bool(phrase) and norm(typed) == norm(phrase)


def confirm(token: str, phrase: str, typed: str) -> bool:
    """A person typed the phrase at a screen: remember that this token was confirmed."""
    if not token or not typed_ok(phrase, typed):
        return False
    now = time.time()
    for k in [k for k, t in _CONFIRMED.items() if t < now]:
        _CONFIRMED.pop(k, None)
    _CONFIRMED[token] = now + CONFIRM_TTL
    return True


def consume(token: str) -> bool:
    """Was this token confirmed by typing? Once only. Every approver that never asked for the
    phrase (a phone, a scheduler, an older page) leaves it unconfirmed, so the step is refused."""
    t = _CONFIRMED.pop(token, 0)
    return bool(t and t >= time.time())


# --- proving a site is yours ------------------------------------------------------------

PROOF_PATH = "/.well-known/bento-proof.txt"


def prove_start(cfg: dict, host: str) -> dict:
    """A token for `host`, to be served at https://<host>/.well-known/bento-proof.txt."""
    h = _norm_host(host)
    if not _HOST_RE.match(h):
        raise ValueError(f"{host!r} isn't a site name (like example.com)")
    e = cfg.setdefault("ethics", {})
    tok = (e.setdefault("pending", {}).get(h)) or f"bento-proof-{secrets.token_hex(12)}"
    e["pending"][h] = tok
    return {"host": h, "token": tok, "url": f"https://{h}{PROOF_PATH}"}


async def prove_check(cfg: dict, host: str) -> tuple[bool, str]:
    """Fetch the proof file (through netguard) and, when it carries the token, record the site."""
    from . import netguard
    h = _norm_host(host)
    tok = (conf(cfg)["pending"]).get(h)
    if not tok:
        return False, f"Start with `bento ethics prove {h}` to get the token to put there."
    try:
        status, _ct, body = await netguard.read_capped(f"https://{h}{PROOF_PATH}", 4096, timeout=15)
    except Exception as e:                              # noqa: BLE001
        return False, f"Couldn't fetch https://{h}{PROOF_PATH}: {e}"
    if status != 200 or tok not in body.decode("utf-8", "replace"):
        return False, f"https://{h}{PROOF_PATH} answered {status} without the token."
    e = cfg.setdefault("ethics", {})
    e.setdefault("sites", [])
    e["sites"] = [s for s in e["sites"] if _norm_host(s.get("host")) != h] + \
        [{"host": h, "at": int(time.time()), "how": "proof file"}]
    e.get("pending", {}).pop(h, None)
    return True, f"{h} is yours: it served the proof file."


def forget_site(cfg: dict, host: str) -> bool:
    h = _norm_host(host)
    e = cfg.setdefault("ethics", {})
    before = len(e.get("sites") or [])
    e["sites"] = [s for s in (e.get("sites") or []) if _norm_host(s.get("host")) != h]
    return len(e["sites"]) != before


def refusal_words(v: Verdict) -> str:
    """What a refused step tells the agent and the ledger."""
    facts = "; ".join(v.facts[:3])
    return (f"Bento's ethics check refused this: {v.why}" + (f" ({facts})" if facts else "")
            + " No permission, approval or autonomy level can allow it.")


def caution_words(v: Verdict) -> str:
    facts = "; ".join(v.facts[:4])
    return (f"Bento's ethics check wants a person to confirm this: {v.why}" + (f" ({facts})" if facts else "")
            + f" A person types “{v.confirm}” at a screen to go ahead.")


def summary(cfg: dict) -> dict:
    """What the Settings card, `bento ethics` and /api/ethics show."""
    c = conf(cfg)
    return {"own": c["own"], "evaluator": c["evaluator"],
            "rules": [{"id": r[0], "harmed": r[1], "harmed_words": HARMED_WORDS[r[1]], "level": r[2],
                       "switchable": r[3], "words": r[4],
                       "on": c["own"] if r[0] == "own" else True} for r in RULES],
            "sites": c["sites"], "pending": [{"host": h, "token": t} for h, t in c["pending"].items()]}

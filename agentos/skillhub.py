"""Skills from the open: search, read, and install exactly what the person saw.

Asked for as "if something is not there it needs to look for skills out there in the
open and find the right tools it needs". A skill is text the agent will later follow
as a procedure, so a skill from a stranger is the untrusted-content problem in its
most durable form: one installed is an instruction that outlives the turn. So:

- **Searching reads, and only from GitHub** (`search`): Anthropic's public skills
  collection first (`CURATED`), then repositories that describe themselves as agent
  skills. No index is kept on disk and nothing is installed.
- **Reading pins the bytes** (`read`): a skill is fetched at a COMMIT, so the source
  names immutable bytes (the federated registry's argument), and the text and its
  findings are kept in memory for this person (`_SEEN`). `read_skill` is untrusted
  content in the agent loop: the words are somebody else's.
- **Installing installs what was read, and a person says yes every time.**
  `install_skill` is `skill.install`, in ALWAYS_ASK and refused to every non-user
  principal (policy._DEFINE); the approval card shows the skill's text and the
  findings (`approvalcard.body`), and `install` refuses a source that was not read
  first, so the card can never describe bytes other than the ones saved.
- **Only the text arrives.** A skill folder can carry scripts; they are not
  downloaded, and the findings say so, because a procedure that says "run
  scripts/build.py" will not find one here.
- **A name that exists is never replaced** (`save_skill` updates by name and
  somebody may rely on that skill).

Kept free of the server: `bento`'s terminal and the agent's tools call the same
functions. `AGENTOS_SKILLHUB_API` / `AGENTOS_SKILLHUB_RAW` point it at a stand-in.
"""
from __future__ import annotations

import os
import re
import time

import httpx

from . import users as usersmod

CURATED = ("anthropics/skills",)
MAX_BYTES = 100_000
TREE_TTL = 3600
SEEN_TTL = 3600
UA = {"User-Agent": "AgentOS/0.1", "Accept": "application/vnd.github+json"}

#: A repository is an agent skill only when it says it is for an agent: "skills" alone
#: matched a programming course and a whitepaper
AGENT_WORDS = ("claude", "codex", "cursor", "skill.md", "agent skill", "agent-skill",
               "agentskill", "ai agent", "ai-agent", "for agents", "llm", "gemini cli", "mcp")

_AGENT_RE = re.compile(r"(?<![a-z])(" + "|".join(re.escape(a) for a in AGENT_WORDS) + r")(?![a-z])")

_TREES: dict[str, tuple[float, str, list[str]]] = {}     # repo -> (when, sha, paths)
_SEEN: dict[tuple[str, str], dict] = {}                  # (uid, source) -> what was read

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "with", "make", "build", "create", "a", "an", "of", "to",
         "my", "our", "some", "that", "this", "about", "skill", "skills", "using", "use"}

#: What a reader should look at twice, in words a person can act on. A finding is a
#: reason to read the text on the card, never a verdict that it is safe.
FINDINGS = [
    (r"(curl|wget)[^\n|]*\|\s*(ba|z)?sh\b", "runs a script straight from the internet"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "deletes files with rm -rf"),
    (r"ignore (all |any )?(previous|prior|above|your) (instructions|rules)|disregard (the|your|all)"
     r"|do not (tell|inform) the user|without (asking|telling) the user",
     "tells the agent to ignore its rules or keep something from you"),
    (r"(api[_ -]?key|secret|password|token|\.env\b|id_rsa|\.ssh/|credentials)",
     "talks about keys, passwords or credentials"),
    (r"(curl|wget|fetch|requests\.(post|put))[^\n]*(-X\s*POST|--data|-d\s|upload|webhook)",
     "sends data to an address on the internet"),
    (r"\b(pip3?|npm|pnpm|yarn|brew|apt(-get)?|cargo|go)\s+(install|add|i)\b",
     "installs software"),
    (r"\bsudo\b", "asks for administrator rights"),
]


def _api() -> str:
    return os.environ.get("AGENTOS_SKILLHUB_API", "https://api.github.com").rstrip("/")


def _raw() -> str:
    return os.environ.get("AGENTOS_SKILLHUB_RAW", "https://raw.githubusercontent.com").rstrip("/")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None):
    r = await client.get(url, params=params)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RuntimeError("GitHub's search limit for this hour is used up; try again later")
    r.raise_for_status()
    return r


async def _tree(client, repo: str) -> tuple[str, list[str]]:
    """(commit sha, every path) of a repository's default branch, kept an hour."""
    hit = _TREES.get(repo)
    if hit and time.time() - hit[0] < TREE_TTL:
        return hit[1], hit[2]
    meta = (await _get(client, f"{_api()}/repos/{repo}")).json()
    branch = meta.get("default_branch") or "main"
    sha = (await _get(client, f"{_api()}/repos/{repo}/commits/{branch}")).json()["sha"]
    tree = (await _get(client, f"{_api()}/repos/{repo}/git/trees/{sha}",
                       {"recursive": "1"})).json()
    paths = [t["path"] for t in tree.get("tree") or [] if t.get("type") == "blob"]
    _TREES[repo] = (time.time(), sha, paths)
    return sha, paths


def _skill_paths(paths: list[str]) -> list[str]:
    return [p for p in paths if p.rsplit("/", 1)[-1] == "SKILL.md"]


def front(text: str, fallback: str) -> tuple[str, str, str]:
    """(name, description, text) from a SKILL.md: YAML front matter when there is
    one, else the first heading and the first line under it."""
    name, desc, named = fallback, "", False
    body = text.lstrip()
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            for line in body[3:end].splitlines():
                if ":" in line and not line.startswith((" ", "\t")):
                    k, v = line.split(":", 1)
                    k, v = k.strip().lower(), v.strip().strip("\"'")
                    if k == "name" and v:
                        name, named = v, True
                    elif k == "description" and v and v not in (">", "|", ">-", "|-"):
                        desc = v
            body = body[end + 4:]
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if not named:
                name, named = s.lstrip("# ").strip() or fallback, True
            continue
        desc = desc or s[:200]
        break
    name = re.sub(r"[^A-Za-z0-9 _.-]+", "", name).strip()[:60] or fallback
    return name, " ".join(desc.split())[:300], text


async def search(query: str, limit: int = 8) -> list[dict]:
    """Skills that match these words. Each: {source, name, description, repo, stars,
    curated}. `source` is what `read` takes."""
    want = _words(query)
    if not want:
        return []
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA) as client:
        for repo in CURATED:
            try:
                sha, paths = await _tree(client, repo)
            except Exception:
                continue
            ranked = []
            for p in _skill_paths(paths):
                folder = p.rsplit("/", 2)[-2] if "/" in p else repo
                n = len(want & _words(folder.replace("-", " ")))
                n += sum(1 for w in want if len(w) >= 5 and w[:5] in folder.lower())
                if n:
                    ranked.append((n, p, folder))
            ranked.sort(key=lambda x: (-x[0], x[1]))
            for _n, p, folder in ranked[:4]:
                desc = ""
                try:
                    r = await _get(client, f"{_raw()}/{repo}/{sha}/{p}")
                    desc = front(r.text[:4000], folder)[1]
                except Exception:
                    pass
                out.append({"source": f"{repo}:{p}", "name": folder, "description": desc,
                            "repo": repo, "stars": None, "curated": True})
        try:
            q = " ".join(sorted(want)[:4])
            r = await _get(client, f"{_api()}/search/repositories",
                           {"q": f"{q} skill in:name,description,topics", "sort": "stars",
                            "per_page": 8})
            for it in r.json().get("items") or []:
                full = it.get("full_name") or ""
                if not full or full in CURATED or any(o["repo"] == full for o in out):
                    continue
                # GitHub's search matches loosely: keep a repository that calls itself
                # a skill and is about at least one of the words
                about = f"{full} {it.get('description') or ''} {' '.join(it.get('topics') or [])}".lower()
                if "skill" not in about or not (want & _words(about)) \
                        or not _AGENT_RE.search(about):
                    continue
                out.append({"source": full, "name": full.split("/")[-1],
                            "description": " ".join(str(it.get("description") or "").split())[:200],
                            "repo": full, "stars": it.get("stargazers_count"),
                            "curated": False})
        except Exception:
            if not out:
                raise
    return out[:max(1, int(limit))]


def findings(text: str) -> list[str]:
    low = (text or "").lower()
    return [why for pat, why in FINDINGS if re.search(pat, low)]


async def read(source: str) -> dict:
    """Fetch one skill at a commit and keep exactly those bytes for this person.

    `source` is `owner/repo:path/SKILL.md`, `owner/repo` (one SKILL.md, or a list to
    choose from), or an https address of a .md file. Returns {source, name,
    description, text, findings, extra, choices}; `choices` is set, and nothing is
    kept, when a repository holds several skills."""
    src = (source or "").strip()
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA) as client:
        if src.startswith("https://"):
            if not src.lower().endswith(".md"):
                raise ValueError("an address must point at a .md file")
            text = (await _get(client, src)).text
            pinned, extra = src, []
        else:
            repo, _, path = src.partition(":")
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                raise ValueError("give owner/repo, owner/repo:path/SKILL.md, or an https .md address")
            sha, paths = await _tree(client, repo)
            skills = _skill_paths(paths)
            if not path:
                if len(skills) != 1:
                    return {"source": repo, "choices": [f"{repo}:{p}" for p in skills[:40]],
                            "text": "", "findings": []}
                path = skills[0]
            if path not in paths:
                raise ValueError(f"{repo} has no file {path}")
            text = (await _get(client, f"{_raw()}/{repo}/{sha}/{path}")).text
            folder = path.rsplit("/", 1)[0] if "/" in path else ""
            extra = [p for p in paths if folder and p.startswith(folder + "/") and p != path]
            pinned = f"{repo}@{sha[:12]}:{path}"
            src = f"{repo}:{path}"
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"that skill is over {MAX_BYTES // 1000} KB; not a procedure")
    fallback = (src.rsplit("/", 2)[-2] if src.endswith("SKILL.md") and "/" in src
                else src.rsplit("/", 1)[-1].removesuffix(".md"))
    name, desc, text = front(text, fallback)
    found = findings(text)
    if extra:
        found.append(f"comes with {len(extra)} other file(s) (scripts, references) that are "
                     f"not installed; only this text is")
    rec = {"source": src, "pinned": pinned, "name": name, "description": desc, "text": text,
           "findings": found, "extra": extra[:20], "choices": [], "at": time.time()}
    _SEEN[(usersmod.current() or "", src)] = rec
    return rec


def seen(source: str) -> dict | None:
    """What this person last read from this source, while it is fresh."""
    rec = _SEEN.get((usersmod.current() or "", (source or "").strip()))
    if rec and time.time() - rec["at"] < SEEN_TTL:
        return rec
    return None


def install(store, source: str, as_name: str = "") -> str:
    """Save exactly the bytes `read` kept. Refuses a source not read first, and a name
    that already exists."""
    rec = seen(source)
    if not rec:
        return ("[error] read it first with read_skill, so the person sees the text they "
                "are agreeing to")
    name = (as_name or rec["name"]).strip()[:60]
    if not name:
        return "[error] the skill has no name; pass as_name"
    if store.get_skill(name):
        return (f"[error] a skill called '{name}' is already installed and is kept as it "
                f"is; pass as_name to install this one beside it")
    store.save_skill(name, rec["description"], rec["text"], source=rec["pinned"])
    store.log("system", f"skill '{name}' installed from {rec['pinned']}")
    return (f"installed skill '{name}' from {rec['pinned']}. Load it with use_skill('{name}')"
            + (". Its folder had other files that were not installed" if rec["extra"] else ""))


def card_text(source: str) -> str:
    """The approval card's body for installing this source: the text and what to look at."""
    rec = seen(source)
    if not rec:
        return f"source: {source}\n(not read yet: the install will refuse)"
    head = [f"source: {rec['pinned']}", f"name: {rec['name']}"]
    if rec["findings"]:
        head.append("look at: " + "; ".join(rec["findings"]))
    return "\n".join(head) + "\n\n" + rec["text"]

"""Which tools to put in front of the model this step.

AgentOS ships 90 tools. Their JSON schemas are ~11,600 tokens, and they are sent
on *every* call of every step. Against a local model configured at
`ollama_num_ctx: 24576` that is 47% of the context window spent before the system
prompt (memories, graph facts, skills, the MCP catalogue) or a single word of the
conversation has been added. Two things follow, and both have been visible in
this project's own bug history: the prompt crowds out the thing being asked, and
a small model picks worse from a list of ninety than from a list of thirty.

The fix is not fewer tools. It is fewer tools *at once*:

- a **core** set is always offered — the things any turn may need, so scoping can
  never strand a turn that just wanted to read a file or remember something;
- everything else is scored against what the user actually said and the top few
  are added;
- anything the turn has **already used** stays offered for the rest of the turn,
  because a model that called `git_status` will want `git_commit` next and the
  user's words never mentioned either;
- and `find_tools` is the way back: the model asks for a capability in its own
  words, and the matching tools appear on the next step. Tool sets are rebuilt
  per step, so this costs one step, not a lost turn.

**Default OFF, because it was measured and it did not pay.** The reasoning above
is sound and the token arithmetic is real, but `agentos eval` on this machine's
local model says the opposite of what the reasoning predicts:

    ollama/qwen3.5:9b, 11 cases x 2 rounds, same cases, only `scope` differs
      scope: all     21/22 passed   median case 9.9s
      scope: always  19/22 passed   median case 8.0s

Narrowing made the model faster per step and slightly *worse* at the task, twice
running. 22 samples is a small n and the individual failures look like ordinary
9B flakiness (a different case failed each round), but the direction was
consistent and nothing here supports turning it on for everyone. So the default
is `all`: the mechanism ships, tested and documented, and a user with a tighter
window can enable it and check with the harness on their own model.

The open question this leaves — whether the cost was the narrowing itself or the
`catalogue()` note that comes with it — is worth one more experiment before the
default is ever revisited. `find_tools` stays useful either way: a model that
cannot spot a tool in a list of ninety can now ask for it by name.

No model names anywhere in the decision: it reads the configured window, so a
128k local model is treated like the large model it is.
"""

from __future__ import annotations

import json
import re

# Always offered. Not "the most used" — the ones whose absence would strand a
# turn mid-thought, plus the two that let the model find its way back to the rest.
CORE = {
    # know things
    "remember", "recall", "forget", "kg_add", "kg_query",
    # see things
    "read_file", "list_dir", "search_files", "fetch_url",
    # do things
    "write_file", "run_command", "run_python",
    # say things
    "save_report", "llm_generate",
    # find the other eighty
    "find_tools", "use_skill",
}

DEFAULTS = {
    # "all" by default — see the measurement in this module's docstring. "auto"
    # is the reasoned behaviour (narrow only on a tight window) for anyone whose
    # own eval run says it helps on their model.
    "scope": "all",         # all | auto | always
    "budget": 30,           # how many tools to offer when scoping
    "window_share": 0.20,   # scope once schemas exceed this share of the context window
    "cloud_context": 128000,  # assumed window when the provider does not tell us
}

_WORD = re.compile(r"[a-z0-9_]+")
# Words that match everything and therefore rank nothing.
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "my",
         "me", "i", "it", "this", "that", "is", "are", "do", "does", "please", "can",
         "you", "get", "set", "run", "make", "use", "from", "about", "what", "how",
         "tool", "tools", "agentos", "user", "returns", "return", "list"}


def cfg_for(cfg: dict) -> dict:
    d = dict(DEFAULTS)
    d.update(cfg.get("tools") or {})
    return d


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2 and w not in _STOP}


def context_window(cfg: dict, model_id: str = "") -> int:
    """What we actually know about the window, not what we hope."""
    tc = cfg_for(cfg)
    if (model_id or cfg.get("default_model", "")).startswith("ollama/"):
        return int(cfg.get("ollama_num_ctx", 24576))
    return int(tc.get("cloud_context") or 128000)


def schema_tokens(schemas: list) -> int:
    return len(json.dumps(schemas)) // 4


def should_scope(schemas: list, cfg: dict, model_id: str = "") -> bool:
    tc = cfg_for(cfg)
    mode = str(tc.get("scope") or "auto")
    if mode == "all":
        return False
    if mode == "always":
        return True
    return schema_tokens(schemas) > float(tc.get("window_share", 0.20)) * context_window(cfg, model_id)


def _overlap(want: set[str], have: set[str]) -> int:
    """Word overlap, tolerating the endings English adds.

    "scheduling" should find `schedule_task` and "notifications" should find the
    notification trigger. Real stemming would be a dependency for a rounding
    error; a five-character prefix covers the cases that come up. Four was tried
    and matched "unrelated" against "unread" — the threshold is doing real work.
    """
    n = len(want & have)
    for w in want - have:
        if len(w) >= 5 and any(h.startswith(w[:5]) for h in have):
            n += 1
    return n


def score(schema: dict, want: set[str]) -> int:
    """How much this tool looks like what was asked for.

    The name is worth more than the description because a name is what the user
    half-remembers ("schedule a task", "commit that") — and an exact mention of
    the tool's own name is decisive.
    """
    name = schema.get("name", "")
    nwords = _words(name.replace("_", " "))
    dwords = _words(schema.get("description", "")[:400])
    s = 3 * _overlap(want, nwords) + _overlap(want, dwords)
    if name.lower() in want or name.lower().replace("_", "") in {w.replace("_", "") for w in want}:
        s += 10
    # a family the turn is clearly in: "git status" should surface every git_*
    prefix = name.split("_")[0].lower()
    if len(prefix) > 2 and prefix in want:
        s += 4
    return s


def match_names(schemas: list, text: str, limit: int = 12) -> list[str]:
    """The tools that best match a phrase — what `find_tools` answers with."""
    want = _words(text)
    ranked = sorted(((score(t, want), t["name"]) for t in schemas), key=lambda x: (-x[0], x[1]))
    return [n for s, n in ranked[:limit] if s > 0]


def scope(schemas: list, text: str, cfg: dict, pinned: set | None = None,
          model_id: str = "") -> tuple[list, bool]:
    """Returns (schemas_to_offer, narrowed?).

    `pinned` is what this turn has already used or explicitly unlocked; it is
    never dropped, because taking a tool away mid-turn is how a model ends up
    insisting a capability disappeared.
    """
    if not should_scope(schemas, cfg, model_id):
        return schemas, False
    tc = cfg_for(cfg)
    budget = int(tc.get("budget") or 30)
    keep = set(CORE) | set(pinned or set())
    want = _words(text)
    rest = sorted(((score(t, want), t["name"]) for t in schemas if t["name"] not in keep),
                  key=lambda x: (-x[0], x[1]))
    for s, n in rest:
        if len(keep) >= budget and s <= 0:
            break
        if len(keep) >= budget:
            break
        keep.add(n)
    out = [t for t in schemas if t["name"] in keep]
    return out, True


def catalogue(schemas: list, offered: list) -> str:
    """One line naming what is NOT on the table, so the model knows to ask.

    Without this the narrowing is invisible to the model and it will confidently
    tell the user the OS cannot do something it can.
    """
    hidden = [t["name"] for t in schemas if t["name"] not in {o["name"] for o in offered}]
    if not hidden:
        return ""
    return (f"\n\nTOOLS: you are being shown {len(offered)} of {len(schemas)} tools — the ones "
            f"that fit this request. {len(hidden)} more exist (including: "
            f"{', '.join(hidden[:12])}…). If you need a capability you cannot see, call "
            f"`find_tools` with a plain description of what you need and it will be added "
            f"before your next step. Never tell the user something is impossible because "
            f"its tool was not in this list.")

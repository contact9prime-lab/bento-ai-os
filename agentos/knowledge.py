"""Background knowledge engine.

After each chat turn, a small LLM pass mines the exchange for durable user facts,
session context, and knowledge-graph triples — so memory and the knowledge base
populate themselves instead of waiting for the agent to volunteer a `remember`/
`kg_add` call. The same pass applies corrections: facts the user contradicted are
updated or retracted rather than accumulating alongside stale versions.

A periodic maintenance loop keeps the knowledge healthy:
  - embeds memories for semantic recall (Ollama embed model, auto-detected),
  - rolls idle conversations' session memories up into durable user memories,
  - merges duplicate knowledge-graph entities ("Piyush" / "piyush accacia").
"""

import asyncio
import json
import math
import re
import time

import httpx

from . import providers

EXTRACT_PROMPT = """You are the memory subsystem of AgentOS. Analyze one exchange between the user and the assistant and extract knowledge worth keeping. Be selective — most exchanges contain little or nothing worth storing. Never invent facts that are not in the text.

{space_header}
Return ONLY a JSON object (no markdown, no commentary) with this exact shape:
{{
  "user_memories": ["durable facts about the user or their machine that will still matter in future conversations NO MATTER what they are working on: name, role, preferences, tools, recurring goals"],
  "space_memories": ["facts about the CURRENT SPACE named above: its goals, its stack, the people in it, decisions taken inside it. True there, not necessarily anywhere else"],
  "session_memories": ["context that matters only within THIS ongoing conversation: what the user is currently trying to do, decisions made, constraints agreed, state of the task"],
  "facts": [{{"subject": "...", "relation": "...", "object": "...", "subject_type": "person|project|tool|org|place|concept|", "object_type": "...", "scope": "global|space"}}],
  "updates": [{{"old": "<one of the existing memories below that this exchange corrected>", "new": "<the corrected version>"}}],
  "retractions": ["<one of the existing memories below that this exchange showed to be wrong or withdrawn>"]
}}

Rules:
- Every list may be empty. Prefer empty over noise. Small talk, questions answered from general knowledge, and failed attempts usually yield NOTHING.
- Do not re-store anything already covered by the existing memories listed below.
- "updates"/"retractions" must quote an existing memory VERBATIM in "old"/the retraction — only when the user explicitly corrected or withdrew it.
- Each memory is one short self-contained sentence.
- Facts are (subject, relation, object) triples about named entities and how they connect, e.g. ("Piyush", "works at", "Accacia").
- GLOBAL vs SPACE, the one test that decides it: if the fact would STILL BE TRUE after this project ends, it is a user_memory and its triples are "global". If it stops being true when the project does, it is a space_memory and its triples are "space". "Piyush works at Accacia" is global. "This project deploys on Fridays" is space.
- When there is no current space, put everything durable in "user_memories" and leave "space_memories" empty.

Existing user memories (do NOT duplicate):
{existing}

=== The exchange ===
User: {user_text}

Assistant: {assistant_text}
=== end exchange ==="""

ROLLUP_PROMPT = """You are the memory subsystem of AgentOS. A conversation has gone idle. Below are its session memories (working context captured while it was active). Distill anything of LASTING value into durable user memories; discard everything that only mattered inside that conversation.

Return ONLY a JSON object: {{"user_memories": ["..."]}} — 0 to 3 short self-contained sentences. Usually 0 or 1. Do not duplicate the existing user memories listed below.

Conversation title: {title}

Session memories:
{memories}

Existing user memories (do NOT duplicate):
{existing}"""

KG_DEDUP_PROMPT = """You maintain the knowledge graph of AgentOS. Below is the list of entity names currently in the graph. Identify groups that are clearly the SAME real-world entity (case variants, with/without surname, abbreviations, obvious typos). Be conservative: when in doubt, do not merge.

Return ONLY a JSON object: {{"merges": [{{"keep": "<best canonical name>", "merge": ["<duplicate name>", ...]}}]}} — empty list if nothing should merge.

Entities:
{names}"""


def _mem_cfg(cfg: dict) -> dict:
    return cfg.get("memory") or {}


# -- foreground-first scheduling ---------------------------------------------
# Local model servers (Ollama) serialize requests, so a background extraction or
# maintenance call issued mid-conversation makes the user's next turn queue behind
# it — chat feels stuck. Foreground turns register here; background LLM work waits
# until the machine is idle (or a generous timeout passes).

_active_turns = {"n": 0}
# When did the user last talk to us? Idle triggers and the "while you were away"
# briefing read this. `ts` is 0.0 until a turn happens in this process; `boot`
# keeps idle math sane on a fresh start (idle counts from server start, not 1970).
_last_turn = {"ts": 0.0, "boot": time.time()}


def turn_started():
    _active_turns["n"] += 1
    _last_turn["ts"] = time.time()


def turn_ended():
    _active_turns["n"] = max(0, _active_turns["n"] - 1)
    _last_turn["ts"] = time.time()


def last_turn_ts() -> float:
    """Timestamp idle periods are measured from (last turn, else process start)."""
    return _last_turn["ts"] or _last_turn["boot"]


def last_turn_seen() -> float:
    """Last turn in THIS process; 0.0 if none yet (the briefing falls back to the DB)."""
    return _last_turn["ts"]


def _is_local(model_id: str) -> bool:
    return providers.parse_model_id(model_id or "")[0] == "ollama"


async def wait_model_idle(model_id: str = "", max_wait: float = 900):
    """Only local models contend for the GPU — cloud APIs handle requests in
    parallel, so background calls to them never need to wait."""
    if model_id and not _is_local(model_id):
        return
    waited = 0.0
    while _active_turns["n"] > 0 and waited < max_wait:
        await asyncio.sleep(3)
        waited += 3


def _parse_json(text: str) -> dict:
    """Extract the first JSON object from model output (tolerates code fences/prose)."""
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE)
    start = text.find("{")
    if start < 0:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return {}
    return {}


# ---------------------------------------------------------------------------
# Embeddings & semantic recall
# ---------------------------------------------------------------------------

_embed_cache = {"model": None, "ts": 0.0}


async def embed_model(cfg: dict) -> str | None:
    """The embedding model to use: memory.embed_model, or the first embedding-ish
    model installed in Ollama. None disables semantic recall (keyword fallback)."""
    mc = _mem_cfg(cfg)
    if mc.get("embed_model"):
        return mc["embed_model"]
    if time.time() - _embed_cache["ts"] < 300:
        return _embed_cache["model"]
    names = await providers.ollama_models(cfg["providers"]["ollama"]["base_url"])
    hints = ("embed", "minilm", "bge-", "bge:", "arctic")
    pick = next((n for n in names if any(h in n.lower() for h in hints)), None)
    _embed_cache.update(model=pick, ts=time.time())
    return pick


async def embed_texts(cfg: dict, texts: list[str]) -> list[list[float]] | None:
    """Embed texts via Ollama. Returns None when no embed model is available."""
    if not texts:
        return []
    model = await embed_model(cfg)
    if not model:
        return None
    base = cfg["providers"]["ollama"]["base_url"]
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{base}/api/embed",
                              json={"model": model, "input": texts, "truncate": True})
        r.raise_for_status()
        return r.json().get("embeddings") or None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


async def semantic_rank(cfg: dict, mems: list[dict], query: str) -> list[dict] | None:
    """Order memories by relevance to `query`. Memories without embeddings keep their
    original (recency) order at the tail. None = semantic recall unavailable."""
    query = (query or "").strip()
    if not query or not mems:
        return None
    qvecs = await embed_texts(cfg, [query[:2000]])
    if not qvecs:
        return None
    qv = qvecs[0]
    scored, unscored = [], []
    for m in mems:
        try:
            vec = json.loads(m.get("embedding") or "null")
        except Exception:
            vec = None
        if vec:
            scored.append((_cosine(qv, vec), m))
        else:
            unscored.append(m)
    scored.sort(key=lambda t: t[0], reverse=True)
    return [m for _, m in scored] + unscored


async def backfill_embeddings(cfg: dict, store, batch: int = 64) -> int:
    """Embed any memories that don't have a vector yet. Returns how many were embedded."""
    done = 0
    while True:
        missing = store.memories_missing_embedding(limit=batch)
        if not missing:
            return done
        vecs = await embed_texts(cfg, [m["content"] for m in missing])
        if not vecs:
            return done  # no embed model — stay on keyword recall
        for m, v in zip(missing, vecs):
            store.set_memory_embedding(m["id"], json.dumps(v))
            done += 1
        if len(missing) < batch:
            return done


# ---------------------------------------------------------------------------
# Per-turn extraction
# ---------------------------------------------------------------------------

async def extract_from_turn(cfg: dict, store, cid: str, user_text: str,
                            assistant_text: str, broadcast=None):
    """Fire-and-forget after a chat turn. Must never raise into the caller."""
    mc = _mem_cfg(cfg)
    if not mc.get("auto_extract", True):
        return
    model = mc.get("model") or cfg.get("default_model") or ""
    if not model or not (assistant_text or "").strip():
        return
    try:
        await wait_model_idle(model)  # never make a live conversation queue behind us
        # The space this conversation lives in decides where what we learn is
        # filed. It comes from the conversation, not from whatever the user last
        # clicked — see spaces.py.
        space_id = ""
        try:
            space_id = (store.get_conversation(cid) or {}).get("space_id") or ""
        except Exception:
            pass
        if space_id:
            from . import spaces as spacemod
            info = spacemod.describe(store, space_id)
            desc = f" — {info['description']}" if info.get("description") else ""
            space_header = (f"Current space: {info['name']}{desc}\n"
                            f"(There is also a GLOBAL scope for what is true about the user "
                            f"no matter what they are working on.)\n")
        else:
            space_header = ("Current space: none — the user is not working inside a "
                            "particular project right now.\n")
        existing = store.search_memories("", limit=40, scope="user", space=space_id)
        existing_txt = "\n".join(f"- {m['content']}" for m in existing) or "(none yet)"
        prompt = EXTRACT_PROMPT.format(
            space_header=space_header,
            existing=existing_txt,
            user_text=(user_text or "")[:4000],
            assistant_text=(assistant_text or "")[:4000],
        )
        raw = await providers.complete(cfg, model, prompt)
        data = _parse_json(raw)
        if not data:
            return
        added = {"user": 0, "space": 0, "session": 0, "facts": 0, "updated": 0, "retracted": 0}
        # corrections first, so a superseded fact can't block its replacement as a "duplicate"
        for u in (data.get("updates") or [])[:5]:
            old, new = (u.get("old") or "").strip(), (u.get("new") or "").strip()
            hit = store.find_memory(old) if old else None
            if hit and new:
                store.update_memory(hit["id"], content=new)
                added["updated"] += 1
        for old in (data.get("retractions") or [])[:5]:
            hit = store.find_memory(old) if isinstance(old, str) else None
            if hit and not hit.get("pinned"):  # pinned memories only die by the user's hand
                store.delete_memory(hit["id"])
                added["retracted"] += 1
        for content in (data.get("user_memories") or [])[:5]:
            if isinstance(content, str) and content.strip():
                # global on purpose, even inside a space: this bucket is defined as
                # "still true after the project ends"
                if store.add_memory(content, scope="user", source="auto"):
                    added["user"] += 1
        for content in (data.get("space_memories") or [])[:5]:
            if isinstance(content, str) and content.strip() and space_id:
                if store.add_memory(content, scope="user", source="auto", space_id=space_id):
                    added["space"] += 1
        for content in (data.get("session_memories") or [])[:5]:
            if isinstance(content, str) and content.strip():
                if store.add_memory(content, scope="session", conversation_id=cid,
                                    source="auto", space_id=space_id):
                    added["session"] += 1
        for f in (data.get("facts") or [])[:10]:
            try:
                s, r, o = (f.get("subject") or "").strip(), (f.get("relation") or "").strip(), \
                          (f.get("object") or "").strip()
                if s and r and o:
                    # an assertion is filed where it is true; "global" (or no space
                    # at all) puts it in the graph everything can see
                    fact_space = space_id if str(f.get("scope") or "").lower() == "space" else ""
                    store.kg_add(s, r, o, f.get("subject_type") or "",
                                 f.get("object_type") or "", space_id=fact_space)
                    added["facts"] += 1
            except Exception:
                continue
        if any(added.values()):
            store.log("memory", "auto-extracted: " + ", ".join(
                f"{v} {k}" for k, v in added.items() if v),
                {"conversation_id": cid, "model": model, "space_id": space_id},
                conversation_id=cid, space_id=space_id)
            if broadcast:
                await broadcast({"type": "knowledge_update", **added})
        try:
            await backfill_embeddings(cfg, store)
        except Exception:
            pass
    except Exception as e:
        try:
            store.log("error", f"knowledge extraction failed: {type(e).__name__}: {e}")
        except Exception:
            pass


def schedule_extraction(cfg: dict, store, cid: str, user_text: str,
                        assistant_text: str, broadcast=None):
    """Non-blocking helper for callers inside the event loop."""
    asyncio.create_task(
        extract_from_turn(cfg, store, cid, user_text, assistant_text, broadcast))


# ---------------------------------------------------------------------------
# Maintenance: session rollup, KG dedup, embedding backfill
# ---------------------------------------------------------------------------

async def rollup_idle_sessions(cfg: dict, store, broadcast=None) -> int:
    """Distill session memories of idle conversations into durable user memories."""
    mc = _mem_cfg(cfg)
    hours = float(mc.get("rollup_after_hours", 24) or 0)
    model = mc.get("model") or cfg.get("default_model") or ""
    if hours <= 0 or not model:
        return 0
    await wait_model_idle(model)
    total = 0
    existing = store.search_memories("", limit=40, scope="user")
    existing_txt = "\n".join(f"- {m['content']}" for m in existing) or "(none yet)"
    for conv in store.rollup_candidates(time.time() - hours * 3600):
        mems = store.search_memories("", limit=100, scope="session", conversation_id=conv["id"])
        if not mems:
            store.mark_rolled_up(conv["id"])
            continue
        prompt = ROLLUP_PROMPT.format(
            title=conv.get("title") or "(untitled)",
            memories="\n".join(f"- {m['content']}" for m in mems),
            existing=existing_txt)
        try:
            data = _parse_json(await providers.complete(cfg, model, prompt))
        except Exception:
            continue  # model unavailable — retry next cycle
        added = 0
        # What a conversation inside a project taught us is, by default, about
        # that project — so it rolls up INTO the space rather than into the
        # user's global memory. Promoting it further is a judgement the Memory
        # app makes with a human present, not one a nightly job should make
        # silently for three clients at once.
        space_id = conv.get("space_id") or ""
        for c in (data.get("user_memories") or [])[:3]:
            if isinstance(c, str) and c.strip() and store.add_memory(
                    c, scope="user", source="auto", space_id=space_id):
                added += 1
        store.mark_rolled_up(conv["id"])
        total += added
        if added:
            store.log("memory", f"session rollup: {added} durable memories from "
                                f"'{(conv.get('title') or '')[:60]}'",
                      {"conversation_id": conv["id"], "space_id": space_id},
                      conversation_id=conv["id"], space_id=space_id)
    if total and broadcast:
        await broadcast({"type": "knowledge_update", "rollup": total})
    return total


_kg_state = {"last_node_count": -1}


async def kg_dedup(cfg: dict, store, broadcast=None, force: bool = False) -> int:
    """Merge knowledge-graph nodes that name the same entity. Skips when the graph
    hasn't grown since the last pass (unless forced)."""
    mc = _mem_cfg(cfg)
    if not mc.get("kg_dedup", True) and not force:
        return 0
    model = mc.get("model") or cfg.get("default_model") or ""
    nodes = store.kg_graph()["nodes"]
    if not model or len(nodes) < 5:
        return 0
    if not force and len(nodes) == _kg_state["last_node_count"]:
        return 0
    await wait_model_idle(model)
    names = [n["name"] for n in nodes][:300]
    try:
        data = _parse_json(await providers.complete(
            cfg, model, KG_DEDUP_PROMPT.format(names="\n".join(f"- {n}" for n in names))))
    except Exception:
        return 0
    merged = 0
    for g in (data.get("merges") or [])[:20]:
        keep = (g.get("keep") or "").strip()
        dupes = [d for d in (g.get("merge") or [])
                 if isinstance(d, str) and d.strip() and d.strip().lower() != keep.lower()]
        if keep and dupes:
            merged += store.kg_merge_nodes(keep, dupes)
    _kg_state["last_node_count"] = len(store.kg_graph()["nodes"])
    if merged:
        store.log("memory", f"knowledge graph dedup: merged {merged} duplicate entities")
        if broadcast:
            await broadcast({"type": "knowledge_update", "kg_merged": merged})
    return merged


async def run_maintenance(cfg: dict, store, broadcast=None, force: bool = False):
    """One maintenance pass. Each stage fails independently and quietly."""
    try:
        await backfill_embeddings(cfg, store)
    except Exception as e:
        store.log("error", f"embedding backfill failed: {type(e).__name__}: {e}")
    try:
        await rollup_idle_sessions(cfg, store, broadcast)
    except Exception as e:
        store.log("error", f"session rollup failed: {type(e).__name__}: {e}")
    try:
        # after the rollup, the attention engine may float at most ONE actionable
        # suggestion ("you asked about X three times — want a scheduled digest?")
        from . import attention
        await attention.maybe_suggest(cfg, store, broadcast)
    except Exception as e:
        store.log("error", f"suggestion pass failed: {type(e).__name__}: {e}")
    try:
        await kg_dedup(cfg, store, broadcast, force=force)
    except Exception as e:
        store.log("error", f"kg dedup failed: {type(e).__name__}: {e}")
    try:
        # The MCP catalogue is 35 MB of parsed JSON for an app that is opened
        # occasionally. Let it go when nobody has searched for a while; the file
        # stays and the next search reads it back.
        from . import mcp_store as mcp_storemod
        said = mcp_storemod.housekeeping(cfg)
        if said:
            store.log("system", said)
    except Exception:
        pass
    try:
        # Retention. Nothing in this database was ever deleted by age, which on a
        # Raspberry Pi with an SD card is the failure mode rather than an
        # untidiness: a machine doing its job every day fills its own disk, and
        # the first symptom is being unable to write the log that would say why.
        # Telemetry only — the ledger and the user's own work are never touched.
        r = (cfg.get("retention") or {})
        if r.get("enabled", True):
            gone = store.prune(int(r.get("logs_days", 30)),
                               int(r.get("events_days", 30)),
                               int(r.get("usage_days", 365)))
            if gone:
                store.log("system", "retention: dropped "
                          + ", ".join(f"{n} {t}" for t, n in gone.items())
                          + f" · database now {store.db_bytes() // 1024} kB")
    except Exception as e:
        store.log("error", f"retention sweep failed: {type(e).__name__}: {e}")
    try:
        # keep the file search index warm while the machine is idle
        from . import search as searchmod
        await searchmod.maintenance_tick(cfg, store)
    except Exception as e:
        store.log("error", f"search index refresh failed: {type(e).__name__}: {e}")


async def maintenance_loop(cfg: dict, store, broadcast=None, interval: int = 1800):
    from . import users as usersmod
    await asyncio.sleep(90)  # let the server (and Ollama) settle after boot
    while True:
        # Everybody's graph, one at a time. A machine with accounts keeps its
        # memory in each person's own database, so a loop that only ever swept the
        # machine's would leave every real user's knowledge unconsolidated —
        # silently, and in the one subsystem whose whole job is to notice things.
        for uid in usersmod.sweep():
            with usersmod.as_user(uid):
                await run_maintenance(*usersmod.resolve(cfg, store), broadcast)
        await asyncio.sleep(interval)

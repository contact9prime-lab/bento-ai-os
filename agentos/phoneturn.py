"""Who answers a message that came from a phone, for Telegram and WhatsApp alike.

Each bridge had its own copy of this, and the two drifted from the desktop's chat turn
(`server._run_chat`) one seam at a time: no brain fallback (a usage limit or a lapsed
sign-in just failed, on the surfaces where nobody is watching), no huddle (`@a @b …`), a
specialist or a department addressed by name ran without the thread it was addressed in,
a turn on an agent CLI was missing from Usage, and a photo never reached the brain. One
function now, so the next thing a chat turn learns is learned once for both phones.

GUI: the desktop's own turn is `server._run_chat`, which streams; this is its twin for a
surface with no event stream. TUI: the terminal chat goes through the server's socket and
so through `_run_chat`. SUI: nothing here touches a window.
"""
from __future__ import annotations

NO_TEXT = "(done — no text output)"


async def answer(store, cfg: dict, toolbox, *, cid: str, text: str, surface: str, emit, approver,
                 note: str = "", images: tuple = (), on_run=None, steerable: bool = False,
                 tell=None) -> dict:
    """One turn for the message just saved as the conversation's last.

    Returns {"reply", "steps", "meta"}; the caller saves and sends it. `note` goes in
    front of the message for the built-in loop (what the channel is). `on_run` is handed
    the CLI run so the bridge can steer it; `tell(sentence)` says something on the phone
    while the turn is still going (a fallback)."""
    from . import executors as execmod
    from . import fabric as fabricmod
    from . import fallback as fb
    from . import knowledge as _k
    from . import usage as _usage
    control = getattr(toolbox, "fabric", None)
    prior = store.get_messages(cid)[:-1]
    huddle = fabricmod.parse_huddle(store, text) if control else None
    mention = fabricmod.parse_mention(store, text) if control and not huddle else None
    dept = None
    if control and not (huddle or mention):
        from . import company as _company
        dept = _company.parse_department(cfg, store, text)
    # whoever is addressed by name reads the thread they were addressed in
    thread = execmod.thread_note(prior, cfg.get("agent_name") or "Aria") if (huddle or mention or dept) else ""

    def asked(task: str) -> str:
        return task + (("\n\n" + thread) if thread else "")

    _k.turn_started()
    try:
        if dept:        # '@Sales …' from the phone is a task for that department
            d, task = dept
            reply = await fabricmod.department_reply(control, d["name"], asked(task), cid, approver, surface)
            return {"reply": reply, "steps": [], "meta": {"department": d["name"]}}
        if huddle:      # '@a @b …' from the phone convenes them, as it does at the desk
            names, topic = huddle

            async def say(e):
                await emit({"type": "agent_say", **e})
            await emit({"type": "turn_start", "model": "huddle", "huddle": names})
            res = await control.huddle(names, asked(topic), conversation_id=cid, say=say, approver=approver)
            return {"reply": res["text"], "steps": [], "meta": {"huddle": res["agents"]}}
        if mention:     # '@researcher …' goes straight to that specialist
            defn, task = mention
            res = await control.run_subagent(defn, task, context=thread, conversation_id=cid,
                                             approver=approver)
            usage = res.get("usage") or {}
            _usage.record(store, cfg, res.get("model") or "", {"input": usage.get("in", 0),
                          "output": usage.get("out", 0)}, surface=surface, conversation_id=cid)
            return {"reply": f"@{defn['name']} · {res['status']}\n\n"
                             + (res["content"] or res["fault"] or "(no output)"),
                    "steps": res["steps"], "meta": {}}

        # The lead, on whatever brain this machine runs on; and when that brain isn't
        # available, the next one on the person's list (fallback.py), as at the desk.
        engine, model, exec_model = execmod.resolve_engine(cfg), cfg.get("default_model") or "", ""
        tried: list = []
        while True:
            errors: list = []

            async def sink(ev, _errors=errors):
                if isinstance(ev, dict) and ev.get("type") == "error":
                    _errors.append(str(ev.get("message") or ""))
                await emit(ev)
            out = await (_on_cli(store, cfg, toolbox, engine, exec_model, cid, text, surface, sink,
                                 approver, prior, images, on_run, steerable) if engine != "aria"
                         else _built_in(store, cfg, toolbox, model, cid, text, surface, sink, approver,
                                        note, images, errors))
            nxt = fb.after(cfg, tried, engine, model, errors, out["said"])
            if not nxt:
                break
            why = next((e for e in errors if e.strip()), out["said"])[:160]
            line = f"{tried[-1]} isn't available right now ({why}). Asking {fb.words(nxt)} instead…"
            try:
                store.log("turn", line, {"conversation_id": cid, "fallback": fb.request(nxt)})
                if tell:
                    await tell(line)
            except Exception:
                pass
            engine = nxt["executor"]
            model, exec_model = (nxt["model"], "") if engine == "aria" else (model, nxt.get("model") or "")
        _usage.record(store, cfg, out["model"], out["tokens"], surface=surface, conversation_id=cid,
                      cost_usd=out.get("cost_usd"))
        return {"reply": out["said"] or NO_TEXT, "steps": out["steps"], "meta": out["meta"]}
    finally:
        _k.turn_ended()


async def _on_cli(store, cfg, toolbox, engine, exec_model, cid, text, surface, sink, approver,
                  prior, images, on_run, steerable) -> dict:
    """The turn on an agent CLI (Claude Code, Gemini CLI, Codex), with the team door."""
    from . import executors as execmod
    run = execmod.Run(engine=engine)
    if on_run:
        on_run(run)
    reply, _run = await execmod.forward(
        engine, text, cfg, execmod.default_workspace(cfg), emit=sink,
        session_id=store.exec_session(cid), prior=prior,
        # the team door: "build me a tool" from the phone reaches the toolsmith
        team={"toolbox": toolbox, "store": store, "approver": approver,
              "conversation_id": cid, "surface": surface},
        run=run, steerable=steerable, images=tuple(images), model=exec_model)
    got = _run or run
    meta = {}
    if getattr(got, "session_id", ""):
        # kept in the conversation row, so a restart does not make every phone thread a
        # stranger (an in-memory dict did)
        store.set_exec_session(cid, got.session_id)
        meta = {"engine": engine, "exec_session": got.session_id}
    cost = getattr(got, "cost_usd", 0) or None
    return {"said": reply or "", "steps": [{"type": "executor", "name": engine, "cost_usd": cost}],
            "meta": meta, "model": engine, "cost_usd": cost,
            "tokens": {"input": getattr(got, "tokens_in", 0), "output": getattr(got, "tokens_out", 0)}}


async def _built_in(store, cfg, toolbox, model, cid, text, surface, sink, approver, note, images,
                    errors) -> dict:
    """The turn on the built-in loop, over the same rebuilt history the desktop reads."""
    from . import history as _history
    from .agent import Agent
    h, _info = await _history.build(store, cid, cfg, model)
    if h and h[-1].get("role") == "user" and str(h[-1].get("content") or "").strip() == text:
        h = h[:-1]          # the message just saved goes in once, with its note
    entry = {"role": "user", "content": note + text}
    if images:
        entry["images"] = list(images)
    agent = Agent(cfg, toolbox, model, sink, approver, conversation_id=cid, surface=surface)
    try:
        result = await agent.run(h + [entry])
    except Exception as e:
        # a failed turn still leaves a message saying so, and may go to the next brain
        errors.append(f"{type(e).__name__}: {e}")
        return {"said": f"[error] {type(e).__name__}: {e}", "steps": list(agent.partial_steps or []),
                "meta": {}, "model": model, "tokens": {}}
    return {"said": result.get("content") or "", "steps": result.get("steps") or [], "meta": {"model": model},
            "model": model, "tokens": result.get("tokens") or {}}

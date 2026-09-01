"""`bento setup` — the same onboarding arc, walked in a terminal.

This is not a terminal-shaped copy of the wizard. It reads the SAME catalogue
(`onboarding.STEPS`) and the same probe (`onboarding.state`), so a step is ticked
here for exactly the reason it is ticked in the browser: the machine has the
thing. Run the GUI wizard half way and finish it over SSH and you will pick up
where you left off, with the right steps already green.

Two properties follow from that and are worth protecting:

  * **There is no "terminal version" of a step to drift.** Where a step creates
    something — an agent, a flow, a job, an account — this calls the same
    function the HTTP route calls. Where it genuinely needs a screen (a
    wallpaper), it says so and sets what it can.
  * **A headless machine gets the whole arc.** That is the point: a Pi over SSH
    is exactly where a machine that works without you earns its keep, and it is
    exactly where there has never been a wizard.

The rail is drawn every time round the loop rather than after each action,
because re-probing is what keeps it honest — including for things changed from
somewhere else while you sit here.
"""

from __future__ import annotations

import asyncio
import getpass
import shutil
import textwrap

from . import config as cfgmod
from . import onboarding as ob

TICK = {"done": "✓", "skipped": "–", "todo": "○"}


def _wrap(text: str, indent: str = "  ") -> str:
    """Wrap to the terminal, not to 80. A step blurb is a sentence somebody has to
    read to decide whether they want the thing, and an unwrapped one in an 80-column
    SSH window is a sentence nobody reads."""
    width = max(48, min(shutil.get_terminal_size((84, 24)).columns, 96)) - len(indent)
    return textwrap.fill(text, width, initial_indent=indent, subsequent_indent=indent)


def _ask(prompt: str, default: str = "") -> str:
    tag = f" [{default}]" if default else ""
    try:
        val = input(f"  {prompt}{tag}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""
    return val or default


def _yes(prompt: str, default: bool = True) -> bool:
    d = "y" if default else "n"
    return (_ask(f"{prompt} (y/n)", d) or d).lower().startswith("y")


def _save(cfg: dict) -> None:
    cfgmod.save_config(cfg)


# ---------------------------------------------------------------------------
# The rail
# ---------------------------------------------------------------------------

def _draw(st: dict, agent_name: str) -> None:
    print(f"\n▲ Set up {agent_name} — {st['done']} of {st['total']} done\n")
    for i, s in enumerate(st["steps"], 1):
        mark = TICK.get(s["status"], "○")
        detail = s["detail"] or ("needs " + ", ".join(s["blocked"]) if s["blocked"] else "")
        line = f"  {mark} {i:>2}  {s['title']:<32}"
        print(line + (f"  {detail}" if detail else ""))
    nxt = st["next"]
    print()
    if nxt:
        n = next(i for i, s in enumerate(st["steps"], 1) if s["id"] == nxt)
        print(f"  next: {n}. {ob.BY_ID[nxt].title}")
    print("  a number to do a step · s<n> to skip one · q to finish")


# ---------------------------------------------------------------------------
# The steps
# ---------------------------------------------------------------------------

def _step_name(cfg, store) -> None:
    v = _ask("\n  Name", cfg.get("agent_name") or "Aria")
    if not v:
        return
    cfg["agent_name"] = v
    _save(cfg)
    print(f"  ✓ it answers to {v} now")


def _step_model(cfg, store) -> None:
    from . import providers
    print()
    try:
        local = asyncio.run(providers.ollama_models(
            cfg["providers"]["ollama"]["base_url"]))
    except Exception:
        local = []
    if not local:
        from . import setup as setupmod
        print("  Nothing runs locally yet.")
        if _yes("Install Ollama (MIT) so this machine can run models itself?", False):
            if setupmod._offer_local_runtime():
                try:
                    local = asyncio.run(providers.ollama_models(
                        cfg["providers"]["ollama"]["base_url"]))
                except Exception:
                    local = []
    if local:
        for i, m in enumerate(local, 1):
            print(f"    {i}. ollama/{m}   local — private, free, no key")
        print("    c. a cloud model instead (needs an API key)")
        pick = _ask("Choice", "1")
        if pick.lower() != "c" and pick.isdigit() and 1 <= int(pick) <= len(local):
            cfg["default_model"] = f"ollama/{local[int(pick) - 1]}"
            _save(cfg)
            print(f"  ✓ {cfg['default_model']}")
            return
    print("\n  Cloud model:  1. Anthropic   2. OpenAI   3. OpenRouter")
    prov = {"1": "anthropic", "2": "openai",
            "3": "openrouter"}.get(_ask("Provider", "1"), "anthropic")
    key = _ask(f"{prov} API key")
    if not key:
        print("  (nothing set — add one later with `bento setup` or in Settings)")
        return
    defaults = {"anthropic": "claude-sonnet-5", "openai": "gpt-4o",
                "openrouter": "anthropic/claude-sonnet-4.5"}
    model = _ask("Model", defaults[prov])
    p = cfg.setdefault("providers", {}).setdefault(prov, {})
    p["api_key"], p["enabled"] = key, True
    cfg["default_model"] = f"{prov}/{model}"
    _save(cfg)
    print(f"  ✓ {cfg['default_model']}")


def _step_hello(cfg, store) -> None:
    """One real turn, not a provider ping.

    What this proves is that the whole stack works — provider, key, model id, the
    agent loop. An HTTP 200 from an API proves none of it, and this is the step
    that turns a configuration into a machine somebody believes in.
    """
    from . import knowledge
    from .agent import Agent
    from .tools import Toolbox
    model = (cfg.get("default_model") or "").strip()
    if not model:
        print("  pick a model first")
        return
    text = ("In two sentences: what can you do on this machine that a chat website "
            "cannot?")
    print(f"\n  asking {model}…\n")
    cid = store.create_conversation("✦ First hello")
    store.add_message(cid, "user", text)

    async def emit(_ev):
        pass

    async def approver(*_a, **_k):
        return False        # a hello never needs to touch anything

    async def go():
        agent = Agent(cfg, Toolbox(cfg, store), model, emit, approver,
                      conversation_id=cid, surface="tui")
        knowledge.turn_started()
        try:
            return await asyncio.wait_for(
                agent.run([{"role": "user", "content": text}]), timeout=120)
        finally:
            knowledge.turn_ended()

    try:
        res = asyncio.run(go())
    except asyncio.TimeoutError:
        print(f"  {model} did not answer within two minutes — check the model name "
              f"and the key")
        return
    except Exception as e:
        print(f"  {model} could not answer: {e}")
        return
    reply = (res.get("text") if isinstance(res, dict) else str(res)) or ""
    store.add_message(cid, "assistant", reply)
    for line in reply.strip().splitlines():
        print("    " + line)
    print(f"\n  ✓ that came from {model}, through the whole agent")


def _step_fork(cfg, store) -> None:
    """Start life as a fork of somebody's shared agent — the arc's version of
    `bento agent fork`, through the same module and the same consent."""
    import json
    import os
    from pathlib import Path

    from . import agentbundle as ab
    src = _ask("Where is it? (a bento.agent.json path, URL, owner/repo — or blank to skip)")
    if not src.strip():
        print("  (nothing imported — `bento agent fork <source>` works any time)")
        return
    key = _ask("Peer key, if it is a hosted share (blank for a published file)")
    if key.strip():
        bundle, err = ab.fetch_peer(src.strip(), key.strip())
    else:
        p = Path(os.path.expanduser(src.strip()))
        bundle, err = ({}, "")
        if p.is_file():
            try:
                bundle = json.loads(p.read_text())
            except Exception as e:                             # noqa: BLE001
                err = f"{src} is not a bundle: {e}"
        else:
            import urllib.request
            last = ""
            for cand in ab.resolve_source(src.strip()):
                try:
                    with urllib.request.urlopen(cand, timeout=30) as r:
                        bundle = json.loads(r.read())
                        break
                except Exception as e:                         # noqa: BLE001
                    last = str(e)
            if not bundle:
                err = f"no shared agent at '{src}' ({last})"
    if err:
        print(f"  ✗ {err}")
        return
    pv = ab.fork_preview(bundle, store, cfg, source=src.strip())
    print(f"\n  {pv['name']}" + (f" — {pv['description']}" if pv["description"] else ""))
    print(f"  integrity: {pv['verify']['status']} · provenance: {pv['tofu']['status']}"
          f" · app scan: {pv['security']['verdict']}")
    for i in pv["items"]:
        print(f"    · {i['kind']}: {i['name']}" + ("  (skipped — exists)" if i["skipped"] else ""))
    print(f"  permissions written now: {pv['grants_written_now']} — enabling each "
          f"flow later is what grants")
    if pv["verify"]["status"] in ("checksum-mismatch", "bad-signature"):
        print(f"  ✗ not forking: {pv['verify']['note']}")
        return
    if not _yes("Fork it — everything disabled, nothing granted?"):
        return
    res = ab.fork(bundle, store, cfg, source=src.strip())
    if not res["ok"]:
        print(f"  ✗ {res['error']}")
        return
    _save(cfg)
    arr = res["arrival"]
    print("\n  What changed:")
    for c in arr["changed"]:
        print(f"    · {c['kind']}: {', '.join(c['names'])}"
              + (f" — {c['note']}" if c["note"] else ""))
    print("  What did not:")
    for u in arr["unchanged"]:
        print(f"    · {u}")
    print(f"\n  Test it — the `hello` step, or:  bento ask "
          f"\"{arr['try_message'][:60]}…\"")


def _step_agent(cfg, store) -> None:
    d = ob.starter_agent(store)
    print(f"\n  {d['name']} — researches, verifies against a second source, and says "
          f"plainly when it could not find something.")
    print("  tools: " + " · ".join(d["tools"]))
    if not _yes("Create this agent?"):
        return
    store.save_subagent(d)
    print(f"  ✓ @{d['name']} exists — call it by name from any chat")


def _step_app(cfg, store) -> None:
    d = ob.starter_app(store)
    print(f"\n  {d['name']} — {d['description']}")
    print("  It goes on the desktop like any other app, and you can rewrite it from "
          "a sentence later in App Studio.")
    if not _yes(f"Create {d['name']}?"):
        return
    store.save_app(d["name"], "", d["description"], d["html"], note="setup")
    print(f"  ✓ {d['name']} exists — open it from the desktop or the launcher")


def _step_flow(cfg, store) -> None:
    from . import flows as flowsmod
    roster = [s["name"] for s in store.list_subagents() if not s.get("builtin")]
    if not roster:
        print("  build an agent first — a flow needs somebody to delegate to")
        return
    d = ob.starter_flow(store, roster)
    print(f"\n  {d['name']} — {d['description']}")
    print(f"  roster: {', '.join(r['subagent'] for r in d['roster'])}")
    print("  may: " + ", ".join(d["permissions"]["tools"]))
    if not _yes("Create the flow?"):
        return
    flow, report = flowsmod.save(store, d)
    print(f"  ✓ {flow['name']} created — {(report.get('grants') or {}).get('added', 0)} "
          f"permissions granted")
    print(f"    run it with:  bento flow run {flow['name']} \"a topic\"")


def _step_schedule(cfg, store) -> None:
    """The same job catalogue as the Jobs app and `bento job` — one list, so what
    is set up here is editable everywhere else."""
    from . import jobs as jobsmod
    recipes = jobsmod.RECIPES
    print()
    for i, r in enumerate(recipes, 1):
        print(f"    {i}. {r.title:<26} {r.blurb}")
    pick = _ask("Which one", "1")
    if not (pick.isdigit() and 1 <= int(pick) <= len(recipes)):
        return
    r = recipes[int(pick) - 1]
    answers = {}
    for need in r.needs:
        if need.key == "deliver":
            ways = [d for d in jobsmod.deliveries(cfg)]
            print("\n  Where should it land?")
            for j, d in enumerate(ways, 1):
                print(f"    {j}. {d['label']:<12} {d['detail']}"
                      + ("" if d["ready"] else "   (not set up)"))
            got = _ask("Choice", "1")
            answers["deliver"] = (ways[int(got) - 1]["id"]
                                  if got.isdigit() and 1 <= int(got) <= len(ways)
                                  else "report")
            continue
        answers[need.key] = _ask(need.label, str(need.default or ""))
    try:
        prev = jobsmod.preview(cfg, store, r.id, answers)
    except ValueError as e:
        print(f"  {e}")
        return
    # The same computation the browser's consent screen runs — `jobs.preview` is
    # `install` one step short of the write, so what is printed here cannot drift
    # from what gets saved.
    print("\n  What you are agreeing to:")
    for t in prev.get("triggers", []):
        c = t.get("config") or {}
        if c.get("type") == "daily":
            print(f"    · runs every day at {c.get('at')}")
        elif c.get("type") == "interval":
            print(f"    · runs every {c.get('minutes')} minutes")
        elif t.get("kind") == "os_event":
            print("    · runs when something changes in that folder")
    for path in prev.get("reads", []):
        print(f"    · reads {path} — and nothing else")
    print(f"    · delivers by: {(prev.get('delivery') or {}).get('label', 'report')}")
    print(f"    · {len(prev.get('grants', []))} permissions, all revocable "
          f"with `bento audit` / the Permissions app")
    if not _yes("Set it up?"):
        return
    res = jobsmod.install(cfg, store, r.id, answers)
    _save(cfg)
    print(f"  ✓ {res['flow']['name']} — runs {res.get('next') or 'when you say so'}")


def _step_channel(cfg, store) -> None:
    """Telegram only, and that is deliberate.

    Pairing WhatsApp means scanning a QR code, which a terminal can print but a
    headless SSH session usually cannot show anybody. So this does the one that
    works entirely with a pasted token, and points at the other rather than
    starting something that will strand somebody half way.
    """
    print("\n  Telegram — message @BotFather, /newbot, and paste the token here.")
    print("  WhatsApp needs a QR scan; `bento channels` sets it up on a machine "
          "with a screen.")
    tok = _ask("Bot token (blank to leave it)")
    if not tok:
        return
    tg = cfg.setdefault("telegram", {})
    tg["bot_token"], tg["enabled"] = tok, True
    cfg.setdefault("channels", {}).setdefault("telegram", {})["enabled"] = True
    _save(cfg)
    print("  ✓ token saved. Start the server, then send /start to your bot —")
    print("    the first person to do that becomes its owner, and nobody else "
          "gets through.")


def _step_look(cfg, store) -> None:
    """A terminal can pick a theme; it cannot show you one.

    So it sets what it can and says what it cannot, rather than pretending or
    silently leaving the step un-doable from here.
    """
    themes = ["bento", "midnight", "aurora", "paper", "terminal"]
    print("\n  Theme (the desktop reads this the next time it loads):")
    for i, t in enumerate(themes, 1):
        print(f"    {i}. {t}")
    pick = _ask("Choice", "1")
    d = cfg.setdefault("desktop", {})
    if pick.isdigit() and 1 <= int(pick) <= len(themes):
        d["theme"] = themes[int(pick) - 1]
    d["voice_tts"] = _yes("Speak replies aloud in the desktop UI?", False)
    _save(cfg)
    print(f"  ✓ theme {d.get('theme', 'default')}, voice "
          f"{'on' if d['voice_tts'] else 'off'}")
    print("    Wallpapers need a screen — Settings → Appearance, or the "
          "Personalize app.")


def _step_account(cfg, store) -> None:
    """Accounts from a terminal, which is where a headless machine needs them.

    The same credentials are the remote ones: there is no separate passphrase to
    invent, so this says that here rather than letting somebody discover it.
    """
    from . import users as usersmod
    people = usersmod.list_users()
    if people:
        print("\n  " + ", ".join(f"{u['name']} ({u['role']})" for u in people))
    else:
        print("\n  This machine has one user: whoever is at it.")
        print("  Adding the first account turns on accounts:")
        print("    · everything you have just set up becomes that account's")
        print("    · this machine starts asking who you are, here and from a phone")
        print("    · the first account is an admin, whatever you ask for")
    print(_wrap("The username and password below are also the remote sign-in — "
                "there is no separate passphrase to invent or share."))
    name = _ask("Username (blank to leave it single-user)")
    if not name:
        return
    problem = usersmod.name_problem(name)
    if problem:
        print(f"  {problem}")
        return
    display = _ask("Display name", name)
    try:
        pw = getpass.getpass("  Password: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return
    role = "executor"
    if people:
        role = "admin" if _ask("Role (executor/admin)", "executor").lower().startswith("a") \
            else "executor"
    try:
        u = usersmod.create(name, pw, role=role, display=display)
    except ValueError as e:
        print(f"  {e}")
        return
    print(f"  ✓ {u['name']} ({u['role']}) — home {usersmod.home_for(u['id'])}")
    if not people:
        # The rest of this session is theirs. Two reasons, and the second is a bug
        # if it is left out: it is what somebody means by "this machine is mine
        # now", and without it the next `save_config` from this terminal writes the
        # whole config — agent name, channels, theme — straight back into the
        # MACHINE file that `adopt` just stripped, handing it to the next person
        # who signs up. `run()` re-resolves the pair each time round the loop.
        usersmod.set_current(u["id"])
        print(_wrap(f"Everything above is yours now. From here: "
                    f"`bento --user {u['name']} ...` for the data verbs, and this "
                    f"desktop asks who you are — with this same password."))


HANDLERS = {
    "name": _step_name, "model": _step_model, "hello": _step_hello,
    "fork": _step_fork, "app": _step_app,
    "agent": _step_agent, "flow": _step_flow, "schedule": _step_schedule,
    "channel": _step_channel, "look": _step_look, "account": _step_account,
}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def run(cfg=None, store=None) -> None:
    if cfg is None:
        cfg = cfgmod.load_config()
        cfgmod.ensure_dirs(cfg)
    if store is None:
        from .memory import Store
        store = Store(cfgmod.DB_PATH)

    # Every handler is present, checked here rather than discovered when somebody
    # types the number: a step in the catalogue with nothing behind it in the
    # terminal is exactly the silent gap the three-faces rule exists to prevent.
    missing = [s.id for s in ob.STEPS if s.id not in HANDLERS]
    if missing:                                              # pragma: no cover
        print(f"  (no terminal handler for: {', '.join(missing)})")

    from . import users as usersmod
    machine = (cfg, store)
    while True:
        # Re-resolved every pass, not bound once: the account step can change WHO
        # this session is half way through the arc, and the steps after it must
        # then be configuring that person rather than the machine.
        cfg, store = usersmod.resolve(*machine)
        st = ob.state(cfg, store)
        _draw(st, cfg.get("agent_name") or "your agent")
        if st["finished"]:
            print("\n  Everything is answered. `q` writes that down and leaves.")
        raw = _ask("Step", st["next"] and str(
            next(i for i, s in enumerate(st["steps"], 1) if s["id"] == st["next"])) or "q")
        if not raw or raw.lower() in ("q", "quit", "done", "exit"):
            break
        skip = raw.lower().startswith("s") and raw[1:].strip().isdigit()
        num = raw[1:].strip() if skip else raw
        if not num.isdigit() or not (1 <= int(num) <= len(st["steps"])):
            print("  a step number, `s` and a number to skip it, or `q`")
            continue
        step = st["steps"][int(num) - 1]
        if skip:
            try:
                ob.skip(cfg, step["id"])
                _save(cfg)
                print(f"  – {step['title']} skipped — `bento setup` offers it again")
            except ValueError as e:
                print(f"  {e}")
            continue
        if step["blocked"]:
            print(f"  {step['title']} needs {', '.join(step['blocked'])} first")
            continue
        if step["status"] == "skipped":
            ob.unskip(cfg, step["id"])
        print(f"\n{'─' * 60}\n  {step['icon']} {step['title']}")
        print(_wrap(step["blurb"]))
        print(_wrap(f"You will end up with: {step['produces']}"))
        try:
            HANDLERS[step["id"]](cfg, store)
        except (EOFError, KeyboardInterrupt):
            print("\n  (left that one)")
        except Exception as e:                               # pragma: no cover
            print(f"  that did not work: {type(e).__name__}: {e}")

    cfgmod.mark_setup_complete(cfg)
    st = ob.state(cfg, store)
    print(f"\n✓ {st['done']} of {st['total']} done. `bento setup` picks this up again "
          f"any time — nothing here is one-shot.")
    print("  `bento` for the desktop · `bento tui` for the terminal UI · "
          "`bento ask \"...\"` for one question.\n")

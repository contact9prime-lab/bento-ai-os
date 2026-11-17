"""A reply that says a step was done, in a turn where the tool for it never ran.

Reported from Telegram on a 12B local model: asked to "huddle and come with a black hole
blueprint", it answered "I have called a huddle between our researcher and the validator …
The blueprint is now ready. On your phone, you can access the interactive walk-through and a
PDF". The ledger for that turn has four `model.use` rows and nothing else: no huddle, no
scene, no file. Three more replies were then built on the first one ("it is in the Stage or
Documents app"). A small model writes about the work instead of doing it, and nothing here
compared what it said with what it ran.

So the loop compares them (`agent.Agent.run`): `unbacked()` is the list of steps a reply
claims whose tools did not run in the turn. The model is asked once to actually make the
call; if it still has not, the reply carries `note()`, which says in plain words that
nothing was made and that this model is not up to that step. Only first-person claims of a
finished step are read ("I have called a huddle", "the blueprint is ready"): a plan ("I
will…"), a refusal ("I could not…") and a question are left alone, because a guard that
fires on ordinary sentences is one people learn to ignore.

Stdlib only, no I/O: the loop decides what to do with the answer.
GUI, TUI and the phones all read the same reply, so the note reaches every face.
"""
from __future__ import annotations

import re

_I = r"\b(?:i|we)(?:'ve|’ve| have)? (?:just |now |already |also )?"

# (what it says it did, the tools any one of which would make it true, how it is said)
CLAIMS = (
    ("called a huddle", ("huddle",),
     _I + r"(?:called|convened|held|started|run|ran|organi[sz]ed|set up) (?:a|the) huddle"),
    ("made a blueprint or a visual story", ("show_scene",),
     r"\bblueprint (?:is|has been) (?:now |already )?(?:\w+ and )?(?:ready|complete|completed|available|done|created|built|saved)"
     r"|" + _I + r"(?:created|built|drawn|generated|made|prepared|put together) (?:a|an|the|your) "
     r"(?:[\w-]+ ){0,4}(?:blueprint|chart|map|timeline|scene|visual story)"),
    ("handed the work to somebody", ("delegate", "department_task", "ask_agent", "run_flow"),
     _I + r"(?:delegated|handed|assigned|passed|given) (?:this|that|it|the (?:[\w-]+ ){0,3}(?:task|work|job|research|analysis)) "
     r"(?:over |off )?to\b"),
    ("set up a schedule", ("schedule_task", "create_flow", "create_trigger"),
     _I + r"(?:scheduled (?:a|an|the|this|that|it|your)\b|set up (?:a|an|the|your) (?:[\w-]+ ){0,2}(?:schedule|reminder|scheduled task))"),
    ("saved a file", ("write_file", "save_report", "stage_file", "save_asset", "create_app"),
     _I + r"(?:saved|written|exported|created|generated) (?:a|an|the|your) "
     r"(?:[\w-]+ ){0,4}(?:file|report|pdf|document|spreadsheet|presentation|deck)\b"),
    ("saved it to memory", ("remember", "kg_add"),
     _I + r"(?:saved|stored|recorded|noted) (?:it|this|that|these|those|the (?:[\w-]+ ){0,3}\w+) (?:in|to) (?:my |your |the |long-term )?memory"),
)
_RX = tuple((what, tools, re.compile(rx, re.I)) for what, tools, rx in CLAIMS)
_NOT = re.compile(r"(?:\bnot|n't|n’t|\bnever|\bcannot|\bunable to|\bwithout having|\bif|\bonce|\bwhen|\bbefore)\s+(?:\w+\s+){0,3}$", re.I)


def ran(steps: list) -> set:
    """The tools that actually ran in this turn."""
    return {str(s.get("name") or "") for s in steps or [] if s.get("type") == "tool"}


def unbacked(text: str, steps: list) -> list[dict]:
    """[{what, tools, said}] for each step the reply says was done whose tool did not run.
    `said` is the sentence fragment, for the nudge and the note."""
    did = ran(steps)
    out, seen = [], set()
    body = " ".join(str(text or "").replace("*", "").split())
    for what, tools, rx in _RX:
        if what in seen or did & set(tools):
            continue
        for m in rx.finditer(body):
            if _NOT.search(body[max(0, m.start() - 40):m.start()]):
                continue                      # "I have not called a huddle", "once I have…"
            seen.add(what)
            out.append({"what": what, "tools": tools, "said": body[m.start():m.end()]})
            break
    return out


def nudge(found: list[dict], offered: set) -> str:
    """What the model is told, once: do it now, or say it is not done."""
    lines = []
    for f in found:
        can = [t for t in f["tools"] if t in offered]
        lines.append(f"- you wrote that you {f['what']} (\"{f['said']}\"), but you called no tool for it"
                     + (f": call {can[0]} now" if can else ": you have no tool for it here"))
    return ("STOP. Nothing in your last reply has happened yet. Writing that a step was done does not "
            "do it; only a tool call does.\n" + "\n".join(lines)
            + "\nMake the tool call(s) now, with real arguments, and only then answer from what "
              "comes back. If you cannot make a call, say in one plain sentence that it has NOT "
              "been done and why. Do not repeat the claim.")


def note(model: str, found: list[dict]) -> str:
    """The line the person reads when the model still claimed work it did not do."""
    what = " and ".join(f["what"] for f in found[:3])
    name = str(model or "").split("/", 1)[-1] or "This model"
    return (f"⚠ Not done. {name} wrote that it {what}, but it ran no tool for that, so nothing was "
            f"made: the reply above is only words. This model often describes a step instead of "
            f"doing it and isn't equipped for this kind of request. Ask again on a stronger brain: "
            f"the model picker in Chat, or /model on Telegram and WhatsApp.")


HANDED = 6000        # how much of what a tool brought back is shown when the model said nothing


def after_silence(model: str, steps: list) -> str:
    """What the person gets when the model ran tools and then gave no answer at all.

    Measured on gemma4:12b with the request above: it did call the huddle (two and a half
    minutes of two specialists talking), then spent its reply in its thinking channel
    twice, and the turn ended on an error with an empty answer. The work existed and
    nobody was shown it. '' when no tool brought anything back."""
    done = [st for st in steps or [] if st.get("type") == "tool" and str(st.get("output") or "").strip()]
    if not done:
        return ""
    name = str(model or "").split("/", 1)[-1] or "This model"
    last = done[-1]
    out = str(last.get("output") or "").strip()
    shown = out if len(out) <= HANDED else out[:HANDED].rsplit("\n", 1)[0] + "\n… (cut here; the rest is in the run)"
    ran_names = ", ".join(dict.fromkeys(str(st.get("name")) for st in done))
    return (f"⚠ {name} ran {ran_names} and then gave no answer of its own, so nothing was put "
            f"together from it. This model isn't equipped for a request with this many steps: ask "
            f"again on a stronger brain (the model picker in Chat, or /model on Telegram and "
            f"WhatsApp). What {last.get('name')} brought back:\n\n{shown}")

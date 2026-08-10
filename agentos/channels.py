"""Channels — every way a conversation can arrive at this machine.

A channel is **not** "a messenger". It is a way in: the browser window, the
session desktop, a terminal over SSH, a browser on your phone across the house,
the HTTP API, a scheduled task, Telegram. Each one carries the same conversation
to the same agent, with the same memory and the same tools. What differs is
*who can speak through it* and *how much it is trusted*.

That second half already existed and is not reimplemented here:

    policy.SURFACES          the IO gates a capability call can arrive on
    grants.surfaces          per-grant scoping to a subset of those gates
    policy.channel_posture   the per-channel ceiling this module configures
    remote.status            who may reach the remote browser, and from where
    memory.Store tokens      who holds an API token

This module is the catalogue that names those gates, states in one sentence what
each is and who can talk on it, and reads their live condition. It is the front
door onto machinery that is already load-bearing — the settings page it feeds is
a view, not a second source of truth.

Three faces (per CLAUDE.md):
  GUI  Settings → Channels lists every channel, including the one you are using.
  TUI  `agentos channels` prints the same table; `agentos channels <id> …` sets
       posture and on/off, because a headless machine is exactly where "who may
       reach this over the API" most needs answering.
  SUI  identical to GUI — the session desktop is a channel in this list rather
       than a special case, which is the point of modelling it this way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# What a posture means, in the words the settings page shows.
POSTURE_LABELS = {
    "inherit": "Same as the machine",
    "read_only": "Look, don't touch",
    "ask": "Ask me first",
    "full": "Act without asking",
}
POSTURE_HELP = {
    "inherit": "Whatever autonomy this machine is set to.",
    "read_only": "Anything that would change something is refused, not queued. "
                 "Right for a way in that nobody is watching.",
    "ask": "Anything risky waits for an explicit approval, even if the machine "
           "is otherwise set to act freely.",
    "full": "Risky steps run without stopping to ask. Only sensible where you "
            "are present and can see what happened.",
}


@dataclass
class Field:
    """One thing a channel needs before it can work."""

    key: str
    label: str
    help: str = ""
    secret: bool = False
    required: bool = True
    placeholder: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "help": self.help,
                "secret": self.secret, "required": self.required,
                "placeholder": self.placeholder}


@dataclass
class Channel:
    id: str                       # also the policy IO gate, where one exists
    title: str
    what: str                     # one sentence: what this way in is
    reach: str                    # who can speak through it
    gate: str = ""                # policy.SURFACES gate; '' when it has none yet
    # Built-in ways in cannot be switched off from here — the browser window you
    # are reading this in is one of them. Saying so is better than a toggle that
    # would lock you out of your own machine.
    builtin: bool = False
    fields: list[Field] = field(default_factory=list)
    # Where the *who* is configured, when it lives in another panel already
    reach_panel: str = ""
    note: str = ""

    @property
    def own_gate(self) -> bool:
        """Does this channel have a gate to itself?

        Postures are enforced per IO gate, and several channels legitimately share
        one — the session desktop and a remote browser are the same page arriving
        through the same 'gui' gate. Those follow the posture of whichever channel
        owns the gate rather than offering a control that would never be read.
        """
        return self.gate == self.id

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "what": self.what,
                "reach": self.reach, "gate": self.gate, "builtin": self.builtin,
                "reach_panel": self.reach_panel, "note": self.note,
                "own_gate": self.own_gate,
                "fields": [f.as_dict() for f in self.fields]}


CATALOGUE: list[Channel] = [
    Channel(
        id="gui", title="This window", gate="gui", builtin=True,
        what="AgentOS in a browser window on this machine — Chat, the prompt bar, "
             "the copilot panel in every app.",
        reach="Whoever is signed in to this computer.",
    ),
    Channel(
        id="sui", title="The session", gate="gui", builtin=True,
        what="AgentOS as the desktop itself, when you log in to it as your session.",
        reach="Whoever logs in to this machine.",
        note="Shares the 'gui' gate with the browser window — it is the same page "
             "and the same conversation, drawn as the desktop instead of inside one.",
    ),
    Channel(
        id="tui", title="Terminal", gate="tui", builtin=True,
        what="The text interface — `agentos tui` at the console or over SSH, on a "
             "machine with no screen.",
        reach="Anyone with a shell on this machine, which usually means anyone who "
              "can SSH to it.",
    ),
    Channel(
        id="remote", title="Remote browser", gate="gui",
        what="The same interface from another device — your phone, a laptop in "
             "another room — over the network.",
        reach="Anyone with the passphrase, from the addresses you allow.",
        reach_panel="System → Remote access",
        note="Native app windows are not in the page, so a remote browser cannot "
             "see them; it is told when something opened here instead.",
    ),
    Channel(
        id="api", title="API", gate="api", builtin=True,
        what="Programs talking to AgentOS over HTTP — scripts, other machines, "
             "anything holding a token.",
        # Served whenever AgentOS is running, so there is no switch here; what
        # controls it is who holds a token, which lives in the Tokens app.
        reach="Holders of an API token, and nobody else.",
        reach_panel="the Tokens app",
    ),
    Channel(
        id="task", title="Scheduled", gate="task", builtin=True,
        what="Turns this machine starts by itself — scheduled tasks, reminders, "
             "the things it does while you are away.",
        reach="Nobody: these start from the schedule you set.",
        note="Nothing is watching a scheduled turn, so 'Ask me first' means it "
             "stops and waits rather than acts.",
    ),
    Channel(
        id="webhook", title="Webhooks", gate="webhook", builtin=True,
        what="Other services calling in over HTTP to start a flow — a form submission, "
             "a CI job, a device, a monitor that noticed something.",
        reach="Whoever holds a flow's hook secret. Each trigger has its own; rotating it "
              "in Workflows → Flows revokes every caller at once.",
        reach_panel="Workflows → Flows",
        note="A webhook body is content from outside this machine, so a flow started by "
             "one runs tainted: risky steps are shown to you rather than assumed.",
    ),
    Channel(
        id="telegram", title="Telegram", gate="telegram",
        what="The same conversation from your phone, with answers and approvals "
             "coming back to you there.",
        reach="Only the chats you have paired. The first /start pairs you; "
              "everyone else is ignored.",
        fields=[Field("bot_token", "Bot token",
                      "Create a bot with @BotFather and paste its token.",
                      secret=True, placeholder="123456:ABC-DEF…")],
    ),
    Channel(
        id="whatsapp", title="WhatsApp", gate="whatsapp",
        what="The same conversation on WhatsApp — your agent, your memory, your "
             "tools, answering on the app you already have open.",
        reach="Only the number you have paired. The first message pairs you; "
              "everyone else is told this machine is not theirs.",
        note="A message here reaches THIS agent, with your memory and permissions. "
             "It needs a public HTTPS address for "
             "Meta's webhook, and WhatsApp only allows free-form replies within 24 "
             "hours of your last message — so a scheduled job cannot speak first to "
             "a silent chat.",
        fields=[
            Field("phone_number_id", "Phone number ID",
                  "From the WhatsApp product page on developers.facebook.com.",
                  placeholder="123456789012345"),
            Field("access_token", "Access token",
                  "The permanent token for your system user. Temporary tokens expire "
                  "in 24 hours and the channel will simply stop.",
                  secret=True),
            Field("app_secret", "App secret",
                  "Used to verify that a webhook delivery really came from Meta. "
                  "Without it the webhook is refused — it is a public URL.",
                  secret=True),
            Field("verify_token", "Verify token",
                  "Any string you invent. Paste the same one into Meta's console "
                  "when you set the callback URL."),
        ],
    ),
]

# ---------------------------------------------------------------------------
# Channels are the ones AgentOS owns, end to end
#
# There used to be a second tier here: platforms "carried" by the Hermes gateway —
# Slack, Signal, Discord, Teams, Matrix and the rest — delivered by shelling out to
# another agent already installed on the machine. They were removed deliberately.
#
# The reasoning was never that the bridges did not work. It was that we could not
# judge them: a carried channel could only ever deliver OUT, a reply arriving there
# was answered by a different agent with a different memory, and none of what that
# agent did reached this OS's grants, ledger or budgets. That is a lot of surface to
# stand behind while being unable to say whether it is good.
#
# So the rule is now simple enough to hold: a channel is offered here only if AgentOS
# owns it end to end — it brings a conversation to THIS agent, through this policy,
# and every capability call it makes lands in this ledger. Telegram and WhatsApp
# qualify. When Slack or Signal earn a place, they will be built to that same bar
# rather than proxied to something that cannot meet it.
#
# Fewer channels, each of which means what it says.
# ---------------------------------------------------------------------------


BY_ID = {c.id: c for c in CATALOGUE}


def _missing(chan: Channel, conf: dict) -> list[str]:
    """Which required fields still have no value, by label."""
    return [f.label for f in chan.fields
            if f.required and not str((conf or {}).get(f.key) or "").strip()]


def _conf(cfg: dict, chan: Channel) -> dict:
    conf = dict((cfg.get("channels") or {}).get(chan.id) or {})
    # Telegram predates the channel registry and keeps its own config block, which
    # the running poller reads. Read through to it rather than making anyone set
    # the same bot up twice.
    if chan.id == "telegram":
        legacy = cfg.get("telegram") or {}
        conf.setdefault("bot_token", legacy.get("bot_token", ""))
        conf.setdefault("enabled", legacy.get("enabled", False))
    elif chan.id == "whatsapp":
        # whatsapp.conf() is the one reader that merges the registry block with the
        # running bridge's own state (the paired number). Going through it means a
        # value set in either place is seen by both.
        from . import whatsapp as wamod
        conf = {**wamod.conf(cfg), **{k: v for k, v in conf.items() if v}}
    return conf


def state(cfg: dict, store=None) -> list[dict]:
    """Every channel and what is true about it right now.

    Secrets are never returned — only whether one is set — so this can be
    rendered on a page, printed in a terminal, or sent to a phone without
    leaking a token into any of them.
    """
    out: list[dict] = []
    for chan in CATALOGUE:
        conf = _conf(cfg, chan)
        missing = _missing(chan, conf)
        # A shared gate reports the posture actually in force, and says whose it is.
        owner = chan if chan.own_gate else BY_ID.get(chan.gate)
        oconf = conf if chan.own_gate else _conf(cfg, owner) if owner else {}
        posture = str(oconf.get("posture") or "inherit")
        if posture not in POSTURE_LABELS:
            posture = "inherit"

        if chan.builtin:
            enabled, status, detail = True, "on", "always on"
        elif missing:
            enabled, status = False, "needs"
            detail = "needs " + ", ".join(missing)
        elif chan.id == "remote":
            enabled = bool((cfg.get("remote") or {}).get("enabled"))
            status = "on" if enabled else "off"
            detail = "reachable from other devices" if enabled else "off — only this machine"
        else:
            enabled = bool(conf.get("enabled"))
            status = "on" if enabled else "off"
            detail = "connected" if enabled else "ready — switch it on to use it"

        d = chan.as_dict()
        d.update({
            "enabled": enabled, "status": status, "detail": detail,
            "posture": posture,
            "posture_label": POSTURE_LABELS[posture],
            "posture_from": "" if chan.own_gate else (owner.title if owner else ""),
            # Every channel offered here brings a conversation TO this agent. The
            # keys stay so a surface that renders both directions still works if a
            # deliver-only channel is ever added back on its own merits.
            "carrier": "", "direction": "both",
            "set": {f.key: bool(str(conf.get(f.key) or "").strip()) for f in chan.fields},
            "values": {f.key: ("" if f.secret else str(conf.get(f.key) or ""))
                       for f in chan.fields},
        })
        # How many permission rules are scoped specifically to this gate — the
        # honest answer to "and what may it actually do", pointing at the
        # Permissions app rather than restating its rules here.
        if store is not None and chan.gate:
            try:
                d["scoped_grants"] = sum(
                    1 for g in store.grants_live()
                    if chan.gate in {s.strip() for s in (g.get("surfaces") or "*").split(",")}
                )
            except Exception:
                d["scoped_grants"] = 0
        out.append(d)
    return out


def save(cfg: dict, channel_id: str, patch: dict) -> tuple[bool, str]:
    """Apply a settings change to one channel.

    A blank secret means "leave it alone", never "clear it": the UI shows a saved
    secret as set rather than echoing it back, so an empty box is the normal
    state of a configured channel, not an instruction to erase it.
    """
    chan = BY_ID.get(channel_id)
    if not chan:
        return False, f"no such channel: {channel_id}"

    conf = cfg.setdefault("channels", {}).setdefault(channel_id, {})

    if "posture" in patch:
        p = str(patch["posture"] or "inherit")
        if p not in POSTURE_LABELS:
            return False, f"unknown posture: {p}"
        if not chan.own_gate:
            owner = BY_ID.get(chan.gate)
            return False, (f"{chan.title} arrives through the same gate as "
                           f"{owner.title if owner else chan.gate}, so it follows that "
                           f"channel's permissions — set it there")
        conf["posture"] = p

    if "enabled" in patch:
        if chan.builtin:
            # Refusing here rather than pretending: switching off the window you
            # are reading this in is not a setting, it is a lockout.
            return False, f"{chan.title} is how you reach this machine — it cannot be switched off"
        conf["enabled"] = bool(patch["enabled"])

    for f in chan.fields:
        if f.key not in patch:
            continue
        val = str(patch[f.key] or "").strip()
        if f.secret and not val:
            continue
        conf[f.key] = val[:400]

    # Decide `enabled` BEFORE mirroring it. A half-configured channel cannot be on,
    # and the mirrored block is what the running service actually reads — so writing
    # the mirror first and correcting `conf` afterwards left the bridge switched on
    # by a save that had just been refused.
    missing = _missing(chan, _conf(cfg, chan))
    refused = bool(conf.get("enabled") and missing)
    if refused:
        conf["enabled"] = False

    # Keep the legacy blocks in step, since the running services read those.
    if channel_id == "whatsapp":
        wa = cfg.setdefault("whatsapp", {})
        for k in ("phone_number_id", "access_token", "app_secret", "verify_token"):
            if conf.get(k):
                wa[k] = conf[k]
        if "enabled" in conf:
            wa["enabled"] = bool(conf["enabled"])
    elif channel_id == "telegram":
        tg = cfg.setdefault("telegram", {})
        if "enabled" in conf:
            tg["enabled"] = bool(conf["enabled"])
        if conf.get("bot_token"):
            tg["bot_token"] = conf["bot_token"]
    elif channel_id == "remote" and "enabled" in patch:
        cfg.setdefault("remote", {})["enabled"] = bool(patch["enabled"]) and not refused

    if refused:
        return False, "still needs " + ", ".join(missing)
    return True, "saved"

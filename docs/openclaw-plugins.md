# OpenClaw plugins

AgentOS can hand a turn to OpenClaw — that is what an *executor* is, and it has
worked for a while (see [Models & brains](models.md)). What it could not do was
**extend** it.

OpenClaw's extension surface is plugins: tools, model providers, messaging
channels, hooks and MCP servers, installed with `openclaw plugins install`. That
command is a sentence you type into a terminal, and until now AgentOS never saw
it. So a machine could be carefully governed on every other axis — apps behind a
scan and a consent screen, MCP servers behind grants, flows behind quarantine —
and still be extended by third-party code through a door with no lock on it.

This is that door.

```
bento openclaw search calendar          # what is out there
bento openclaw install clawhub:cal      # lands DISABLED, and is scanned
bento openclaw show cal                 # what enabling would let it reach
bento openclaw enable cal --yes         # the act of granting
bento openclaw doctor                   # is any of this still true?
```

The same thing lives in **Settings → Executors → OpenClaw plugins**, and the
agent can reach the first two steps itself. All three read one module
(`agentos/ocplugins.py`), so there is one scan, one consent computation and one
set of permissions however you arrive.

---

## Three ways to run a plugin here, and their different limits

This is the first thing to get straight, because each path has its **own** limit
and it is easy to carry one path's caveat onto another.

| | Who runs the code | What AgentOS can enforce | The limit |
|---|---|---|---|
| **1. Leave it in OpenClaw** `ocplugins.py` | OpenClaw's own gateway process | the lifecycle (install/enable/update/uninstall) and enablement | **cannot refuse an individual call** — the code is in another process |
| **2. Host it here** `ochost.py` | a Node process AgentOS starts | **every tool call** — PDP, ledger, rate meter, quarantine | its own filesystem and subprocess are closed by Node; **its network is not**, without an OS jail |
| **3. Port it natively** `ocnative.py` | nothing foreign — MCP servers, flows and skills AgentOS already runs | **everything**, exactly as for any other MCP tool or flow | not everything is portable, and what is not is **named** rather than approximated |

**The two limits in rows 1 and 2 do not apply to row 3.** That is the whole
reason the port exists. A ported plugin is not a plugin any more — it is an MCP
server, a flow and a skill, each already behind the permission engine. There is
no gateway to be outside of and no Node host whose network to worry about.

What row 3 costs instead is **coverage, not control**: some OpenClaw concepts
have no equivalent here (host-trusted tool policies, tool-result middleware,
providers, channels, the memory slot, in-turn hooks). Those are reported in the
[report](#coming-from-openclaw-the-report) with what losing each one costs you —
they are a visible gap, not a silent one.

So: choose row 1 for interop with a machine that already runs OpenClaw, row 2
when you want the calls gated but the plugin's own code intact, and row 3 when
you want the capability with no foreign runtime at all.

### You do not need OpenClaw installed to port a plugin

The `openclaw` CLI is needed to **acquire** one — to resolve `clawhub:`, `npm:`
and `git:` specs and unpack them — and for nothing else. Reading a manifest,
hosting the plugin (path 2 runs `node` directly) and porting it (path 3 reads
only the manifest) all work on bytes that are already on disk.

So a plugin **directory** is a first-class source. Point at a folder and the
scan, the report and the port all work with no OpenClaw on this machine:

```
bento openclaw show   ./path/to/the-plugin
bento openclaw report ./path/to/the-plugin
bento openclaw native ./path/to/the-plugin --yes
```

That folder can be a git clone, an unpacked tarball, or a copy of
`~/.openclaw/extensions/<id>` from the machine you are leaving. Which is the
point: **somebody migrating off OpenClaw should not have to install OpenClaw to
do it.** Only `install`, `enable`, `update`, `uninstall`, `hold`, `doctor`,
`list` and `search` genuinely drive the CLI, and those say so.

---

## Path 1 in detail: what AgentOS adds, and what it cannot

Everything in this section is about **leaving the plugin in OpenClaw's gateway**.
Paths 2 and 3 above have different answers; do not carry this one onto them.

**AgentOS gates the lifecycle.** Install, enable, update and uninstall each go
past the policy decision point and leave a row in the ledger saying who did it.
`plugin.install` and `plugin.enable` are their own actions — not another
`tool.use` string — so "may install a plugin" and "may read a file" are separate
grants, and an app or a subagent may do neither, ever.

**AgentOS enforces enablement afterwards.** A plugin whose permission you revoke,
or that gets quarantined, is disabled through the one lever OpenClaw documents as
absolute: `plugins.deny` wins over allow and over per-plugin enablement.

**AgentOS cannot gate an individual call the plugin makes.** Once enabled, a
plugin runs inside OpenClaw's own process. Its tool calls do not pass through
this policy engine the way an app's do, and nothing here can refuse one. If that
matters for a particular plugin, the answer is not to enable it.

That is the whole boundary, stated once. Everything below is built on it.

---

## Install leaves it disabled

This is the load-bearing decision and it is worth understanding.

To scan a package *before* it exists on disk, AgentOS would have to re-implement
OpenClaw's resolver for npm, ClawHub, git, archives and marketplaces — five ways
to be subtly wrong about which bytes are about to arrive. So the bytes arrive
first, **disabled**, and the scan reads the real `openclaw.plugin.json` that
landed.

A disabled plugin holds nothing. No grants are written, nothing is armed, and
your OpenClaw behaves exactly as it did. **Enabling is the act of granting** —
the same rule flows already run on.

That is also why the agent may install a plugin but may not enable one. It can
put a candidate on the disk and tell you what it found; the decision is yours,
and it is confirmed every time, at full autonomy included.

---

## The scan

Deterministic, needs no model and no network, and reads the plugin's **manifest**
— its declarations — rather than its code.

That is a real limit, stated as one: a manifest is what the plugin says it is
for. OpenClaw enforces parts of it (a runtime `registerTool` must match
`contracts.tools`; an installed plugin registering an undeclared trusted policy
is rejected before registration) and the rest is a claim. So the scan answers
*what has it declared it will reach?*, which is the question a consent screen
needs. It does not claim to answer *is this code malicious?*, which reading a
manifest cannot.

Three severities, the same words the app registry uses:

| | What it means |
|---|---|
| **high** | A capability whose whole point is to sit in front of something — a host-trusted pre-tool policy, tool-result middleware, in-process Gateway dispatch, claiming the `memory` or `context-engine` slot, or a conversation hook that reads and can rewrite prompts and replies. |
| **medium** | Real reach worth naming — MCP servers it starts, commands it adds to `openclaw`, providers and channels it owns, npm lifecycle scripts, and a source OpenClaw does not treat as trusted. |
| **info** | What the thing *is*: the tools it adds, the events it runs on, and whether it declared a compatibility floor at all. |

Any high or medium finding makes the verdict `caution`. A finding is a sentence
for a person to read, not a ban — refusal stays your decision, as it does
everywhere else in this OS.

---

## Where it came from

AgentOS mirrors OpenClaw's own judgement rather than inventing a second one:
**ClawHub and the official `@openclaw/*` catalogue are trusted sources**;
arbitrary npm, `npm-pack:`, `git:`, a local path and marketplace installs are
not, and OpenClaw itself warns and asks before continuing.

Non-interactively, OpenClaw requires `--force` for one of those — which is the
person saying they looked at the source and vouch for it. AgentOS therefore
never passes `--force` on its own. `bento openclaw install` wants `--yes`, the
GUI asks, and the agent's tool cannot supply it at all.

npm installs are **pinned** by default. An unpinned install is a different set of
bytes each time the registry's default line moves, and a review of bytes that get
replaced without another review is not a review.

---

## Trust on first use

There is nobody handing out "verified" badges for plugins, so the useful question
is not *is this signed?* but *is this the same thing I decided about last time?*
— which is exactly what SSH's `known_hosts` answers.

Enabling a plugin records **where it came from and how it scanned**. Both are
compared later:

- **the source moved** — same plugin id, different origin. Either the author
  moved house or somebody took the name. You decide, told plainly.
- **the scan got worse** — it now declares something it did not declare when you
  approved it.

Either one **holds** the plugin: it is quarantined, disabled, and its permissions
are taken back, with the reason recorded. Getting *quieter* is not drift and is
left alone — a hold that fires on every update is a hold people learn to click
through.

The pinned verdict matters more than it first looks. AgentOS does not own the
`openclaw` CLI: someone can run `openclaw plugins update` in a terminal, or edit
a linked plugin's own source, and none of that passes this consent screen. So the
baseline is what you agreed to, not a reading taken a moment before an update
AgentOS happened to run — and `bento openclaw doctor` re-reads the bytes and
catches it either way.

Pins are personal. They live under the `registry` config key, which is one of the
per-user keys ([Users](users.md)): whom *you* trust costs nothing machine-wide
and reconfigures nothing.

---

## Permissions

Enabling writes real `grants` rows — the ones the Permissions app lists — with
`source='openclaw-plugin'` and `source_ref='ocplugin:<id>'`:

| Action | Resource | Written for |
|---|---|---|
| `plugin.run` | `ocplugin:<id>` | the enablement itself |
| `tool.use` | `tool:<name>` | each tool in `contracts.tools` |
| `mcp.use` | `mcp:<name>` | each MCP server it contributes |
| `model.use` | `model:<provider>/*` | each provider it owns |

The first row is not decoration. **Revoke it and AgentOS disables the plugin** —
`bento openclaw doctor` (and the GUI's *Check them*) reads it back and turns off
anything whose permission is gone. That is the binding that makes the Permissions
app a real control over something running in another process.

Reconciliation only ever turns things **off**. Turning a plugin on is a person's
act; a reconciler that could do it would be a way to grant without being asked.

Grants written by hand are never touched — the filter is `source` plus
`source_ref`, so editing or disabling a plugin cannot quietly undo a permission
you deliberately gave it.

---

## Quarantine

A held plugin lands in the ordinary quarantine list, with the ordinary release
modes — `once` (still watched), `forever` (an exemption, which is why the row is
kept), `deleted`. `bento quarantine list` and Permissions → Quarantine both show
it; there is no second surface, because a second one would be a second set of
bugs in something people only look at when they are already worried.

A plugin is held when an update moves its source or worsens its scan, or when you
hold it yourself:

```
bento openclaw hold noisy-plugin --reason "started calling home"
bento quarantine release <id> --mode once
```

---

## When OpenClaw is not installed

Every surface says so in a sentence and stops. AgentOS **does not ship an
OpenClaw installer** — it detects and uses the CLI if you have it, and a button
that ran a command we invented would be worse than no button. Install OpenClaw
yourself and this comes to life.

---

## Two things that will surprise you

**A change is not live until OpenClaw's gateway restarts.** OpenClaw loads plugin
code at gateway start, so enabling something here arms it for the *next* start,
not this instant. Every surface says so where you do it.

**`plugins list` is a registry read, not a probe of a running gateway.** It is
the right answer to "is this installed and enabled?" and the wrong one to "is
this loaded right now?" — `openclaw health` answers the second, and AgentOS does
not pretend to.

---

## When it does not fit: build it natively instead

Every install and enable screen — CLI, desktop, and the agent — first says **what will
not work here**, from one computation, so the sentences never differ by surface:

```
⚠ 4 things about this plugin will not work here. AgentOS could rebuild 4 of the
  things it declares out of its own parts instead.
  [high  ] AgentOS cannot refuse what this plugin does
           left in OpenClaw's gateway it runs in OpenClaw's process, so its calls
           never reach this OS's permission engine.
           → build it natively instead, and every call goes through the PDP
  [medium] it wants host-trusted pre-tool policies
           AgentOS's PDP IS that tier and is not delegable to a plugin.
```

Then it offers the other road. A disclaimer whose only button is *Proceed* is a
formality people learn to click through, so there are always two:

```
bento openclaw enable <id> --yes     # accept the caveats
bento openclaw native <id> --yes     # have AgentOS rebuild it out of its own parts
```

### What "natively" means

The plugin's manifest is a specification — it names the tools it provides, the MCP
servers it starts, the events it wants and the config it needs. That is enough to
brief the agent to build the same capability from primitives this OS already governs:

| The plugin declares | AgentOS builds |
|---|---|
| `mcpServers` | the same MCP servers, in AgentOS's own config — these port across **unchanged**, and are already gated per call |
| `contracts.tools` | an MCP server, or a flow whose mission does the job |
| `cliCommands` | a flow, runnable by name |
| `activation.onHooks` | a flow trigger — cron, message, webhook, os_event |
| `configSchema` | what the build asks you for, once |
| trusted tool policies · tool-result middleware · providers · channels · the memory slot · in-turn hooks | **nothing** — these are reported as not portable rather than approximated |

That last row is the important one. A concept with no equivalent here is named as
unportable; it is never quietly mapped onto the nearest thing that compiles.

### Three rules the build runs under

- **The brief is derived, never invented.** Everything in it traces to something the
  manifest declares. A manifest that declares nothing produces no brief and says so —
  AgentOS will not guess what a plugin called `voice-call` probably does.
- **A port is a proposal.** Every flow, skill and MCP entry it writes lands
  **disabled**. Enabling is still the act of granting.
- **The agent checks its own work**, against the same brief it was built from:

```
bento openclaw verify <id>
  ✓ [mcp   ] twilio     — configured as an MCP server; 1 tool(s) live
  ✓ [mcp   ] place_call — reachable as an MCP tool
  ✓ [flow  ] loud       — a flow of this name exists
  all 3 part(s) of the brief are in place
```

That check proves **reachability** — that a flow exists, that an MCP tool is offered —
and says so plainly. It does not prove the tool does the right thing; run it once and
look. Overclaiming here would make "verified" the most dangerous word on the screen.

---

## Coming from OpenClaw: the report

The point of all of this is that people already running OpenClaw can move without
losing what they built. So a port ends in a document you can sign off on, not a
green tick:

```
bento openclaw report <id>
```

It has four parts, and the third is the one that matters:

- **Ported and reachable** — checked, not claimed
- **Declared, not built yet** — what the brief asked for and is still missing
- **Cannot be carried across, and what that costs** — each unportable thing with
  its **implication**, in your terms. Not "trusted tool policies: unsupported",
  but *"any budget or guardrail rule it enforced is gone — write it as a grant or
  a deny policy in Permissions instead, where it is enforced for everything, not
  just for this plugin."*
- **What would you like to do?** — three answers, always

The report ends in a **proposal, not a verdict**. A gap is a thing you can decide
to have built, live with, or keep the original for:

| | |
|---|---|
| have the agent build the rest | `bento openclaw native <id> --yes` |
| continue as it is | a partial port covering what you actually use is a fine place to stop |
| keep running the original alongside | `bento openclaw enable <id> --yes` |

---

## Licences: the same one means two different things here

AgentOS already refuses to ship anything non-permissive and states the licence of
everything it merely offers ([Licensing](licensing.md)). A plugin raises that
question twice, and the honest answers differ:

**Installing it** means *running* it. Running someone's GPL software is what the
GPL is for and needs nobody's permission. The licence is stated, and only a
missing or proprietary one is worth stopping you over.

**Porting it** means the agent writes new code that does the same job. For a
copyleft plugin that raises a derivative-work question, and it is asked before
anything is built:

```
Licence: AGPL-3.0 (from package.json)
Strong copyleft. If the port ends up a derivative of that source, its terms
would attach to what AgentOS writes — which, for AGPL, can extend to software
you only ever run as a service.

✗ This plugin declares AGPL-3.0. A native build reads what it DECLARES — the
  names of its tools, MCP servers, events and settings — and writes new code to
  do that job; it does not copy its source. Whether the result is a derivative
  work is a judgement about your situation that AgentOS cannot make for you.
  AgentOS cannot answer that for you — it is not legal advice.
    bento openclaw native <id> --yes --accept-licence
```

A permissive licence never stops anybody. `MIT OR GPL-3.0` is read as permissive
(you may take the MIT branch); `MIT AND GPL-3.0` as copyleft (you are bound by
both). **No declared licence is not "probably fine"** — with no grant, the
default is that you have no rights to copy or adapt it, so it asks too.

AgentOS states what the licence is and what the port would read. It does not give
legal advice, and it says so.

---

## Command reference

| Command | What it does |
|---|---|
| `bento openclaw list` | what is installed, with `●` on, `○` off, `⛔` held |
| `bento openclaw search <term>` | ClawHub, through OpenClaw's own search |
| `bento openclaw show <id>` | the scan, the source, the history and what enabling would grant |
| `bento openclaw install <spec> [--yes] [--no-pin]` | install it, disabled, then show the review |
| `bento openclaw enable <id> --yes` | write the permissions and turn it on |
| `bento openclaw disable <id>` | turn it off and take the permissions back |
| `bento openclaw update <id>` | update, re-scan, and hold it if it now asks for more |
| `bento openclaw uninstall <id>` | remove it and revoke everything it held |
| `bento openclaw hold <id> --reason …` | stop it now |
| `bento openclaw doctor` | OpenClaw's own check, plus: does its enablement still match what was granted here? |
| `bento openclaw native <id> [--yes] [--print-brief]` | rebuild what it declares out of AgentOS's own parts, behind the PDP |
| `bento openclaw verify <id>` | check a native build against the brief it was built from |
| `bento openclaw report <id>` | ported, outstanding, not portable and what each gap costs, ending in a proposal |

A spec is `clawhub:<package>`, `npm:<package>`, `npm-pack:<file.tgz>`,
`git:github.com/<owner>/<repo>[@ref]`, a local path or archive, or
`<plugin>@<marketplace>`.

---

## See also

- [Models & brains](models.md) — OpenClaw as an executor, and how the brain is chosen
- [The app registry](app-registry.md) — the same scan/consent/trust ideas, for apps
- [Security](security.md) — the policy decision point, grants and the ledger
- [Users](users.md) — why pins are personal and plugins are the machine's

# Sharing your agent — and forking somebody else's

AgentOS can package the agent you have shaped — its skills, its teammates, its
standing flows, the apps you choose, the shapes of the MCP servers it uses, and
(only if you say so) its soul — into one file that anybody running AgentOS can
fork. The format is `agentos-agent/1`, the file is `bento.agent.json`, and the
protocol is deliberately two verbs and one refusal.

```
bento agent share "Morning Aria" --desc "a briefing agent" --apps notes
bento agent show   owner/repo          # read it before taking it
bento agent fork   owner/repo --yes    # everything lands disabled, nothing granted
bento agent verify owner/repo          # integrity + signature only
```

The GUI face is Settings → Agent → **Share this agent**; the same module
(`agentos/agentbundle.py`) decides everything on every surface.

---

## The vital drop: data and credentials never travel

This is the constraint the whole design hangs from, and it is structural, not
reviewed-in:

- **The bundle is built by WHITELIST.** `export()` reads named fields out of
  named tables — skill name/description/content, subagent shape, flow
  definition, app HTML, MCP connection shape — and nothing else. It is never
  "the config minus the secrets": a subtraction fails open the day a new secret
  key is added, a whitelist fails closed.
- **Your memory, knowledge graph and conversations are never read.** They are
  not filtered out; the export never opens those tables at all.
- **MCP credentials become placeholders.** A server that travels keeps its
  transport, command and URL; every `env` and `headers` VALUE is replaced by
  `<YOUR_KEYNAME>` templates the forking user fills in themselves
  (`sanitize_mcp_conf` — the same one implementation `/api/mcp` uses to render
  config, so the two cannot drift).
- **Webhook secrets are stripped from flow triggers** before the flow is
  serialised, and every exported flow is stamped `enabled: false`.
- **Then the finished bytes are scanned anyway.** `leak_scan` runs over the
  serialised bundle looking for anything key-shaped — Anthropic/OpenAI keys,
  GitHub and Slack tokens, AWS and Google keys, PEM blocks, Telegram bot
  tokens, bearer headers, credential-named JSON fields. A finding **refuses the
  export**, names what it found and the line it is on, and there is **no
  force flag** — deliberately, because a shared credential cannot be unshared.
  The fix is to remove the paste from the skill/app/soul it lives in, which is
  what the person actually wants once they see it.

The tripwire matters even with a perfect whitelist: the whitelist cannot know
that somebody pasted an API key into a skill's instructions or an app's HTML.
`tests/test_agentbundle.py` is mostly attacks on this — a config with a
credential in every slot, keys smuggled into skills and apps — and the pass
condition is refusal, not filtration.

## The soul is opt-in, shown in full, and never adopted silently

A soul is learned from its owner's life as much as written, so it is the most
personal thing in the bundle. Three rules:

- `--with-soul` (or the checkbox) is required for it to travel at all;
- the share report prints its **entire text** before you publish, because the
  author is the only person who can judge it;
- a fork **never** adopts an included soul unless `--adopt-soul` is passed —
  the forking agent keeps its own identity, and the consent screen shows the
  soul's full text next to that choice.

## Shipping apps is a per-app choice

An app is the piece most likely to have something personal built into its HTML,
so apps default to **not** traveling. The share screen renders one checkbox per
app (`--apps name,name` or `--apps all` in the terminal), and every shipped app
is re-scanned by the receiving machine before the fork — the same static scan
the app store runs.

## What a fork writes: everything, disabled; permissions, zero

`fork()` creates skills, subagents, flows, apps and MCP server entries — and:

- **every flow lands `enabled: false`**, whatever the file claims (a tampered
  bundle that flips the flag fails its checksum; one that re-hashes is still
  forced off by the fork itself);
- **zero grant rows are written** — the constant `grants_written_now: 0` on the
  consent screen is the design, not a summary. The bundle carries a
  `permissions` list, but it is *disclosure*: what enabling every flow would
  grant, computed by the same `flows.declared_grants` the editor uses, so you
  read the ceiling before anything exists. Enabling each flow later is the act
  of granting, through exactly the doors a hand-written flow goes through.
  This is the flows rule — "a disabled flow holds nothing" — applied to
  everything that arrives from outside;
- **MCP servers land off**, with placeholder credentials to fill;
- **nothing of yours is overwritten** — a name collision is skipped and said
  out loud on the consent screen before the fork, not discovered after it;
- the consent screen and the fork are **one computation** (`fork_preview` is
  what `fork` re-derives), so the sentence agreed to is what happens.

## Integrity, identity, and first-contact trust

The rails are the app registry's, reused rather than re-invented:

- `checksum` is SHA-256 over the canonical manifest; a bundle whose content
  does not match is refused outright (`checksum-mismatch`).
- The optional signature is Ed25519 over the checksum, minted by the same key
  as `bento registry keygen`. `unsigned` is **not hostile** — your own shares
  are unsigned; only `checksum-mismatch` and `bad-signature` mean do-not-fork.
- First fork pins source + signer (`tofu_check`, the SSH model, under the
  personal `registry` config key): `changed-key` on a later fork is the loudest
  alarm, because that is what a hijacked author account looks like.

## Two intentions: a published file, or "it stays with me — take it"

Share and fork are not the same decision seen from two sides. A **fork of a
published file** is a copy the taker owns forever — nothing the author does
later can reach it. A **hosted share** is the other intention: the agent stays
with its owner, and a peer takes it through an authenticated door on the
owner's running machine.

```
bento agent host --on                    # start serving my share
bento agent peers --add laptop-b         # mint a key (shown once) — this IS the grant
bento agent peers                        # who holds keys, and when they last took it
bento agent peers --revoke laptop-b      # end the arrangement: key and grant together

# on the taking machine:
bento agent fork http://host:8321 --key bap_… --yes
```

What the hosted intention buys, that a file in a repo cannot express:

- **Always current.** The bundle is built fresh on every take — the same
  `export()` computation as `bento agent share`, so the whitelist holds and
  **the leak scan runs on every single fetch**: a key pasted into a skill
  yesterday refuses today's take too, with the finding named to the peer.
- **Revocable.** Revoking the key ends it. So does revoking the peer's grant in
  the Permissions app — minting a key writes a real `peer:<name> may
  agent.share` grant row, every take is a `PDP.decide` under that principal
  (ledger row included), and the door re-reads the grant each time. Two ways to
  end it, both of which actually end it.
- **Authenticated, with honest refusals.** Keys are minted by the owner
  (`bap_…`, shown once, optional `--days` lifetime), compared in constant time,
  and the three refusals have three different sentences — `unknown key`,
  `revoked`, and `expired` (which says "rotate it — this is not a leak"),
  because they call for three different actions. A guess flood trips an
  in-memory ceiling before any work happens, the webhook's rule.

### The door speaks MCP

`POST /api/agent/mcp` is a minimal MCP server (JSON-RPC over HTTP, `Bearer`
auth), so the taker does not have to be a Bento machine — any agent that can
call an MCP server can take a hosted share. It offers exactly two tools:
`agent_card` (what a fetch would contain — counts and checksum, never content)
and `fetch_agent` (the bundle itself). A peer principal is denied **everything
else by default** at the policy layer — the minted grant is its entire reach,
and even a hand-written grant cannot take a peer past the built-in denies.

The door sits outside the remote-access gate (a machine caller has no cookie
jar), which also means: if remote access is off, the door is reachable only
from the machine itself, and every surface says so rather than letting a key
open nothing silently.

## Where a shared agent lives: federation, no central host

Nobody hosts the commons — the same design as app distribution. A shared agent
lives in its author's repo as `bento.agent.json` (or
`.bento/agent.agent.json`), discovery is the GitHub topic **`bento-agent`**,
and `owner/repo[@ref]` resolves across two CDNs so one outage does not take
sharing down. `owner/repo@commit` pins immutable bytes — a git hash is a Merkle
root. One resolver serves both formats: `appregistry.resolve_source` takes the
well-known names as a parameter.

## Deliberate omissions

- **There is no agent-facing share/fork tool.** Sharing publishes what may be
  personal and forking brings a stranger's definitions in; both are decisions a
  person makes on a screen that shows them everything. A model that could call
  `share_agent` could be talked into it by a fetched web page. If this changes,
  the tools must be `ALWAYS_ASK` and the export must go nowhere on its own.
- **A fork does not follow updates.** The pin records what you took; taking a
  newer version is a new fork, read on the same consent screen. Silent
  auto-update of somebody else's flows into your machine is the exact thing
  the zero-grant rule exists to prevent.

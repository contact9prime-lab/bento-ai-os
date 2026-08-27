# Bento App Registry

Apps for [Bento Box AI (AgentOS)](https://github.com/contact9prime-lab/bento-ai-os),
as `.agentapp.json` packages — the same portable format the OS itself exports and
imports, with two things added on top: an **AI + static security scan** recorded
inside each manifest, and an **Ed25519 signature** that makes "verified" a checkable
claim instead of a badge.

## Installing an app

Every package here installs into any AgentOS today, no new machinery:

1. Open **Store → Import** on your machine.
2. Paste the package's raw URL, e.g.
   `https://raw.githubusercontent.com/contact9prime-lab/bento-app-registry/main/apps/hello-notes/hello-notes.agentapp.json`
3. Review what it asks for. The consent screen shows every permission, the
   security verdict, and whether the package is **verified** — signed by this
   registry — before anything runs or is granted.

`index.json` lists everything here with its verification state; it is derived by
CI from the packages and never edited by hand.

## What "verified" means — exactly

- The package's `checksum` is a sha256 over the canonical manifest **and** the app
  code. The security scan's verdict lives *inside* the manifest, so it is under
  that checksum too.
- The `signature` is Ed25519 over that checksum, made by a registry maintainer's
  key. The public key is pinned in AgentOS itself.
- So a verified package cannot have its code, its permission list, **or its scan
  verdict** changed — by anyone, anywhere between this repo and your machine —
  without verification failing loudly.

Unsigned is not a refusal: your own exports are unsigned and installing them is
fine. Verified is the strongest claim; the consent screen always tells you which
one you are looking at.

## Every kind of author

People, AI agents, and the two together publish here on identical terms — same
manifest, same scan, same signatures. Authorship is derived from the app's own
edit history and shown on every install screen (`author.kind`: human / agent /
hybrid); packages without it are refused. The rules that keep this worth
trusting are five sentences in [COVENANT.md](COVENANT.md), and the ones that can
be checked mechanically are checked by CI rather than merely asked for.

## Publishing your app

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: `bento registry publish
"Your App"` prints every command, and it ends in an ordinary pull request.

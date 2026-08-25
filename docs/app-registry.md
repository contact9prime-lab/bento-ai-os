# The app registry

The registry is a **Git repository of `.agentapp.json` packages** — the exact
format this OS already exports (Store → an app → Export) and imports (Store →
Import). That one decision does most of the work: propagation is a GitHub raw
URL into the Import door that already existed, publishing is a pull request, and
history/rollback/review are Git's, not ours.

```mermaid
flowchart LR
    A[your AgentOS] -- "bento registry package" --> P[my-app.agentapp.json]
    P -- "bento registry scan --ai" --> P2[+ security verdict IN the manifest]
    P2 -- fork + PR --> R[(bento-app-registry)]
    R -- CI re-validates: checksum, scan, honesty --> R
    R -- maintainer signs (Ed25519 over the checksum) --> V[verified package]
    V -- raw URL --> S[any AgentOS: Store → Import]
    S -- consent screen: permissions + verdict + Verified --> I[installed]
```

## The trust chain, exactly

- `checksum` = sha256 over the **canonical manifest + the app HTML**. The security
  block lives inside the manifest, so the verdict is under the checksum.
- `signature` = Ed25519 over that checksum string, by a registry maintainer's key.
  The public key is pinned in `agentos/appregistry.py` (`BUILTIN_KEYS`); users can
  pin additional keys via `registry.keys` in config — config can **add** trust,
  never replace a built-in.
- Therefore: editing the code, the permission list, or the scan verdict of a
  verified package breaks verification. Recomputing the checksum after editing
  turns `checksum-mismatch` into `bad-signature`. There is no quiet path.

Statuses the install screen can show: `verified` / `unsigned` (your own exports —
fine) / `unknown-key` / `bad-signature` / `checksum-mismatch` (the last two mean
do not install, and the UI says so in red).

## The security scan

Two layers, honestly labelled in `manifest.security.scanner`:

- **static/1** — deterministic rules (sandbox-escape attempts, eval/obfuscation,
  external exfiltration channels, shell requests…). Runs identically on your
  machine and in the registry's CI, because it is the same imported code.
- **ai/<model>** — `bento registry scan --ai` reads the code with this machine's
  own brain using a fixed audit prompt; the report is recorded as a finding and
  the scanner name says which model looked.

A finding is a sentence for a human, not a ban — verdicts are `pass`/`caution`,
and refusal stays a person's decision, as everywhere else in this OS.

## The pipeline

```bash
bento registry package "My App"        # via the RUNNING server's export — one packaging path
bento registry scan my-app.agentapp.json --ai
bento registry sign my-app.agentapp.json    # refuses unscanned packages
bento registry verify <path-or-raw-URL>     # what the receiving side runs
bento registry publish "My App"             # prints the exact fork/PR steps
bento registry keygen                       # mint the registry identity (owner, once)
```

The registry's CI (`registry/.github/workflows/`) pip-installs this repo and
imports `agentos.appregistry` — **one implementation** of the checksum, scan and
signature check everywhere, so a package that passes locally passes there.

## Standing it up

`registry/` in this repo is the complete seed of
`contact9prime-lab/bento-app-registry` — see `registry/SETUP.md`. Until the
public key is pinned in `BUILTIN_KEYS`, everything works except the `verified`
badge: packages install as `unsigned`/`unknown-key`, which is the honest state.

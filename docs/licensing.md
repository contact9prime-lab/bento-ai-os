# Licensing and trademarks

Two different obligations get confused with each other constantly, and the
difference decides what AgentOS is allowed to do:

- **A licence** governs the *code*. GPL, LGPL, MIT, BSD — these say what you may
  do with the software itself.
- **A trademark** governs the *name and the logo*. It is not granted by the
  licence, and a permissive licence grants none of it. Ubuntu's code being free
  to modify does not make the word "Ubuntu" or the Circle of Friends free to put
  on your product.

Almost every mistake in this area is treating the first as if it covered the
second.

---

## What AgentOS is

AgentOS is MIT (see `LICENSE`). Its own code, its own assets — the mark, the
Plymouth theme, the wallpapers — are its own.

## What AgentOS ships

Only permissively licensed dependencies (MIT/Apache/BSD/ISC).
`packaging/audit-licenses.sh` enforces it and must stay green; a copyleft
dependency that is genuinely useful becomes an *offer*, never a bundle, through
`agentos/components.py`. That is why `agentos-desktop` uses `Suggests:` and never
`Depends:`/`Recommends:` for such things — apt installs Recommends by default,
which is bundling with a softer name.

## What AgentOS does NOT ship: the distribution

**AgentOS does not redistribute Ubuntu, or any other distribution.** There is no
ISO, no image, no remaster. It installs *onto* a distro you already have.

Every distro package it needs — sway, GTK, WebKitGTK, NetworkManager, CUPS,
including all the GPL ones — is fetched by **your** package manager from **your**
distro's own archive, at your explicit request, with the licence shown before
you agree (`agentos installer`, or Settings → Components). AgentOS is not a
party to that transfer. This is the single fact that keeps the GPL question
simple: you cannot be redistributing what you never distributed.

## Where the trademark line actually is

| Doing this | Fine? | Why |
|---|---|---|
| Saying "AgentOS runs on Ubuntu 24.04+" | Yes | Nominative use — naming a thing to say something true about it |
| `apt install` instructions that name Ubuntu packages | Yes | Same; it is a factual reference, not branding |
| Replacing the Ubuntu boot splash on **your own machine** | Yes | Your computer, your theme. Consented, and reversible — see below |
| Shipping an ISO built from Ubuntu, **carrying Ubuntu marks** | **No** | Redistributing a modified Ubuntu under its brand needs Canonical's permission |
| Shipping an ISO built from Ubuntu, marks removed | Case by case | The code permits it; the marks must go, and Canonical's [IP policy](https://ubuntu.com/legal/intellectual-property-policy) governs how far "remove the marks" has to reach |
| Naming a product "Ubuntu AgentOS" | **No** | That is brand use, and it implies endorsement |

The practical rule: **the moment AgentOS starts distributing an image rather than
an installer, trademarks stop being somebody else's problem.** Nothing in the
repository builds an image today, and `tests/test_licensing.py` fails if that
changes without this document being revisited.

## The boot splash, specifically

`agentos/de_assets/plymouth/` replaces the distribution's boot splash — the one
place AgentOS overwrites distro branding on a machine. It is:

- **opt-in** — a catalogue component nobody installs by accident;
- **local** — it changes your machine, and redistributes nothing;
- **reversible** — `install.sh` records the theme it displaces to
  `/var/lib/agentos/plymouth-previous-theme`, and `uninstall.sh` puts it back.

That last point was a real gap: the installer used to overwrite the default theme
without recording what it had been, so restoring meant already knowing your
distro's theme name. Removing someone's branding must always be undoable.

## If you fork or rebrand AgentOS

MIT lets you. Two things to keep straight:

1. Keep the MIT notice and copyright — that is the licence's one real condition.
2. The AgentOS name and mark are ours in the same way Ubuntu's are Canonical's.
   Fork the code freely; ship it under your own name.

## Attribution

`NOTICES.md` carries a generated table of every distribution package
`agentos-desktop` depends on, with version, licence and role, produced by
`packaging/audit-licenses.sh --write-notices`. It states plainly that those
packages are installed from the distribution's archive and are not bundled,
modified or redistributed by AgentOS.

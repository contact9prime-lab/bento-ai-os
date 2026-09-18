# Contributing

Thanks for being here. The short version: read [`CLAUDE.md`](CLAUDE.md) before
changing anything. It is not a style guide — it records decisions that are
expensive to rediscover, and most review comments on a PR here are already
answered in it.

## Getting set up

```bash
git clone https://github.com/contact9prime-lab/bento-ai-os
cd bento-ai-os
uv sync --group dev
uv run bento                 # the desktop, at http://127.0.0.1:8321
uv run bento tui             # the same OS in a terminal
uv run pytest -q             # ~1,900 tests, about 90 seconds
```

You need a model to do anything interesting: either [Ollama](https://ollama.com)
running locally with a tool-capable model, or an API key for a cloud provider.
Setup asks on first launch, and `bento brain` sets it from a terminal.

One test, `test_safe_folders`, cannot pass on macOS — pytest's temp dir resolves
under `/private/var`, which is an environment fact rather than a regression. CI
runs on Linux for that reason. Everything else should be green before you open a
PR.

## The three rules that catch most PRs

**1. A feature is built for all three faces.** GUI (a browser or app window), TUI
(a terminal, over SSH, on a headless Pi) and SUI (Bento as the whole Linux
session) are one codebase and one server. Answer all three in the PR description.
"Not applicable" is fine — window snapping has no meaning in a terminal — but say
so in a comment rather than leaving a silent gap.

**2. The desktop is generated.** Edit `agentos/ui/src/`, then run:

```bash
uv run python -m agentos.ui.build
```

`agentos/ui/index.html` is the output and `tests/test_ui_build.py` fails if the
shipped file is stale. The bundle is one concatenated script in filename order,
so top-level `let`/`const` is a trap — use `var`, or name the file so it loads
first.

**3. Never a dead control.** A capability that is missing reports *why*, in a
sentence, plus the component that would fix it. A button that answers a tap by
doing nothing is indistinguishable from the OS being broken, and on a phone it is
reported as exactly that.

## A few more that are load-bearing

- **Touch targets are real size, not a halo.** `--tap` is the floor. Two 16px
  buttons with 40px invisible halos overlap, and whichever paints last silently
  eats the other's taps. Measure with real touch emulation, not by reading CSS.
- **Windows sleep.** Periodic work goes in `winTick(w, fn, ms)`, never a bare
  `setInterval`. `tests/test_ui_lifecycle.py` enforces it.
- **Dependencies must be permissively licensed** (MIT/Apache/BSD/ISC). What this
  project depends on it is effectively distributing.
  `packaging/audit-licenses.sh` gates it and CI runs it. Anything copyleft that
  is genuinely useful is *asked for* at runtime through
  `agentos/components.py`, with its licence in view — never shipped.
- **Fix the cause, and measure.** This may be running on a Raspberry Pi. If a
  change touches performance or footprint, put the before and after numbers in
  the commit message.

## Translations

`docs/i18n/README.<lang>.md` are eleven hand-written translations of the front
page. They are prose, not generated, so editing the English README puts all
eleven out of date and `tests/test_i18n_readme.py` will say so. If you cannot
make a change in all eleven, prefer leaving the English narrower — a sentence
nobody on the team can proofread is worse than a sentence that says less.

Corrections to a translation are very welcome on their own.

## Security

Please don't open a public issue. See [`SECURITY.md`](SECURITY.md).

## Licence

MIT. By contributing you agree your work ships under it.

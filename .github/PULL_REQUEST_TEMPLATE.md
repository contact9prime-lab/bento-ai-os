## What this changes

<!-- And why. The why is the part that is expensive to rediscover later. -->

## The three faces

CLAUDE.md asks this first, not last. "Not applicable" is a fine answer; silence
is not.

- **GUI** —
- **TUI** —
- **SUI** —

## Checks

- [ ] `pytest` passes (or the only failure is `test_safe_folders` on a Mac, which
      is an environment fact — see CLAUDE.md)
- [ ] If the desktop changed: edited `agentos/ui/src/`, ran `python -m agentos.ui.build`,
      and committed the generated `index.html`
- [ ] If a capability can be missing: it reports **why**, in a sentence, with the
      component that would fix it — never a dead control
- [ ] If this is a performance or footprint change: before and after numbers, here
      and in the commit message

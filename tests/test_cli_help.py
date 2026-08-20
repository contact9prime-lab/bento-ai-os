"""`bento --help` — the front page of the CLI, which is the first thing a headless
install shows anybody.

The failure this file exists to prevent is not a crash. It is a fresh Raspberry Pi,
reached over SSH, whose owner types `bento --help` and is shown thirty-nine verbs in
one flat list under a usage line that is itself a forty-word wall — at which point
the honest reading of the screen is "you have to understand all of this before you
can start", when the true answer is one word long (`setup`).

So the listing is SHORT and the catalogue is COMPLETE, and those are two different
commands. Three invariants keep that from rotting into "we hid some commands":

1. **Nothing is removed.** A verb absent from `--help` is still a valid choice and
   still has its own `--help`. argparse has no hidden-subcommand feature; the
   mechanism is that a parser registered without `help=` is left out of the listing
   while remaining in `sub.choices`, which is easy to mistake for deletion.
2. **`bento help --all` prints every verb**, hidden ones included, so the short list
   is never the only list. That is what makes shortening it legitimate.
3. **`--help` says where the rest are.** A shorter page that does not admit it is
   shorter is just a page that is missing things.
"""

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _run(*args) -> str:
    p = subprocess.run([sys.executable, "-m", "agentos", *args],
                       cwd=REPO, capture_output=True, text=True, timeout=120)
    return p.stdout + p.stderr


def _listed(help_text: str) -> list[str]:
    """The verbs `--help` actually shows, read out of the commands block."""
    body = help_text.split("commands:", 1)
    if len(body) < 2:
        return []
    out = []
    for ln in body[1].split("\n"):
        m = re.match(r"^ {4}([a-z][a-z-]*)(?: \(.*\))?(?:\s{2,}| *$)", ln)
        if m:
            out.append(m.group(1))
    return out


def _catalogue(all_text: str) -> list[str]:
    return re.findall(r"^ {4}([a-z][a-z-]*)\s{2,}\S", all_text, re.M)


# --------------------------------------------------------------- the short listing

def test_the_front_page_is_short_enough_to_read():
    """Thirty-nine verbs is not a menu, it is a wall. The number here is a ceiling on
    what somebody can take in at once, not a target."""
    listed = _listed(_run("--help"))
    assert listed, "the `commands:` block of --help has moved or changed shape"
    assert len(listed) <= 12, (
        f"`bento --help` lists {len(listed)} commands again: {', '.join(listed)}")


def test_setup_is_the_first_thing_a_new_machine_is_shown():
    """The one answer to "I just installed this, now what?". Anywhere below the fold
    it is indistinguishable from the other thirty-eight."""
    listed = _listed(_run("--help"))
    assert listed[0] == "setup", f"--help now opens on `{listed[0]}`, not `setup`"


def test_the_usage_line_is_not_a_wall_of_every_verb():
    """Without `metavar` argparse prints every choice, comma-separated, in the usage
    line — which on an 80-column SSH window scrolls the actual help off the screen."""
    usage = _run("--help").split("\n", 1)[0]
    assert "<command>" in usage, "the usage line no longer uses a metavar"
    assert usage.count(",") == 0, f"the usage line lists every verb again: {usage}"


def test_help_says_where_the_rest_of_the_commands_are():
    """A shorter page that does not admit it is shorter is a page that is missing
    things — and the reader has no way to tell which."""
    text = _run("--help")
    assert "help --all" in text, (
        "--help no longer points at the full catalogue, so the hidden verbs are "
        "genuinely undiscoverable")


# ------------------------------------------------------------- nothing is removed

def test_every_hidden_verb_is_still_a_real_command():
    """The mechanism is a missing `help=`, not a missing parser. If that ever becomes
    a real deletion, this is what says so."""
    listed = set(_listed(_run("--help")))
    catalogue = _catalogue(_run("help", "--all"))
    hidden = [v for v in catalogue if v not in listed]
    assert hidden, "no verbs are hidden — the listing is not being shortened at all"
    for verb in hidden:
        out = _run("help", verb)
        assert "no such command" not in out, f"`{verb}` is listed but does not exist"
        assert "usage:" in out, f"`bento help {verb}` prints no usage"


def test_the_catalogue_is_a_superset_of_the_listing():
    listed = _listed(_run("--help"))
    catalogue = set(_catalogue(_run("help", "--all")))
    missing = [v for v in listed if v not in catalogue]
    assert not missing, (
        f"`bento help --all` does not list {missing} — the two lists are drifting, "
        f"and the long one is the one people are sent to")


def test_the_catalogue_covers_the_verbs_a_headless_machine_needs():
    """A spot check with teeth: these are the ones a Pi over SSH is driven with, and
    every one of them was reachable before this listing was shortened."""
    catalogue = set(_catalogue(_run("help", "--all")))
    for verb in ("setup", "serve", "tui", "remote", "service", "doctor", "update",
                 "job", "config", "audit", "flow", "user", "mcp", "install-session"):
        assert verb in catalogue, f"`{verb}` has fallen out of the catalogue"


def test_an_unknown_command_points_at_the_full_list():
    """The commonest way somebody meets the short listing is by typing a verb it does
    not show. "no such command" alone would confirm the wrong conclusion."""
    out = _run("help", "definitely-not-a-command")
    assert "no such command" in out
    assert "--all" in out

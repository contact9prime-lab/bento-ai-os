"""Missions: the shortest path from a fresh install to something that runs by itself.

A **mission is a flow**. This module invents nothing: it turns a recipe plus three or
four answers into a flow definition, and hands it to `flows.save`. The scheduler,
the permission gate, the audit ledger and the delivery sinks are the ones that
already exist. If a mission could do something a flow cannot, that would be a second
permission system, and there is exactly one.

Why it exists at all: the gap between "installed" and "useful" is where this OS
is lost. A flow the user has to design themselves is a blank page; a mission they
pick from a short list and answer two questions about is a habit by Wednesday.

The catalogue is organised by WHO IS ASKING — a founder, a coder, a consultant —
because "what should this machine do for you" has a different answer for each,
and a list that opens with disk space is a list a founder closes. A persona is a
filter over one catalogue, never a second one: every recipe is reachable by
everybody, the persona only decides which are shown first.

Three rules that are load-bearing:

- **Consent is shown before it is written, in the words of the thing being
  consented to.** `preview()` returns the exact `grants` rows saving would create
  (via `flows.declared_grants`, which is pure), and the folder question is asked
  as "which folder may I read", not as a text field that quietly becomes an
  `fs.read` grant. A mission that reads ~/Downloads says so on the card.

- **Delivery is probed, never declared.** `deliveries()` asks the machine which
  ways out actually work right now. Offering Telegram on a machine with no bot
  token is how a first-run flow teaches somebody that this OS lies.

- **A recipe is honest about its tools.** Every tool it names exists in the
  toolbox and is on its specialists' lists, and a recipe that remembers declares
  `memory="read-write"` — the first cut of page-watch granted `remember` under a
  read-only memory scope, so the PDP refused every write and the page was
  "compared to last time" against nothing. `tests/test_jobs.py` pins both.
  There is deliberately no mail or calendar recipe: nothing here can read either
  yet, and a mission that cannot run is the dead control the honesty rules forbid.

Three faces (per CLAUDE.md):
  GUI  the last beat of the first-run wizard, and the Missions app.
  TUI  `bento job` — list, recipes [--for founder], add <recipe> ..., run <name>.
       This is the whole point of keeping the module HTTP-free and async-free.
  SUI  identical to GUI; a mission is not a window, so there is nothing to reserve.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from . import flows as flowsmod

# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

#: The personas the catalogue is sorted by. `everyone` is the neutral answer and
#: the recipes tagged with it appear under every persona.
PERSONAS: list[dict] = [
    {"id": "founder", "label": "Founder",
     "blurb": "Running a company: the market, the competition, the numbers, the update "
              "you owe people every week.",
     "icon": "◆"},
    {"id": "coder", "label": "Coder",
     "blurb": "Shipping code: what changed, what broke, what a dependency did overnight, "
              "and the standup you have not written.",
     "icon": "⌥"},
    {"id": "consultant", "label": "Consultant",
     "blurb": "Serving clients: what landed in their folder, what is due, what they are "
              "in the news for, and the report that is due Friday.",
     "icon": "◈"},
    {"id": "everyone", "label": "Just me",
     "blurb": "One person, one machine that keeps an eye on things.",
     "icon": "○"},
]
PERSONA_IDS = tuple(p["id"] for p in PERSONAS)


def persona_of(cfg: dict) -> str:
    """The persona this person picked, or '' — never a guess."""
    p = str((cfg or {}).get("persona") or "").strip().lower()
    return p if p in PERSONA_IDS else ""


def set_persona(cfg: dict, persona: str) -> str:
    """Record who is asking. '' clears it. Refuses anything not in the table, in a
    sentence, because a persona nothing lists would filter the catalogue to nothing."""
    p = str(persona or "").strip().lower()
    if p and p not in PERSONA_IDS:
        raise ValueError(f"'{persona}' is not one of: {', '.join(PERSONA_IDS)}")
    cfg["persona"] = p
    return p


# ---------------------------------------------------------------------------
# The specialists the recipes need
# ---------------------------------------------------------------------------

#: Subagents the catalogue relies on beyond the three the server seeds
#: (researcher, writer, validator). Created if absent, never overwritten —
#: `ensure_roster` is idempotent, so a machine that already has an `engineer`
#: somebody designed keeps theirs.
ROSTER: list[dict] = [
    {"name": "engineer",
     "soul": "You are a senior engineer reading a codebase you did not write. Use git and "
             "the files to find out what actually changed; quote commits and file paths. "
             "Say what is risky and why in one line each. Never edit, commit or push — "
             "you report, the person decides. If the tests are red, find the likely "
             "cause in the failure tail and the recent commits, and propose the fix as a "
             "diff in your answer rather than applying it.",
     "tools": ["git_status", "git_log", "git_diff", "read_file", "list_dir", "search_files",
               "run_tests", "save_report"],
     "max_steps": 18, "max_seconds": 600},
    {"name": "analyst",
     "soul": "You turn what this machine has seen into a short, sourced account. Read the "
             "files you are pointed at, the timeline and memory; cite the file or the "
             "event every claim comes from. A number without a source is not a number — "
             "leave it out and say so. Never invent a metric, a date or a name. When "
             "asked to remember something, store the fact as one plain sentence.",
     "tools": ["read_file", "list_dir", "search_files", "recall", "remember", "kg_query",
               "timeline", "save_report"],
     "max_steps": 15, "max_seconds": 480},
    # The watcher exists because the seeded researcher cannot `remember`: the first
    # cut of page-watch rostered the researcher, granted `remember` at the flow, and
    # the specialist never called it — a grant a specialist cannot use is a
    # permission for nothing. tests/test_jobs.py now checks the two lists agree.
    {"name": "watcher",
     "soul": "You watch things for a person who is not looking. Fetch exactly what you are "
             "pointed at, `recall` what it said last time, `remember` a compact summary of "
             "what it says now, and report ONLY what changed — with the before and the "
             "after quoted. Banners, dates and reordering are not changes. If nothing "
             "moved, say 'no change' in one line and stop.",
     "tools": ["fetch_url", "recall", "remember", "save_report"],
     "max_steps": 14, "max_seconds": 420},
]


# ---------------------------------------------------------------------------
# What a recipe asks for
# ---------------------------------------------------------------------------


@dataclass
class Need:
    """One question a recipe asks before it can become a flow.

    `kind` is what the surface should draw, not what the value is: 'folder' is a
    string like every other answer, but a folder picker with the consent sentence
    beside it is a different thing from a text box, and the recipe is what knows
    which one this is. 'lines' is several answers in one box, one per line.
    """

    key: str
    label: str
    kind: str = "text"            # text | folder | time | minutes | url | lines | day | choice
    default: str = ""
    help: str = ""
    placeholder: str = ""
    choices: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "kind": self.kind,
                "default": self.default, "help": self.help,
                "placeholder": self.placeholder, "choices": list(self.choices)}


@dataclass
class Recipe:
    id: str
    title: str                    # what it does, in the user's words
    blurb: str                    # one sentence, present tense
    example: str                  # what the first delivery actually looks like
    needs: list                   # list[Need] — always ends with the delivery question
    tools: list                   # tools the roster is granted
    roster: list                  # (subagent, why)
    mission: str                  # {answer} placeholders filled from the answers
    for_: tuple = ("everyone",)   # which personas show it first
    reads_path: str = ""          # which answer key is a folder that must be granted
    schedule: str = "daily"       # daily | weekly | interval | file_change
    memory: str = "read-space"    # flows.MEMORY_SCOPES — read-write when it remembers
    icon: str = "◇"
    worth: str = ""               # what it is for, in one line — the reason to say yes

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "blurb": self.blurb,
                "example": self.example, "icon": self.icon, "worth": self.worth,
                "for": list(self.for_), "schedule": self.schedule,
                "reads_path": self.reads_path, "tools": list(self.tools),
                "roster": [r[0] for r in self.roster],
                "needs": [n.as_dict() for n in self.needs]}


# The delivery question every recipe ends with. Its choices are filtered by
# `deliveries()` against what this machine can actually do.
DELIVER = Need("deliver", "Where should it reach you?", kind="choice", default="report",
               help="You can change this later without touching the rest of the mission.")
AT = Need("at", "When do you want it?", kind="time", default="08:00")
DAY = Need("day", "Which day?", kind="day", default="friday")

# The one place a news search is spelled. Google News publishes an RSS feed per
# query with no key and no account, which is what makes "tell me when X is in the
# news" a mission this machine can honestly run today.
NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
NEWS_NET = "https://news.google.com/rss/*"

RECIPES: list[Recipe] = [
    # ---------------------------------------------------------------- everyone
    Recipe(
        id="morning-brief",
        icon="☀",
        for_=("everyone", "founder", "consultant"),
        title="Brief me every morning",
        blurb="Reads up on the things you follow overnight and leaves one page waiting.",
        worth="Ten minutes of reading you no longer do, before the day starts.",
        example="A page headed 'Tuesday' with four or five paragraphs — what moved, "
                "what is worth reading, and what needs you.",
        schedule="daily",
        needs=[
            Need("topics", "What should I keep an eye on?", kind="text",
                 placeholder="my industry, the two companies I compete with, rust releases",
                 help="Plain words. I will use what I already know about you to fill in "
                      "the rest."),
            AT,
            DELIVER,
        ],
        tools=["fetch_url", "save_report", "recall", "kg_query"],
        roster=[("researcher", "gathers and verifies the material"),
                ("writer", "writes the page itself")],
        mission="Every morning, produce ONE page for the user about: {topics}.\n\n"
                "Use `recall` and `kg_query` first to find out what they already care "
                "about, so this reads as if you know them. Then research: what actually "
                "changed since yesterday, what is worth their time, and anything that "
                "needs a decision from them. Verify before you write — an unsourced claim "
                "is worse than a shorter page.\n\n"
                "Keep it to one page. Lead with the thing that matters most. If nothing "
                "happened, say so in two lines rather than padding it out.",
    ),
    Recipe(
        id="folder-watch",
        icon="🗂",
        for_=("everyone",),
        title="Watch a folder for me",
        blurb="Notices what lands in a folder you choose, works out what it is, and tells you.",
        worth="Nothing that lands in Downloads goes unread again.",
        example="'Three files arrived: an invoice from Acme (₹42,000, due 14 Aug), a "
                "signed contract, and a screenshot.'",
        schedule="file_change",
        reads_path="folder",
        needs=[
            Need("folder", "Which folder may I read?", kind="folder",
                 default="~/Downloads",
                 help="I am only granted permission to READ this one folder. Nothing "
                      "else on the machine, and nothing is moved or deleted."),
            DELIVER,
        ],
        tools=["read_file", "list_dir", "search_files"],
        roster=[("analyst", "reads what arrived and decides what it is")],
        mission="Something new appeared in {folder}. Work out what it is.\n\n"
                "Read the new files. For each one, say in a single line what it is and "
                "the one thing the user would want to know from it — a supplier, an "
                "amount and a due date for an invoice; the counterparty and the date for "
                "a contract; the subject for anything else.\n\n"
                "You may READ this folder and nothing else. Do not move, rename or delete "
                "anything. If a file is nothing worth mentioning, say nothing about it "
                "rather than describing it.",
    ),
    Recipe(
        id="page-watch",
        icon="◉",
        for_=("everyone",),
        title="Tell me when a page changes",
        blurb="Checks a page you name and speaks up only when something real has changed.",
        worth="A price, a term or a status you will hear about the hour it changes.",
        example="'The pricing page changed: the Team plan went from $20 to $25 per seat.'",
        schedule="interval",
        memory="read-write",
        needs=[
            Need("url", "Which page?", kind="url",
                 placeholder="https://example.com/pricing"),
            Need("minutes", "How often should I look?", kind="minutes", default="60",
                 help="Checking more often than the page changes just spends tokens."),
            DELIVER,
        ],
        tools=["fetch_url", "recall", "remember"],
        roster=[("watcher", "fetches the page and compares it to last time")],
        mission="Check {url} and report only REAL changes.\n\n"
                "Fetch the page. Use `recall` to find what it said last time you looked, "
                "and `remember` to store what it says now, so the next run has something "
                "to compare against.\n\n"
                "If nothing meaningful changed — a rotating banner, a timestamp, a "
                "different testimonial — finish silently and say 'no change'. Only speak "
                "up for something a person would want to know: a price, a term, a "
                "feature, an announcement. Quote the before and the after.",
    ),
    Recipe(
        id="week-log",
        icon="▤",
        for_=("everyone", "consultant", "coder", "founder"),
        title="Tell me what I worked on this week",
        blurb="Every week, turns what this machine saw you do into a log by project.",
        worth="A timesheet, a status line or an honest answer to 'what did I do?' — "
              "without keeping one.",
        example="'Mon–Wed: Acme migration (14 runs, 3 reports). Thu: the pricing deck. "
                "Fri: mostly interviews — nothing on this machine.'",
        schedule="weekly",
        needs=[DAY, Need("at", "At what time?", kind="time", default="17:00"), DELIVER],
        tools=["timeline", "recall", "kg_query", "save_report"],
        roster=[("analyst", "reads the timeline and memory and groups it by project")],
        mission="It is the end of the week. Write the user a log of what they worked on, "
                "grouped by project or client, from what THIS machine saw.\n\n"
                "Use `timeline` (the last seven days: runs, reports, apps, memory) and "
                "`recall` for names of projects and clients. Give each group the days it "
                "was active and roughly how much happened. Say plainly that it is what "
                "this machine saw — the days with nothing here were not empty days, and "
                "the log must not pretend to know them.\n\n"
                "One page at most. Newest first. No line without something behind it.",
    ),
    # ----------------------------------------------------------------- founder
    Recipe(
        id="competitor-watch",
        icon="◆",
        for_=("founder",),
        title="Watch my competitors",
        blurb="Reads the pages you name every day and tells you only what actually changed.",
        worth="Their pricing, their changelog and their hiring page, read for you daily.",
        example="'Acme changed pricing: Pro now $49 (was $39) and the free tier lost API "
                "access. Bolt shipped SSO. Nothing else moved.'",
        schedule="daily",
        memory="read-write",
        needs=[
            Need("urls", "Which pages? One per line.", kind="lines",
                 placeholder="https://acme.com/pricing\nhttps://acme.com/changelog\n"
                             "https://bolt.dev/careers",
                 help="Pricing, changelog, careers, docs — the pages that move when "
                      "they move. I may fetch these addresses and nothing else."),
            AT,
            DELIVER,
        ],
        tools=["fetch_url", "recall", "remember", "save_report"],
        roster=[("watcher", "fetches each page and compares it to what it remembers")],
        mission="Watch these competitor pages and report only REAL changes:\n{urls}\n\n"
                "For each page: fetch it, `recall` what it said last time, and `remember` "
                "a compact summary of what it says now (prices, plans, features, roles, "
                "headlines) so the next run has something to compare against.\n\n"
                "Ignore banners, dates, testimonials and reordering. Report a price, a "
                "plan, a limit, a feature, a job opening, a customer logo or an "
                "announcement — with the before and the after quoted. If nothing moved, "
                "finish with 'no change' in one line. Never guess what a change means "
                "for the user's business; state what changed and let them decide.",
    ),
    Recipe(
        id="news-watch",
        icon="◎",
        for_=("founder", "consultant"),
        title="Tell me when someone is in the news",
        blurb="Searches the news for the names you give it and reports only what is new.",
        worth="Your company, your competitors, your clients — you hear first.",
        example="'New today: TechCrunch — Acme raises $12M Series A. Nothing new on Bolt "
                "or Initech.'",
        schedule="daily",
        memory="read-write",
        needs=[
            Need("names", "Which names? One per line.", kind="lines",
                 placeholder="Acme Corp\nBolt\nJane Doe",
                 help="Companies, products or people. Each becomes a news search; I may "
                      "read the news feed and nothing else on the web."),
            AT,
            DELIVER,
        ],
        tools=["fetch_url", "recall", "remember", "save_report"],
        roster=[("watcher", "reads each feed and keeps track of what it has seen")],
        mission="Find what is NEW in the news about these names:\n{names}\n\n"
                "For each name, fetch its feed:\n{feeds}\n\n"
                "Use `recall` to find which headlines you have already reported, and "
                "`remember` the ones you report today, so nothing is repeated tomorrow. "
                "Report new items only, one line each: source, headline, and why it "
                "might matter — in ten words, without speculating. If there is nothing "
                "new for a name, say so in three words. Skip press-release rewrites of a "
                "story already listed.",
    ),
    Recipe(
        id="investor-update",
        icon="▣",
        for_=("founder",),
        title="Draft my investor update",
        blurb="Every week, drafts the update from your notes and numbers folder — sourced, "
              "never invented.",
        worth="The update you owe people, drafted Friday, with every number traced to a file.",
        example="'Highlights: MRR $18.4k (+6%, from metrics/sept.csv). Lowlights: churn "
                "up 2 accounts (notes/churn.md). Asks: an intro to a fintech CFO.'",
        schedule="weekly",
        reads_path="folder",
        needs=[
            Need("folder", "Which folder holds my notes and numbers?", kind="folder",
                 default="~/Documents",
                 help="Metrics exports, meeting notes, a decisions file — whatever you "
                      "keep. I may READ this one folder and nothing else."),
            DAY, Need("at", "At what time?", kind="time", default="16:00"),
            DELIVER,
        ],
        tools=["read_file", "list_dir", "search_files", "recall", "kg_query", "timeline",
               "save_report"],
        roster=[("analyst", "reads the week's files and pulls the facts, with sources"),
                ("writer", "writes the update in the user's voice")],
        mission="Draft this week's investor update from {folder} and from what this "
                "machine knows.\n\n"
                "Read what changed in the folder this week (list it, read the files "
                "that are new or modified). Use `recall` and `kg_query` for context on "
                "the company. Then draft five short sections: Highlights, Numbers, "
                "Lowlights, Asks, Next week.\n\n"
                "Every number carries the file it came from in brackets. A number with "
                "no source is left out, and the draft says what is missing so the user "
                "can fill it in — never estimate, round up or invent. Write it in the "
                "first person, plainly, under 400 words. It is a DRAFT for the user to "
                "send; do not send anything yourself.",
    ),
    # ------------------------------------------------------------------- coder
    Recipe(
        id="standup",
        icon="⌥",
        for_=("coder",),
        title="Write my standup",
        blurb="Every morning, reads your repos and drafts yesterday / today / blockers.",
        worth="The standup written before you sit down, from the commits, not from memory.",
        example="'Yesterday: 4 commits on api (auth refactor, #212 fixed). Today: the "
                "open branch feat/webhooks has uncommitted work. Blockers: 2 tests red "
                "on main since 3c1a9f.'",
        schedule="daily",
        reads_path="folder",
        needs=[
            Need("folder", "Where is my code?", kind="folder", default="~/code",
                 help="The folder your repositories live in. I may READ it and run git "
                      "in it — I never commit, push or edit anything."),
            Need("at", "When do you want it?", kind="time", default="09:00"),
            DELIVER,
        ],
        tools=["git_log", "git_status", "git_diff", "list_dir", "read_file", "search_files",
               "save_report"],
        roster=[("engineer", "reads the repositories and drafts the three lines")],
        mission="Draft the user's standup from the repositories under {folder}.\n\n"
                "Find the repositories (folders with a .git inside, one level down at "
                "most). For each: `git_log` for the last day's commits and `git_status` "
                "for uncommitted work. Then write three short sections — Yesterday (what "
                "the commits say, in plain words, with the repo and the count), Today "
                "(what the open branches and uncommitted changes suggest is in flight — "
                "say it is a guess), Blockers (anything the status or log shows is stuck; "
                "if nothing, say 'none visible').\n\n"
                "Under 120 words. Never commit, push, stash or edit. If a folder has no "
                "repositories, say so in one line and stop.",
    ),
    Recipe(
        id="nightly-review",
        icon="◫",
        for_=("coder",),
        title="Review what I pushed today",
        blurb="Every evening, reads the day's diffs and leaves a short review: risks, "
              "missing tests, loose ends.",
        worth="A second pair of eyes on every day's work, before anyone else sees it.",
        example="'api: the auth refactor drops the rate limit on /login (auth.py:88) — "
                "intended? 3 new functions have no tests. TODO left in billing.py.'",
        schedule="daily",
        reads_path="folder",
        needs=[
            Need("folder", "Where is my code?", kind="folder", default="~/code",
                 help="I may READ it and run git in it. Nothing is edited, committed or "
                      "pushed — it is a review, not a fix."),
            Need("at", "When do you want it?", kind="time", default="18:30"),
            DELIVER,
        ],
        tools=["git_log", "git_diff", "git_status", "list_dir", "read_file", "search_files",
               "save_report"],
        roster=[("engineer", "reads the diffs and writes the review")],
        mission="Review today's work in the repositories under {folder}.\n\n"
                "For each repository with commits today (`git_log`), read the diff of "
                "those commits (`git_diff` against the ref before them) and the "
                "uncommitted diff. Review as a careful colleague: behaviour changes that "
                "look unintended, anything security-relevant (secrets, auth, input "
                "handling), new code with no test beside it, TODO/FIXME left behind, "
                "and files that grew a lot. Quote file and line.\n\n"
                "Be specific and short: one line per finding, worst first, and end with "
                "what looked good. If nothing was pushed today, say so in one line. "
                "Never edit, commit or push.",
    ),
    Recipe(
        id="test-guard",
        icon="✓",
        for_=("coder",),
        title="Keep my tests green",
        blurb="Runs a project's tests on a schedule and, when they fail, says why and "
              "proposes the fix.",
        worth="You find out the suite is red from a page with the cause in it, not from CI "
              "an hour before a demo.",
        example="'RED: 2 failed (test_billing.py::test_refund). Likely cause: commit 3c1a9f "
                "changed the refund rounding. Proposed fix below as a diff.'",
        schedule="daily",
        reads_path="folder",
        needs=[
            Need("folder", "Which project?", kind="folder", default="~/code/myproject",
                 help="One repository with a test suite. I may READ it and run its "
                      "tests; I never change a file."),
            Need("at", "When should it run?", kind="time", default="07:00"),
            DELIVER,
        ],
        tools=["run_tests", "git_log", "git_status", "read_file", "search_files", "save_report"],
        roster=[("engineer", "runs the suite and diagnoses a failure")],
        mission="Run the test suite in {folder} with `run_tests` and report.\n\n"
                "GREEN: one line — how many passed, how long — and stop.\n"
                "RED: name the failing tests, read the failure tail and the recent "
                "commits (`git_log`), read the files involved, and say what most likely "
                "broke it. Propose the fix as a unified diff in the report. Do NOT apply "
                "it, do not edit any file, do not commit — the person decides.\n\n"
                "If the tests cannot run at all (no suite, missing dependency), say "
                "exactly what is missing rather than reporting green.",
    ),
    Recipe(
        id="dependency-watch",
        icon="⬡",
        for_=("coder",),
        title="Tell me when a dependency ships",
        blurb="Reads the release pages you name daily and reports new versions, with "
              "what changed.",
        worth="Breaking changes reach you as a paragraph, not as a failed build.",
        example="'fastapi 0.115 released: dropped Python 3.8, new lifespan API. "
                "pydantic: nothing new.'",
        schedule="daily",
        memory="read-write",
        needs=[
            Need("urls", "Which release pages? One per line.", kind="lines",
                 placeholder="https://github.com/fastapi/fastapi/releases\n"
                             "https://pypi.org/project/pydantic/",
                 help="Release or changelog pages. I may fetch these addresses and "
                      "nothing else."),
            AT,
            DELIVER,
        ],
        tools=["fetch_url", "recall", "remember", "save_report"],
        roster=[("watcher", "reads each page and remembers the latest version seen")],
        mission="Check these release pages for NEW versions:\n{urls}\n\n"
                "For each: fetch it, `recall` the latest version you reported before, "
                "and `remember` the latest version on the page now. Report only versions "
                "newer than what you remembered, with the two or three changes that "
                "matter to somebody depending on it — breaking changes first. If "
                "nothing is new anywhere, finish with 'no new releases' in one line.",
    ),
    # -------------------------------------------------------------- consultant
    Recipe(
        id="client-inbox",
        icon="◈",
        for_=("consultant",),
        title="Keep up with a client's folder",
        blurb="When a client's files land, reads them and tells you what they want, by "
              "when, and for how much.",
        worth="Every brief, contract and invoice a client drops is read the minute it lands.",
        example="'From Acme: a revised SOW (scope adds a data migration, due 30 Sep, "
                "₹6.2L), and a meeting note asking for the deck by Thursday.'",
        schedule="file_change",
        reads_path="folder",
        memory="read-write",
        needs=[
            Need("client", "Which client?", kind="text", placeholder="Acme Corp"),
            Need("folder", "Which folder is theirs?", kind="folder",
                 default="~/Clients/Acme",
                 help="I may READ this one folder. Nothing is moved, renamed or deleted."),
            DELIVER,
        ],
        tools=["read_file", "list_dir", "search_files", "recall", "remember"],
        roster=[("analyst", "reads what arrived and pulls out the asks, dates and amounts")],
        mission="Something new arrived from {client} in {folder}. Read it.\n\n"
                "For each new file, one line: what it is, what they are asking for, any "
                "date, any amount. Then `remember` the asks and dates as facts about "
                "{client}, so later questions ('what does Acme still owe us?') can be "
                "answered.\n\n"
                "Read only; move nothing. If a file is noise (a screenshot, a duplicate), "
                "leave it out rather than describing it.",
    ),
    Recipe(
        id="client-report",
        icon="▥",
        for_=("consultant",),
        title="Draft the weekly client report",
        blurb="Every week, drafts a client's status report from their folder and what "
              "was done — every line sourced.",
        worth="The Friday report drafted before Friday, with nothing in it you cannot back.",
        example="'Acme — week 38. Done: data model signed off (notes/2025-09-16.md). "
                "Open: migration plan (waiting on their DBA). Next: dry run Tuesday. "
                "Asks: staging access.'",
        schedule="weekly",
        reads_path="folder",
        needs=[
            Need("client", "Which client?", kind="text", placeholder="Acme Corp"),
            Need("folder", "Which folder is theirs?", kind="folder",
                 default="~/Clients/Acme",
                 help="Notes, deliverables, their files. I may READ this one folder and "
                      "nothing else."),
            DAY, Need("at", "At what time?", kind="time", default="15:00"),
            DELIVER,
        ],
        tools=["read_file", "list_dir", "search_files", "recall", "kg_query", "timeline",
               "save_report"],
        roster=[("analyst", "reads the week's files and the timeline, with sources"),
                ("writer", "writes the report in a client-ready voice")],
        mission="Draft this week's status report for {client} from {folder} and from "
                "what this machine did for them.\n\n"
                "Read what is new or changed in the folder this week; use `timeline` and "
                "`recall` for work done here. Four sections: Done this week, Open items, "
                "Next week, Asks of the client. Every line carries where it came from in "
                "brackets (a file, a date). Nothing without a source; say what you could "
                "not find rather than filling it in.\n\n"
                "Client-ready tone, under 300 words. It is a DRAFT for the user to send.",
    ),
]

BY_ID = {r.id: r for r in RECIPES}


def recipes_for(persona: str = "") -> list[Recipe]:
    """The catalogue in the order this persona should see it: theirs first, then
    everybody's, then the rest — the WHOLE catalogue, never a subset, because a
    consultant who also writes code must be able to reach the coder's missions."""
    p = (persona or "").strip().lower()
    if p not in PERSONA_IDS:
        return list(RECIPES)

    def rank(r: Recipe) -> int:
        if p in r.for_:
            return 0
        if "everyone" in r.for_:
            return 1
        return 2
    return sorted(RECIPES, key=lambda r: (rank(r), RECIPES.index(r)))


# ---------------------------------------------------------------------------
# Can a mission run on THIS machine at all?
# ---------------------------------------------------------------------------

def readiness(cfg: dict) -> dict:
    """Whether a mission can run here, and if not, the sentence and the fix.

    A mission is a flow, and a flow is run by the BUILT-IN loop on a provider
    model — never forwarded to an executor such as Claude Code — because that is
    the only loop whose every step passes this PDP, which is what the consent
    screen promises ("reads this folder and nothing else"). So a machine whose
    brain is Claude Code with no provider model set can chat, and cannot run a
    mission: found by installing one on exactly such a machine and watching the
    row say 'ConnectError'. This is the sentence the surfaces show BEFORE that,
    in place of a Run button that fails.
    """
    from . import executors
    model = str(cfg.get("default_model") or "").strip()
    provider = model.split("/", 1)[0] if "/" in model else ""
    prov_on = bool(((cfg.get("providers") or {}).get(provider) or {}).get("enabled")) if provider else False
    engine = executors.resolve_engine(cfg)
    title = next((e["title"] for e in executors.EXECUTOR_CATALOGUE if e["id"] == engine), engine)
    if model and prov_on:
        return {"ok": True, "model": model, "engine": engine,
                "note": (f"Missions run on {model} through the built-in loop, so every "
                         f"step is checked against their permissions"
                         + (f" — {title} answers your chats but does not run missions." if engine != "aria" else ".")),
                "fix": ""}
    why = ("No provider model is set" if not model else
           f"The model '{model}' belongs to a provider that is not enabled")
    if engine != "aria":
        why += (f", and {title} — your brain — answers chats but cannot run a mission: "
                f"a mission is a flow, run step by step through this OS's permissions, "
                f"which only the built-in loop does")
    return {"ok": False, "model": model, "engine": engine,
            "note": why + ".",
            "fix": "Settings → AI providers: enable a provider (Ollama is free and local) "
                   "and pick a model. Missions will run on it; your chats keep their brain."}


# ---------------------------------------------------------------------------
# What this machine can actually do with a finished mission
# ---------------------------------------------------------------------------

def deliveries(cfg: dict) -> list[dict]:
    """The ways out that work on THIS machine right now.

    Each entry carries `ready` and, when it is not, the sentence that says why and
    what would fix it. Nothing is hidden — a way out you cannot use yet is more
    useful shown greyed with its reason than absent, because absent reads as
    "this OS cannot do that".
    """
    from . import whatsapp as wamod
    tg = (cfg.get("telegram") or {})
    tg_ready = bool(tg.get("enabled") and tg.get("bot_token") and tg.get("owner_chat_id"))
    wa = wamod.conf(cfg)
    wa_ready = bool(wa.get("enabled") and wamod.configured(cfg) and wa.get("owner_wa_id"))
    return [
        {"id": "report", "label": "Leave it in Reports",
         "detail": "Saved as a page in Files → reports. Always works.",
         "ready": True, "sink": "report", "tool": "save_report"},
        {"id": "notify", "label": "Notify me on this machine",
         "detail": "A desktop notification, if you are at the machine.",
         "ready": True, "sink": "notify", "tool": "notify"},
        {"id": "telegram", "label": "Message me on Telegram",
         "detail": "Reaches you wherever you are." if tg_ready else
                   "Needs a bot token and one /start — Settings → Channels → Telegram.",
         "ready": tg_ready, "sink": "telegram", "tool": "telegram_send"},
        # WhatsApp is offered for missions with its one real limitation stated up front
        # rather than discovered at 08:00 on a Tuesday: Meta will not carry a
        # free-form message to a chat that has been silent for a day, so an
        # unattended mission genuinely cannot rely on it. Saying so is the difference
        # between a constraint and a bug report.
        {"id": "whatsapp", "label": "Message me on WhatsApp",
         "detail": ("Only if you have messaged it in the last 24 hours — WhatsApp will "
                    "not let it speak first. It saves a report as well, so nothing is "
                    "lost when the window has closed.") if wa_ready else
                   "Needs the Cloud API details and one message from your phone — "
                   "Settings → Channels → WhatsApp.",
         "ready": wa_ready, "sink": "whatsapp", "tool": "whatsapp_send"},
    ]


def delivery(cfg: dict, choice: str) -> dict:
    """One delivery option by id, falling back to Reports.

    Falling back rather than refusing is deliberate: a mission whose Telegram was
    unpaired between the answer and the save should still exist and still deliver
    somewhere the user can find it. `install` reports the substitution.
    """
    opts = {d["id"]: d for d in deliveries(cfg)}
    d = opts.get(choice or "")
    if d and d["ready"]:
        return d
    return opts["report"]


# ---------------------------------------------------------------------------
# A recipe plus answers, as a flow definition
# ---------------------------------------------------------------------------

_SAFE_PATH = re.compile(r"^[^\0]{1,400}$")


def _folder(value: str) -> str:
    """A folder answer, as an absolute path, or ValueError with a sentence.

    Refused here rather than at grant time: `fs:` + a path that does not exist is
    a permission for nothing, and the person who could fix it is on the screen
    right now.
    """
    raw = (value or "").strip()
    if not raw or not _SAFE_PATH.match(raw):
        raise ValueError("pick a folder for me to read")
    path = os.path.abspath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        raise ValueError(f"there is no folder at {path} — pick one that exists")
    return path


def _minutes(value, default: int = 60) -> int:
    # `str(None)` is "None", which is truthy — so an unanswered question has to be
    # caught before the string, not after it, or the default never applies.
    raw = "" if value is None else str(value).strip()
    if not raw:
        return default
    try:
        n = int(float(raw))
    except ValueError:
        raise ValueError("how often, in minutes — a number like 60") from None
    return max(5, min(n, 60 * 24 * 7))


def _url(value: str) -> str:
    u = (value or "").strip()
    if not re.match(r"^https?://[^\s]+$", u):
        raise ValueError("that is not a web address — it should start with https://")
    return u[:500]


def _lines(value, what: str, limit: int = 12) -> list[str]:
    """A 'lines' answer as a list: one per line (or comma), blanks dropped, capped —
    twelve competitor pages a day is a mission, forty is a crawler."""
    if isinstance(value, (list, tuple)):
        raw = [str(v) for v in value]
    else:
        raw = re.split(r"[\n,]", str(value or ""))
    out = []
    for item in raw:
        s = " ".join(item.split()).strip()
        if s and s not in out:
            out.append(s)
    if not out:
        raise ValueError(f"give me at least one {what}, one per line")
    return out[:limit]


def _urls(value) -> list[str]:
    return [_url(u) for u in _lines(value, "web address")]


def _names(value) -> list[str]:
    return [n[:80] for n in _lines(value, "name")]


def _text(value, what: str, limit: int = 200) -> str:
    s = " ".join(str(value or "").split())[:limit]
    if not s:
        raise ValueError(f"tell me {what}")
    return s


def _name_for(store, recipe: Recipe, answers: dict) -> str:
    """A flow name a person would recognise in a list of twenty."""
    hint = ""
    if recipe.reads_path:
        hint = os.path.basename(_folder(answers.get(recipe.reads_path, "")).rstrip("/"))
    if "client" in {n.key for n in recipe.needs} and (answers.get("client") or "").strip():
        hint = str(answers.get("client")).strip()
    elif recipe.id == "page-watch":
        hint = re.sub(r"^www\.", "", (_url(answers.get("url", "")).split("/")[2]))
    elif "urls" in {n.key for n in recipe.needs}:
        first = _urls(answers.get("urls"))[0]
        hint = re.sub(r"^www\.", "", first.split("/")[2])
    elif "names" in {n.key for n in recipe.needs}:
        hint = _names(answers.get("names"))[0]
    base = re.sub(r"[^A-Za-z0-9]+", "-", f"{recipe.id}-{hint}".strip("-")).strip("-").lower()[:44]
    base = base or recipe.id
    if store is not None and store.get_flow(base):
        return flowsmod._unique_name(store, base)
    return base


def build(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """A complete, validated flow definition. Writes NOTHING.

    Pure enough to preview: this is what `preview()` runs the grant calculation
    over, so the consent shown on screen is computed from the same definition that
    is later saved rather than from a description of it.
    """
    recipe = BY_ID.get((recipe_id or "").strip())
    if not recipe:
        raise ValueError(f"no mission recipe called '{recipe_id}'")
    answers = dict(answers or {})
    keys = {n.key for n in recipe.needs}
    fill: dict = {}
    perms: dict = {"tools": list(recipe.tools), "memory": recipe.memory,
                   "fs_read": [], "net": [], "skills": [], "fs_write": []}
    triggers: list[dict] = []

    # --- what it may read: the one grant the user was actually asked about, scoped
    #     to the folder they picked and nothing above it
    if recipe.reads_path:
        folder = _folder(answers.get(recipe.reads_path, ""))
        fill[recipe.reads_path] = folder
        perms["fs_read"] = [os.path.join(folder, "*")]

    # --- when it runs: the recipe's schedule, never the folder's presence
    if recipe.schedule == "file_change":
        triggers.append({"kind": "os_event",
                         "config": {"event": "file_change", "path": fill[recipe.reads_path]},
                         "cooldown_secs": 120})
    elif recipe.schedule == "daily":
        at = flowsmod._at_time(answers.get("at") or _default(recipe, "at", "08:00"))
        triggers.append({"kind": "cron", "config": {"type": "daily", "at": at}})
    elif recipe.schedule == "weekly":
        at = flowsmod._at_time(answers.get("at") or _default(recipe, "at", "17:00"))
        day = flowsmod._weekday(answers.get("day") or _default(recipe, "day", "friday"))
        triggers.append({"kind": "cron", "config": {"type": "weekly", "at": at, "day": day}})
    elif recipe.schedule == "interval":
        mins = _minutes(answers.get("minutes"), 60)
        fill["minutes"] = str(mins)
        triggers.append({"kind": "cron", "config": {"type": "interval", "minutes": mins}})

    # --- what it may reach on the web: exactly the addresses it was given
    if "url" in keys:
        url = _url(answers.get("url", ""))
        fill["url"] = url
        perms["net"] = [url]
    if "urls" in keys:
        urls = _urls(answers.get("urls"))
        fill["urls"] = "\n".join(f"- {u}" for u in urls)
        perms["net"] = list(urls)
    if "names" in keys:
        names = _names(answers.get("names"))
        fill["names"] = "\n".join(f"- {n}" for n in names)
        fill["feeds"] = "\n".join(f"- {n}: {NEWS_RSS.format(q=quote_plus(n))}" for n in names)
        perms["net"] = [NEWS_NET]
    if "topics" in keys:
        fill["topics"] = _text(answers.get("topics"), "what to keep an eye on — a few words "
                                                        "is enough", 400)
        perms["net"] = ["*"]      # research means the open web; say so on the card
    if "client" in keys:
        fill["client"] = _text(answers.get("client"), "which client this is for", 80)

    dev = delivery(cfg, answers.get("deliver") or "report")
    if dev["tool"] not in perms["tools"]:
        perms["tools"].append(dev["tool"])
    if dev["id"] in ("telegram", "whatsapp") and "save_report" not in perms["tools"]:
        # A page that will not fit in a message still has to land somewhere — and on
        # WhatsApp the message may be refused outright by the 24-hour window, so the
        # report is not a nicety, it is the thing that stops the run from vanishing.
        perms["tools"].append("save_report")

    mission = recipe.mission.format(**fill)
    mission += f"\n\nDELIVER IT: {_deliver_line(dev)}"

    return {
        "name": _name_for(store, recipe, answers),
        "description": recipe.blurb,
        "mission": mission,
        "roster": [{"subagent": s, "why": why} for s, why in recipe.roster],
        "permissions": perms,
        "sinks": [{"kind": dev["sink"]}],
        "triggers": triggers,
        "max_steps": 20,
        "max_seconds": 900,
        "enabled": 1,
        "job": recipe.id,
    }


def _default(recipe: Recipe, key: str, fallback: str) -> str:
    for n in recipe.needs:
        if n.key == key and n.default:
            return n.default
    return fallback


def _deliver_line(dev: dict) -> str:
    if dev["id"] == "whatsapp":
        return ("`save_report` the finished page FIRST, then `whatsapp_send` a short "
                "summary. In that order: WhatsApp refuses free-form messages to a chat "
                "that has been quiet for 24 hours, and when it does the report is the "
                "only thing left. If the send comes back refused, that is expected — "
                "finish successfully and say the report is waiting.")
    if dev["id"] == "telegram":
        return ("send it to the user's Telegram with `telegram_send`. If it is longer than "
                "a few paragraphs, `save_report` it and send a short summary with a "
                "pointer instead.")
    if dev["id"] == "notify":
        return ("call `notify` with a one-line headline. Keep it to one sentence — it is "
                "a notification, not the report.")
    return ("call `save_report` with the finished page. That is the deliverable; do not "
            "finish having only gathered material.")


# ---------------------------------------------------------------------------
# Preview, install, run
# ---------------------------------------------------------------------------

def ensure_roster(cfg: dict, store) -> list[str]:
    """Make sure the specialists the recipes name actually exist. Returns what it made.

    The server seeds researcher / writer / validator at startup, so those are a
    no-op here; `engineer` and `analyst` are this catalogue's own and are created
    the first time anything asks — on a machine that has run for a year as much as
    on a fresh Pi over SSH, because `seed_builtins` returns early once ANY subagent
    exists and a recipe naming a specialist that is not there fails at its first
    delegation with "no subagent named 'engineer'", a true sentence that tells a
    new user nothing they can act on.
    """
    from . import fabric as fabricmod
    fabricmod.seed_builtins(cfg, store)
    made = []
    for spec in ROSTER:
        if store.get_subagent(spec["name"]):
            continue          # theirs, whatever it is — never overwritten
        store.save_subagent({**spec, "builtin": 1, "model": ""})
        made.append(spec["name"])
    return made


def preview(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """Exactly what installing this would create — before anything is written.

    Same code path as `install`, one step short of the write, so the consent screen
    can never drift from what the save actually does.
    """
    ensure_roster(cfg, store)
    body = build(cfg, store, recipe_id, answers)
    d = flowsmod.validate(body, store)
    return {"flow": {k: body[k] for k in ("name", "description", "mission")},
            "grants": flowsmod.declared_grants(d),
            "triggers": d["triggers"],
            "delivery": delivery(cfg, answers.get("deliver") or "report"),
            "reads": (body.get("permissions") or {}).get("fs_read") or [],
            "net": (body.get("permissions") or {}).get("net") or []}


def install(cfg: dict, store, recipe_id: str, answers: dict) -> dict:
    """Create the mission, enabled, and say what it will do next.

    ENABLED on purpose, unlike a composed draft. A draft is a model's proposal
    that a person has not read; this is a person picking a named thing off a list
    and answering its questions — the consent already happened, and a mission that
    arrives switched off is a mission that never runs.
    """
    ensure_roster(cfg, store)
    body = build(cfg, store, recipe_id, answers)
    asked = answers.get("deliver") or "report"
    dev = delivery(cfg, asked)
    flow, report = flowsmod.save(store, body)
    out = {"ok": True, "flow": flow, "report": report,
           "recipe": recipe_id, "delivery": dev,
           "next_run": next_run(store, flow["name"]),
           "reads": (body.get("permissions") or {}).get("fs_read") or []}
    if asked != dev["id"]:
        out["substituted"] = (f"{asked} is not set up on this machine, so it will leave "
                              f"the results in Reports instead.")
    try:
        store.log("system", f"mission '{flow['name']}' created from the '{recipe_id}' "
                            f"recipe — delivers via {dev['id']}",
                  {"flow": flow["name"], "recipe": recipe_id, "delivery": dev["id"]})
    except Exception:
        pass
    return out


def next_run(store, flow_name: str) -> float | None:
    """When the clock will next start this, or None when nothing polls a clock for it.

    Read off the `tasks` rows rather than recomputed, because the task row is what
    actually fires — a second calculation here would be a second answer, and the
    wrong one would be the one on screen.
    """
    best = None
    for t in store.flow_triggers(flow_name):
        if not t.get("task_id"):
            continue
        task = next((x for x in store.list_tasks() if x["id"] == t["task_id"]), None)
        nr = (task or {}).get("next_run")
        if nr and (best is None or nr < best):
            best = nr
    return best


def describe_next(store, flow_name: str, now: float | None = None) -> str:
    """'in about 3 hours' / 'when something lands in that folder' — the sentence the
    card ends with, so a freshly installed mission says when it will prove itself."""
    trigs = store.flow_triggers(flow_name)
    nr = next_run(store, flow_name)
    if nr:
        secs = max(0, nr - (now if now is not None else time.time()))
        if secs < 90:
            return "in under a minute"
        mins = int(secs // 60)
        if mins < 90:
            return f"in about {mins} minutes"
        hours = int(round(mins / 60))
        if hours < 36:
            return f"in about {hours} hours"
        return f"in about {int(round(hours / 24))} days"
    if any((t.get("config") or {}).get("event") == "file_change" for t in trigs):
        return "the next time something lands in that folder"
    return "when you run it"


# ---------------------------------------------------------------------------
# What it has done: the value surface
# ---------------------------------------------------------------------------

WEEK = 7 * 86400


def _outcome(run: dict | None) -> dict:
    """One run as a line a person reads: when, how it went, and the first sentence
    of what it produced. Honest about failure — 'error' and 'timeout' are the
    status words the run recorded, not softened."""
    if not run:
        return {}
    text = (run.get("output") or run.get("fault") or "").strip()
    text = " ".join(text.split())
    return {"run_id": run["id"], "status": run.get("status") or "",
            "at": run.get("finished_at") or run.get("started_at"),
            "tokens": int(run.get("tokens_in") or 0) + int(run.get("tokens_out") or 0),
            "said": text[:220]}


def installed(store, now: float | None = None) -> list[dict]:
    """Every flow that came from a recipe, newest first, with what it has done —
    the 'what have I got running, and is it worth it?' answer, for the Missions
    app and for `bento job list`.

    Tokens are counted, cost is not claimed: a flow run records its tokens, and the
    price depends on the model each child actually woke up on — that sum lives in
    Usage, where it is priced per row. A cost line here would be a second number
    that disagrees with the first."""
    now = now if now is not None else time.time()
    since = now - WEEK
    grants = store.list_grants()
    out = []
    for f in store.list_flows():
        rid = f.get("job") or ""
        if not rid:
            continue
        runs = store.fabric_runs_for(f["name"], limit=60)
        week = [r for r in runs if (r.get("started_at") or 0) >= since]
        done = [r for r in week if r.get("status") not in ("running", None, "")]
        held = [g for g in grants if (g.get("source_ref") or "") == f"flow:{f['name']}"]
        out.append({"name": f["name"], "recipe": rid, "enabled": bool(f.get("enabled")),
                    "title": (BY_ID[rid].title if rid in BY_ID else f.get("description") or ""),
                    "description": f.get("description") or "",
                    "next": describe_next(store, f["name"], now),
                    "next_run": next_run(store, f["name"]),
                    "last": _outcome(runs[0] if runs else None),
                    "runs_7d": len(done),
                    "ok_7d": sum(1 for r in done if r.get("status") == "ok"),
                    "tokens_7d": sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0)
                                     for r in week),
                    "grants": len(held),
                    "running": any(r.get("status") == "running" for r in runs[:3])})
    return out


def summary(store, now: float | None = None) -> dict:
    """The week in one line: how many missions, how many times they ran, how many
    delivered, how many failed, what they held. Derived from `installed()` so the
    header and the rows can never disagree."""
    rows = installed(store, now)
    return {"missions": len(rows),
            "enabled": sum(1 for r in rows if r["enabled"]),
            "runs_7d": sum(r["runs_7d"] for r in rows),
            "ok_7d": sum(r["ok_7d"] for r in rows),
            "failed_7d": sum(r["runs_7d"] - r["ok_7d"] for r in rows),
            "tokens_7d": sum(r["tokens_7d"] for r in rows),
            "grants": sum(r["grants"] for r in rows)}

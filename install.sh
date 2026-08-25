#!/bin/sh
# Bento Box AI (AgentOS) — one command, from nothing to a machine that answers:
#
#   curl -fsSL https://raw.githubusercontent.com/contact9prime-lab/bento-ai-os/master/install.sh | sh
#
# NOTE: master, not main. Both branches exist on the remote; HEAD is master and
# main is stale, so a raw URL pointing at main 404s and the pipe silently
# installs nothing.
#
# Order matters here, and it is the order a person would use:
#   1. check the network FIRST. Every step below downloads something, and a
#      half-finished install caused by a captive portal or an unconfigured wifi
#      is far worse than being told to connect first — it leaves a repo with no
#      dependencies and a doctor that cannot explain why.
#   2. uv, the repo, the Python dependencies.
#   3. offer the session desktop's own dependencies, on Linux, with what each
#      one is for. AgentOS bundles none of them and asks before installing.
#   4. ask how this machine is to be REACHED, then the launcher and the
#      login/boot service — in that order, so the service comes up already bound
#      the way it was asked for. On a headless box the answer to that question is
#      the difference between an install you can look at and one you cannot.
#   5. START IT AND ASK IT A QUESTION. See "why step 5 exists" below.
#   6. leave it running, because on a server nobody logs into, "installed" has
#      to mean "listening".
#   7. doctor — last, so it reports on a machine that has actually run once.
#
# Flags:
#   --yes                     answer yes to every optional install
#   --passphrase=SECRET       also make it reachable from your network (binds
#                             0.0.0.0 and requires that passphrase to sign in).
#                             Without it, an install with a terminal ASKS; one
#                             with none stays on 127.0.0.1. --yes does not answer
#                             that question: an open port here is an open shell.
#   --bind=ADDR               which interface to listen on once reachable
#                             (default 0.0.0.0 — all of them). Needs --passphrase.
#   --port=N                  the port to answer on (default 8321). Saved to the
#                             config, so the boot service uses it too.
#   --lite                    footprint profile for a small machine (a Pi): the MCP
#                             catalogue is fetched while you search and deleted
#                             when you stop, and telemetry is kept 7 days rather
#                             than 30. `bento profile` shows or changes it later.
#   --no-service              do not install the launcher/login service (containers, CI)
#   --no-verify               skip the "prove it works" step
#
# NOTE ON PASSING FLAGS THROUGH curl: `curl … | sh --port=80` passes the flag to
# `sh`, not to this script, and sh rejects it. The pipe gives the script no argv of
# its own, so there has to be a `-s --` to say "the rest is for the script":
#
#   curl -fsSL <url> | sh -s -- --passphrase='<something long>' --bind=0.0.0.0 --port=80
#
# This is the single most common way the flags below are lost, and the error it
# produces names sh rather than AgentOS.
set -e

# The real, public, MIT-licensed repository — over HTTPS, which needs no
# credentials for a public repo.
#
# This was `https://github.com/YOUR_ORG/agentic-os.git`, a placeholder nobody
# filled in, and the way it failed is worth remembering: git did not say "no
# such repository". GitHub cannot admit a repo is missing without confirming to
# an anonymous caller that it is missing — that would leak the existence of
# private repos — so it answers a 404 the same way it answers a private repo,
# by asking who you are. The prompt for a GitHub username and password was
# therefore not a sign that the install needed a login. It was the only symptom
# a wrong URL is allowed to have.
#
# (And the password could never have worked: GitHub removed password auth for
# git over HTTPS in August 2021. Anyone who typed one got "Support for password
# authentication was removed", which points at credentials — the one thing that
# was never the problem.)
REPO="${AGENTOS_REPO:-https://github.com/contact9prime-lab/bento-ai-os.git}"
DIR="${AGENTOS_DIR:-$HOME/.local/src/agentic-os}"
ASSUME_YES="${AGENTOS_YES:-}"
VERIFY=1
# Install the launcher, the login item and the boot service. Off is for the places
# that have their own supervisor and must not gain a second one: containers, CI,
# and testing this script — on macOS `launchctl bootstrap` registers into the real
# GUI session no matter what HOME says, so a "sandboxed" run without this takes
# over the port of the machine it was only meant to be tested on.
SERVICE=1
PROBE_PORT="${AGENTOS_PROBE_PORT:-8399}"

# Reachable from other machines, decided here rather than discovered later.
# 127.0.0.1 is the right default — the agent has a real shell, so an open port is an
# open shell — but on a server you SSH'd into, loopback means "reachable by nothing",
# and the way to change it (`bento remote --on`) is a sentence at the end that scrolls
# past. Giving it a passphrase up front is the same decision, made where it is useful.
PASSPHRASE="${AGENTOS_PASSPHRASE:-}"
# Which interface and which port, decided here rather than discovered later. BIND is
# only honoured together with a passphrase — see step 3c; that coupling is the whole
# security argument and this script must not be the place it is loosened.
BIND="${AGENTOS_BIND:-}"
PORT_WANTED="${AGENTOS_PORT:-}"
# Light mode, decided here rather than discovered after the first SD card fills.
# Empty means "let the machine decide" — the profile resolves from RAM on first
# run and writes down what it chose.
PROFILE="${AGENTOS_PROFILE:-}"

for a in "$@"; do
  case "$a" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-verify) VERIFY=0 ;;
    --no-service) SERVICE=0 ;;
    --passphrase=*) PASSPHRASE="${a#--passphrase=}" ;;
    --bind=*) BIND="${a#--bind=}" ;;
    --port=*) PORT_WANTED="${a#--port=}" ;;
    --lite) PROFILE=lite ;;
    --full) PROFILE=full ;;
    -h|--help) sed -n '2,43p' "$0"; exit 0 ;;
    -*) printf 'unknown flag: %s  (try --help)\n' "$a" >&2; exit 2 ;;
  esac
done

case "$PORT_WANTED" in
  ''|*[!0-9]*) [ -z "$PORT_WANTED" ] || { echo "--port must be a number" >&2; exit 2; } ;;
esac

# The PATH we INHERITED, before this script widens its own — captured here, at the
# top, because it is the only honest answer to "will `bento` be found in the user's
# next terminal?" and it is destroyed a hundred lines below.
#
# This is the bug that made a successful install print instructions nobody could
# follow. Step 2 prepends $HOME/.local/bin unconditionally so that `uv` can be run
# from here; the later "is $BIN on PATH?" test then examined that widened copy,
# always matched, and skipped writing the PATH line to the user's shell rc. The
# install said "installed the 'bento' command", the last lines said `bento tui`,
# and a new terminal said `bento: command not found` — with nothing anywhere
# admitting why. On Linux it is the normal case rather than an edge one: a GUI
# terminal tab is a NON-login shell, so it reads .bashrc and never .profile, and
# Ubuntu's stock ~/.local/bin snippet lives in .profile and is conditional on the
# directory already existing when the shell started — which, on a first install,
# it did not.
ORIG_PATH="$PATH"
# Set when a shell rc had to be edited, and printed as a required step at the end.
SOURCE_ME=""
# Set when this install actually opened the port, so the last lines can name the
# address that will work rather than the one that happens to be loopback.
REMOTE_ON=""
# ...and who signs in there, when the answer is a person rather than a secret.
REMOTE_WHO=""

say()  { printf '\033[36m▲ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!  %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗  %s\033[0m\n' "$*" >&2; exit 1; }

# Anything that is missing but not fatal is collected and printed ONCE at the
# end. A warning in the middle of a five-minute install scrolls past unread, and
# "it installed fine" followed by a broken feature is the failure this whole
# script is trying to avoid.
GAPS=""
gap() { GAPS="$GAPS
  · $*"; }

# Is there a person here to answer?
#
# `[ -t 0 ]` is the wrong test for THIS script, and it is wrong on the one path
# everybody uses. The documented install is `curl … | sh`, so stdin is the pipe,
# not a terminal — every question below was therefore answered "no" without ever
# being asked, on a script whose whole design is to ask before it changes
# anything. The terminal to talk to is /dev/tty, which the reads already used;
# this is the test agreeing with them. Opening it fails with no controlling
# terminal (a systemd unit, a docker build, CI), which is exactly the case that
# must never block on a prompt.
INTERACTIVE=""
if [ -t 0 ]; then
  INTERACTIVE=1
elif [ -c /dev/tty ] && (: </dev/tty) 2>/dev/null; then
  INTERACTIVE=1
fi

ask() {   # ask "question" -> 0 for yes. Non-interactive installs answer no.
  [ -n "$ASSUME_YES" ] && return 0
  [ -n "$INTERACTIVE" ] || return 1
  printf '\033[36m?  %s [y/N] \033[0m' "$1"
  read -r a </dev/tty 2>/dev/null || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# A question `--yes` does NOT answer, and the only one in this script.
#
# "answer yes to every optional install" is consent to install THINGS. Opening a
# port on this OS is not an install: the agent behind it has a real shell, so it
# is consent to hand that shell to whatever can reach the machine. A flag that was
# typed to skip package prompts must not be able to reach that decision, which is
# also why there is no `--remote` flag — the only way in is `--passphrase`, where
# the person picking the secret is the person deciding.
ask_deliberate() {
  [ -n "$INTERACTIVE" ] || return 1
  printf '\033[36m?  %s [y/N] \033[0m' "$1"
  read -r a </dev/tty 2>/dev/null || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# A question with a typed answer rather than y/n. Same terminal, same rule about
# there being somebody at it: with nobody there ANSWER is the default and nothing
# blocks.
ask_line() {
  ANSWER="$2"
  [ -n "$INTERACTIVE" ] || return 0
  printf '\033[36m?  %s [%s]: \033[0m' "$1" "$2"
  if read -r _line </dev/tty 2>/dev/null; then
    [ -n "$_line" ] && ANSWER="$_line"
  fi
}

# A secret, read without echoing it into the scrollback of a shared terminal.
# `stty` is not always there (a stripped container); showing the characters is a
# worse outcome than refusing to ask, but only slightly — and refusing would mean
# a machine that cannot be reached from anywhere, so it asks anyway and says so.
ask_secret() {
  _s_prompt="$1"
  printf '\033[36m?  %s\033[0m ' "$_s_prompt"
  if command -v stty >/dev/null 2>&1 && stty -echo </dev/tty 2>/dev/null; then
    read -r SECRET </dev/tty 2>/dev/null || SECRET=""
    stty echo </dev/tty 2>/dev/null || true
    echo
  else
    printf '(typed in the clear) '
    read -r SECRET </dev/tty 2>/dev/null || SECRET=""
  fi
}

# ---------------------------------------------------------------------------
# 0. is this script the right one for this machine?
#
# Ahead of the network check, because it is the one question that costs nothing
# to ask and can save a download that was never going to help. It is deliberately
# a coarse `uname` test and nothing more: the REAL capability detection is
# osdetect, and that cannot run until the dependencies are installed. This is
# only "does a POSIX install make sense here at all".
# ---------------------------------------------------------------------------
case "$(uname -s)" in
  Linux|Darwin) ;;
  MINGW*|MSYS*|CYGWIN*)
    warn "this looks like Windows under a POSIX shell."
    echo "   AgentOS has a native Windows installer — it sets up the service and"
    echo "   the Start-menu entry, which this script cannot do from here:"
    echo "     https://github.com/contact9prime-lab/bento-ai-os/releases"
    die "wrong installer for this machine" ;;
  *)
    warn "unrecognised system: $(uname -s). Continuing, but only the browser"
    warn "desktop and the TUI are likely to work." ;;
esac

# ---------------------------------------------------------------------------
# 1. the network, before anything that needs it
# ---------------------------------------------------------------------------
say "checking the network"
net_ok=""
# Ask about the hosts this install ACTUALLY uses, not two homepages. The list was
# `astral.sh github.com`, and it had three faults that only appear on somebody
# else's network:
#
#   · it asked astral.sh even when uv was already installed. That host exists to
#     INSTALL uv, and step 2 below skips the download when uv is present — so the
#     one probe that could veto the install was for something we did not need.
#   · it asked github.com's HOMEPAGE rather than the git endpoint it clones from,
#     so the probe and the operation it stands in for were different requests to
#     different services.
#   · it never asked PyPI, which `uv sync` genuinely cannot proceed without.
#
# And `curl -f` fails on any 4xx, so anything that answers a bare GET with 403 —
# a corporate proxy, a CI network policy, a captive portal — made this abort an
# install that would have worked, under a message telling the user to check their
# wifi. Wrong diagnosis, and the one it hands out is unfalsifiable from where the
# user is standing.
probes="https://api.github.com https://pypi.org"
command -v uv >/dev/null 2>&1 || probes="https://astral.sh $probes"
for probe in $probes; do
  if curl -fsS -m 12 -o /dev/null "$probe" 2>/dev/null; then net_ok=1; break; fi
done
# A reachable git remote is proof by itself, and it is the only probe that tests
# the URL actually about to be cloned — so an AGENTOS_REPO override is checked
# rather than assumed. GIT_TERMINAL_PROMPT=0 because a repo git cannot see is a
# CREDENTIAL PROMPT, not an error (the note at the top of this file is the whole
# story), and a prompt here would hang an unattended install forever.
if [ -z "$net_ok" ] && command -v git >/dev/null 2>&1; then
  GIT_TERMINAL_PROMPT=0 git ls-remote --heads "$REPO" >/dev/null 2>&1 && net_ok=1
fi

if [ -z "$net_ok" ]; then
  warn "no internet connection — everything below needs one."
  # On a headless Pi this is nearly always wifi that has never been configured,
  # so offer the tool rather than just reporting the problem.
  if command -v nmcli >/dev/null 2>&1; then
    echo "   Wi-Fi networks in range:"
    nmcli -t -f SSID,SIGNAL,SECURITY device wifi list 2>/dev/null \
      | awk -F: 'NF && $1!="" {printf "     %-32s %s%%  %s\n", $1, $2, $3}' | head -12 || true
    echo
    echo "   Connect with:"
    echo "     nmcli device wifi connect 'YOUR-SSID' password 'YOUR-PASSWORD'"
  elif [ -f /etc/wpa_supplicant/wpa_supplicant.conf ] || command -v raspi-config >/dev/null 2>&1; then
    echo "   On Raspberry Pi OS:  sudo raspi-config  →  System Options → Wireless LAN"
  else
    echo "   Connect this machine to the network, then run this installer again."
  fi
  die "stopping before a half-finished install"
fi
ok "network is up"

if ! command -v git >/dev/null 2>&1; then
  # macOS has git behind the Command Line Tools, and the prompt is Apple's own.
  if [ "$(uname -s)" = "Darwin" ]; then
    warn "git is missing — macOS provides it through the Command Line Tools."
    xcode-select --install >/dev/null 2>&1 || true
    die "accept the macOS install prompt, wait for it to finish, then run this again"
  fi
  die "git is required — install it first (sudo apt install git)"
fi

# ---------------------------------------------------------------------------
# 2. uv, the repo, the dependencies
#
# uv brings its own Python, which is why this script never asks the user to
# install one: `uv sync` downloads a matching interpreter if the machine has
# nothing suitable. That is the whole reason uv is the bootstrap here.
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "installing uv (Python package manager)"
  curl -fsSL https://astral.sh/uv/install.sh | sh
fi
# Both locations, because the installer's choice has changed across versions and
# a PATH that is missing it turns every command below into "uv: not found".
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PATH
command -v uv >/dev/null 2>&1 || die "uv installed but is not on PATH — open a new terminal and run this again"

# A directory is only an install if the SOURCE is in it. `[ -d "$DIR/.git" ]` was
# the test, and a `.git` with nothing beside it is exactly what an interrupted or
# failed clone leaves behind — after which every later run took the "update" path,
# failed to pull (a warning, not an error), and ran `uv sync` in a directory with
# no pyproject.toml. The message the user then got was uv's:
#
#   error: No `pyproject.toml` found in current directory or any parent directory
#
# which names neither the broken clone nor the way out of it. Once a machine got
# into that state it never left, because the thing that would fix it — cloning —
# was the branch it could no longer reach.
repo_ok() { [ -f "$1/pyproject.toml" ] && grep -q '"agentos' "$1/pyproject.toml" 2>/dev/null; }

if [ -d "$DIR/.git" ] && repo_ok "$DIR"; then
  say "updating AgentOS in $DIR"
  # A failed pull is survivable — local edits, a detached HEAD, no upstream — and
  # the checkout is known good, so keep going with what is there.
  git -C "$DIR" pull --ff-only || warn "could not fast-forward — keeping what is there"
else
  if [ -e "$DIR" ]; then
    if [ -z "$(ls -A "$DIR" 2>/dev/null)" ]; then
      rmdir "$DIR" 2>/dev/null || true
    else
      # Moved, never deleted: it is somebody's directory and it may hold work.
      broken="$DIR.broken.$(date +%s 2>/dev/null || echo old)"
      warn "$DIR exists but is not a usable AgentOS checkout"
      warn "moving it to $broken and cloning fresh"
      mv "$DIR" "$broken" || die "could not move $DIR aside — remove it and run this again"
    fi
  fi
  say "cloning AgentOS into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone "$REPO" "$DIR" || die "clone failed — check the network and try again"
fi

repo_ok "$DIR" || die "no AgentOS source in $DIR after cloning — remove it and run this again"
cd "$DIR"

# The build toolchain a source compile needs, and the ladder to install it.
#
# On x86-64 and 64-bit ARM (aarch64) every dependency here ships a wheel, so
# `uv sync` never touches a compiler. But 32-bit Raspberry Pi OS (armv7/armv6)
# has NO wheel for cffi — pulled in by cryptography, pulled in by the MCP SDK —
# so pip builds it from source and stops with "you likely need to install
# ffi.h". This is not the drifting runtime-component apt block that used to live
# below: it is the small, stable set of headers and compilers that building any
# native Python package requires, and naming it is the difference between a
# five-word fix and an afternoon.
#
# The ladder is the one this project keeps everywhere: passwordless sudo →
# a sudo prompt → hand back the exact command. Never a silent system change.
APT_BUILD_DEPS="build-essential python3-dev libffi-dev libssl-dev pkg-config"
UVSYNC_LOG="${TMPDIR:-/tmp}/agentos-uvsync.$$.log"

# Install the build headers/compilers, by the ladder this project keeps
# everywhere: passwordless sudo → a sudo prompt → the caller hands back the
# command. Returns 0 only if they are now installed. POSIX sh, no `local`.
ensure_build_deps() {
  command -v apt-get >/dev/null 2>&1 || return 1        # not Debian/Pi OS
  say "installing the build tools those packages need: $APT_BUILD_DEPS"
  if [ "$(id -u)" = 0 ]; then
    apt-get update >/dev/null 2>&1
    apt-get install -y $APT_BUILD_DEPS && return 0
  elif command -v sudo >/dev/null 2>&1; then
    if sudo -n true 2>/dev/null; then
      sudo apt-get update >/dev/null 2>&1
      sudo apt-get install -y $APT_BUILD_DEPS && return 0
    elif ask "install the build tools with sudo (you may be asked for your password)?"; then
      sudo apt-get update >/dev/null 2>&1
      sudo apt-get install -y $APT_BUILD_DEPS && return 0
    fi
  fi
  return 1
}

# 32-bit Raspberry Pi (armv6l/armv7l) has NO wheel on PyPI for cffi, cryptography
# or pydantic-core, so uv compiles them from source: minutes of 100% CPU that look
# exactly like a hang and, on a small Pi, can thrash into an OOM kill. piwheels.org
# is the Raspberry Pi project's own wheelhouse of precisely these packages built
# for ARM; pip on Pi OS uses it by default, but uv does not, so it is pointed at it
# here. `unsafe-best-match` is the documented way to let a supplemental index
# satisfy a wheel PyPI only has as an sdist — safe BECAUSE it is added only on
# 32-bit ARM, where PyPI has no wheel to be confused with and piwheels is the
# canonical source for one. If piwheels is unreachable, uv falls back to the PyPI
# sdist and the compile path below still applies, so this only ever helps.
UV_PI_ARGS=""
case "$(uname -m)" in
  armv6l|armv7l)
    UV_PI_ARGS="--extra-index-url https://www.piwheels.org/simple --index-strategy unsafe-best-match" ;;
esac

# `uv sync`, backgrounded with a heartbeat. On a Pi a source build is minutes of
# silence at full CPU, and silence reads as a hang — so a dot every few seconds
# says "working, not stuck". Backgrounded so `wait` yields uv's OWN exit status
# (a `| tee` pipe would report tee's, which is the reason live output was dropped
# before); the log is still written, for the failure classifier below. POSIX sh:
# no pipefail, no process substitution, `$UV_PI_ARGS` intentionally word-split.
run_uv_sync() {
  uv sync $UV_PI_ARGS >"$UVSYNC_LOG" 2>&1 &
  _uvpid=$!
  while kill -0 "$_uvpid" 2>/dev/null; do
    printf '.'
    sleep 5
  done
  wait "$_uvpid"
}

# Pin the interpreter. `requires-python = ">=3.10"` has no ceiling, so on a fresh
# machine uv provisions the NEWEST CPython it can — and the newest is where wheels
# have not caught up yet: cryptography 49, pydantic-core and friends ship prebuilt
# wheels for 3.11–3.13 but not the bleeding-edge release, so uv falls back to
# compiling them (cryptography needs Rust) and the install dies on a 64-bit Pi for
# a reason that has nothing to do with ARM. `.python-version` fixes the interpreter
# at a version with full wheel coverage; this clears a `.venv` a previous run built
# on a different Python so the pin actually takes — uv rebuilds it from the lock.
PYPIN=""
[ -f .python-version ] && PYPIN="$(cat .python-version 2>/dev/null)"
if [ -n "$PYPIN" ] && [ -x .venv/bin/python ]; then
  _have="$(.venv/bin/python -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
  case "$_have" in
    "$PYPIN"|"$PYPIN".*) : ;;                              # already the pinned line
    "") rm -rf .venv ;;                                    # unusable, rebuild
    *) say "rebuilding the environment on Python $PYPIN (was $_have — too new for prebuilt wheels)"; rm -rf .venv ;;
  esac
fi

say "installing dependencies (this fetches Python too, if needed)"
if [ -n "$UV_PI_ARGS" ]; then
  echo "   (32-bit Raspberry Pi — using piwheels prebuilt ARM wheels so packages download instead of compiling; anything not on piwheels still compiles, which is slow)"
elif [ -n "$PYPIN" ]; then
  echo "   (using Python $PYPIN, which has prebuilt wheels for every dependency, so nothing is compiled)"
fi
printf '   working'
if run_uv_sync; then
  echo ""                                               # close the dotted line
  rm -f "$UVSYNC_LOG"
  ok "dependencies ready"
else
  echo ""
  cat "$UVSYNC_LOG"                                      # show what actually failed
  # A cryptography source build, spotted by any of its telltales — the OpenSSL 3.0
  # `#error`, a Rust/cargo failure, "could not compile cryptography". The point is
  # that all three are SYMPTOMS: they only appear once uv has fallen back to
  # building from source, and on 32-bit ARM the reason it fell back is almost always
  # glibc. cryptography DOES ship a prebuilt armv7 wheel — but it is tagged
  # manylinux_2_31, so it needs glibc >= 2.31 (Raspberry Pi OS "Bullseye"). "Buster"
  # has glibc 2.28, too old, so there is no wheel to download and uv compiles — and
  # only THEN meets the OpenSSL/Rust wall. Moving off Buster to Bullseye+ gets the
  # wheel and skips the compile entirely. (Verified against PyPI: the 2_31_armv7l
  # wheel exists and is what a Bullseye Pi downloads.)
  if grep -qiE "MUST be linked with OpenSSL 3|OpenSSL 3\.0\.0 or later|cargo|rust(c| compiler|>=| toolchain)|requires rust|maturin|setuptools[_-]rust|could not compile .?cryptography" "$UVSYNC_LOG" 2>/dev/null; then
    rm -f "$UVSYNC_LOG"
    _g="$(ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | tail -1)"
    _gmaj="${_g%%.*}"; _gmin="$(printf '%s' "${_g#*.}" | tr -cd '0-9')"
    [ -z "$_gmin" ] && _gmin=0
    # glibc >= 2.31 ? (unknown or major>2 counts as new-enough)
    if { [ "$_gmaj" = 2 ] && [ "$_gmin" -ge 31 ] 2>/dev/null; } || { [ -n "$_gmaj" ] && [ "$_gmaj" != 2 ] 2>/dev/null; }; then
      NEW_GLIBC=1
    else
      NEW_GLIBC=0
    fi
    case "$(uname -m)" in
      armv7l)
        if [ "$NEW_GLIBC" = 0 ]; then
          die "cryptography could not install, and the real reason is the OS version — NOT Rust or
   OpenSSL, which are only what the fallback source build then tripped over.

   cryptography ships a PREBUILT 32-bit ARM wheel, but it needs glibc 2.31 or newer. This system
   has glibc ${_g:-older than 2.31} — Raspberry Pi OS 'Buster' is 2.28, too old — so there was no
   wheel to download and uv tried to compile instead.

   The fix is to move off Buster to Raspberry Pi OS 'Bullseye' or 'Bookworm' — 32-BIT IS FINE. There
   the wheel installs in seconds: no compile, no Rust, no swap, and it bundles its own OpenSSL so the
   system's version stops mattering. Reflash (or upgrade) to Bullseye/Bookworm and re-run me."
        else
          die "cryptography compiled even though this system's glibc (${_g}) is new enough for the prebuilt
   32-bit ARM wheel — which usually means an out-of-date uv/pip that cannot see manylinux_2_31 wheels.
   Update uv and re-run:
       uv self update
   As a last resort, build it (needs a modern Rust and OpenSSL 3.0, i.e. Bookworm not Buster):
       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
       . \"\$HOME/.cargo/env\" && sudo apt install -y $APT_BUILD_DEPS"
        fi ;;
      armv6l)
        # armv6 (Pi Zero / 1) is not armv7 — the manylinux wheel does not apply, so
        # cryptography must be built, which needs OpenSSL 3.0 (Bookworm) and rustup.
        die "this is an armv6 Pi (Zero / 1), which has NO prebuilt cryptography wheel at all — the 32-bit
   wheel is armv7-only. Either use a newer Pi (Zero 2 W / 3 / 4 / 5) with 64-bit Bookworm, where
   everything is prebuilt, or compile it on Bookworm (needs OpenSSL 3.0, so not Buster/Bullseye):
       curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
       . \"\$HOME/.cargo/env\" && sudo apt install -y $APT_BUILD_DEPS
   Ensure at least 1 GB of swap first; the build is slow and can still fail on armv6." ;;
      *)
        # 64-bit (aarch64 / x86-64) DOES have a wheel — for 3.11–3.13. Reaching a Rust
        # compile here means uv picked a Python too new for the wheel (3.14+). The pin
        # above prevents it; if we still got here, the pin was missing or overridden.
        die "cryptography tried to compile with Rust on a 64-bit machine, where a prebuilt wheel exists —
   which means uv used a Python too new for it (3.14+). This copy pins Python to ${PYPIN:-3.13}
   in .python-version to avoid exactly that.

   Delete the environment and re-run me so the pin takes effect:
       rm -rf .venv
   If it recurs, uv is ignoring the pin — force the interpreter explicitly:
       uv python install ${PYPIN:-3.13} && uv sync --python ${PYPIN:-3.13}" ;;
    esac
  # "you likely need to install ffi.h" and its siblings mean exactly one thing —
  # a source compile with no C toolchain — so name the fix and, with permission,
  # apply it and try once more rather than making the machine be told twice.
  elif grep -qiE "ffi\.h|Python\.h|openssl/|libffi|command .(gcc|cc). failed|need to install.*development|Microsoft Visual C" "$UVSYNC_LOG" 2>/dev/null; then
    warn "a dependency had no prebuilt wheel for this machine and was COMPILED from source, but the C build tools are missing."
    if ensure_build_deps; then
      printf '   working'
      if run_uv_sync; then
        echo ""
        rm -f "$UVSYNC_LOG"
        ok "dependencies ready (after installing the build tools)"
      else
        echo ""
        rm -f "$UVSYNC_LOG"
        die "a dependency still failed to build after installing the tools — the output above says why.
   If it is cryptography, it needs a modern Rust (rustup), not just the C tools; 64-bit Pi OS avoids it."
      fi
    else
      rm -f "$UVSYNC_LOG"
      die "a dependency must be compiled and the build tools are missing. Install them, then re-run this installer:
     sudo apt install -y $APT_BUILD_DEPS
   On a Raspberry Pi, 64-bit Pi OS avoids this entirely — every dependency ships a prebuilt wheel
   there, so nothing is compiled. cryptography on 32-bit additionally needs a modern Rust via rustup
   (Debian's 'cargo' is too old), which is one more reason to prefer 64-bit Pi OS."
    fi
  else
    rm -f "$UVSYNC_LOG"
    die "dependency install failed — the output above says why"
  fi
fi

# ---------------------------------------------------------------------------
# 2b. what THIS machine can do — asked of AgentOS, not decided here.
#
# `osdetect` already knows the distro, its package manager and whether a login
# session is even possible, and `components.py` and the Settings panel both read
# it. A second copy of that knowledge in shell is precisely the mistake the old
# hardcoded apt block made: it drifted, and the half that drifted was the one
# nobody was running. So this asks, and then only offers what came back.
#
# It is done HERE, immediately after the dependencies exist, because everything
# below is a choice — and offering somebody a Wayland login session on a Mac, or
# silently not mentioning it on Linux, are the same failure in two directions.
# ---------------------------------------------------------------------------
OS_ID=""; OS_PRETTY=""; OS_MANAGER=""; OS_SESSION=""; OS_WHY=""
eval "$(uv run python - <<'PY' 2>/dev/null || true
import shlex
from agentos import osdetect
d = osdetect.detect()
for k, v in (("OS_ID", d.get("os") or ""),
             ("OS_PRETTY", d.get("pretty") or ""),
             ("OS_MANAGER", d.get("manager") or ""),
             ("OS_SESSION", "1" if d.get("session_capable") else ""),
             ("OS_WHY", d.get("why") or "")):
    print("%s=%s" % (k, shlex.quote(str(v))))
PY
)"

echo
say "this machine: ${OS_PRETTY:-$(uname -s)}"
if [ -n "$OS_MANAGER" ]; then
  echo "   packages via ${OS_MANAGER}"
else
  echo "   no package manager AgentOS knows — optional components will be listed, not installed"
fi
echo "   ✓ the desktop, in a browser or an app window   (every OS)"
echo "   ✓ the TUI — the whole OS in a terminal          (every OS)"
if [ -n "$OS_SESSION" ]; then
  echo "   ✓ AgentOS AS your login session                 (this OS can)"
else
  # Never silence. A capability that is missing says why, in a sentence.
  echo "   – AgentOS as your login session: ${OS_WHY:-Linux only}"
fi
echo

# ---------------------------------------------------------------------------
# 3. hand off to the AgentOS installer
#
# This step used to live here as a hardcoded apt block: `command -v apt-get`,
# then a fixed list of Debian package names. It had two faults that only show up
# on somebody else's machine. Behind that apt test, every Fedora, Arch and
# openSUSE user was silently offered NOTHING and told the install had succeeded.
# And the package list, being a second copy, drifted from the real one — it was
# still missing python3-gi-cairo long after that was known to be the difference
# between a desktop and a black screen at login.
#
# So it is not duplicated here any more. `agentos installer` detects the distro,
# resolves the package names for it, shows each licence, and installs only what
# is agreed to — and it is the same catalogue the desktop's Settings panel uses,
# so there is one list to keep true instead of three.
# ---------------------------------------------------------------------------
say "checking what this machine needs"
if [ -n "$ASSUME_YES" ]; then
  uv run bento installer --yes || true
elif [ -t 0 ]; then
  uv run bento installer < /dev/tty || true
else
  # No terminal to ask on: report, change nothing, and say how to finish.
  uv run bento installer < /dev/null || true
  say "run 'bento installer' from a terminal to install what is missing"
fi

# Optional, and each one is a feature that silently does nothing without it. Say
# so here rather than letting it be discovered later as a broken button.
#
# Asked of AgentOS rather than of this shell. `command -v node` is the wrong test:
# the server resolves binaries over an EXTENDED path, because a GUI-launched
# process does not inherit nvm — so this script's own PATH says "missing" for a
# Node the product can see perfectly well, and a false gap is worse than none.
wa_gap=$(uv run python -c 'from agentos import wa_baileys as w; print(w.why_not())' 2>/dev/null || true)
[ -n "$wa_gap" ] && gap "WhatsApp (QR link): $wa_gap"
if command -v claude >/dev/null 2>&1; then
  # Several installs of the CLI on one machine is normal (Homebrew, the official
  # installer, \`claude migrate-installer\`) and AgentOS picks the newest itself.
  # An old one FIRST on PATH is still worth naming: it is what the user's own
  # shell will run.
  cver=$(claude --version 2>/dev/null | head -1)
  case "$cver" in
    1.*) gap "the \`claude\` on your PATH is $cver — AgentOS will use a newer one if you have it; upgrade with: npm i -g @anthropic-ai/claude-code" ;;
  esac
fi

# ---------------------------------------------------------------------------
# 3b. put `bento` on PATH.
#
# Everything this script prints at the end — `bento tui`, `bento setup`,
# `bento doctor` — assumed a command that was never installed. The binaries live
# in the repo's own .venv, which nothing is going to find, so the last line of a
# successful install was advice you could not follow.
#
# A two-line shim rather than a symlink into .venv/bin: the venv's console script
# hardcodes its interpreter path, so a symlink works but breaks silently the day
# the repo moves. `uv run --project` re-resolves, and it also keeps working after
# `uv sync` swaps the Python underneath.
# ---------------------------------------------------------------------------
BIN="$HOME/.local/bin"
mkdir -p "$BIN"

# The shim resolves `uv` by ABSOLUTE PATH, decided here, where we have just proven
# one works. `exec uv run …` was the old line and it inherits this script's widened
# PATH only by luck: it is correct for an interactive shell that can already find
# `bento` in the same directory, and wrong everywhere PATH is not the user's —
# a systemd unit, a cron line, a .desktop Exec=, a `sudo -u`. Each of those got
# "uv: not found" from a command that is plainly installed.
#
# The `command -v` fallback is what keeps it working after `uv self update` moves
# the binary, or after a distro package replaces it.
UV_BIN="$(command -v uv 2>/dev/null || echo uv)"
for cmd in bento agentos; do
  cat > "$BIN/$cmd" <<SHIM
#!/bin/sh
# Installed by AgentOS's install.sh. Safe to delete; re-run the installer to restore.
UV="$UV_BIN"
[ -x "\$UV" ] || UV="\$(command -v uv 2>/dev/null)"
if [ -z "\$UV" ]; then
  echo "$cmd: uv is missing — it is what runs AgentOS." >&2
  echo "  reinstall it:  curl -fsSL https://astral.sh/uv/install.sh | sh" >&2
  exit 127
fi
exec "\$UV" run --project "$DIR" $cmd "\$@"
SHIM
  chmod +x "$BIN/$cmd"
done

# Prove the shim runs before telling anyone it exists. Everything below — the PATH
# advice, the closing "terminal: bento tui" — is a claim about a command, and this
# is the cheapest possible check that the claim is true.
if "$BIN/bento" --help >/dev/null 2>&1; then
  say "installed the 'bento' command (and 'agentos') in $BIN"
else
  warn "wrote $BIN/bento but it does not run — its output:"
  "$BIN/bento" --help 2>&1 | head -n 5 | sed 's/^/     /'
  gap "the 'bento' command is broken; run AgentOS with: cd $DIR && uv run bento"
fi

# On PATH for the shell that will run them next? Asked of $ORIG_PATH — the PATH we
# were STARTED with — never of $PATH, which this script widened itself in step 2 and
# which therefore always contains $BIN and always answers yes. See the note at the
# top of the file: that one substitution is what silently disabled everything below.
case ":$ORIG_PATH:" in
  *":$BIN:"*) ON_PATH=1 ;;
  *) ON_PATH="" ;;
esac
if [ -z "$ON_PATH" ]; then
  # Appended, and said out loud. A PATH line added silently to somebody's shell is
  # the kind of thing they should be able to find later — hence the marker comment.
  #
  # Which files: every rc that already exists, PLUS the one the user's login shell
  # reads even if it does not exist yet. `[ -f "$rc" ] || continue` alone was not
  # enough — a fresh Debian/Alpine/Arch account, a Docker image, or anyone whose
  # shell is zsh with no ~/.zshrc got NOTHING written and no error, which is the
  # same "installed but not found" this block exists to prevent.
  case "${SHELL:-}" in
    # Two files for zsh, because its split is the one that bites: .zshrc covers the
    # interactive terminal, .zprofile covers login (which is what SSH gives you).
    */zsh)  want="$HOME/.zshrc $HOME/.zprofile" ;;
    */bash) want="$HOME/.bashrc" ;;
    */fish) want="" ;;          # different syntax entirely; handled in the gap below
    *)      want="$HOME/.profile" ;;
  esac
  for w in $want; do
    [ -f "$w" ] || : > "$w"
  done

  # `.zprofile` is in this list because `.zshrc` is not enough on its own: zsh reads
  # it for INTERACTIVE shells only. A zsh user typing in a terminal is fine, but
  # `ssh host 'bento service status'` — a login, non-interactive shell — reads
  # .zshenv/.zprofile/.zlogin and never .zshrc, so the command was still not found
  # over SSH, which is exactly where a headless machine is driven from. bash has the
  # mirror-image split and `.profile` already covers its login side.
  added=""
  for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.zprofile" "$HOME/.profile"; do
    [ -f "$rc" ] || continue
    if grep -q 'added by AgentOS installer' "$rc" 2>/dev/null; then
      added="$added $rc(already)"
      continue
    fi
    printf '\n# added by AgentOS installer\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$rc"
    added="$added $rc"
  done
  if [ -n "$added" ]; then
    say "added $BIN to your PATH in:$added"
    # Name the file THIS user's shell actually reads. The message was hardcoded to
    # `. ~/.bashrc`, which is wrong for the zsh users who are the default on macOS
    # and common on Linux — they ran it, nothing changed, and the next step was to
    # work out for themselves that they wanted ~/.zshrc. A script cannot source
    # anything into the shell that invoked it (that is what makes this a gap and
    # not a step), so the least it can do is print the exact line to paste.
    case "${SHELL:-}" in
      */zsh)  rc_now="$HOME/.zshrc" ;;
      */bash) rc_now="$HOME/.bashrc" ;;
      *)      rc_now="$HOME/.profile" ;;
    esac
    # Also carried to the closing block: it is the single next thing the user has to
    # do, and a line buried in a list headed "working, with these gaps" is not where
    # a required step belongs.
    SOURCE_ME="$rc_now"
    gap "\`bento\` is not on the PATH of THIS shell yet — see the line above the gaps"
  else
    gap "add this to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
  case "${SHELL:-}" in
    */fish) gap "fish uses different syntax:  fish_add_path \$HOME/.local/bin" ;;
  esac
  # This script's own remaining steps must not depend on the rc file it just wrote.
  PATH="$BIN:$PATH"; export PATH
fi

# ---------------------------------------------------------------------------
# 3c. the address it answers on, if that was asked for.
#
# Before the launcher, so the service that starts below comes up already bound the
# way it was asked for rather than binding to loopback and needing a restart to
# move — and so the systemd unit / LaunchAgent bakes in the right port, which it
# reads from the config at install time.
# ---------------------------------------------------------------------------
# The BIND is decided before the PORT on purpose. `bento remote --port` verifies the
# port by really binding it, against whichever interface the config currently names —
# and macOS refuses 127.0.0.1:80 to a non-root process while allowing 0.0.0.0:80, so
# checking the port while the config still said loopback reported a refusal for a
# setup that was two lines from working.
if [ -n "$PASSPHRASE" ]; then
  # 0.0.0.0 unless a specific interface was named. --bind ALONE is deliberately not
  # enough: binding off loopback without a passphrase is refused by `serve` anyway
  # (the agent has a real shell, so an open port is an open shell), and quietly
  # accepting the flag here would teach that it works.
  bind_to="${BIND:-0.0.0.0}"
  say "turning on remote access (binding $bind_to)"
  if uv run bento remote --on --passphrase "$PASSPHRASE" --bind "$bind_to" >/dev/null 2>&1; then
    ok "reachable from your network — sign in with that passphrase"
    gap "this machine now answers on $bind_to. If it faces the internet, put it behind a tunnel or a firewall."
    REMOTE_ON=1
  else
    # Never a silent half-state: refusing is usually the passphrase being too short,
    # and leaving it on loopback is the safe outcome to report.
    warn "could not enable remote access — still loopback only"
    gap "set it yourself:  bento remote --on --passphrase '<something long>' --bind $bind_to"
  fi
elif [ -n "$INTERACTIVE" ] && ! uv run bento remote 2>/dev/null | head -1 | grep -q 'ON'; then
  # `--bind` on its own still does not open anything — but somebody who typed it
  # was asking for exactly this, and answering them with a warning and nothing else
  # is a refusal where a question belongs. The interface they named is carried into
  # the offer; the passphrase is still the thing that decides.
  if [ -n "$BIND" ]; then
    warn "--bind=$BIND on its own is not enough: binding off loopback needs a passphrase."
    warn "AgentOS hands whoever loads it a real shell, so an open port is an open shell."
  fi
  # ASK, on a machine with somebody at the keyboard.
  #
  # Loopback-only is the right default and it stays the default — but on the box
  # this install is written for (a Pi, reached over SSH, no screen) it is also the
  # setting that makes everything that was just installed unreachable. The desktop
  # is a browser page; a machine with no browser and a closed port is an install
  # nobody can look at, and the only thing that said so was one line at the end of
  # a long log.
  #
  # Deliberately NOT covered by --yes: opening a port here opens a shell, and
  # "yes to every optional install" is not consent to that. It needs a passphrase
  # a person chose, so an unattended install cannot reach this at all.
  bind_to="${BIND:-0.0.0.0}"
  echo
  say "this machine answers on 127.0.0.1 only — nothing else on your network can reach it"
  echo "   AgentOS is a desktop in a browser, so on a machine with no screen that"
  echo "   means nothing can open it. Turning it on binds $bind_to and requires a"
  echo "   passphrase to sign in."
  echo "   (You can do it later instead: bento remote --on)"
  if ask_deliberate "make this machine reachable from your phone or laptop?"; then
    # WHO signs in, asked as a choice rather than assumed.
    #
    # A passphrase is not a user. On a machine with no accounts you sign in with
    # one shared secret and you are the machine itself — which is the right shape
    # for one person and one Pi, and is genuinely confusing if you expected a
    # username. The alternative is real and this is the moment to offer it, but
    # NOT as a second secret: `remote.lock_kind` is explicit that accounts win and
    # a passphrase in front of them is dead config, so this is one question with
    # two answers, not two questions.
    echo
    echo "   Two ways to sign in:"
    echo "     1  a passphrase — one secret, for whoever uses this machine."
    echo "        Simplest, and right for one person and one machine."
    echo "     2  an account — your own username and password."
    echo "        This machine then asks who you are at the keyboard too; everything"
    echo "        already here becomes that first account's, and it is an admin."
    ask_line "1 or 2" "1"
    # Kept in its own variable, because `ask_line` writes ANSWER and the retry
    # loop asks for a username with it — so re-testing ANSWER for the MODE meant
    # that a mistyped password on the account path silently dropped you into the
    # passphrase path, which then reported "sign in with that passphrase" for a
    # machine where you had just been asked to choose a username.
    signin="$ANSWER"
    tries=0
    while [ "$tries" -lt 3 ]; do
      tries=$((tries + 1))
      if [ "$signin" = "2" ]; then
        ask_line "a username" "$(id -un 2>/dev/null || echo me)"
        who="$ANSWER"
        ask_secret "a password for $who (8 characters or more):"
        pass1="$SECRET"
        ask_secret "again:"
        pass2="$SECRET"
        SECRET=""
        [ -n "$pass1" ] || { warn "nothing typed — staying on loopback"; break; }
        if [ "$pass1" != "$pass2" ]; then warn "those did not match"; continue; fi
        # Two calls, because they are two facts: WHO may sign in, and THAT this
        # machine answers off loopback. The account is the lock, so `remote --on`
        # needs no passphrase once it exists — and if the account is refused
        # (a name already taken, a password too short) the port is never opened,
        # which is the safe way round.
        if user_out="$(uv run bento user add "$who" --password "$pass1" --role admin 2>&1)"; then
          if remote_out="$(uv run bento remote --on --bind "$bind_to" 2>&1)"; then
            ok "reachable from your network — sign in as $who"
            gap "this machine now answers on $bind_to. If it faces the internet, put it behind a tunnel or a firewall."
            REMOTE_ON=1
            REMOTE_WHO="$who"
            break
          fi
          printf '%s\n' "$remote_out" | sed -n '1,3p' | sed 's/^/   /'
        else
          printf '%s\n' "$user_out" | sed -n '$p' | sed 's/^/   /'
        fi
      else
        ask_secret "a passphrase to sign in with (8 characters or more):"
        pass1="$SECRET"
        ask_secret "again:"
        pass2="$SECRET"
        SECRET=""
        [ -n "$pass1" ] || { warn "nothing typed — staying on loopback"; break; }
        if [ "$pass1" != "$pass2" ]; then warn "those did not match"; continue; fi
        # One call, and it is the same one the flag path makes. Its refusal is shown
        # verbatim rather than paraphrased here, where the rule would drift from
        # `remote.passphrase_problem` the first time that rule changes.
        if remote_out="$(uv run bento remote --on --passphrase "$pass1" --bind "$bind_to" 2>&1)"; then
          ok "reachable from your network — sign in with that passphrase"
          gap "this machine now answers on $bind_to. If it faces the internet, put it behind a tunnel or a firewall."
          REMOTE_ON=1
          break
        fi
        printf '%s\n' "$remote_out" | sed -n '1,3p' | sed 's/^/   /'
      fi
      if [ "$tries" -ge 3 ]; then
        warn "leaving remote access off"
        gap "turn it on when you have chosen one:  bento remote --on"
      fi
    done
    pass1=""; pass2=""
  else
    gap "reachable from elsewhere later:  bento remote --on"
  fi
elif [ -n "$BIND" ]; then
  # Nobody to ask (a systemd unit, a container build, CI). Never silently applied:
  # `serve` refuses it anyway, and accepting it here would teach that it worked.
  warn "--bind=$BIND ignored: binding off loopback needs a passphrase."
  warn "AgentOS hands whoever loads it a real shell, so an open port is an open shell."
  gap "reachable from your network:  --passphrase='<something long>' --bind=$BIND"
fi

if [ -n "$PORT_WANTED" ]; then
  say "setting the port to $PORT_WANTED"
  # `bento remote --port` prints the refusal itself, having ASKED the kernel rather
  # than assuming from the number. The rule of thumb everyone reaches for — "below
  # 1024 needs root" — is true on Linux and false on macOS, and even on Linux it is
  # only true until somebody lowers net.ipv4.ip_unprivileged_port_start, which
  # containers routinely do. So the output is shown rather than a guess printed here.
  if port_out="$(uv run bento remote --port "$PORT_WANTED" 2>&1)"; then
    ok "port $PORT_WANTED"
    case "$port_out" in
      *"will not let AgentOS listen"*)
        printf '%s\n' "$port_out" | sed -n '/will not let AgentOS listen/,$p' \
          | grep -v '^remote access:\|^  binds:\|^  reach:' | sed 's/^/  /'
        gap "port $PORT_WANTED needs the one-time step printed above before it will bind"
        ;;
    esac
  else
    warn "could not set the port — staying on the default"
    gap "set it yourself:  bento remote --port $PORT_WANTED"
  fi
fi

# The footprint profile. Set before the first run, so a small machine never even
# fetches the 12 MB MCP catalogue it is not going to keep. Left alone otherwise:
# the server resolves "auto" from this machine's RAM on its first boot and writes
# down what it chose, which `bento profile` then reports.
if [ -n "$PROFILE" ]; then
  say "setting the footprint profile to $PROFILE"
  if prof_out="$(uv run bento profile "$PROFILE" 2>&1)"; then
    printf '%s\n' "$prof_out" | sed -n '1p' | sed 's/^/  /'
  else
    warn "could not set the profile — the machine will decide on first run"
    gap "set it yourself:  bento profile $PROFILE"
  fi
fi

# ---------------------------------------------------------------------------
# 4. install the launcher
# ---------------------------------------------------------------------------
if [ "$SERVICE" = 1 ]; then
  say "installing launcher + login service"
  uv run bento install || warn "the launcher/login step reported a problem — AgentOS still runs with 'bento'"
else
  say "skipping the launcher and login service (--no-service)"
fi

# ---------------------------------------------------------------------------
# 5. prove it. WHY THIS EXISTS:
#
# Every failure this project has shipped looked like a successful install. A
# wheel that unpacked and a server that could not start; a bridge whose flags the
# installed CLI did not have; a first-run screen that answered 404 because the
# process predated the route. In every case the installer said "done".
#
# So the last thing it does is start the server on a spare port, ask it the one
# question that requires the whole stack to be alive — the setup arc, which needs
# config, database and routes — and then stop it. A spare port because a machine
# that is already running AgentOS must not have its session disturbed by its own
# installer.
# ---------------------------------------------------------------------------
if [ "$VERIFY" = 1 ]; then
  say "starting it once to check it actually works"
  uv run bento serve --port "$PROBE_PORT" --no-browser >/tmp/agentos-verify.$$ 2>&1 &
  probe_pid=$!
  verified=""
  i=0
  while [ "$i" -lt 60 ]; do
    i=$((i + 1))
    sleep 1
    kill -0 "$probe_pid" 2>/dev/null || break     # it died; stop waiting for it
    if curl -fsS -m 3 -o /dev/null "http://127.0.0.1:${PROBE_PORT}/api/onboarding" 2>/dev/null; then
      verified=1
      break
    fi
  done
  kill "$probe_pid" 2>/dev/null || true
  wait "$probe_pid" 2>/dev/null || true

  if [ -n "$verified" ]; then
    ok "it starts, serves the desktop, and answers"
    rm -f "/tmp/agentos-verify.$$"
  else
    warn "AgentOS installed, but the server did not answer within 60s."
    echo "   The last lines of its output:"
    tail -n 15 "/tmp/agentos-verify.$$" 2>/dev/null | sed 's/^/     /'
    echo "   Full log: /tmp/agentos-verify.$$"
    echo "   Try it yourself:  cd $DIR && uv run bento serve"
    die "stopping here rather than reporting a success nobody checked"
  fi
fi

# ---------------------------------------------------------------------------
# 6. leave it RUNNING.
#
# Step 5 proves the stack can start; it does not leave anything up. On a server
# nobody is going to log into, "installed" has to mean "listening" — a login
# service that only starts at login is not started on a box where nobody logs in.
# `bento install` already enables systemd linger for that; this is the part that
# checks the promise was kept, and starts it by hand when it was not.
# ---------------------------------------------------------------------------
PORT=$(uv run python -c 'from agentos import config as c; print(c.load_config().get("port") or 8321)' 2>/dev/null || echo 8321)
# The address to PROBE, which is not always the address it BINDS. A server bound to
# one specific interface (--bind=192.168.1.5) does not answer on 127.0.0.1 at all,
# and probing loopback would report a perfectly healthy machine as "did not come up"
# — then start a second copy beside the one that was already working. 0.0.0.0 and
# loopback both answer on 127.0.0.1, so only a named interface changes the probe.
PROBE_HOST=127.0.0.1
case "$BIND" in
  ''|0.0.0.0|::|127.0.0.1|localhost) ;;
  *) PROBE_HOST="$BIND" ;;
esac
# Any HTTP answer counts, including 401: a machine with accounts is locked, and
# locked is a running server, not a broken one.
listening() { [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://${PROBE_HOST}:${PORT}/api/platform" 2>/dev/null)" != "000" ]; }

# Whether anything is actually listening when this script ends. The last lines used
# to print "✓ AgentOS is running." whenever the service step had been ATTEMPTED —
# so a box with no systemd (a container, a non-systemd distro, SSH with no user bus)
# reported the service failing to come up in the middle and then claimed it was
# running four lines later. Both sentences were on the screen at once. This variable
# is the one that gets the last word.
RUNNING=""

if [ "$SERVICE" = 0 ]; then
  say "not started (--no-service) — run it with: cd $DIR && uv run bento serve"
elif listening; then
  ok "already serving on ${PROBE_HOST}:${PORT}"
  RUNNING=1
else
  say "starting the service"
  case "$(uname -s)" in
    Darwin) launchctl kickstart -k "gui/$(id -u)/com.agentos.server" >/dev/null 2>&1 || true ;;
    Linux)  systemctl --user start agentos >/dev/null 2>&1 || true ;;
  esac
  i=0
  while [ "$i" -lt 20 ] && ! listening; do i=$((i + 1)); sleep 1; done
  if listening; then
    ok "serving on ${PROBE_HOST}:${PORT}"
    RUNNING=1
  else
    # Not a failure of the install — step 5 already proved it runs. This is the
    # service manager, which is a different problem with a different fix, and
    # `bento service start` now performs it on whichever supervisor exists (or
    # none, in which case it starts the server directly and says so).
    gap "the background service did not come up; start it with: bento service start"
    warn "installed and working, but not running as a service yet"
  fi
fi

# ---------------------------------------------------------------------------
# 7. the environment check, AFTER it has run once.
#
# Deliberately last. Run before the first start, doctor reports a fresh install's
# empty state as damage — "db check failed: unable to open database file" is the
# database not existing YET, on a machine where nothing has opened it. A red ✗ on
# every clean install teaches people to ignore the one tool that tells them when
# something is genuinely wrong.
# ---------------------------------------------------------------------------
say "environment check"
uv run bento doctor || true

# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------
echo
# Reports what step 6 FOUND, not what it attempted. `[ "$SERVICE" = 1 ]` was the
# test, so a machine where the service demonstrably failed to start was still told
# "AgentOS is running" — the exact shape of lie this installer's step 5 exists to
# prevent, printed by the last line of the same script.
if [ -n "$RUNNING" ]; then
  ok "AgentOS is running."
elif [ "$SERVICE" = 1 ]; then
  ok "AgentOS is installed — but nothing is listening yet."
else
  ok "AgentOS is installed (nothing was started — --no-service)."
fi
# ONE next step, not eight.
#
# The old ending printed seven `bento …` lines and a passphrase incantation, all at
# the same weight, to somebody who had just watched five minutes of log scroll past.
# Every one of them was true and none of them was the answer to "what do I do now?"
# — which on a machine that has never been set up is exactly one thing. The rest of
# the catalogue is one command away and now says so in one line.
echo
printf '\033[1m▲ next:  bento setup\033[0m   — name it, give it a brain, put it to work\n'
if [ -n "$RUNNING" ]; then
  echo "   or open the desktop:  http://${PROBE_HOST}:${PORT}"
  # The address that will actually work from the laptop this was typed on. `bento
  # remote` already computes it (it knows the interfaces and the port); reprinting
  # its answer is how the two never disagree.
  if [ -n "$REMOTE_ON" ]; then
    uv run bento remote 2>/dev/null \
      | sed -n 's|^  reach:   |   from another device:  |p'
    if [ -n "$REMOTE_WHO" ]; then
      echo "   sign in as:  $REMOTE_WHO"
    else
      echo "   sign in with:  the passphrase you just chose"
    fi
  fi
else
  echo "   start it first:  bento service start"
fi
echo
echo "   everything else:  bento help    — the ten commands you need, and where the rest are"
if [ -z "$REMOTE_ON" ]; then
  # Printed, never done — widening this is the user's decision and it needs a
  # passphrase they choose. Asked for above when there was somebody to ask.
  echo "   reach it from your phone:  bento remote --on"
fi
# `session_capable`, not `command -v sway`. The old test asked whether a
# compositor happened to be installed, so a Linux box that had simply not been
# offered one yet was told nothing — the option existed and was never mentioned.
# Whether the OS can host a login session at all is a different question, and it
# is the one `osdetect` answers.
if [ -n "$OS_SESSION" ]; then
  echo "   as your desktop:  bento install-session   (then pick AgentOS at login)"
fi
# Last, and on its own, because every `bento …` line above is unreachable until it is
# done — so it reads as the step that unlocks the rest, which is what it is. A script
# cannot put a directory on the PATH of the shell that ran it: the export happens in a
# child process and dies with it. So this really is the user's step, and the job here
# is to make it one line they can paste, naming the file their own shell reads.
if [ -n "$SOURCE_ME" ]; then
  echo
  printf '\033[36m▲ one step left — this shell has not got `bento` on its PATH yet:\033[0m\n'
  printf '\033[1m     source %s\033[0m\n' "$SOURCE_ME"
  echo "   (or just open a new terminal — new shells will pick it up by themselves)"
fi

if [ -n "$GAPS" ]; then
  echo
  warn "working, with these gaps:"
  printf '%s\n' "$GAPS"
fi

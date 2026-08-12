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
#   4. the launcher and the login/boot service.
#   5. START IT AND ASK IT A QUESTION. See "why step 5 exists" below.
#   6. leave it running, because on a server nobody logs into, "installed" has
#      to mean "listening".
#   7. doctor — last, so it reports on a machine that has actually run once.
#
# Flags:  --yes  answer yes to every optional install   --no-verify  skip step 5
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
PROBE_PORT="${AGENTOS_PROBE_PORT:-8399}"

for a in "$@"; do
  case "$a" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-verify) VERIFY=0 ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
  esac
done

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

ask() {   # ask "question" -> 0 for yes. Non-interactive installs answer no.
  [ -n "$ASSUME_YES" ] && return 0
  [ -t 0 ] || return 1
  printf '\033[36m?  %s [y/N] \033[0m' "$1"
  read -r a </dev/tty 2>/dev/null || return 1
  case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ---------------------------------------------------------------------------
# 1. the network, before anything that needs it
# ---------------------------------------------------------------------------
say "checking the network"
net_ok=""
for probe in https://astral.sh https://github.com; do
  if curl -fsS -m 12 -o /dev/null "$probe" 2>/dev/null; then net_ok=1; break; fi
done

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

if [ -d "$DIR/.git" ]; then
  say "updating AgentOS in $DIR"
  git -C "$DIR" pull --ff-only || warn "could not fast-forward — keeping what is there"
else
  say "cloning AgentOS into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
say "installing dependencies (this fetches Python too, if needed)"
uv sync || die "dependency install failed — the output above says why"
ok "dependencies ready"

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
# 4. install the launcher
# ---------------------------------------------------------------------------
say "installing launcher + login service"
uv run bento install || warn "the launcher/login step reported a problem — AgentOS still runs with 'bento'"

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
# Any HTTP answer counts, including 401: a machine with accounts is locked, and
# locked is a running server, not a broken one.
listening() { [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/platform" 2>/dev/null)" != "000" ]; }

if listening; then
  ok "already serving on 127.0.0.1:${PORT}"
else
  say "starting the service"
  case "$(uname -s)" in
    Darwin) launchctl kickstart -k "gui/$(id -u)/com.agentos.server" >/dev/null 2>&1 || true ;;
    Linux)  systemctl --user start agentos >/dev/null 2>&1 || true ;;
  esac
  i=0
  while [ "$i" -lt 20 ] && ! listening; do i=$((i + 1)); sleep 1; done
  if listening; then
    ok "serving on 127.0.0.1:${PORT}"
  else
    # Not a failure of the install — step 5 already proved it runs. This is the
    # service manager, which is a different problem with a different fix.
    gap "the background service did not come up; start it yourself with: cd $DIR && uv run bento serve"
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
ok "AgentOS is running."
echo "   open:       http://127.0.0.1:${PORT}"
echo "   terminal:   bento tui          — the whole OS over SSH"
echo "   set it up:  bento setup        — the same nine steps as the desktop"
echo "   check:      bento doctor"
# On a box you reach over SSH, loopback-only is the default and it is the right
# default: the agent has a real shell, so an open port here is an open shell.
# Printed, never done — widening this is the user's decision, and it needs a
# passphrase they choose.
echo "   from your phone/laptop:  bento remote --on --passphrase '<something long>'"
if [ "$(uname -s)" = "Linux" ] && command -v sway >/dev/null 2>&1; then
  echo "   as your desktop:  bento install-session   (then pick AgentOS at login)"
fi
if [ -n "$GAPS" ]; then
  echo
  warn "working, with these gaps:"
  printf '%s\n' "$GAPS"
fi

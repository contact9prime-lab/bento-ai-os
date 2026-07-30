#!/bin/sh
# AgentOS one-command installer (Linux/macOS):
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
#   4. doctor, launcher, done.
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

say()  { printf '\033[36m▲ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!  %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗  %s\033[0m\n' "$*" >&2; exit 1; }

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
say "network is up"

command -v git >/dev/null 2>&1 || die "git is required — install it first (sudo apt install git)"

# ---------------------------------------------------------------------------
# 2. uv, the repo, the dependencies
# ---------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  say "installing uv (Python package manager)…"
  curl -fsSL https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
fi

if [ -d "$DIR/.git" ]; then
  say "updating AgentOS in $DIR"
  git -C "$DIR" pull --ff-only
else
  say "cloning AgentOS into $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone "$REPO" "$DIR"
fi

cd "$DIR"
say "installing dependencies"
uv sync

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
  uv run agentos installer --yes || true
elif [ -t 0 ]; then
  uv run agentos installer < /dev/tty || true
else
  # No terminal to ask on: report, change nothing, and say how to finish.
  uv run agentos installer < /dev/null || true
  say "run 'agentos installer' from a terminal to install what is missing"
fi

# ---------------------------------------------------------------------------
# 4. check, install the launcher, done
# ---------------------------------------------------------------------------
say "environment check"
uv run agentos doctor || true

say "installing launcher + login service"
uv run agentos install

say "done — AgentOS is at http://127.0.0.1:8321 (launch 'AgentOS' from your app menu)"
if [ "$(uname -s)" = "Linux" ] && command -v sway >/dev/null 2>&1; then
  say "to make it your desktop: agentos install-session  (then pick AgentOS at login)"
fi

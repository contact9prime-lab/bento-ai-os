#!/bin/sh
# AgentOS one-command installer (Linux/macOS):
#   curl -fsSL https://raw.githubusercontent.com/<you>/agentic-os/main/install.sh | sh
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

REPO="${AGENTOS_REPO:-https://github.com/YOUR_ORG/agentic-os.git}"
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
# 3. the desktop session (Linux only, entirely optional)
#
# AgentOS runs as a browser desktop with nothing extra. These packages are what
# turn it into a Linux SESSION you can log into, where the desktop is a real
# Wayland surface and native app windows stack above it. They belong to the
# distribution — AgentOS neither ships nor redistributes them — so they are
# offered, with what each one does, and never installed silently.
# ---------------------------------------------------------------------------
if [ "$(uname -s)" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
  # sway: the compositor engine. python3-gi + gtk-layer-shell + webkit2gtk: the
  # native desktop surface. grim/slurp: screenshots. swaylock/swayidle: locking.
  SESSION_PKGS="sway swaybg swayidle swaylock grim slurp foot"
  SUI_PKGS="python3-gi gir1.2-gtk-3.0 gir1.2-gtklayershell-0.1 gir1.2-webkit2-4.1"
  missing=""
  command -v sway >/dev/null 2>&1 || missing="$missing sway"
  if ! python3 -c 'import gi; gi.require_version("GtkLayerShell","0.1")' >/dev/null 2>&1; then
    missing="$missing layer-shell"
  fi
  if [ -n "$missing" ]; then
    echo
    say "optional: run AgentOS as your Linux desktop session"
    echo "   Two groups of distribution packages, and what they are for:"
    echo "     · sway + swaybg/swayidle/swaylock/grim  — the compositor engine, wallpaper,"
    echo "       screen lock and screenshots.                                   (MIT)"
    echo "     · python3-gi, gtk-layer-shell, webkit2gtk — draw the AgentOS desktop as a real"
    echo "       Wayland layer-shell surface, so app windows stack above it normally."
    echo "                                       (MIT; GTK and WebKitGTK are LGPL-2.1+)"
    echo "   Without them AgentOS still works — as a window on your current desktop."
    if ask "install these now?"; then
      sudo apt-get update
      # shellcheck disable=SC2086
      sudo apt-get install -y $SESSION_PKGS $SUI_PKGS
      say "session packages installed — run 'agentos install-session' to add AgentOS"
      say "to your login screen"
    else
      echo "   Later, either of:"
      echo "     sudo apt install $SESSION_PKGS"
      echo "     sudo apt install $SUI_PKGS"
      echo "   or from the desktop: System Settings → Components."
    fi
  fi
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

#!/bin/sh
# AgentOS installer wizard (Linux). Runs from inside the self-extracting .run —
# the payload (wheel, debs, LICENSE) sits in the current directory.
#
# Interactive: whiptail dialogs when available and on a TTY, plain prompts
# otherwise. Unattended: --unattended [--user|--system] [--prefix DIR]
# [--no-launcher] [--no-service] [--with-session] [--autologin] [--launch].
#
# Two wizards, two jobs: THIS one decides where AgentOS goes and how it starts
# (install location, login service, desktop session, autologin). The first time
# the desktop opens, AgentOS's own setup wizard takes over for product choices
# (agent name, model provider, autonomy).
set -u

VER="@VER@"
PAYLOAD="$(pwd)"
APP="AgentOS"

# ---------- option state (defaults) -----------------------------------------
MODE=""                 # system | user
PREFIX="${HOME}/.local/share/agentos"
OPT_LAUNCHER=1          # app-menu launcher + start at login window
OPT_SERVICE=1           # background server at login (systemd --user)
OPT_SESSION=0           # AgentOS as a login-screen session (Wayland/sway)
OPT_AUTOLOGIN=0         # boot straight into AgentOS (implies session)
OPT_LAUNCH=1            # open AgentOS when done
OPT_SYMLINK=1           # put `agentos` on PATH via ~/.local/bin
UNATTENDED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --unattended) UNATTENDED=1; OPT_LAUNCH=0 ;;
    --system) MODE=system ;;
    --user) MODE=user ;;
    --prefix) shift; PREFIX="$1" ;;
    --no-launcher) OPT_LAUNCHER=0 ;;
    --no-service) OPT_SERVICE=0 ;;
    --no-symlink) OPT_SYMLINK=0 ;;
    --with-session) OPT_SESSION=1 ;;
    --autologin) OPT_SESSION=1; OPT_AUTOLOGIN=1 ;;
    --with-deps) WITH_DEPS=1 ;;
    --launch) OPT_LAUNCH=1 ;;
    -h|--help)
      sed -n '2,9p' "$0"; exit 0 ;;
  esac
  shift
done

HAVE_WHIPTAIL=0
[ "$UNATTENDED" = 0 ] && [ -t 0 ] && [ -t 1 ] && command -v whiptail >/dev/null 2>&1 && HAVE_WHIPTAIL=1

say()  { printf '%s\n' "$*"; }
fail() { say "✗ $*"; exit 1; }

# ---------- dialog helpers (whiptail with plain fallbacks) -------------------
msg() {  # title, text
  if [ "$HAVE_WHIPTAIL" = 1 ]; then whiptail --title "$1" --msgbox "$2" 16 72
  else say ""; say "== $1 =="; say "$2"; fi
}
ask_yesno() {  # title, text, default(0=yes)
  if [ "$HAVE_WHIPTAIL" = 1 ]; then
    if [ "${3:-0}" = 0 ]; then whiptail --title "$1" --yesno "$2" 12 72
    else whiptail --title "$1" --defaultno --yesno "$2" 12 72; fi
    return $?
  fi
  def="Y/n"; [ "${3:-0}" = 1 ] && def="y/N"
  printf '%s [%s] ' "$2" "$def"; read -r ans || ans=""
  case "$ans" in
    [Yy]*) return 0 ;; [Nn]*) return 1 ;;
    *) [ "${3:-0}" = 0 ]; return $? ;;
  esac
}

# ---------- steps ------------------------------------------------------------
welcome() {
  [ "$UNATTENDED" = 1 ] && return 0
  msg "$APP $VER" \
"Welcome to the $APP installer.

$APP is your machine, with a brain: a local-first AI desktop that can also
become your login session.

This wizard decides WHERE AgentOS is installed and HOW it starts. Product
setup (your agent's name, model, autonomy) happens on first launch, in
AgentOS itself." || true
}

license_gate() {
  [ "$UNATTENDED" = 1 ] && return 0
  if [ "$HAVE_WHIPTAIL" = 1 ] && [ -f "$PAYLOAD/LICENSE" ]; then
    whiptail --title "Licence (MIT)" --scrolltext --textbox "$PAYLOAD/LICENSE" 20 74 || true
  fi
  ask_yesno "Licence" "AgentOS is MIT-licensed (full text in LICENSE). Continue?" 0 \
    || fail "cancelled at the licence step"
}

pick_mode() {
  HAS_DPKG=0; command -v dpkg >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1 && HAS_DPKG=1
  if [ -n "$MODE" ]; then
    [ "$MODE" = system ] && [ "$HAS_DPKG" = 0 ] && fail "--system needs a Debian/Ubuntu system (dpkg/apt)"
    return 0
  fi
  if [ "$UNATTENDED" = 1 ]; then MODE=user; return 0; fi
  if [ "$HAS_DPKG" = 1 ]; then
    if [ "$HAVE_WHIPTAIL" = 1 ]; then
      MODE=$(whiptail --title "Install type" --radiolist \
"How should AgentOS be installed?

  system — the .deb package: managed by apt, /usr/bin/agentos,
           available to every user. Needs sudo.
  user   — a private install in your home directory. No root
           needed; removable by deleting one folder." 18 72 2 \
        system "Debian package (recommended, needs sudo)" ON \
        user   "Just for me, in ~/.local (no root)" OFF \
        3>&1 1>&2 2>&3) || fail "cancelled"
    else
      ask_yesno "Install type" "Install system-wide as a .deb (sudo)? 'No' installs privately in ~/.local." 0 \
        && MODE=system || MODE=user
    fi
  else
    MODE=user
    msg "Install type" "This isn't a Debian/Ubuntu system, so AgentOS installs privately into your home directory (no root needed)."
  fi
}

pick_components() {
  [ "$UNATTENDED" = 1 ] && return 0
  WAYLAND_NOTE=""
  command -v sway >/dev/null 2>&1 || WAYLAND_NOTE=" (installs sway with it)"
  if [ "$HAVE_WHIPTAIL" = 1 ]; then
    SEL=$(whiptail --title "Components" --checklist \
"Pick what to set up. Everything here is reversible, and the desktop
session is purely additive — your current desktop stays untouched." 18 74 4 \
      launcher "App-menu launcher + open at login" $([ "$OPT_LAUNCHER" = 1 ] && echo ON || echo OFF) \
      service  "Background server at login (systemd --user)" $([ "$OPT_SERVICE" = 1 ] && echo ON || echo OFF) \
      session  "AgentOS at the login screen (Wayland session)$WAYLAND_NOTE" $([ "$OPT_SESSION" = 1 ] && echo ON || echo OFF) \
      autologin "Boot STRAIGHT into AgentOS (no login screen)" OFF \
      3>&1 1>&2 2>&3) || fail "cancelled"
    OPT_LAUNCHER=0; OPT_SERVICE=0; OPT_SESSION=0; OPT_AUTOLOGIN=0
    case "$SEL" in *launcher*) OPT_LAUNCHER=1 ;; esac
    case "$SEL" in *service*) OPT_SERVICE=1 ;; esac
    case "$SEL" in *session*) OPT_SESSION=1 ;; esac
    case "$SEL" in *autologin*) OPT_SESSION=1; OPT_AUTOLOGIN=1 ;; esac
  else
    ask_yesno "Components" "Add an app-menu launcher and open AgentOS at login?" 0 && OPT_LAUNCHER=1 || OPT_LAUNCHER=0
    ask_yesno "Components" "Start the AgentOS server in the background at login?" 0 && OPT_SERVICE=1 || OPT_SERVICE=0
    ask_yesno "Components" "Install the AgentOS desktop session (pick it at the login screen)?" 1 && OPT_SESSION=1 || OPT_SESSION=0
    if [ "$OPT_SESSION" = 1 ]; then
      ask_yesno "Components" "Boot STRAIGHT into AgentOS (disables the login screen; Ctrl+Alt+F3 is the escape hatch)?" 1 \
        && OPT_AUTOLOGIN=1 || OPT_AUTOLOGIN=0
    fi
  fi
  if [ "$OPT_AUTOLOGIN" = 1 ]; then
    ask_yesno "Are you sure?" \
"Boot-to-AgentOS disables your login screen and logs this user straight
into AgentOS at power-on.

The escape hatch (memorise it): Ctrl+Alt+F3 opens a raw terminal, then
  agentos install-session --remove --autologin
restores the login screen." 1 || OPT_AUTOLOGIN=0
  fi
}

# The wizard also offers what ISN'T on the system yet: each missing piece is
# listed with what it unlocks, and installs only if picked. Nothing is assumed.
DEPS_APT=""            # apt packages chosen
DEPS_SNAP=""           # snap packages chosen
DEPS_OLLAMA=0

pick_missing() {
  HAS_SUDOABLE=0
  command -v sudo >/dev/null 2>&1 && HAS_SUDOABLE=1
  # id|kind|target|default|present-check|label
  CAND="
renderer|snap|chromium|$([ "$OPT_SESSION" = 1 ] && echo ON || echo OFF)|chromium chromium-browser google-chrome google-chrome-stable brave-browser|Chromium browser — draws the AgentOS desktop & app windows
sway|apt|sway swaylock swayidle swaybg grim slurp xdg-desktop-portal-wlr|$([ "$OPT_SESSION" = 1 ] && echo ON || echo OFF)|sway|Wayland compositor stack — required by the AgentOS login session
ollama|ollama|ollama|ON|ollama|Ollama — run local AI models (recommended; cloud keys work too)
bubblewrap|apt|bubblewrap|ON|bwrap|Sandbox — confines the agent's shell to one folder
git|apt|git|ON|git|Git — the Ship pillar (repos, skills, app export)
node|apt|nodejs npm|OFF|npx|Node.js — many MCP tool servers run via npx
wmctrl|apt|wmctrl|OFF|wmctrl|X11 window control — only for hosted X11 desktops
wl-clipboard|apt|wl-clipboard|OFF|wl-copy|Clipboard bridge to native Wayland apps (GPL-3)
ddcutil|apt|ddcutil|OFF|ddcutil|External-monitor brightness over DDC/CI (GPL-2)
"
  ROWS=""; COUNT=0
  while IFS='|' read -r id kind target def check label; do
    [ -n "$id" ] || continue
    found=0
    for c in $check; do command -v "$c" >/dev/null 2>&1 && { found=1; break; }; done
    [ "$id" = sway ] && [ "$OPT_SESSION" = 0 ] && continue   # only relevant with the session
    [ "$found" = 1 ] && continue
    ROWS="$ROWS$id|$kind|$target|$def|$label
"; COUNT=$((COUNT+1))
  done <<EOF
$CAND
EOF
  [ "$COUNT" = 0 ] && return 0
  if [ "$UNATTENDED" = 1 ]; then
    [ "${WITH_DEPS:-0}" = 1 ] || return 0
    # unattended --with-deps: take the defaults
    SEL=$(printf '%s' "$ROWS" | awk -F'|' '$4=="ON"{printf "%s ",$1}')
  elif [ "$HAVE_WHIPTAIL" = 1 ]; then
    ARGS=""
    # build whiptail args safely via set --
    set --
    while IFS='|' read -r id kind target def label; do
      [ -n "$id" ] || continue
      set -- "$@" "$id" "$label" "$def"
    done <<EOF
$ROWS
EOF
    LH=$COUNT; [ "$LH" -gt 8 ] && LH=8
    SEL=$(whiptail --title "Add what's missing" --checklist \
"These useful pieces aren't on this system yet. Pick what to install
alongside AgentOS (uses sudo apt/snap; each shows what it unlocks):" 20 76 "$LH" \
      "$@" 3>&1 1>&2 2>&3) || SEL=""
  else
    SEL=""
    say ""; say "== Add what's missing =="
    while IFS='|' read -r id kind target def label; do
      [ -n "$id" ] || continue
      d=0; [ "$def" = ON ] || d=1
      ask_yesno "Missing" "Install $label?" "$d" && SEL="$SEL $id"
    done <<EOF
$ROWS
EOF
  fi
  for pick in $SEL; do
    pick=$(printf '%s' "$pick" | tr -d '"')
    line=$(printf '%s' "$ROWS" | grep "^$pick|" | head -1)
    kind=$(printf '%s' "$line" | cut -d'|' -f2)
    target=$(printf '%s' "$line" | cut -d'|' -f3)
    case "$kind" in
      apt) DEPS_APT="$DEPS_APT $target" ;;
      snap) DEPS_SNAP="$DEPS_SNAP $target" ;;
      ollama) DEPS_OLLAMA=1 ;;
    esac
  done
  if [ -n "$DEPS_APT$DEPS_SNAP" ] && [ "$HAS_SUDOABLE" = 0 ]; then
    say "! sudo isn't available — skipping system packages ($DEPS_APT$DEPS_SNAP)"
    DEPS_APT=""; DEPS_SNAP=""
  fi
}

# apt refuses to work if a previous dpkg run was interrupted (power cut,
# closed terminal mid-update…). Detect that BEFORE the first apt call and
# offer the standard one-command repair, instead of failing halfway through.
apt_preflight() {
  command -v dpkg >/dev/null 2>&1 || return 0
  if [ -n "$(ls -A /var/lib/dpkg/updates 2>/dev/null)" ]; then
    if [ "$UNATTENDED" = 1 ] || ask_yesno "Package system needs repair" \
"An earlier system update was interrupted, and apt won't install anything
until it's repaired (this is pre-existing, not caused by AgentOS).

Repair it now? Runs:  sudo dpkg --configure -a" 0; then
      say "→ repairing the package system (sudo dpkg --configure -a)…"
      sudo dpkg --configure -a || fail \
"the repair didn't complete — run 'sudo dpkg --configure -a' in a terminal,
look at its output, then run this installer again."
    else
      say "! skipping repair — package installs will likely fail"
    fi
  fi
}

install_missing() {
  if [ -n "$DEPS_APT$DEPS_SNAP" ] || [ "$MODE" = system ]; then
    apt_preflight
  fi
  if [ -n "$DEPS_APT" ]; then
    say "→ installing missing packages (sudo apt):$DEPS_APT"
    # shellcheck disable=SC2086
    sudo apt-get install -y $DEPS_APT || say "! some packages failed — continuing"
  fi
  if [ -n "$DEPS_SNAP" ]; then
    for s in $DEPS_SNAP; do
      say "→ installing $s (sudo snap)…"
      sudo snap install "$s" || say "! snap install $s failed — continuing"
    done
  fi
  if [ "$DEPS_OLLAMA" = 1 ]; then
    say "→ installing Ollama (official install script)…"
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL https://ollama.com/install.sh | sh || say "! Ollama install failed — get it at https://ollama.com/download"
    else
      say "! curl not available — get Ollama at https://ollama.com/download"
    fi
  fi
}

confirm() {
  [ "$UNATTENDED" = 1 ] && return 0
  extras=""
  [ -n "$DEPS_APT" ] && extras="$extras
  • add packages:$DEPS_APT"
  [ -n "$DEPS_SNAP" ] && extras="$extras
  • add snaps:$DEPS_SNAP"
  [ "$DEPS_OLLAMA" = 1 ] && extras="$extras
  • install Ollama (local AI models)"
  s="Install $APP $VER:

  • ${MODE} install$([ "$MODE" = user ] && printf ' → %s' "$PREFIX")
  • launcher + login window: $([ "$OPT_LAUNCHER" = 1 ] && echo yes || echo no)
  • background server at login: $([ "$OPT_SERVICE" = 1 ] && echo yes || echo no)
  • desktop session at the login screen: $([ "$OPT_SESSION" = 1 ] && echo yes || echo no)
  • boot straight into AgentOS: $([ "$OPT_AUTOLOGIN" = 1 ] && echo yes || echo no)$extras

Proceed?"
  ask_yesno "Ready" "$s" 0 || fail "cancelled"
}

# ---------- the actual install ----------------------------------------------
AGENTOS_BIN=""

install_system() {
  DEB=$(ls "$PAYLOAD"/agentos_*.deb 2>/dev/null | head -1)
  [ -n "$DEB" ] || fail "no .deb in the payload (rebuild with build-linux-installer.sh)"
  say "→ installing the AgentOS package (sudo apt)…"
  sudo apt-get install -y "$DEB" || fail \
"the package didn't install — it targets the Python it was built with.
Re-run this installer and pick the 'user' install, which adapts to your Python."
  AGENTOS_BIN="/usr/bin/agentos"
  if [ "$OPT_SESSION" = 1 ]; then
    DESK=$(ls "$PAYLOAD"/agentos-desktop_*.deb 2>/dev/null | head -1)
    if [ -n "$DESK" ]; then
      say "→ installing the desktop-session package (pulls the sway stack)…"
      sudo apt-get install -y "$DESK" || say "! desktop package failed — you can retry later with: sudo apt install $DESK"
    fi
  fi
  if [ "$OPT_SERVICE" = 1 ]; then
    systemctl --user daemon-reload 2>/dev/null || true
    systemctl --user enable --now agentos 2>/dev/null \
      || say "! could not enable the user service — run: systemctl --user enable --now agentos"
  fi
}

install_user() {
  PY=$(command -v python3 || true)
  [ -n "$PY" ] || fail "python3 is required (3.10+). Install it and re-run."
  "$PY" - <<'EOF' || fail "Python 3.10+ is required."
import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF
  WHEEL=$(ls "$PAYLOAD"/agentos-*.whl 2>/dev/null | head -1)
  [ -n "$WHEEL" ] || fail "no wheel in the payload"
  say "→ creating a private environment in $PREFIX…"
  mkdir -p "$PREFIX"
  "$PY" -m venv --clear "$PREFIX/venv" || fail "venv creation failed (install python3-venv?)"
  say "→ installing AgentOS (this can take a minute)…"
  "$PREFIX/venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$PREFIX/venv/bin/pip" install --quiet "$WHEEL" || fail "pip install failed"
  AGENTOS_BIN="$PREFIX/venv/bin/agentos"
  if [ "$OPT_SYMLINK" = 1 ]; then
    mkdir -p "$HOME/.local/bin"
    ln -sf "$PREFIX/venv/bin/agentos" "$HOME/.local/bin/agentos"
    AGENTOS_BIN="$HOME/.local/bin/agentos"
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
      say "! note: ~/.local/bin is not on your PATH — add it to use the 'agentos' command" ;;
    esac
  fi
  if [ "$OPT_LAUNCHER" = 1 ] || [ "$OPT_SERVICE" = 1 ]; then
    FLAGS=""
    [ "$OPT_SERVICE" = 1 ] || FLAGS="$FLAGS --no-service"
    [ "$OPT_LAUNCHER" = 1 ] || FLAGS="$FLAGS --no-login"
    # shellcheck disable=SC2086
    "$AGENTOS_BIN" install $FLAGS || say "! launcher/service setup reported a problem (see above)"
  fi
  if [ "$OPT_SESSION" = 1 ]; then
    command -v sway >/dev/null 2>&1 \
      || say "! the desktop session needs sway: sudo apt install sway swaylock swayidle swaybg grim slurp xdg-desktop-portal-wlr"
    "$AGENTOS_BIN" install-session || true
  fi
}

run_install() {
  if [ "$MODE" = system ]; then install_system; else install_user; fi
  if [ "$OPT_AUTOLOGIN" = 1 ]; then
    "$AGENTOS_BIN" install-session --autologin || say "! autologin setup needs another step — see above"
  elif [ "$OPT_SESSION" = 1 ] && [ "$MODE" = system ]; then
    : # the agentos-desktop deb already added the login-screen entry
  fi
}

finish() {
  say ""
  say "✓ $APP $VER installed."
  [ "$OPT_SESSION" = 1 ] && say "  • Log out and pick 'AgentOS' (gear icon) at the login screen to enter the AgentOS desktop."
  [ "$OPT_AUTOLOGIN" = 1 ] && say "  • This machine now boots into AgentOS. Escape hatch: Ctrl+Alt+F3."
  say "  • First launch opens the setup wizard (agent name, model, autonomy)."
  say "  • Command line: agentos --help · health check: agentos doctor"
  if [ "$UNATTENDED" = 0 ] && [ "$OPT_LAUNCH" = 1 ]; then
    if ask_yesno "Done" "Open AgentOS now?" 0; then
      nohup "$AGENTOS_BIN" app >/dev/null 2>&1 &
      say "  opening…"
    fi
  fi
}

WITH_DEPS="${WITH_DEPS:-0}"
welcome
license_gate
pick_mode
pick_components
pick_missing
confirm
install_missing
run_install
finish

#!/bin/bash
# AgentOS installer wizard (macOS). Runs from inside the self-extracting
# "AgentOS Installer.command" — the payload (wheel, LICENSE) sits in $PAYLOAD.
#
# Double-clicked from Finder it opens in Terminal and uses native osascript
# dialogs; run from a shell it falls back to plain prompts. Unattended:
#   --unattended [--prefix DIR] [--no-symlink] [--no-login] [--no-service]
#
# Like the Linux wizard, it prompts for what ISN'T on the system: the Python
# toolchain (macOS installs it via the Command Line Tools prompt) and Ollama.
set -u

VER="@VER@"
PAYLOAD="$(pwd)"
APP="AgentOS"

PREFIX="$HOME/Library/Application Support/AgentOS"
OPT_LOGIN=1        # open AgentOS at login + app in ~/Applications
OPT_SERVICE=1      # server LaunchAgent at login
OPT_SYMLINK=1      # /usr/local/bin/agentos (asks for admin password)
OPT_OLLAMA=1       # offer local models
OPT_LAUNCH=1
UNATTENDED=0

while [ $# -gt 0 ]; do
  case "$1" in
    --unattended) UNATTENDED=1; OPT_LAUNCH=0; OPT_OLLAMA=0; OPT_SYMLINK=0 ;;
    --prefix) shift; PREFIX="$1" ;;
    --no-symlink) OPT_SYMLINK=0 ;;
    --no-login) OPT_LOGIN=0 ;;
    --no-service) OPT_SERVICE=0 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
  esac
  shift
done

GUI=0
[ "$UNATTENDED" = 0 ] && command -v osascript >/dev/null 2>&1 && GUI=1

say() { printf '%s\n' "$*"; }
fail() { say "✗ $*"; [ "$GUI" = 1 ] && osascript -e "display dialog \"$*\" with title \"$APP installer\" buttons {\"OK\"} with icon stop" >/dev/null 2>&1; exit 1; }

ask() {  # text, default-yes(0)/no(1) -> 0 yes
  if [ "$GUI" = 1 ]; then
    d="Yes"; [ "${2:-0}" = 1 ] && d="No"
    r=$(osascript -e "button returned of (display dialog \"$1\" with title \"$APP installer\" buttons {\"No\",\"Yes\"} default button \"$d\")" 2>/dev/null) || return 1
    [ "$r" = "Yes" ]
  else
    def="Y/n"; [ "${2:-0}" = 1 ] && def="y/N"
    printf '%s [%s] ' "$1" "$def"; read -r ans || ans=""
    case "$ans" in [Yy]*) return 0 ;; [Nn]*) return 1 ;; *) [ "${2:-0}" = 0 ] ;; esac
  fi
}
note() {
  if [ "$GUI" = 1 ]; then
    osascript -e "display dialog \"$1\" with title \"$APP installer\" buttons {\"Continue\"} default button \"Continue\"" >/dev/null 2>&1 || exit 1
  else
    say ""; say "$1"
  fi
}

# ---------- wizard -----------------------------------------------------------
if [ "$UNATTENDED" = 0 ]; then
  note "Welcome to $APP $VER.

$APP is your machine, with a brain — a local-first AI desktop.

This wizard decides where $APP goes and how it starts. Product setup (your agent's name, model, autonomy) happens on first launch, inside $APP."
  ask "$APP is MIT-licensed (full text in the LICENSE file next to this installer). Agree and continue?" 0 \
    || fail "cancelled at the licence step"
fi

# --- Python: prompt for what's not there ------------------------------------
PY=""
find_python() {
  for c in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
      PY="$c"; return 0
    fi
  done
  return 1
}
if ! find_python; then
  if xcode-select -p >/dev/null 2>&1; then
    fail "Python 3.10+ not found. Install it (https://www.python.org/downloads/ or 'brew install python') and run this installer again."
  fi
  note "$APP needs Python, which macOS provides through the Command Line Tools.

macOS will now show its own install prompt — click Install there, wait for it to finish, then run this installer again."
  xcode-select --install >/dev/null 2>&1 || true
  fail "waiting for the Command Line Tools — run the installer again once they're in"
fi

# --- options -----------------------------------------------------------------
if [ "$UNATTENDED" = 0 ]; then
  ask "Open $APP automatically when you log in? (an app bundle goes in ~/Applications, and the server starts in the background)" 0 \
    && { OPT_LOGIN=1; OPT_SERVICE=1; } || { OPT_LOGIN=0; OPT_SERVICE=0; }
  ask "Add the 'agentos' command to /usr/local/bin? (asks for your admin password)" 0 \
    && OPT_SYMLINK=1 || OPT_SYMLINK=0
  if ! command -v ollama >/dev/null 2>&1; then
    ask "Install Ollama to run AI models locally? (recommended — $APP also works with cloud API keys)" 0 \
      && OPT_OLLAMA=1 || OPT_OLLAMA=0
  else
    OPT_OLLAMA=0
  fi
fi

# --- install -----------------------------------------------------------------
say "→ creating a private environment in $PREFIX…"
mkdir -p "$PREFIX"
"$PY" -m venv --clear "$PREFIX/venv" || fail "could not create the Python environment"
say "→ installing $APP (a minute or two)…"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip >/dev/null 2>&1 || true
WHEEL=$(ls "$PAYLOAD"/agentos-*.whl | head -1)
"$PREFIX/venv/bin/pip" install --quiet "$WHEEL" || fail "pip install failed"
AGENTOS="$PREFIX/venv/bin/agentos"

if [ "$OPT_LOGIN" = 1 ] || [ "$OPT_SERVICE" = 1 ]; then
  FLAGS=""
  [ "$OPT_SERVICE" = 1 ] || FLAGS="$FLAGS --no-service"
  [ "$OPT_LOGIN" = 1 ] || FLAGS="$FLAGS --no-login"
  # shellcheck disable=SC2086
  "$AGENTOS" install $FLAGS || say "! app bundle / login setup reported a problem"
fi

if [ "$OPT_SYMLINK" = 1 ]; then
  if sudo -p "Password (to add /usr/local/bin/agentos): " mkdir -p /usr/local/bin \
     && sudo ln -sf "$AGENTOS" /usr/local/bin/agentos; then
    say "✓ command installed: agentos"
  else
    say "! skipped /usr/local/bin symlink — use $AGENTOS directly"
  fi
fi

if [ "$OPT_OLLAMA" = 1 ]; then
  if command -v brew >/dev/null 2>&1; then
    say "→ installing Ollama (brew)…"
    brew install --quiet ollama || say "! brew install ollama failed — get it at https://ollama.com/download"
  else
    say "→ opening the Ollama download page…"
    open "https://ollama.com/download/mac" 2>/dev/null || say "  get it at https://ollama.com/download"
  fi
fi

say ""
say "✓ $APP $VER installed."
say "  • First launch opens the setup wizard (agent name, model, autonomy)."
say "  • Health check any time: $([ "$OPT_SYMLINK" = 1 ] && echo agentos || echo "$AGENTOS") doctor"
if [ "$UNATTENDED" = 0 ] && [ "$OPT_LAUNCH" = 1 ]; then
  if ask "Open $APP now?" 0; then
    nohup "$AGENTOS" app >/dev/null 2>&1 &
    say "  opening…"
  fi
fi

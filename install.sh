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
# Flags:
#   --yes                     answer yes to every optional install
#   --passphrase=SECRET       also make it reachable from your network (binds
#                             0.0.0.0 and requires that passphrase to sign in).
#                             Without this it listens on 127.0.0.1 only.
#   --no-service              do not install the launcher/login service (containers, CI)
#   --no-verify               skip the "prove it works" step
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

for a in "$@"; do
  case "$a" in
    --yes|-y) ASSUME_YES=1 ;;
    --no-verify) VERIFY=0 ;;
    --no-service) SERVICE=0 ;;
    --passphrase=*) PASSPHRASE="${a#--passphrase=}" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
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
say "installing dependencies (this fetches Python too, if needed)"
uv sync || die "dependency install failed — the output above says why"
ok "dependencies ready"

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
for cmd in bento agentos; do
  cat > "$BIN/$cmd" <<SHIM
#!/bin/sh
# Installed by AgentOS's install.sh. Safe to delete; re-run the installer to restore.
exec uv run --project "$DIR" $cmd "\$@"
SHIM
  chmod +x "$BIN/$cmd"
done
say "installed the 'bento' command (and 'agentos') in $BIN"

# On PATH for the shell that will run them next? `command -v` answers for THIS
# shell, which curl|bash gave us; the rc file is what answers for the next one.
case ":$PATH:" in
  *":$BIN:"*) ON_PATH=1 ;;
  *) ON_PATH="" ;;
esac
if [ -z "$ON_PATH" ]; then
  # Appended, and said out loud. A PATH line added silently to somebody's shell is
  # the kind of thing they should be able to find later — hence the marker comment.
  added=""
  for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
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
    gap "open a new terminal (or \`. ~/.bashrc\`) before \`bento\` works in this one"
  else
    gap "add this to your shell profile:  export PATH=\"\$HOME/.local/bin:\$PATH\""
  fi
  # This script's own remaining steps must not depend on the rc file it just wrote.
  PATH="$BIN:$PATH"; export PATH
fi

# ---------------------------------------------------------------------------
# 3c. reachable from elsewhere, if that was asked for.
#
# Before the launcher, so the service that starts below comes up already bound to
# 0.0.0.0 rather than binding to loopback and needing a restart to move.
# ---------------------------------------------------------------------------
if [ -n "$PASSPHRASE" ]; then
  say "turning on remote access (binding 0.0.0.0)"
  if uv run bento remote --on --passphrase "$PASSPHRASE" --bind 0.0.0.0 >/dev/null 2>&1; then
    ok "reachable from your network — sign in with that passphrase"
    gap "this machine now answers on every interface. If it faces the internet, put it behind a tunnel or a firewall."
  else
    # Never a silent half-state: refusing is usually the passphrase being too short,
    # and leaving it on loopback is the safe outcome to report.
    warn "could not enable remote access — still loopback only"
    gap "set it yourself:  bento remote --on --passphrase '<something long>'"
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
# Any HTTP answer counts, including 401: a machine with accounts is locked, and
# locked is a running server, not a broken one.
listening() { [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/api/platform" 2>/dev/null)" != "000" ]; }

if [ "$SERVICE" = 0 ]; then
  say "not started (--no-service) — run it with: cd $DIR && uv run bento serve"
elif listening; then
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
if [ "$SERVICE" = 1 ]; then
  ok "AgentOS is running."
else
  ok "AgentOS is installed (nothing was started — --no-service)."
fi
echo "   open:       http://127.0.0.1:${PORT}"
echo "   terminal:   bento tui          — the whole OS over SSH"
echo "   set it up:  bento setup        — the same nine steps as the desktop"
echo "   check:      bento doctor"
# On a box you reach over SSH, loopback-only is the default and it is the right
# default: the agent has a real shell, so an open port here is an open shell.
# Printed, never done — widening this is the user's decision, and it needs a
# passphrase they choose.
echo "   from your phone/laptop:  bento remote --on --passphrase '<something long>'"
# `session_capable`, not `command -v sway`. The old test asked whether a
# compositor happened to be installed, so a Linux box that had simply not been
# offered one yet was told nothing — the option existed and was never mentioned.
# Whether the OS can host a login session at all is a different question, and it
# is the one `osdetect` answers.
if [ -n "$OS_SESSION" ]; then
  echo "   as your desktop:  bento install-session   (then pick AgentOS at login)"
fi
if [ -n "$GAPS" ]; then
  echo
  warn "working, with these gaps:"
  printf '%s\n' "$GAPS"
fi

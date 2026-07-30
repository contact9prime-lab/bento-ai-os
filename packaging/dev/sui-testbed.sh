#!/bin/sh
# Bring up a complete AgentOS session (SUI) on a headless compositor, for
# development and for verifying session-mode behaviour without a monitor.
#
#   sui-testbed.sh up      start sway + server + layer-shell shell host
#   sui-testbed.sh status  what is running, and what the compositor sees
#   sui-testbed.sh shot F  capture the whole output to F (grim)
#   sui-testbed.sh app CMD launch a native app the way AgentOS does
#   sui-testbed.sh down    stop everything
#
# This is the same code path a real login uses; only the compositor backend
# differs (headless + software rendering instead of a GPU and a screen). That is
# what makes it a fair test of stacking order, struts and window management.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)
RT=${SUI_RUNTIME:-/tmp/agentos-sui}
PORT=${AGENTOS_PORT:-8321}
LOGS=$RT/logs
MODE=${SUI_MODE:-1600x900}

export XDG_RUNTIME_DIR=$RT/xdg
export WLR_BACKENDS=${WLR_BACKENDS:-headless}
export WLR_RENDERER=${WLR_RENDERER:-pixman}
export LIBSEAT_BACKEND=${LIBSEAT_BACKEND:-noop}
export WAYLAND_DISPLAY=wayland-1
export AGENTOS_SESSION=1
export AGENTOS_PORT=$PORT
export GDK_BACKEND=wayland
# Deliberately NOT setting WEBKIT_DISABLE_COMPOSITING_MODE or
# WEBKIT_DISABLE_DMABUF_RENDERER. They are the folklore fix for WebKitGTK on
# software rendering and they are what actually crashed it here: with WebKit's
# own defaults the desktop renders, and with either of those set the UI process
# segfaults on the first frame. Left as a note so nobody "fixes" it back.

sock() { ls "$XDG_RUNTIME_DIR"/sway-ipc.*.sock 2>/dev/null | head -1; }

case ${1:-up} in
up)
  mkdir -p "$XDG_RUNTIME_DIR" "$LOGS"; chmod 700 "$XDG_RUNTIME_DIR"
  # A stale socket from a dead compositor looks exactly like a live one and
  # every client then fails with "no display" — clear them first.
  pkill -x sway 2>/dev/null || true
  pkill -f 'shellhost.p[y]' 2>/dev/null || true
  pkill -f 'bin/agent[o]s serve' 2>/dev/null || true
  sleep 1
  rm -f "$XDG_RUNTIME_DIR"/sway-ipc.*.sock "$XDG_RUNTIME_DIR"/wayland-* 2>/dev/null || true

  printf 'output * bg #0b0d10 solid_color\ndefault_border normal 2\nfor_window [title=".*"] floating enable\n' \
    > "$RT/sway.conf"
  sway -c "$RT/sway.conf" > "$LOGS/sway.log" 2>&1 &
  i=0; while [ $i -lt 40 ] && [ -z "$(sock)" ]; do i=$((i+1)); sleep 0.25; done
  [ -n "$(sock)" ] || { echo "sway did not start; see $LOGS/sway.log" >&2; exit 1; }
  SWAYSOCK=$(sock); export SWAYSOCK
  swaymsg "output * mode $MODE" >/dev/null 2>&1 || true
  echo "sway      $SWAYSOCK ($MODE)"

  HOME=${SUI_HOME:-$RT/home}; export HOME; mkdir -p "$HOME"
  "$ROOT/.venv/bin/agentos" serve --no-browser --port "$PORT" > "$LOGS/server.log" 2>&1 &
  i=0; while [ $i -lt 80 ] && ! curl -sf -o /dev/null "http://127.0.0.1:$PORT/"; do i=$((i+1)); sleep 0.25; done
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/" || { echo "server did not start; see $LOGS/server.log" >&2; exit 1; }
  echo "server    http://127.0.0.1:$PORT ($(curl -sf "http://127.0.0.1:$PORT/api/platform" | sed -n 's/.*"mode":"\([a-z]*\)".*/mode=\1/p'))"

  PY=$("$ROOT/.venv/bin/python" -c "import sys; sys.path.insert(0,'$ROOT'); from agentos.shellhost import python_with_gi; print(python_with_gi()[0])")
  [ -n "$PY" ] || { echo "no python with PyGObject/gtk-layer-shell/WebKitGTK" >&2; exit 1; }
  "$PY" "$ROOT/agentos/shellhost.py" --port "$PORT" --top 30 --bottom 132 \
    > "$LOGS/shellhost.log" 2>&1 &
  sleep 8
  pgrep -f 'shellhost.p[y]' >/dev/null || { echo "shell host died; see $LOGS/shellhost.log" >&2; tail -5 "$LOGS/shellhost.log" >&2; exit 1; }
  echo "shell     $(sed -n '/shell-host:/s/.*shell-host: //p' "$LOGS/shellhost.log" | head -1)"
  echo "ready — logs in $LOGS"
  ;;

status)
  SWAYSOCK=$(sock); export SWAYSOCK
  [ -n "$SWAYSOCK" ] && echo "sway: running" || echo "sway: DOWN"
  pgrep -f 'shellhost.p[y]' >/dev/null && echo "shell host: running" || echo "shell host: DOWN"
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && echo "server: up" || echo "server: DOWN"
  echo "--- windows the compositor knows about (the desktop is NOT one) ---"
  curl -sf "http://127.0.0.1:$PORT/api/windows" || true
  echo
  ;;

shot)
  grim "${2:-$RT/shot.png}" && echo "wrote ${2:-$RT/shot.png}"
  ;;

app)
  shift
  SWAYSOCK=$(sock); export SWAYSOCK
  curl -sf -X POST -H 'Content-Type: application/json' \
    -d "{\"command\":\"$*\"}" "http://127.0.0.1:$PORT/api/native/run" || \
    swaymsg exec -- "$@"
  ;;

down)
  pkill -f 'shellhost.p[y]' 2>/dev/null || true
  pkill -f 'bin/agent[o]s serve' 2>/dev/null || true
  pkill -x sway 2>/dev/null || true
  echo "stopped"
  ;;

*) echo "usage: $0 {up|status|shot [file]|app CMD|down}" >&2; exit 2 ;;
esac

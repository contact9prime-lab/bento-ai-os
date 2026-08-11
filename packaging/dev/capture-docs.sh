#!/bin/sh
# Photograph the documented flows against a real machine, from nothing.
#
# The arc starts at "this machine has never been set up", and there is no way
# back to that state except a home directory that did not exist a moment ago —
# which is why this owns the whole lifecycle rather than expecting a server to
# already be running. Point it at a throwaway home; it deletes that home.
#
#   packaging/dev/capture-docs.sh [HOME_DIR] [PORT]
set -e
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HOME_DIR=${1:-/tmp/agentos-doc-shots}
PORT=${2:-8899}
PY="$ROOT/.venv/bin/python"

echo "▲ rebuilding $HOME_DIR"
rm -rf "$HOME_DIR"
mkdir -p "$HOME_DIR"

# Rebuild the bundle first: photographing a stale index.html documents the
# previous version of the UI, which is worse than no screenshot at all.
"$PY" -m agentos.ui.build

AGENTOS_HOME="$HOME_DIR" "$ROOT/.venv/bin/agentos" serve --port "$PORT" \
  > "$HOME_DIR/serve.log" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null || true' EXIT INT TERM

i=0
while [ $i -lt 40 ]; do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break
  i=$((i + 1)); sleep 1
done
if [ $i -ge 40 ]; then echo "server did not come up"; tail -20 "$HOME_DIR/serve.log"; exit 1; fi

"$PY" "$ROOT/packaging/dev/capture-docs.py" --port "$PORT" --out "$ROOT/docs/screenshots"

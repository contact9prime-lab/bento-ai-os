#!/bin/sh
# Cloud standby, end to end: a laptop (this checkout, as a process) and a cloud (the real
# Docker image) paired, then every way the work changes hands, with every table of every
# database compared after each one. See docs/standby.md → "How it was tested".
#
#   packaging/dev/standby-e2e/run.sh            # all phases, about 15 minutes
#   packaging/dev/standby-e2e/run.sh p4_move    # one phase (they build on each other)
#
# Needs: Docker, root (the split phase cuts the network with iptables), and this
# checkout's .venv. It writes to $STANDBY_E2E_DIR (default /tmp/bento-standby-e2e) and
# removes its containers at the end of the accounts phase; nothing touches ~/.agentos.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../../.." && pwd)
PY="$REPO/.venv/bin/python"
IMAGE="${STANDBY_E2E_IMAGE:-bento-standby-test}"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "▲ building $IMAGE from this checkout"
  docker build -t "$IMAGE" "$REPO"
fi
"$PY" "$HERE/fakes.py" > "${STANDBY_E2E_DIR:-/tmp/bento-standby-e2e}.fakes.log" 2>&1 &
FAKES=$!
trap 'kill $FAKES 2>/dev/null || true' EXIT
sleep 2
PHASES="${*:-p0_setup p1_pair p2_takeover p2b p3_back p4_move p5_sleep p6_split p7_restarts p8_accounts}"
for p in $PHASES; do
  echo "===== $p"
  (cd "$HERE" && "$PY" "$p.py")
done

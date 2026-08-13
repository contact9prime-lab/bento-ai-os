#!/bin/sh
# What has to happen between `docker run` and a server somebody can reach.
#
# Exactly one thing, and it is a security decision rather than a setup step:
# AgentOS refuses to listen on anything but loopback until remote access is
# explicitly turned on with a passphrase. That refusal is right — the agent has a
# real shell, so an open port is an open shell — but in a container loopback means
# "reachable by nothing", because the port you publish is on the host's side of a
# network namespace the server cannot see.
#
# So a container MUST bind 0.0.0.0, which means it must have a passphrase. This
# script's whole job is to make that a stated requirement with a way to satisfy it,
# instead of a `serve` that exits 4 with a message about a Settings panel nobody
# can open yet.
set -e

PORT="${AGENTOS_PORT:-8321}"

say()  { printf '\033[36m▲ %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# A file first: `docker inspect` shows every environment variable, so a passphrase
# passed as -e is readable by anyone who can talk to the daemon. The _FILE form is
# what docker/podman secrets mount, and it is the one to prefer.
if [ -n "${AGENTOS_PASSPHRASE_FILE:-}" ]; then
  [ -r "$AGENTOS_PASSPHRASE_FILE" ] || die "AGENTOS_PASSPHRASE_FILE is set but not readable: $AGENTOS_PASSPHRASE_FILE"
  AGENTOS_PASSPHRASE="$(cat "$AGENTOS_PASSPHRASE_FILE")"
fi

# Already configured on the volume — a restart must not need the secret again, and
# must not silently reset it either.
already=$(uv run python -c 'from agentos import config as c; print("1" if (c.load_config().get("remote") or {}).get("enabled") else "")' 2>/dev/null || true)

if [ -n "${AGENTOS_PASSPHRASE:-}" ]; then
  say "enabling remote access"
  # Idempotent: run it every start so rotating the secret is just a restart.
  uv run bento remote --on --passphrase "$AGENTOS_PASSPHRASE" >/dev/null \
    || die "could not enable remote access — the passphrase may be too short"
elif [ -n "$already" ]; then
  say "remote access already configured on this volume"
else
  echo >&2
  echo "AgentOS will not listen on a published port without a passphrase." >&2
  echo "The agent has a real shell, so an open port here is an open shell." >&2
  echo >&2
  echo "  docker run -d -p 8321:8321 -v bento-data:/data \\" >&2
  echo "    -e AGENTOS_PASSPHRASE='something long and unguessable' bento" >&2
  echo >&2
  echo "or, keeping it out of \`docker inspect\`:" >&2
  echo "  -e AGENTOS_PASSPHRASE_FILE=/run/secrets/bento_pass" >&2
  echo >&2
  echo "To run it truly locally instead, publish nothing and exec into it:" >&2
  echo "  docker run -d --name bento -v bento-data:/data -e AGENTOS_LOOPBACK=1 bento" >&2
  echo >&2
  die "refusing to start unreachable, rather than starting insecure"
fi

# The escape hatch, stated rather than hidden: bound to loopback the server is
# reachable only from inside the container (`docker exec … bento tui`). Useful for
# a scheduled job that never needs a browser, and it needs no passphrase because
# nothing outside can reach it.
HOST=0.0.0.0
[ -n "${AGENTOS_LOOPBACK:-}" ] && HOST=127.0.0.1

say "starting AgentOS on ${HOST}:${PORT}"
# exec, so signals reach the server and `docker stop` is a clean shutdown rather
# than a ten-second wait and a kill.
exec uv run bento serve --host "$HOST" --port "$PORT" --no-browser "$@"

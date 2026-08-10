#!/usr/bin/env bash
# Re-probe every curated MCP server for real.
#
# tests/test_mcp_catalog.py is deliberately offline — a unit test that failed because
# Canva was having an outage would tell you nothing about this code. But the catalogue
# makes two claims about the outside world that CAN rot without anyone noticing:
#
#   1. the endpoint is still an MCP server that answers `initialize`
#   2. it still supports Dynamic Client Registration, which is what makes it one click
#
# This checks both. Run it when an entry is suspected of having gone bad, and before
# adding a new one — an entry that fails (2) does not belong in the catalogue at all.
#
#   packaging/dev/probe-catalog.sh
#
set -uo pipefail
cd "$(dirname "$0")/../.."

PY=${PY:-.venv/bin/python}
[ -x "$PY" ] || PY=python3

mapfile -t ROWS < <("$PY" - <<'EOF'
from agentos import mcp_catalog
for c in mcp_catalog.all_candidates():
    print(f"{c['key']}\t{c['remote_url']}")
EOF
)

fail=0
printf '%-12s %-38s %-6s %s\n' SERVER ENDPOINT MCP DCR
for row in "${ROWS[@]}"; do
  key=${row%%$'\t'*}; url=${row##*$'\t'}
  origin=$(printf '%s' "$url" | sed -E 's#(https://[^/]+).*#\1#')

  # (1) an MCP server answers initialize — 401 is the CORRECT answer here, because
  # these are all OAuth-protected. A 404/000 means the endpoint moved or died.
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 20 -X POST "$url" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"agentos-probe","version":"1"}}}' 2>/dev/null)
  case "$code" in 200|401|403) mcp_ok="$code" ;; *) mcp_ok="$code ✗"; fail=1 ;; esac

  # (2) DCR, discovered the way the SDK discovers it
  as=$(curl -s -m 20 "$origin/.well-known/oauth-protected-resource/mcp" 2>/dev/null \
       | "$PY" -c 'import json,sys;print((json.load(sys.stdin).get("authorization_servers") or [""])[0])' 2>/dev/null)
  [ -z "$as" ] && as="$origin"
  reg=$(curl -s -m 20 "$as/.well-known/oauth-authorization-server" 2>/dev/null \
        | "$PY" -c 'import json,sys;print(json.load(sys.stdin).get("registration_endpoint") or "")' 2>/dev/null)
  [ -z "$reg" ] && reg=$(curl -s -m 20 "$as/.well-known/openid-configuration" 2>/dev/null \
        | "$PY" -c 'import json,sys;print(json.load(sys.stdin).get("registration_endpoint") or "")' 2>/dev/null)
  if [ -n "$reg" ]; then dcr="yes"; else dcr="NO ✗"; fail=1; fi

  printf '%-12s %-38s %-6s %s\n' "$key" "$url" "$mcp_ok" "$dcr"
done

if [ "$fail" -ne 0 ]; then
  echo
  echo "At least one entry no longer holds. An endpoint that moved should be corrected;"
  echo "one that dropped DCR should be REMOVED — it can no longer be one click, and"
  echo "leaving it on screen is the dead control the catalogue exists to avoid."
  exit 1
fi
echo
echo "All curated entries hold."

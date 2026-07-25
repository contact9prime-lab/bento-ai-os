#!/usr/bin/env bash
# Build the Windows installer: AgentOS-Setup-<version>-windows-x64.exe
#
# Cross-compiled from Linux with NSIS (`sudo apt install nsis`). The result is
# a normal Windows setup wizard: Welcome → Licence → Components (Start Menu,
# desktop shortcut, run-at-login, Ollama) → Directory → Install → Finish.
# At install time, bootstrap.ps1 finds or installs Python on the target PC.
#
#   ./packaging/build-windows-installer.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DIST="$HERE/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"

if ! command -v makensis >/dev/null 2>&1; then
  echo "✗ makensis not found — the Windows installer is cross-built with NSIS."
  echo "  Install it and re-run:  sudo apt install nsis"
  exit 2
fi

echo "▲ Building the Windows installer  version=$VER"
(cd "$REPO" && uv build --wheel >/dev/null 2>&1)
WHEEL="$REPO/dist/agentos-$VER-py3-none-any.whl"
[ -f "$WHEEL" ] || { echo "✗ wheel build failed"; exit 1; }
mkdir -p "$DIST"

makensis -V2 -DVERSION="$VER" -DWHEEL="$WHEEL" -DOUTDIR="$DIST" \
  "$HERE/windows/agentos.nsi"

OUT="$DIST/AgentOS-Setup-${VER}-windows-x64.exe"
echo ""
echo "✓ Built $(du -h "$OUT" | cut -f1)  →  $OUT"
echo "  Unsigned — Windows SmartScreen will warn until the exe is code-signed."

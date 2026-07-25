#!/usr/bin/env bash
# Build every AgentOS distributable this machine can produce.
#
#   ./packaging/build-all.sh
#
# From Linux:  wheel, both .debs, the Linux .run installer, the macOS .command
# installer, and (with `sudo apt install nsis`) the Windows setup.exe.
# The macOS .pkg needs a Mac: packaging/macos/build-macos-pkg.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"

BUILT=""
SKIPPED=""

step() {  # name, script
  echo ""
  if "$2"; then BUILT="$BUILT\n  ✓ $1"
  else SKIPPED="$SKIPPED\n  – $1  ($3)"; fi
}

echo "▲ AgentOS $VER — building all distributables"
step "agentos .deb (Linux system package)" "$HERE/build-deb.sh" ""
step "agentos-desktop .deb (login session)" "$HERE/build-desktop-deb.sh" ""
step "Linux installer (.run, wizard)" "$HERE/build-linux-installer.sh" ""
step "macOS installer (.command, wizard)" "$HERE/build-macos-command.sh" ""
step "Windows installer (setup.exe, wizard)" "$HERE/build-windows-installer.sh" "needs: sudo apt install nsis"

echo ""
echo "──────────────────────────────────────────────"
echo -e "Built:$BUILT"
[ -n "$SKIPPED" ] && echo -e "Skipped:$SKIPPED"
echo ""
echo "Needs a Mac: packaging/macos/build-macos-pkg.sh  → AgentOS-$VER.pkg"
echo "Artifacts in: $HERE/dist/"
ls -lh "$HERE/dist/" | tail -n +2 | awk '{printf "  %-8s %s\n", $5, $NF}'

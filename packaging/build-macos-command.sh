#!/usr/bin/env bash
# Build the macOS installer: "AgentOS Installer.command"
#
# A double-clickable, self-extracting installer buildable from any OS: Finder
# opens it in Terminal, and the wizard talks through native osascript dialogs
# (licence, login/autostart, CLI on PATH, Ollama). If Python is missing it
# routes through Apple's own Command Line Tools prompt. The heavier .pkg with
# an installer-app choices wizard is packaging/macos/build-macos-pkg.sh, which
# must run on a Mac.
#
#   ./packaging/build-macos-command.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DIST="$HERE/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "▲ Building the macOS .command installer  version=$VER"
(cd "$REPO" && uv build --wheel >/dev/null 2>&1)
cp "$REPO/dist/agentos-$VER-py3-none-any.whl" "$STAGE/"
cp "$REPO/LICENSE" "$STAGE/"
sed "s/@VER@/$VER/g" "$HERE/macos-installer-wizard.sh" > "$STAGE/installer.sh"
chmod 755 "$STAGE/installer.sh"

mkdir -p "$DIST"
OUT="$DIST/AgentOS-Installer-${VER}.command"

cat > "$OUT" <<'HDR'
#!/bin/bash
# AgentOS installer for macOS — double-click me.
set -u
TMP="$(mktemp -d "${TMPDIR:-/tmp}/agentos-installer.XXXXXX")" || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM
SKIP=$(awk '/^__PAYLOAD__$/ {print NR + 1; exit 0}' "$0")
tail -n +"$SKIP" "$0" | tar xzf - -C "$TMP" 2>/dev/null || {
  echo "✗ could not unpack the installer (corrupt download?)"; read -r -p "press return"; exit 1; }
cd "$TMP" || exit 1
exec /bin/bash ./installer.sh "$@"
__PAYLOAD__
HDR
tar czf - -C "$STAGE" . >> "$OUT"
chmod 755 "$OUT"

echo ""
echo "✓ Built $(du -h "$OUT" | cut -f1)  →  $OUT"
echo "  Double-click it in Finder (right-click → Open the first time: it's unsigned),"
echo "  or run:  bash '$OUT'"

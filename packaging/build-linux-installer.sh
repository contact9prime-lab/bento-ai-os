#!/usr/bin/env bash
# Build the Linux installer: AgentOS-Setup-<version>-linux-x86_64.run
#
# A self-extracting shell archive (NVIDIA-installer style, no makeself needed):
# a POSIX header + a tar.gz payload holding the wheel, both .debs, the LICENCE
# and the wizard. Running it extracts to a temp dir and starts the wizard —
# whiptail dialogs interactively, or `--unattended` for scripting/CI.
#
#   ./packaging/build-linux-installer.sh
#   sh packaging/dist/AgentOS-Setup-<version>-linux-x86_64.run
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
DIST="$HERE/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

echo "▲ Building the Linux installer  version=$VER"

echo "  → wheel"
(cd "$REPO" && uv build --wheel >/dev/null 2>&1)
cp "$REPO"/dist/agentos-"$VER"-py3-none-any.whl "$STAGE/"

echo "  → debs (system-install path)"
[ -f "$DIST/agentos_${VER}_amd64.deb" ] || "$HERE/build-deb.sh" >/dev/null
[ -f "$DIST/agentos-desktop_${VER}_all.deb" ] || "$HERE/build-desktop-deb.sh" >/dev/null
cp "$DIST/agentos_${VER}_amd64.deb" "$DIST/agentos-desktop_${VER}_all.deb" "$STAGE/"

sed "s/@VER@/$VER/g" "$HERE/linux-installer-wizard.sh" > "$STAGE/installer.sh"
chmod 755 "$STAGE/installer.sh"
cp "$REPO/LICENSE" "$STAGE/"

OUT="$DIST/AgentOS-Setup-${VER}-linux-x86_64.run"
mkdir -p "$DIST"

# Header: everything before __PAYLOAD__ is the extractor; everything after is
# the tar.gz. `tail -n +N | tar xz` needs only POSIX sh + tar.
cat > "$OUT" <<'HDR'
#!/bin/sh
# AgentOS installer — self-extracting archive. Run it; add --unattended for
# scripting (see --help). Built by packaging/build-linux-installer.sh.
set -u
TMP="${TMPDIR:-/tmp}/agentos-installer.$$"
mkdir -p "$TMP" || exit 1
trap 'rm -rf "$TMP"' EXIT INT TERM
SKIP=$(awk '/^__PAYLOAD__$/ {print NR + 1; exit 0}' "$0")
tail -n +"$SKIP" "$0" | tar xzf - -C "$TMP" 2>/dev/null || {
  echo "✗ could not unpack the installer (corrupt download?)"; exit 1; }
cd "$TMP" || exit 1
exec sh ./installer.sh "$@"
__PAYLOAD__
HDR
tar czf - -C "$STAGE" . >> "$OUT"
chmod 755 "$OUT"

echo ""
echo "✓ Built $(du -h "$OUT" | cut -f1)  →  $OUT"
echo "  Interactive:  sh $OUT"
echo "  Unattended:   sh $OUT --unattended --user [--prefix DIR] [--with-deps] [--with-session]"

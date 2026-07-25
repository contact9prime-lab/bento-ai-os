#!/bin/bash
# Build the macOS .pkg installer — RUN THIS ON A MAC (needs pkgbuild/productbuild).
#
# Produces AgentOS-<version>.pkg: the native macOS installer app with a choices
# wizard — Welcome → Licence → "AgentOS core" (required) + "Open at login"
# (optional) → Install. The core payload lands in /Library/AgentOS and the
# postinstall script builds the venv and links /usr/local/bin/agentos; the
# login choice installs per-user LaunchAgents for the console user.
#
# For a signed, notarised pkg add:  --sign "Developer ID Installer: …"
# and notarise the result with `xcrun notarytool`.
#
#   ./packaging/macos/build-macos-pkg.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
DIST="$REPO/packaging/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"

command -v pkgbuild >/dev/null 2>&1 || { echo "✗ pkgbuild not found — run this on macOS"; exit 2; }

echo "▲ Building AgentOS-$VER.pkg"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# --- wheel ------------------------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  (cd "$REPO" && uv build --wheel >/dev/null)
else
  (cd "$REPO" && python3 -m pip wheel --no-deps -w dist . >/dev/null)
fi
WHEEL="$REPO/dist/agentos-$VER-py3-none-any.whl"
[ -f "$WHEEL" ] || { echo "✗ wheel build failed"; exit 1; }

# --- core component: /Library/AgentOS + postinstall -------------------------
mkdir -p "$STAGE/root/Library/AgentOS" "$STAGE/scripts-core"
cp "$WHEEL" "$STAGE/root/Library/AgentOS/"
cp "$REPO/LICENSE" "$STAGE/root/Library/AgentOS/"

cat > "$STAGE/scripts-core/postinstall" <<'EOF'
#!/bin/bash
# AgentOS core postinstall: build the venv, link the CLI.
set -e
cd /Library/AgentOS
PY=""
for c in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  [ -x "$c" ] || continue
  if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "AgentOS: Python 3.10+ not found. Install the Command Line Tools" \
       "(xcode-select --install) or python.org Python, then run:" \
       "  sudo /Library/AgentOS/repair.sh" >&2
  cp /dev/null /Library/AgentOS/.needs-python
  exit 0    # don't fail the whole install — repair.sh finishes the job
fi
"$PY" -m venv --clear venv
./venv/bin/pip install --quiet ./agentos-*.whl
mkdir -p /usr/local/bin
ln -sf /Library/AgentOS/venv/bin/agentos /usr/local/bin/agentos
rm -f /Library/AgentOS/.needs-python
exit 0
EOF
cat > "$STAGE/root/Library/AgentOS/repair.sh" <<'EOF'
#!/bin/bash
# Finish/repair the AgentOS install (e.g. after installing Python).
exec /bin/bash /Library/AgentOS/.postinstall-rerun 2>/dev/null || {
  cd /Library/AgentOS && python3 -m venv --clear venv && \
  ./venv/bin/pip install ./agentos-*.whl && \
  ln -sf /Library/AgentOS/venv/bin/agentos /usr/local/bin/agentos && \
  echo "✓ AgentOS ready — run: agentos app"; }
EOF
chmod 755 "$STAGE/scripts-core/postinstall" "$STAGE/root/Library/AgentOS/repair.sh"

pkgbuild --root "$STAGE/root" \
         --scripts "$STAGE/scripts-core" \
         --identifier com.agentos.core --version "$VER" \
         --install-location / \
         "$STAGE/agentos-core.pkg" >/dev/null

# --- login component: LaunchAgents for the console user ---------------------
mkdir -p "$STAGE/scripts-login"
cat > "$STAGE/scripts-login/postinstall" <<'EOF'
#!/bin/bash
# "Open at login": run `agentos install` as the person sitting at the machine.
set -e
CONSOLE_USER=$(stat -f%Su /dev/console)
[ -n "$CONSOLE_USER" ] && [ "$CONSOLE_USER" != root ] || exit 0
[ -x /Library/AgentOS/venv/bin/agentos ] || exit 0
sudo -u "$CONSOLE_USER" /Library/AgentOS/venv/bin/agentos install || true
exit 0
EOF
chmod 755 "$STAGE/scripts-login/postinstall"
pkgbuild --nopayload \
         --scripts "$STAGE/scripts-login" \
         --identifier com.agentos.loginitems --version "$VER" \
         "$STAGE/agentos-login.pkg" >/dev/null

# --- the product: choices wizard --------------------------------------------
cat > "$STAGE/distribution.xml" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>AgentOS $VER</title>
  <license file="LICENSE"/>
  <welcome file="welcome.html"/>
  <options customize="always" require-scripts="false" rootVolumeOnly="true"/>
  <choices-outline>
    <line choice="core"/>
    <line choice="login"/>
  </choices-outline>
  <choice id="core" title="AgentOS core" enabled="false" selected="true"
          description="The AgentOS application in /Library/AgentOS with the 'agentos' command. Needs Python 3.10+ (macOS offers to install it if missing).">
    <pkg-ref id="com.agentos.core"/>
  </choice>
  <choice id="login" title="Open AgentOS at login" selected="true"
          description="Start the AgentOS server in the background and open the desktop when you log in. You can turn this off later with 'agentos uninstall'.">
    <pkg-ref id="com.agentos.loginitems"/>
  </choice>
  <pkg-ref id="com.agentos.core" version="$VER">agentos-core.pkg</pkg-ref>
  <pkg-ref id="com.agentos.loginitems" version="$VER">agentos-login.pkg</pkg-ref>
</installer-gui-script>
EOF
cat > "$STAGE/welcome.html" <<'EOF'
<html><body style="font-family:-apple-system">
<h2>AgentOS — your machine, with a brain</h2>
<p>A local-first AI desktop. This installer decides where AgentOS goes and how
it starts; product setup (your agent's name, model, autonomy) happens on first
launch, inside AgentOS.</p>
<p>If Python isn't on this Mac yet, the installer will tell you how to add it
with one command.</p>
</body></html>
EOF
cp "$REPO/LICENSE" "$STAGE/LICENSE"

mkdir -p "$DIST"
productbuild --distribution "$STAGE/distribution.xml" \
             --resources "$STAGE" \
             --package-path "$STAGE" \
             "$DIST/AgentOS-$VER.pkg"

echo ""
echo "✓ Built $DIST/AgentOS-$VER.pkg"
echo "  Unsigned — right-click → Open, or sign with a Developer ID for Gatekeeper."

#!/usr/bin/env bash
# Build a self-contained AgentOS .deb (bundles the app + a Python venv with all deps).
# Targets the build machine's Python (currently 3.13 / Ubuntu 25.10). Run from anywhere.
#
#   ./packaging/build-deb.sh
#   sudo dpkg -i packaging/dist/agentos_<version>_amd64.deb
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build"
DIST="$HERE/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"
PYVER="$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

echo "▲ Building AgentOS .deb  version=$VER  python=$PYVER"
rm -rf "$BUILD" "$DIST"
mkdir -p "$BUILD/DEBIAN" "$BUILD/opt/agentos" "$BUILD/usr/bin" \
         "$BUILD/usr/share/applications" "$BUILD/usr/share/icons/hicolor/scalable/apps" \
         "$BUILD/usr/lib/systemd/user" "$BUILD/usr/share/doc/agentos" "$DIST"

echo "  → bundling a venv with all dependencies"
uv venv "$BUILD/opt/agentos/venv" --python "$PYVER" >/dev/null
uv pip install --python "$BUILD/opt/agentos/venv/bin/python" "$REPO" >/dev/null
# drop caches to shrink the package
find "$BUILD/opt/agentos/venv" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "  → launcher, desktop entry, service, icon"
cat > "$BUILD/usr/bin/agentos" <<'EOF'
#!/bin/sh
# AgentOS launcher — runs the bundled venv's python
exec /opt/agentos/venv/bin/python -m agentos "$@"
EOF
chmod 755 "$BUILD/usr/bin/agentos"

cat > "$BUILD/usr/share/applications/agentos.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=AgentOS
GenericName=Agentic OS
Comment=Your machine, with a brain
Exec=/usr/bin/agentos app
Icon=agentos
Terminal=false
Categories=Utility;System;
StartupWMClass=agentos
Keywords=agent;ai;assistant;automation;
EOF

cat > "$BUILD/usr/lib/systemd/user/agentos.service" <<'EOF'
[Unit]
Description=AgentOS server (your machine, with a brain)
After=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
ExecStart=/usr/bin/agentos serve --no-browser
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF

cat > "$BUILD/usr/share/icons/hicolor/scalable/apps/agentos.svg" <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#5eead4"/><stop offset="1" stop-color="#22d3ee"/>
</linearGradient></defs>
<rect width="128" height="128" rx="28" fill="#0b0d10"/>
<rect x="4" y="4" width="120" height="120" rx="24" fill="none" stroke="url(#g)" stroke-width="2" opacity=".35"/>
<path d="M64 26 L102 96 L26 96 Z" fill="url(#g)"/>
<path d="M64 47 L86 88 L42 88 Z" fill="#0b0d10"/>
</svg>
EOF

cp "$REPO/README.md" "$BUILD/usr/share/doc/agentos/README.md"
cp "$REPO/LICENSE" "$BUILD/usr/share/doc/agentos/LICENSE"
cp "$REPO/THIRD_PARTY_NOTICES.md" "$BUILD/usr/share/doc/agentos/THIRD_PARTY_NOTICES.md"

INSTALLED="$(du -sk "$BUILD/usr" "$BUILD/opt" | awk '{s+=$1} END {print s}')"
cat > "$BUILD/DEBIAN/control" <<EOF
Package: agentos
Version: $VER
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= $PYVER), python3 (<< $(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor+1}")'))
Recommends: bubblewrap, xdg-utils
Suggests: ollama, nodejs, git
Installed-Size: $INSTALLED
Maintainer: AgentOS <contact@localhost>
Description: AgentOS — your machine, with a brain
 A local-first agentic operating system: a full desktop environment in the
 browser, driven by an AI agent that takes real actions on your computer.
 Local (Ollama) or cloud models, with your approval. Includes a windowed
 desktop, terminal, file manager, app builder, scheduler, Telegram bridge,
 MCP tool servers, and more.
 .
 After install, run 'agentos app' or launch AgentOS from your menu. To start
 it automatically at login, run: systemctl --user enable --now agentos
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
echo ""
echo "  ▲ AgentOS installed."
echo "    Launch:            agentos app   (or find AgentOS in your app menu)"
echo "    Start at login:    systemctl --user enable --now agentos"
echo "    Then open:         http://127.0.0.1:8321"
echo ""
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst"

cat > "$BUILD/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
systemctl --user stop agentos.service 2>/dev/null || true
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/prerm"

DEB="$DIST/agentos_${VER}_amd64.deb"
echo "  → assembling $DEB"
fakeroot dpkg-deb --build --root-owner-group "$BUILD" "$DEB" >/dev/null

echo ""
echo "✓ Built $(du -h "$DEB" | cut -f1)  →  $DEB"
echo "  Install with:  sudo dpkg -i $DEB"
echo "  (Note: this package targets Python $PYVER; build on the target's Python for other versions.)"

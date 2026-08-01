#!/usr/bin/env bash
# Build agentos-desktop — the package that makes AgentOS a desktop environment.
#
# A thin, ADDITIVE metapackage layered on the agentos .deb: it adds a Wayland
# session entry next to Ubuntu's at the login screen and pulls in the
# permissive-only compositor stack (sway/wlroots, MIT). It does NOT touch the
# display manager, the default session, or any GNOME configuration — installing
# it changes nothing until the user picks AgentOS at the login screen.
#
# The dependency set is gated by audit-licenses.sh: everything in Depends must
# be permissively licensed (GPL daemons we merely talk to over D-Bus are
# Recommends and come from the distro, never from us).
#
# The native desktop surface — gtk-layer-shell, GTK and WebKitGTK — is in
# SUGGESTS, deliberately, even though it is what makes AgentOS a desktop rather
# than a window (the shell goes on the BACKGROUND layer, so application windows
# are above it in normal stacking order and the chrome bands are reserved as
# exclusive zones).
#
# The reason is the rule this package is built on: what we DEPEND on, we are
# effectively distributing, and that stays permissive. gtk-layer-shell is MIT but
# GTK, PyGObject and WebKitGTK are LGPL-2.1+. Recommends would not fix it —
# apt installs Recommends by default, which is the same thing with a softer name.
#
# So they are asked for instead, three times over, with the licences in view:
# install.sh offers them, `agentos install-session` prints the exact apt line if
# they are missing, and System Settings -> Components lists them as the
# "session-ui" entry. Without them the session still runs, drawing the desktop in
# a Chromium window and faking the stacking order.
#
# wayvnc (ISC) and novnc (MPL-2.0) are Suggests for the same reason: they add the
# browser Remote Desktop, and AgentOS only ever binds them to loopback.
#
#   ./packaging/build-desktop-deb.sh
#   sudo dpkg -i packaging/dist/agentos-desktop_<version>_all.deb
#
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BUILD="$HERE/build-desktop"
DIST="$HERE/dist"
VER="$(grep -m1 '^version' "$REPO/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')"

echo "▲ Building agentos-desktop .deb  version=$VER"

echo "  → licence & availability gate"
"$HERE/audit-licenses.sh" >/dev/null || {
  echo "✗ the dependency set failed the licence gate — fix that before packaging."
  "$HERE/audit-licenses.sh"
  exit 1
}

rm -rf "$BUILD"
mkdir -p "$BUILD/DEBIAN" "$BUILD/usr/share/wayland-sessions" \
         "$BUILD/usr/libexec" "$BUILD/usr/share/doc/agentos-desktop" "$DIST"

# The session entry. Its Exec target regenerates the logging-in user's session
# files (sway config, shell launcher) and execs sway — so ANY user on the
# machine can pick AgentOS with zero prior setup.
cat > "$BUILD/usr/share/wayland-sessions/agentos.desktop" <<'EOF'
[Desktop Entry]
Name=AgentOS
Comment=AgentOS — your machine, with a brain
Exec=/usr/libexec/agentos-session
Type=Application
DesktopNames=AgentOS
Keywords=agent;ai;
EOF

cat > "$BUILD/usr/libexec/agentos-session" <<'EOF'
#!/bin/sh
# AgentOS Wayland session — thin Exec shim; the real work is in
# `agentos session run` (agentos/session.py), which stages the user's session
# files and execs sway.
exec /usr/bin/agentos session run
EOF
chmod 755 "$BUILD/usr/libexec/agentos-session"

cp "$REPO/THIRD_PARTY_NOTICES.md" "$BUILD/usr/share/doc/agentos-desktop/"
cp "$REPO/LICENSE" "$BUILD/usr/share/doc/agentos-desktop/"

cat > "$BUILD/DEBIAN/control" <<EOF
Package: agentos-desktop
Version: $VER
Section: x11
Priority: optional
Architecture: all
Depends: agentos (>= $VER), sway, xwayland, swaylock, swayidle, swaybg, grim, slurp, xdg-desktop-portal-wlr, pipewire, wireplumber
Recommends: seatd, network-manager, bluez, upower, power-profiles-daemon
Suggests: python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-gtklayershell-0.1, gir1.2-webkit2-4.1 | gir1.2-webkit-6.0, wl-clipboard, ddcutil, chromium, wayvnc, novnc
Installed-Size: 32
Maintainer: AgentOS <contact@localhost>
Description: AgentOS as your desktop environment (Wayland session)
 Adds an "AgentOS" session to the login screen: a Wayland desktop where
 AgentOS is the shell — its own window management (sway/wlroots engine),
 settings, notifications, and lock screen.
 .
 Purely additive: your existing desktop, display manager and default session
 are untouched. Pick AgentOS at the login screen to enter it; log out and
 pick Ubuntu to leave. For boot-to-AgentOS (no login screen), see
 'agentos install-session --autologin'.
 .
 Every hard dependency of this package is permissively licensed (MIT/BSD).
 The system daemons it talks to over D-Bus (NetworkManager, BlueZ, UPower)
 are recommended, not bundled.
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
echo ""
echo "  ▲ AgentOS desktop session installed."
echo "    Nothing about your current desktop has changed."
echo "    Log out and pick 'AgentOS' (gear icon) at the login screen to enter it."
echo "    A chromium-family browser renders the shell — if none is installed:"
echo "      sudo snap install chromium"
echo ""
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst"

DEB="$DIST/agentos-desktop_${VER}_all.deb"
echo "  → assembling $DEB"
fakeroot dpkg-deb --build --root-owner-group "$BUILD" "$DEB" >/dev/null

echo ""
echo "✓ Built $(du -h "$DEB" | cut -f1)  →  $DEB"
echo "  Install with:  sudo apt install $DEB   (pulls the sway stack from the archive)"

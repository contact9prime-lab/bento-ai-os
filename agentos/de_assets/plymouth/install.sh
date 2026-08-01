#!/bin/sh
# Install the AgentOS plymouth boot theme. Run as root (the components flow
# invokes it via sudo/pkexec after explicit user consent).
#
# This is the one place AgentOS replaces the DISTRIBUTION's branding on a
# machine — the Ubuntu (or Fedora, or Debian) boot splash stops being shown.
# Doing that locally, with consent, is entirely legitimate: it is the user's
# computer and their own choice of theme. Two things follow from it anyway.
#
#   1. It must be reversible, and it was not. This script used to call
#      `plymouth-set-default-theme -R agentos` without recording what had been
#      the default, so "put it back the way it was" had no answer — the user had
#      to already know their distro's theme name. The previous theme is now
#      saved before anything changes, and uninstall.sh restores it.
#
#   2. Replacing a distro's splash on your own machine is NOT the same as
#      redistributing a modified distro. If an AgentOS image is ever built on
#      top of Ubuntu, Canonical's trademarks (the name, the logo) may not travel
#      with it without permission — code being free to modify does not make the
#      marks free to reuse. See docs/licensing.md.
set -e
SRC="$(dirname "$(readlink -f "$0")")"
DST=/usr/share/plymouth/themes/agentos
STATE=/var/lib/agentos
mkdir -p "$DST" "$STATE"
cp "$SRC/agentos.plymouth" "$SRC/agentos.script" "$SRC/logo.png" "$SRC/bar.png" "$SRC/glow.png" "$DST/"

# Remember the theme being displaced, before displacing it. Written only once,
# so re-running the installer can never overwrite the true original with
# "agentos" and strand the user on our theme forever.
if [ ! -f "$STATE/plymouth-previous-theme" ]; then
  prev=""
  if command -v plymouth-set-default-theme >/dev/null 2>&1; then
    prev="$(plymouth-set-default-theme 2>/dev/null || true)"
  fi
  if [ -n "$prev" ] && [ "$prev" != "agentos" ]; then
    printf '%s\n' "$prev" > "$STATE/plymouth-previous-theme"
  fi
fi

if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  plymouth-set-default-theme -R agentos
elif command -v update-alternatives >/dev/null 2>&1; then
  update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$DST/agentos.plymouth" 200
  update-alternatives --set default.plymouth "$DST/agentos.plymouth"
  command -v update-initramfs >/dev/null 2>&1 && update-initramfs -u
fi
echo "AgentOS boot theme installed."
if [ -f "$STATE/plymouth-previous-theme" ]; then
  echo "Previous theme was '$(cat "$STATE/plymouth-previous-theme")'. Restore it with:"
  echo "  sudo sh $SRC/uninstall.sh"
fi

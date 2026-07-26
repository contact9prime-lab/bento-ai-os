#!/bin/sh
# Install the AgentOS plymouth boot theme. Run as root (the components flow
# invokes it via sudo/pkexec after explicit user consent).
set -e
SRC="$(dirname "$(readlink -f "$0")")"
DST=/usr/share/plymouth/themes/agentos
mkdir -p "$DST"
cp "$SRC/agentos.plymouth" "$SRC/agentos.script" "$SRC/logo.png" "$SRC/bar.png" "$SRC/glow.png" "$DST/"
if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  plymouth-set-default-theme -R agentos
elif command -v update-alternatives >/dev/null 2>&1; then
  update-alternatives --install /usr/share/plymouth/themes/default.plymouth default.plymouth "$DST/agentos.plymouth" 200
  update-alternatives --set default.plymouth "$DST/agentos.plymouth"
  command -v update-initramfs >/dev/null 2>&1 && update-initramfs -u
fi
echo "AgentOS boot theme installed."

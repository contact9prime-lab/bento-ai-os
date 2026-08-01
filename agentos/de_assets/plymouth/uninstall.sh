#!/bin/sh
# Put the distribution's boot splash back. Run as root.
#
# The counterpart to install.sh. It exists because AgentOS replacing a distro's
# branding on someone's machine must be a decision they can take back, and
# "reversible in principle" is not reversible if nobody recorded what was there
# before. install.sh saves the displaced theme name; this restores it.
set -e
STATE=/var/lib/agentos
PREV_FILE="$STATE/plymouth-previous-theme"
DST=/usr/share/plymouth/themes/agentos

prev=""
[ -f "$PREV_FILE" ] && prev="$(cat "$PREV_FILE")"

if [ -z "$prev" ]; then
  # Nothing recorded: either the theme was never installed by us, or it was
  # installed by a version that did not record. Guess nothing — a wrong theme
  # name here produces an unbootable-looking splash and is worse than saying so.
  echo "No previous plymouth theme was recorded, so there is nothing to restore to."
  echo "Pick one yourself with:  sudo plymouth-set-default-theme -l"
  echo "then:                    sudo plymouth-set-default-theme -R <name>"
  exit 1
fi

if command -v plymouth-set-default-theme >/dev/null 2>&1; then
  plymouth-set-default-theme -R "$prev"
elif command -v update-alternatives >/dev/null 2>&1; then
  update-alternatives --remove default.plymouth "$DST/agentos.plymouth" || true
  command -v update-initramfs >/dev/null 2>&1 && update-initramfs -u
fi

rm -f "$PREV_FILE"
rm -rf "$DST"
echo "Restored the '$prev' boot theme."

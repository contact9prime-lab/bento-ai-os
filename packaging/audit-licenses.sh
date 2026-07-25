#!/usr/bin/env bash
# Licence & availability gate for the AgentOS desktop package.
#
# AgentOS ships permissively. Everything in SHIPPED becomes a hard `Depends:` of
# agentos-desktop, so each one must (a) exist in the archive and (b) carry a
# permissive primary licence. Anything that fails is not shipped — it moves to
# agentos/components.py and becomes a user-consented optional download instead.
#
# INTERFACE packages are system daemons we only *speak to* over D-Bus. They are
# never bundled and never a hard dependency, so their licence does not constrain
# us; they are listed here so the report is honest about what the desktop talks to.
#
#   ./packaging/audit-licenses.sh                 # report, exit 1 on any FAIL
#   ./packaging/audit-licenses.sh --write-notices # also update THIRD_PARTY_NOTICES.md
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
EXCEPTIONS="$REPO/packaging/licence-exceptions.txt"
NOTICES="$REPO/THIRD_PARTY_NOTICES.md"
BEGIN_MARK="<!-- BEGIN GENERATED: apt dependencies (packaging/audit-licenses.sh) -->"
END_MARK="<!-- END GENERATED -->"

# Hard Depends: of agentos-desktop. Must be permissive.
SHIPPED=(
  sway xwayland seatd
  swaylock swayidle swaybg
  grim slurp
  xdg-desktop-portal-wlr
  pipewire wireplumber
)

# Spoken to over D-Bus. Recommends: only — never bundled, licence unconstrained.
# xdg-desktop-portal is LGPL-2.1+ and arrives as a dependency of the MIT
# xdg-desktop-portal-wlr backend; it is an unmodified distro build of a separate
# daemon, so it is listed here rather than pretended into the shipped set.
INTERFACE=(
  network-manager bluez upower xdg-desktop-portal
)

PERMISSIVE_RE='^(MIT([-_]0)?|Expat|Apache([-_ ]?2(\.0)?)?|BSD([-_ ]?[23][-_ ]?clause)?|ISC|X11|Zlib|zlib\/libpng|CC0([-_ ]?1\.0)?|public[-_ ]domain|FSFAP|Unlicense|WTFPL|BSL[-_ ]?1\.0)'
COPYLEFT_RE='(^|[^A-Za-z])(A?GPL|LGPL|MPL|CDDL|EPL|CPL|OSL|GFDL|SISSL|CC[-_ ]?BY[-_ ]?SA|QPL|Sleepycat)'

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
[ -t 1 ] || { RED=""; GRN=""; YEL=""; DIM=""; RST=""; }

WRITE_NOTICES=0
[ "${1:-}" = "--write-notices" ] && WRITE_NOTICES=1

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

is_excepted() {
  [ -f "$EXCEPTIONS" ] || return 1
  grep -qE "^[[:space:]]*$1[[:space:]]*\|" "$EXCEPTIONS"
}

# Locate a package's copyright file: installed copy first, else fetch the .deb.
copyright_file() {
  local pkg="$1" local_copy="/usr/share/doc/$1/copyright" out="$TMP/$1.copyright"
  if [ -f "$local_copy" ]; then printf '%s' "$local_copy"; return 0; fi
  [ -f "$out" ] && { printf '%s' "$out"; return 0; }
  (
    cd "$TMP"
    apt-get download "$pkg" >/dev/null 2>&1 || exit 1
    deb=$(ls -1 "${pkg}"_*.deb 2>/dev/null | head -1) || exit 1
    [ -n "$deb" ] || exit 1
    # copyright may live under the binary package name or its source name
    dpkg-deb --fsys-tarfile "$deb" 2>/dev/null \
      | tar -xO --wildcards '*/copyright' 2>/dev/null
  ) > "$out" 2>/dev/null || true
  [ -s "$out" ] || return 1
  printf '%s' "$out"
}

# DEP-5 convention puts the catch-all `Files: *` paragraph first, so the first
# License: after the first Files: is the package's primary licence. Matching the
# bare `Files: *` line is not enough — DEP-5 allows folded fields, where the
# value sits on continuation lines (xdg-desktop-portal does this, and matching
# loosely reported its third paragraph and turned an LGPL package into a PASS).
primary_licence() {
  awk '
    /^Files:/ { inblk=1; next }
    inblk && /^License:/ { sub(/^License:[[:space:]]*/,""); if ($0!="") { print; exit } }
  ' "$1" | head -1
}

# Not every package uses DEP-5. X.Org ships a 90KB free-form copyright with no
# machine-readable fields at all, so fall back to recognising licence grants by
# their text. Deliberately conservative: any copyleft grant in a free-form file
# yields an unrecognised token, which routes to human REVIEW rather than PASS.
freeform_licence() {
  local f="$1" mit x11 bsd apache gpl
  mit=$(grep -ci 'permission is hereby granted, free of charge' "$f" || true)
  x11=$(grep -ci 'permission to use, copy, modify, distribute, and sell this software' "$f" || true)
  bsd=$(grep -ci 'redistribution and use in source and binary forms' "$f" || true)
  apache=$(grep -ci 'licensed under the apache license' "$f" || true)
  gpl=$(grep -ci 'gnu \(general\|lesser\|library\) public license' "$f" || true)
  if [ "$gpl" -gt 0 ]; then echo "free-form, contains GPL grants ($gpl)"; return; fi
  if [ $((mit + x11)) -gt 0 ] && [ $((mit + x11)) -ge "$bsd" ] && [ $((mit + x11)) -ge "$apache" ]; then
    echo "MIT/X11 (free-form)"; return
  fi
  [ "$bsd" -gt 0 ] && { echo "BSD (free-form)"; return; }
  [ "$apache" -gt 0 ] && { echo "Apache-2.0 (free-form)"; return; }
  echo ""
}

all_licences() {
  awk '/^License:/ { sub(/^License:[[:space:]]*/,""); if ($0!="") print }' "$1" \
    | sed 's/[[:space:]]*$//' | sort -u | head -20
}

classify() {  # licence token -> PERMISSIVE | COPYLEFT | UNKNOWN
  local l="$1"
  if printf '%s' "$l" | grep -qiE "$COPYLEFT_RE"; then echo COPYLEFT
  elif printf '%s' "$l" | grep -qiE "$PERMISSIVE_RE"; then echo PERMISSIVE
  else echo UNKNOWN; fi
}

fails=0; reviews=0
declare -a ROWS=()

audit() {
  local pkg="$1" role="$2" candidate installed cf primary verdict others note=""

  candidate=$(apt-cache policy "$pkg" 2>/dev/null | awk -F': ' '/Candidate:/{print $2}')
  installed=$(apt-cache policy "$pkg" 2>/dev/null | awk -F': ' '/Installed:/{print $2}')
  if [ -z "$candidate" ] || [ "$candidate" = "(none)" ]; then
    printf '%s  %-24s %sNOT IN ARCHIVE%s  — cannot be a dependency\n' "✗" "$pkg" "$RED" "$RST"
    ROWS+=("$pkg|(unavailable)|—|NOT IN ARCHIVE")
    [ "$role" = shipped ] && fails=$((fails+1))
    return
  fi

  if ! cf=$(copyright_file "$pkg"); then
    printf '%s  %-24s %sNO COPYRIGHT FILE%s (candidate %s) — needs manual review\n' \
      "?" "$pkg" "$YEL" "$RST" "$candidate"
    ROWS+=("$pkg|$candidate|unknown|UNVERIFIED")
    reviews=$((reviews+1))
    return
  fi

  primary=$(primary_licence "$cf")
  [ -n "$primary" ] || primary=$(all_licences "$cf" | head -1)
  [ -n "$primary" ] || primary=$(freeform_licence "$cf")
  [ -n "$primary" ] || primary="unknown"
  others=$(all_licences "$cf" | grep -vxF "$primary" | paste -sd', ' - || true)
  verdict=$(classify "$primary")

  if [ "$role" = interface ]; then
    printf '%s  %-24s %-28s %sinterface only — not bundled%s\n' \
      "·" "$pkg" "$primary" "$DIM" "$RST"
    ROWS+=("$pkg|$candidate|$primary|interface only (D-Bus), not shipped")
    return
  fi

  case "$verdict" in
    PERMISSIVE)
      printf '%s  %-24s %-28s %sPASS%s  %s%s%s\n' "✓" "$pkg" "$primary" "$GRN" "$RST" \
        "$DIM" "${installed:+installed $installed}" "$RST"
      ROWS+=("$pkg|$candidate|$primary|shipped (Depends)")
      ;;
    COPYLEFT)
      if is_excepted "$pkg"; then
        note=$(grep -E "^[[:space:]]*$pkg[[:space:]]*\|" "$EXCEPTIONS" | head -1 | cut -d'|' -f2- | sed 's/^ *//')
        printf '%s  %-24s %-28s %sREVIEWED%s %s\n' "!" "$pkg" "$primary" "$YEL" "$RST" "$note"
        ROWS+=("$pkg|$candidate|$primary|reviewed exception — $note")
        reviews=$((reviews+1))
      else
        printf '%s  %-24s %-28s %sFAIL%s  copyleft primary licence — move to components.py\n' \
          "✗" "$pkg" "$primary" "$RED" "$RST"
        ROWS+=("$pkg|$candidate|$primary|FAIL — not shippable")
        fails=$((fails+1))
      fi
      ;;
    *)
      printf '%s  %-24s %-28s %sREVIEW%s unrecognised licence token\n' \
        "?" "$pkg" "$primary" "$YEL" "$RST"
      ROWS+=("$pkg|$candidate|$primary|needs review")
      reviews=$((reviews+1))
      ;;
  esac
  [ -n "$others" ] && printf '   %salso present: %s%s\n' "$DIM" "$others" "$RST"
  return 0
}

echo
echo "AgentOS desktop — licence & availability gate"
echo "─────────────────────────────────────────────────────────────────────────"
echo "Shipped (hard Depends — must be permissive):"
for p in "${SHIPPED[@]}"; do audit "$p" shipped; done
echo
echo "Interface only (Recommends — spoken to over D-Bus, never bundled):"
for p in "${INTERFACE[@]}"; do audit "$p" interface; done
echo "─────────────────────────────────────────────────────────────────────────"

if [ "$WRITE_NOTICES" = 1 ]; then
  {
    echo "$BEGIN_MARK"
    echo
    echo "## Debian/Ubuntu packages (agentos-desktop)"
    echo
    echo "The \`agentos-desktop\` package depends on the components below. They are"
    echo "installed from the distribution's own archive — AgentOS does not bundle,"
    echo "modify or redistribute them. Generated by \`packaging/audit-licenses.sh\`."
    echo
    echo "| Package | Version | Licence | Role |"
    echo "|---|---|---|---|"
    for r in "${ROWS[@]}"; do
      IFS='|' read -r a b c d <<<"$r"
      echo "| $a | $b | $c | $d |"
    done
    echo
    echo "$END_MARK"
  } > "$TMP/notices.md"

  if grep -qF "$BEGIN_MARK" "$NOTICES"; then
    awk -v b="$BEGIN_MARK" -v e="$END_MARK" -v f="$TMP/notices.md" '
      index($0,b){ while ((getline l < f) > 0) print l; skip=1; next }
      index($0,e){ skip=0; next }
      !skip
    ' "$NOTICES" > "$TMP/out.md"
  else
    cat "$NOTICES" "$TMP/notices.md" > "$TMP/out.md"
  fi
  mv "$TMP/out.md" "$NOTICES"
  echo "✓ wrote generated section into ${NOTICES#"$REPO"/}"
fi

echo
if [ "$fails" -gt 0 ]; then
  echo "${RED}✗ $fails package(s) cannot be shipped.${RST} Move them to agentos/components.py"
  echo "  as user-consented optional downloads, or record a reviewed exception in"
  echo "  ${EXCEPTIONS#"$REPO"/} as:  <package> | <why it is acceptable>"
  exit 1
fi
[ "$reviews" -gt 0 ] && echo "${YEL}! $reviews package(s) need a human decision.${RST}"
echo "${GRN}✓ shipped dependency set is permissive.${RST}"

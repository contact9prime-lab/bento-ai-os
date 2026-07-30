"""Trademarks, which a licence audit does not cover.

`packaging/audit-licenses.sh` gates what AgentOS may *ship*, by licence. That is
a different obligation from what AgentOS may *call itself*, by trademark — and a
permissive licence grants none of the latter. Ubuntu's code being free to modify
does not make the word "Ubuntu" or its logo free to put on a product.

These tests hold the line that docs/licensing.md describes: AgentOS names other
systems only to say true things about them, never as its own branding, and it
does not redistribute a distribution.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Marks belonging to somebody else. Naming these in prose or in an install
#: command is nominative use and entirely fine — "runs on Ubuntu" is a fact.
#: Putting one in a field that says what THIS product *is* would not be.
FOREIGN_MARKS = ("ubuntu", "canonical", "debian", "fedora", "red hat", "redhat",
                 "arch linux", "opensuse", "suse", "windows", "macos")

#: The fields that answer "what is this product called". A trademark here reads
#: as branding or endorsement, not as a reference.
IDENTITY_PATTERNS = (
    ("agentos/session.py", "Name="),                    # the .desktop entry
    ("packaging/build-desktop-deb.sh", "Package:"),
    ("packaging/build-desktop-deb.sh", "Maintainer:"),
    ("packaging/build-deb.sh", "Package:"),
    ("packaging/build-deb.sh", "Maintainer:"),
)


def _identity_values(rel: str, key: str) -> list[str]:
    path = REPO / rel
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip().lstrip('"\'f')
        if s.startswith(key):
            out.append(s[len(key):].strip().strip('"\','))
    return out


@pytest.mark.parametrize("rel,key", IDENTITY_PATTERNS)
def test_product_identity_carries_no_foreign_trademark(rel, key):
    """What AgentOS calls itself must be its own name.

    "AgentOS runs on Ubuntu" is a true statement about a real thing. An
    `Name=Ubuntu AgentOS` in a .desktop file, or a Debian `Package:` naming
    another vendor, is brand use that implies endorsement — the exact line
    Canonical's IP policy draws.
    """
    for value in _identity_values(rel, key):
        low = value.lower()
        for mark in FOREIGN_MARKS:
            assert mark not in low, (
                f"{rel} {key!r} is {value!r}, which carries the trademark "
                f"{mark!r}. Identity fields must use AgentOS's own name.")


def test_agentos_still_ships_no_distribution_image():
    """The trademark question changes completely the day this stops being true.

    While AgentOS is an installer, the distro packages are fetched by the user's
    own package manager from their own archive and AgentOS is not a party to the
    transfer. Build an ISO from Ubuntu and you are redistributing a modified
    Ubuntu, at which point its marks may not travel with it. If this test fails,
    that has happened — read docs/licensing.md before deleting it.
    """
    builders = " ".join(
        p.read_text(errors="replace")
        for p in (REPO / "packaging").rglob("*.sh") if p.is_file())
    for tool in ("debootstrap", "live-build", "mkosi", "xorriso", "genisoimage"):
        assert tool not in builders, (
            f"packaging/ now uses {tool!r} — AgentOS appears to build a distribution "
            f"image. Trademark obligations change; see docs/licensing.md.")


def test_the_licence_is_present_and_is_the_one_we_claim():
    text = (REPO / "LICENSE").read_text()
    assert "MIT License" in text
    assert (REPO / "docs" / "licensing.md").is_file(), (
        "the licensing position must stay written down, not folklore")


def test_replacing_distro_branding_is_reversible():
    """The one place AgentOS overwrites a distribution's branding.

    Doing it locally with consent is fine. Doing it without recording what was
    replaced is not: "restore my distro's boot splash" then has no answer, and
    the user has to already know their distro's theme name.
    """
    plymouth = REPO / "agentos" / "de_assets" / "plymouth"
    install = (plymouth / "install.sh").read_text()
    assert "plymouth-previous-theme" in install, (
        "install.sh must record the theme it displaces")
    uninstall = plymouth / "uninstall.sh"
    assert uninstall.is_file(), "there must be a way back to the distro's splash"
    assert "plymouth-previous-theme" in uninstall.read_text()


# NOTE: there is deliberately no "copyleft is not in Depends" test here.
#
# There was one, and it was wrong twice over. It matched package names by
# substring, so `xdg-desktop-portal` (LGPL-2.1+, Recommends, spoken to over
# D-Bus) matched inside `xdg-desktop-portal-wlr` (Expat, a legitimate Depends).
# And it read a catalogue entry's licence string — which describes a GROUP of
# packages, "MIT and LGPL-2.1+" — as though it applied to each package in that
# group. It reported a violation that did not exist.
#
# `packaging/audit-licenses.sh` already gates exactly this, per package, against
# the real dpkg copyright files, with a reviewed-exceptions list. That is the
# gate CLAUDE.md names and it must stay green. A crude second implementation of
# a gate is worse than no second implementation: it fails on correct code, and
# people learn to delete the failing test.
#
# These tests cover what the audit does NOT: trademarks.


def test_the_licence_audit_is_still_the_licence_gate():
    """Keep the pointer honest — the audit is where licence enforcement lives."""
    audit = REPO / "packaging" / "audit-licenses.sh"
    assert audit.is_file() and audit.stat().st_mode & 0o111, (
        "audit-licenses.sh must exist and be executable — it is the licence gate")
    assert "components.py" in audit.read_text(), (
        "the audit must keep pointing copyleft findings at the consent catalogue")

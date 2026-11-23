"""32-bit Pi OS: deprecated on Bullseye and newer, too old below glibc 2.31 (agentos/oldpi.py)."""
from agentos import oldpi, updates


def test_a_64bit_machine_hears_nothing():
    for m, b in (("aarch64", 64), ("x86_64", 64), ("x86_64", 32)):
        st = oldpi.state(machine=m, bits=b, libc=(2, 36))
        assert st == {"deprecated": False, "too_old": False, "line": ""}


def test_32bit_on_bullseye_is_deprecated_not_too_old():
    for m in ("armv7l", "aarch64"):          # a Pi 4 on 32-bit Pi OS boots a 64-bit kernel
        st = oldpi.state(machine=m, bits=32, libc=(2, 31))
        assert st["deprecated"] and not st["too_old"]
        assert "deprecated" in st["line"] and "64-bit" in st["line"]


def test_buster_is_too_old_and_names_the_last_version():
    st = oldpi.state(machine="armv7l", bits=32, libc=(2, 28))
    assert st["too_old"] and st["deprecated"]
    assert oldpi.LAST_OLD["version"] in st["line"] and "2.28" in st["line"] and "Bookworm" in st["line"]


def test_an_unknown_libc_is_deprecated_never_refused():
    st = oldpi.state(machine="armv7l", bits=32, libc=None)
    assert st["deprecated"] and not st["too_old"]


def test_update_refuses_on_a_pi_too_old(monkeypatch):
    real = oldpi.state
    monkeypatch.setattr(oldpi, "state", lambda **kw: real(machine="armv7l", bits=32, libc=(2, 28)))
    ok, why = updates.can_apply({})
    assert not ok and "0.99.0" in why


def test_the_line_has_no_dash_clauses():
    for libc in ((2, 28), (2, 36)):
        line = oldpi.state(machine="armv7l", bits=32, libc=libc)["line"]
        assert " — " not in line and " - " not in line

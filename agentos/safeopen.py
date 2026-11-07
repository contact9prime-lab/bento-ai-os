"""Open a file by a path already checked, so that a path changed since cannot be followed.

A guard that resolves a path and then opens it by name has a gap between the two: flip a symlink
in that gap and the open lands on whatever the link now names. Measured by the audit: 80 of 26,631
tries of `read_file` read another account's key that way.

So the callers check the REAL path (no links in it at that moment), and this walks it one component
at a time with O_NOFOLLOW from an open directory. Anything that became a link since then is refused
rather than followed, and the descriptor is compared with the name afterwards where /proc can say.
It costs about 1 microsecond a component, which no file tool will notice.

Stdlib only, no openat2: it has no Python binding, and this also runs on macOS.
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat

_DIR = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC | getattr(os, "O_PATH", os.O_RDONLY)


class Moved(OSError):
    """The path stopped being what was checked: a link appeared, or it is not a plain file."""


def _walk(real: str, make_dirs: bool) -> tuple[int, str]:
    """An open descriptor on the folder holding `real`, and the last part of the name."""
    if not os.path.isabs(real):
        raise Moved(errno.EINVAL, "not an absolute path", real)
    parts = [p for p in real.split(os.sep) if p]
    if not parts:
        raise IsADirectoryError(errno.EISDIR, "that is a folder", real)
    dfd = os.open(os.sep, _DIR)
    try:
        for part in parts[:-1]:
            if part == "..":
                raise Moved(errno.EINVAL, "not a resolved path", real)
            try:
                nfd = os.open(part, _DIR, dir_fd=dfd)
            except FileNotFoundError:
                if not make_dirs:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, 0o777, dir_fd=dfd)
                nfd = os.open(part, _DIR, dir_fd=dfd)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise Moved(e.errno, "a folder on the way there changed", real) from e
                raise
            os.close(dfd)
            dfd = nfd
    except BaseException:
        os.close(dfd)
        raise
    return dfd, parts[-1]


def _confirm(fd: int, real: str) -> None:
    """The descriptor's own name, where the OS can say: check the fd, not the string."""
    try:
        now = os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return                                  # no /proc (macOS): the walk above is the check
    if now != real:
        raise Moved(errno.ESTALE, "the file moved while it was being opened", real)


def open_file(real: str, *, write: bool = False, make_dirs: bool = False, mode: int = 0o644) -> int:
    """A descriptor on the plain file at `real`, an already-resolved absolute path. Refuses a
    link anywhere in the path, and anything that is not a plain file: a FIFO would hang the
    server's thread forever, and a device has no business being read by a file tool."""
    dfd, leaf = _walk(real, make_dirs)
    try:
        flags = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        flags |= (os.O_WRONLY | os.O_CREAT) if write else os.O_RDONLY
        try:
            fd = os.open(leaf, flags, mode, dir_fd=dfd)
        except OSError as e:
            if e.errno in (errno.ELOOP, errno.ENXIO):
                raise Moved(e.errno, "that is not a plain file", real) from e
            raise
    finally:
        os.close(dfd)
    try:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            raise IsADirectoryError(errno.EISDIR, "that is a folder", real)
        if not stat.S_ISREG(st.st_mode):
            raise Moved(errno.EINVAL, "that is not a plain file", real)
        _confirm(fd, real)
    except BaseException:
        os.close(fd)
        raise
    return fd


def read_bytes(real: str) -> bytes:
    with os.fdopen(open_file(real), "rb") as f:
        return f.read()


def write_bytes(real: str, data: bytes, *, make_dirs: bool = True) -> None:
    """Truncates only after the descriptor is known to be the plain file that was checked."""
    fd = open_file(real, write=True, make_dirs=make_dirs)
    with os.fdopen(fd, "wb") as f:
        f.truncate(0)
        f.write(data)

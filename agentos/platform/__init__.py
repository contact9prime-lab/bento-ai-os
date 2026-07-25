"""Platform backends — one contract, four implementations.

Callers should go through `get_platform()` rather than importing a backend
directly, so the right one is chosen from the run mode and the machine.

    from .platform import get_platform
    p = get_platform()
    if p.can(caps.NET_WIFI_JOIN): ...
"""

from __future__ import annotations

from .. import runmode
from . import caps
from .base import Capability, Platform, missing, ok, unsupported

_cache: dict[str, Platform] = {}


def _build(mode: str) -> Platform:
    if runmode.IS_MAC:
        from .macos import MacOS
        return MacOS(mode=runmode.HOSTED)
    if runmode.IS_WIN:
        from .windows import Windows
        return Windows(mode=runmode.HOSTED)
    if mode == runmode.DE:
        from .linux_de import LinuxDE
        return LinuxDE(mode=mode)
    from .linux_hosted import LinuxHosted
    return LinuxHosted(mode=mode)


def get_platform(cfg: dict | None = None, refresh: bool = False) -> Platform:
    """The backend for the current run mode, built once per mode.

    `refresh=True` rebuilds and re-probes — use it after something that could
    change the answer, such as installing an optional component.
    """
    mode, _detected = runmode.resolve(cfg)
    if refresh:
        _cache.pop(mode, None)
    if mode not in _cache:
        _cache[mode] = _build(mode)
    else:
        _cache[mode].capabilities(refresh=refresh)
    return _cache[mode]


def describe(cfg: dict | None = None) -> dict:
    """Everything the UI needs to decide what to render. Backs GET /api/platform."""
    mode, detected = runmode.resolve(cfg)
    p = get_platform(cfg)
    out = p.describe()
    out["detected_mode"] = detected
    out["pinned"] = mode != detected
    out["summary"] = runmode.describe(mode)
    out["modes"] = list(runmode.CHOICES)
    return out


__all__ = ["Capability", "Platform", "caps", "describe", "get_platform",
           "missing", "ok", "unsupported"]

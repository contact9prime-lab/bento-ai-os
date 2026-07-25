"""PipeWire audio: devices, default sink switching, per-app volume.

PipeWire has no D-Bus API — its own tools are the interface: `pw-dump` emits
the whole node graph as JSON and `wpctl` applies changes. Both ship in the
pipewire/wireplumber packages (MIT) that agentos-desktop depends on, so unlike
the daemons this module's siblings talk to, these are guaranteed present in the
session. Master volume stays in the platform backend (host.get_volume); this
covers what a desktop needs beyond it.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from . import HostCtlError


def available() -> tuple[bool, str]:
    if not (shutil.which("pw-dump") and shutil.which("wpctl")):
        return False, "PipeWire tools (pw-dump/wpctl) are not installed."
    return True, ""


def _run(cmd: list[str], timeout: float = 5) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            raise HostCtlError((r.stderr or r.stdout).strip() or f"{cmd[0]} failed")
        return r.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HostCtlError(f"{cmd[0]}: {e}") from e


def parse_graph(dump: list, default_sink_name: str = "", default_source_name: str = "") -> dict:
    """pw-dump → sinks, sources and app streams. Pure, testable.

    Sinks/sources are Audio/Sink and Audio/Source nodes; app streams are
    Stream/Output/Audio (playback) with the owning app's name.
    """
    sinks, sources, streams = [], [], []
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Node":
            continue
        props = (obj.get("info") or {}).get("props") or {}
        cls = props.get("media.class", "")
        row = {
            "id": obj.get("id"),
            "name": props.get("node.name", ""),
            "description": props.get("node.description") or props.get("node.nick")
                           or props.get("node.name", ""),
        }
        if cls == "Audio/Sink":
            row["default"] = bool(default_sink_name) and row["name"] == default_sink_name
            sinks.append(row)
        elif cls == "Audio/Source":
            row["default"] = bool(default_source_name) and row["name"] == default_source_name
            sources.append(row)
        elif cls == "Stream/Output/Audio":
            row["app"] = (props.get("application.name")
                          or props.get("application.process.binary") or row["description"])
            streams.append(row)
    return {"sinks": sinks, "sources": sources, "streams": streams}


def _default_node_names(dump: list) -> tuple[str, str]:
    """WirePlumber publishes the chosen defaults as metadata entries."""
    sink = source = ""
    for obj in dump:
        if obj.get("type") != "PipeWire:Interface:Metadata":
            continue
        if ((obj.get("props") or {}).get("metadata.name")) != "default":
            continue
        for m in obj.get("metadata") or []:
            try:
                name = (m.get("value") or {}).get("name", "")
            except AttributeError:
                continue
            if m.get("key") == "default.audio.sink":
                sink = name
            elif m.get("key") == "default.audio.source":
                source = name
    return sink, source


def devices() -> dict:
    dump = json.loads(_run(["pw-dump"], timeout=10))
    return parse_graph(dump, *_default_node_names(dump))


def set_default(node_id: int) -> None:
    _run(["wpctl", "set-default", str(int(node_id))])


def set_node_volume(node_id: int, percent: int) -> None:
    _run(["wpctl", "set-volume", str(int(node_id)),
          f"{max(0, min(150, int(percent)))}%"])

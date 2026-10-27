"""What a machine's hardware is: the board and every sensor, camera, pin, bus and port on it.

Asked for as "the complete hardware understanding of the Pi is the profile of the Pi … it has
to be discovered every day and the full inventory is with the hub", "it needs to go all the
way down to the sensors, and everything should be mapped to the Pi's inventory name". The hub
is the Pi's nervous system: it keeps what each Pi has, and later what each sensor read and who
may read or set it (docs/design/devices.md). This module is the first step, discovery.

Four rules:

  * Discovery only READS. It lists /sys, /proc and /dev and asks the few tools a Pi ships
    (rpicam-hello, vcgencmd, pinctrl) to list what they see. It never scans an I2C bus (a
    probe that writes to a bus can upset what is on it), never opens a camera, never sets a
    pin, and never installs anything to find out more.
  * A thing is listed by what it IS, never by the device node. A Pi has ten /dev/video nodes
    and no camera: they are the chip's codec and image processor. A camera is what
    rpicam-hello lists, or a USB video device (uvcvideo).
  * Every item has an id that is stable on that machine (`cpu.temp`, `gpio.17`, `i2c.1.0x48`,
    `usb.1-1.2`), so `<machine>/<id>` is its inventory name for every later step: readings,
    permissions and profiles all name it that way.
  * The hub reads what arrives field by field (`clean`): a closed set of kinds, bounded
    strings and lists, plain text. A machine's answer about itself is its claim.

`quick()` is the cheap half (directory listings only), hashed into the hello every minute, so
a USB camera plugged in is noticed within a minute and the full probe runs then. Free of HTTP
and asyncio: the link's op, the server's routes and `bento hardware` call into it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

# where the kernel says things; a test points this at a folder laid out the same way
ROOT = Path(os.environ.get("AGENTOS_HW_ROOT") or "/")

KINDS = ("camera", "temperature", "power", "gpio", "i2c", "spi", "serial", "usb", "audio_in",
         "audio_out", "input", "network", "bluetooth", "sensor", "system")
KIND_WORDS = {"camera": "Cameras", "temperature": "Temperature", "power": "Power", "gpio": "GPIO pins",
              "i2c": "I2C", "spi": "SPI", "serial": "Serial ports", "usb": "USB devices",
              "audio_in": "Microphones", "audio_out": "Speakers and audio out", "input": "Input devices",
              "network": "Network", "bluetooth": "Bluetooth", "sensor": "Sensors", "system": "System"}
VERBS = ("read", "snapshot", "listen", "write")
MAX_ITEMS = 200
TOOL_TIMEOUT = 12          # seconds one listing tool may take (rpicam-hello starts the camera stack)
EVERY_S = 24 * 3600        # the hub asks for the whole inventory at least this often
_ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,63}")

# the bits vcgencmd get_throttled reports, now (low half) and since boot (high half)
THROTTLE_BITS = {0: "under-voltage", 1: "frequency capped", 2: "throttled", 3: "soft temperature limit"}


def _p(*parts) -> Path:
    return ROOT.joinpath(*[str(x).lstrip("/") for x in parts])


def _read(path, limit: int = 4096) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(limit).replace(b"\0", b"").decode("utf-8", "replace").strip()
    except OSError:
        return ""


def _natural(s: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]


def _ls(path) -> list[str]:
    try:
        return sorted(os.listdir(path), key=_natural)
    except OSError:
        return []


def _run(argv: list[str], timeout: float = TOOL_TIMEOUT) -> str:
    """A listing tool's output, or '' when it is not here or did not answer. Only tools that
    list; nothing that sets. Never through a shell."""
    if ROOT != Path("/") or not shutil.which(argv[0]):
        return ""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C"})
        return (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""


def _num(s: str):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _item(id_: str, kind: str, name: str, *, detail: str = "", value=None, unit: str = "",
          can: tuple = ("read",), **extra) -> dict:
    it = {"id": id_, "kind": kind, "name": name, "detail": detail, "can": list(can)}
    if value is not None:
        it["value"] = value
    if unit:
        it["unit"] = unit
    it.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return it


# ---- the board ------------------------------------------------------------------------------

def board() -> dict:
    model = _read(_p("proc/device-tree/model")) or _read(_p("sys/firmware/devicetree/base/model"))
    if not model:
        model = _read(_p("sys/class/dmi/id/product_name"))
        vendor = _read(_p("sys/class/dmi/id/sys_vendor"))
        model = " ".join(x for x in (vendor, model) if x) or platform.machine()
    serial = _read(_p("proc/device-tree/serial-number"))
    if not serial:
        m = re.search(r"^Serial\s*:\s*(\S+)", _read(_p("proc/cpuinfo"), 65536), re.M)
        serial = m.group(1) if m else ""
    mem = re.search(r"^MemTotal:\s*(\d+)", _read(_p("proc/meminfo")), re.M)
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', _read(_p("etc/os-release")), re.M))
    return {"model": model, "serial": serial, "ram_mb": int(mem.group(1)) // 1024 if mem else 0,
            "os": osr.get("PRETTY_NAME", ""), "kernel": platform.release() if ROOT == Path("/") else "",
            "arch": platform.machine() if ROOT == Path("/") else "", "pi": "raspberry pi" in model.lower()}


# ---- each kind ------------------------------------------------------------------------------

def _temperatures() -> list[dict]:
    out, seen = [], set()
    for z in _ls(_p("sys/class/thermal")):
        if not z.startswith("thermal_zone"):
            continue
        typ = _read(_p("sys/class/thermal", z, "type")) or z
        t = _num(_read(_p("sys/class/thermal", z, "temp")))
        if t is None:
            continue
        key = "cpu" if typ in ("cpu-thermal", "cpu_thermal", "x86_pkg_temp") else re.sub(r"[^a-z0-9]+", "_", typ.lower())
        if key in seen:
            key = f"{key}_{z.removeprefix('thermal_zone')}"
        seen.add(key)
        out.append(_item(f"{key}.temp", "temperature", "CPU temperature" if key == "cpu" else f"{typ} temperature",
                         detail=typ, value=round(t / 1000, 1), unit="°C"))
    if "cpu" not in seen:           # a PC without a thermal zone: the CPU's sensor chip says it
        for h in _ls(_p("sys/class/hwmon")):
            name = _read(_p("sys/class/hwmon", h, "name"))
            t = _num(_read(_p("sys/class/hwmon", h, "temp1_input")))
            if name in ("k10temp", "coretemp") and t is not None:
                out.append(_item("cpu.temp", "temperature", "CPU temperature", detail=name,
                                 value=round(t / 1000, 1), unit="°C"))
                break
    return out


def _power() -> list[dict]:
    raw = _run(["vcgencmd", "get_throttled"], 5)
    out = []
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", raw)
    if m:
        v = int(m.group(1), 16)
        now = [w for b, w in THROTTLE_BITS.items() if v & (1 << b)]
        ever = [w for b, w in THROTTLE_BITS.items() if v & (1 << (b + 16))]
        words = ("now: " + ", ".join(now)) if now else "fine now"
        if ever:
            words += "; since boot: " + ", ".join(ever)
        out.append(_item("power.throttle", "power", "Power and throttling", detail=words, value=m.group(1).lower(),
                         flags={"now": now, "since_boot": ever}))
    m = re.search(r"volt=([\d.]+)V", _run(["vcgencmd", "measure_volts", "core"], 5))
    if m:
        out.append(_item("power.core_volts", "power", "Core voltage", value=float(m.group(1)), unit="V"))
    return out


def _cameras(full: bool) -> list[dict]:
    out = []
    if full:
        listed = _run(["rpicam-hello", "--list-cameras"]) or _run(["libcamera-hello", "--list-cameras"])
        for m in re.finditer(r"^\s*(\d+)\s*:\s*(\S+)\s*\[([^\]]*)\]\s*(?:\(([^)]*)\))?", listed, re.M):
            out.append(_item(f"camera.{m.group(1)}", "camera", f"Camera {m.group(1)} ({m.group(2)})",
                             detail=m.group(3).strip(), can=("snapshot",), sensor=m.group(2), path=m.group(4) or ""))
    for v in _ls(_p("sys/class/video4linux")):
        drv = os.path.basename(os.path.realpath(_p("sys/class/video4linux", v, "device/driver"))) \
            if _p("sys/class/video4linux", v, "device/driver").exists() else ""
        if drv != "uvcvideo" or _read(_p("sys/class/video4linux", v, "index")) not in ("", "0"):
            continue            # the chip's codec and ISP nodes are not cameras; one id per USB camera
        out.append(_item(f"camera.usb.{v.removeprefix('video')}", "camera", _read(_p("sys/class/video4linux", v, "name")) or "USB camera",
                         detail="USB video", can=("snapshot",), node=f"/dev/{v}"))
    return out


def _gpio() -> list[dict]:
    """The header pins as pinctrl reads them (mode and level), else the gpiochips."""
    out = []
    for line in _run(["pinctrl", "get", "0-27"], 5).splitlines():
        m = re.match(r"\s*(\d+):\s*(\S+)\s+(\S+)\s*\|\s*(hi|lo)\s*//\s*(\S+)\s*=\s*(\S+)", line)
        if not m:
            continue
        n, mode, level, name, fn = int(m.group(1)), m.group(2), m.group(4), m.group(5), m.group(6)
        word = {"ip": "input", "op": "output"}.get(mode, fn if fn not in ("input", "output") else mode)
        out.append(_item(f"gpio.{n}", "gpio", f"GPIO {n}", detail=word, value=1 if level == "hi" else 0,
                         label=name.split("/")[0] if "/" in name else ""))
    if out:
        return out
    for c in _ls(_p("sys/class/gpio")):
        if c.startswith("gpiochip"):
            out.append(_item(f"gpio.chip.{c.removeprefix('gpiochip')}", "gpio", _read(_p("sys/class/gpio", c, "label")) or c,
                             detail=f"{_read(_p('sys/class/gpio', c, 'ngpio'))} lines", can=()))
    return out


def _buses() -> list[dict]:
    out = []
    for d in _ls(_p("sys/bus/i2c/devices")):
        if d.startswith("i2c-"):
            out.append(_item(f"i2c.{d[4:]}", "i2c", f"I2C bus {d[4:]}", detail=_read(_p("sys/bus/i2c/devices", d, "name")), can=()))
        elif re.fullmatch(r"\d+-[0-9a-f]{4}", d):
            bus, addr = d.split("-")
            out.append(_item(f"i2c.{bus}.0x{addr[2:]}", "i2c", _read(_p("sys/bus/i2c/devices", d, "name")) or "I2C device",
                             detail=f"bus {bus}, address 0x{addr[2:]}"))
    for d in _ls(_p("dev")):
        if d.startswith("spidev"):
            out.append(_item(f"spi.{d[6:]}", "spi", f"SPI {d[6:]}", detail=f"/dev/{d}", can=()))
        elif re.fullmatch(r"tty(AMA|USB|ACM)\d+|ttyS0|serial\d", d):
            out.append(_item(f"serial.{d}", "serial", d, detail=f"/dev/{d}", can=()))
    return out


def _usb() -> list[dict]:
    out = []
    for d in _ls(_p("sys/bus/usb/devices")):
        base = _p("sys/bus/usb/devices", d)
        vid = _read(base / "idVendor")
        if not vid or d.startswith("usb") or _read(base / "bDeviceClass") == "09":
            continue            # root hubs and hubs are plumbing
        prod = " ".join(x for x in (_read(base / "manufacturer"), _read(base / "product")) if x)
        # what the kernel drives it with says what it is when it has no name (a Pi's Ethernet)
        drivers = sorted({os.path.basename(os.path.realpath(base.parent / f / "driver")) for f in _ls(base.parent)
                          if f.startswith(d + ":") and (base.parent / f / "driver").exists()})
        ident = f"{vid}:{_read(base / 'idProduct')}"
        out.append(_item(f"usb.{d}", "usb", prod or (f"USB {drivers[0]}" if drivers else f"USB {ident}"),
                         detail=" · ".join([ident] + drivers), can=()))
    return out


def _audio() -> list[dict]:
    out = []
    cards = {str(int(m.group(1))): m.group(2).split(" - ", 1)[-1].strip() for m in
             re.finditer(r"^\s*(\d+)\s*\[[^\]]*\]:\s*(.*)$", _read(_p("proc/asound/cards")), re.M)}
    for line in _read(_p("proc/asound/pcm")).splitlines():
        m = re.match(r"(\d+)-(\d+):\s*[^:]*:\s*([^:]*?)\s*:(.*)", line)
        if not m:
            continue
        card, dev, name, caps = str(int(m.group(1))), str(int(m.group(2))), m.group(3), m.group(4)
        label = cards.get(card) or name
        if "playback" in caps:
            out.append(_item(f"audio.out.{card}.{dev}", "audio_out", label, detail=name, can=()))
        if "capture" in caps:
            out.append(_item(f"audio.in.{card}.{dev}", "audio_in", label, detail=name, can=("listen",)))
    return out


def _inputs() -> list[dict]:
    """Keyboards, mice, buttons. Named by where they are plugged in (the kernel's Phys), so the
    id stays when the machine restarts or something else is plugged in first."""
    out, seen = [], set()
    for block in _read(_p("proc/bus/input/devices"), 65536).split("\n\n"):
        name = re.search(r'^N: Name="([^"]*)"', block, re.M)
        if not name:
            continue
        name = name.group(1).strip()
        if "hdmi" in name.lower() or "jack" in name.lower():
            continue            # the HDMI port's own events, not something a person plugged in
        phys = (re.search(r"^P: Phys=(\S*)", block, re.M) or [None, ""])[1]
        # usb-3f980000.usb-1.3/input1 -> usb.1.3.input1: the port path, without the controller
        where = re.sub(r"^usb-[^-]+-", "usb.", phys) if phys.startswith("usb-") else phys if "/" in phys else ""
        slug = re.sub(r"[^a-z0-9.]+", "-", (where or name).lower().replace("/", ".")).strip("-.")[:50] or "device"
        iid, n = f"input.{slug}", 2
        while iid in seen:
            iid, n = f"input.{slug}-{n}", n + 1
        seen.add(iid)
        out.append(_item(iid, "input", name, can=()))
    return out


def _network() -> list[dict]:
    out = []
    wifi = {m.group(1): float(m.group(2)) for m in
            re.finditer(r"^\s*(\w+):\s*\S+\s+\S+\s+(-?[\d.]+)", _read(_p("proc/net/wireless")), re.M)}
    for n in _ls(_p("sys/class/net")):
        if n == "lo" or n.startswith(("veth", "docker", "br-", "virbr", "tailscale")):
            continue
        st = _read(_p("sys/class/net", n, "operstate"))
        it = _item(f"net.{n}", "network", n, detail=st, mac=_read(_p("sys/class/net", n, "address")),
                   wireless=_p("sys/class/net", n, "wireless").exists() or None)
        if n in wifi:
            it.update(value=wifi[n], unit="dBm")
        out.append(it)
    for h in _ls(_p("sys/class/bluetooth")):
        if re.fullmatch(r"hci\d+", h):
            out.append(_item(f"bluetooth.{h}", "bluetooth", f"Bluetooth {h}", can=()))
    return out


def _sensors() -> list[dict]:
    """What a driver already exposes: 1-Wire thermometers, IIO sensors, hwmon chips."""
    out = []
    for d in _ls(_p("sys/bus/w1/devices")):
        if d.startswith("w1_bus"):
            continue
        t = _num(_read(_p("sys/bus/w1/devices", d, "temperature")))
        out.append(_item(f"w1.{d}", "sensor", "1-Wire thermometer" if d.startswith("28-") else f"1-Wire {d}",
                         value=round(t / 1000, 2) if t is not None else None, unit="°C" if t is not None else ""))
    for d in _ls(_p("sys/bus/iio/devices")):
        if not d.startswith("iio:device"):
            continue
        chans = [c for c in _ls(_p("sys/bus/iio/devices", d)) if c.endswith(("_raw", "_input"))][:12]
        out.append(_item(f"iio.{d.removeprefix('iio:device')}", "sensor", _read(_p("sys/bus/iio/devices", d, "name")) or d,
                         detail=", ".join(c.rsplit("_", 1)[0] for c in chans)))
    for h in _ls(_p("sys/class/hwmon")):
        name = _read(_p("sys/class/hwmon", h, "name"))
        if name in ("cpu_thermal", "coretemp", "k10temp", "acpitz", ""):
            continue            # the CPU's own, already listed under temperature
        ins = [c for c in _ls(_p("sys/class/hwmon", h)) if c.endswith("_input")][:12]
        if ins:
            out.append(_item(f"hwmon.{name}", "sensor", name, detail=", ".join(c.removesuffix("_input") for c in ins)))
    return out


def _system() -> list[dict]:
    out = []
    la = _read(_p("proc/loadavg")).split()
    if la:
        out.append(_item("system.load", "system", "Load (1 minute)", value=_num(la[0])))
    m = re.search(r"^MemAvailable:\s*(\d+)", _read(_p("proc/meminfo")), re.M)
    if m:
        out.append(_item("system.memory_free", "system", "Memory available", value=int(m.group(1)) // 1024, unit="MB"))
    if ROOT == Path("/"):
        try:
            du = shutil.disk_usage("/")
            out.append(_item("system.disk_free", "system", "Disk free", value=du.free // (1 << 20), unit="MB"))
        except OSError:
            pass
    up = _num(_read(_p("proc/uptime")).split(" ")[0] if _read(_p("proc/uptime")) else "")
    if up is not None:
        out.append(_item("system.uptime", "system", "Up for", value=int(up), unit="s"))
    return out


# ---- the whole answer -----------------------------------------------------------------------

def probe(full: bool = True) -> dict:
    """Everything on this machine, at this moment. `full` also asks the camera stack, which
    takes a few seconds; the minute's hello uses `quick()` instead."""
    items = (_cameras(full) + _temperatures() + _power() + _sensors() + _gpio() + _buses() + _usb()
             + _audio() + _inputs() + _network() + _system())
    out = {"at": time.time(), "board": board(), "items": items[:MAX_ITEMS], "quick": quick()}
    out["digest"] = digest(out)
    return out


def sample() -> dict:
    """The numbers worth keeping over time, by inventory id: temperatures, power (1 when it is
    under-voltage or throttled now, else 0), core voltage, 1-Wire thermometers, Wi-Fi signal,
    load, free memory and disk, and each pin's level. No camera, no listing tool but vcgencmd
    and pinctrl get: this runs every ten seconds on the Zero (telemetry.Buffer)."""
    out = {}
    for it in _temperatures() + _power() + _system() + _network() + _gpio() + \
            [i for i in _sensors() if i["id"].startswith("w1.")]:
        if it["id"] == "power.throttle":
            out[it["id"]] = 1 if (it.get("flags") or {}).get("now") else 0
        elif it["id"] == "system.uptime":
            continue
        elif isinstance(it.get("value"), (int, float)) and not isinstance(it.get("value"), bool):
            out[it["id"]] = it["value"]
    return out


def quick() -> str:
    """A hash of what is plugged in, from directory listings alone (no tools, no values): it
    changes when a camera, a USB device, a bus device or a sound card comes or goes."""
    parts = [d for d in _ls(_p("dev")) if re.match(r"(video|i2c-|spidev|tty(AMA|USB|ACM)|gpiochip|media)", d)]
    parts += ["usb:" + d + ":" + _read(_p("sys/bus/usb/devices", d, "idVendor")) + _read(_p("sys/bus/usb/devices", d, "idProduct"))
              for d in _ls(_p("sys/bus/usb/devices"))]
    for folder in ("sys/bus/i2c/devices", "sys/bus/w1/devices", "sys/bus/iio/devices", "sys/class/sound",
                   "sys/class/net", "sys/class/bluetooth"):
        parts += [folder.rsplit("/", 1)[-1] + ":" + d for d in _ls(_p(folder))]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def digest(p: dict) -> str:
    """What the inventory is, without its readings: two probes with the same things plugged in
    digest the same, whatever the temperature was."""
    shape = [(it.get("id"), it.get("kind"), it.get("name"), it.get("detail") if it.get("kind") not in
              ("gpio", "power", "network", "system") else "") for it in p.get("items") or []]
    b = p.get("board") or {}
    return hashlib.sha256(json.dumps([b.get("model"), b.get("serial"), b.get("ram_mb"), shape]).encode()).hexdigest()[:16]


def answer(cfg: dict, lk: dict) -> dict:
    """On the machine: its own hub asked what it has (wire op zero_hardware). Nobody else is
    answered: another linked team learns nothing about this machine's hardware."""
    from . import zero as zeromod
    if not zeromod.is_my_hub(cfg, lk):
        return {"ok": False, "error": "only the hub that set this machine up can read its hardware"}
    return {"ok": True, "hardware": probe()}


# ---- on the hub: what arrived, read field by field -----------------------------------------

def _plain(v, n: int) -> str:
    from . import teamlink
    return teamlink.plain(str(v if v is not None else ""), n, newlines=False).strip()


def clean(p, dropped: list | None = None) -> dict:
    """A machine's answer about itself, held to the closed set. What is refused is named."""
    dropped = dropped if dropped is not None else []
    p = p if isinstance(p, dict) else {}
    b = p.get("board") if isinstance(p.get("board"), dict) else {}
    out = {"at": float(p.get("at") or time.time()) if _num(p.get("at")) is not None else time.time(),
           "board": {"model": _plain(b.get("model"), 80), "serial": _plain(b.get("serial"), 40),
                     "ram_mb": int(_num(b.get("ram_mb")) or 0), "os": _plain(b.get("os"), 80),
                     "kernel": _plain(b.get("kernel"), 60), "arch": _plain(b.get("arch"), 20),
                     "pi": bool(b.get("pi"))},
           "items": [], "quick": _plain(p.get("quick"), 16)}
    seen = set()
    for it in (p.get("items") if isinstance(p.get("items"), list) else [])[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        iid, kind = str(it.get("id") or ""), str(it.get("kind") or "")
        if not _ID.fullmatch(iid) or kind not in KINDS or iid in seen:
            dropped.append(f"item '{_plain(iid, 40) or '?'}' ({_plain(kind, 20) or 'no kind'})")
            continue
        seen.add(iid)
        c = {"id": iid, "kind": kind, "name": _plain(it.get("name"), 80) or iid,
             "detail": _plain(it.get("detail"), 160), "can": [v for v in (it.get("can") or []) if v in VERBS][:4]}
        v = it.get("value")
        if isinstance(v, bool) or v is None:
            pass
        elif isinstance(v, (int, float)):
            c["value"] = v
        else:
            c["value"] = _plain(v, 40)
        for k, n in (("unit", 8), ("label", 40), ("sensor", 40), ("mac", 17), ("node", 40), ("path", 120)):
            if it.get(k):
                c[k] = _plain(it[k], n)
        if isinstance(it.get("flags"), dict):
            c["flags"] = {w: [x for x in (it["flags"].get(w) or []) if x in THROTTLE_BITS.values()]
                          for w in ("now", "since_boot")}
        out["items"].append(c)
    out["digest"] = digest(out)
    return out


def diff(old: dict | None, new: dict) -> list[tuple[str, str]]:
    """What changed between two inventories, as (event, words). Readings are not changes;
    things arriving, leaving, and the power state turning bad or good again are."""
    if not old or not old.get("items"):
        return [("hardware", f"{len(new.get('items') or [])} things found")]
    ev = []
    ob, nb = old.get("board") or {}, new.get("board") or {}
    if ob.get("serial") and nb.get("serial") and ob["serial"] != nb["serial"]:
        ev.append(("board", f"a different board answers now ({nb.get('model') or '?'}, serial {nb['serial']})"))
    olds = {i["id"]: i for i in old.get("items") or []}
    news = {i["id"]: i for i in new.get("items") or []}
    skip = ("system", "gpio")          # values that move, not things that come and go
    for iid in news.keys() - olds.keys():
        if news[iid]["kind"] not in skip:
            ev.append(("found", f"found {news[iid]['name']} ({iid})"))
    for iid in olds.keys() - news.keys():
        if olds[iid]["kind"] not in skip:
            ev.append(("gone", f"{olds[iid]['name']} ({iid}) is gone"))
    o, n = (olds.get("power.throttle") or {}).get("flags") or {}, (news.get("power.throttle") or {}).get("flags") or {}
    if set(n.get("now") or []) != set(o.get("now") or []):
        ev.append(("power", "power: " + (", ".join(n.get("now") or []) or "fine again")))
    return ev


def by_kind(items: list[dict]) -> list[tuple[str, list[dict]]]:
    """The items grouped in the order a person reads them."""
    return [(KIND_WORDS[k], [i for i in items if i["kind"] == k]) for k in KINDS
            if any(i["kind"] == k for i in items)]


def value_words(it: dict) -> str:
    v = it.get("value")
    if v is None:
        return ""
    if it["kind"] == "gpio":
        return "high" if v else "low"
    if it.get("unit") == "s":
        h = int(v) // 3600
        return f"{h // 24} d {h % 24} h" if h >= 24 else f"{h} h {int(v) % 3600 // 60} min"
    return f"{v}{' ' if it.get('unit') not in ('°C',) else ''}{it.get('unit') or ''}".strip()


def text(name: str, p: dict) -> str:
    """The inventory as a terminal reads it: every item under its inventory name."""
    b = p.get("board") or {}
    head = [f"  {name}: {b.get('model') or 'unknown board'}"
            + (f", {b['ram_mb']} MB" if b.get("ram_mb") else "") + (f", {b['os']}" if b.get("os") else "")]
    if p.get("at"):
        head.append(f"  read {time.strftime('%Y-%m-%d %H:%M', time.localtime(p['at']))}")
    lines = []
    for title, items in by_kind(p.get("items") or []):
        lines.append(f"\n  {title}")
        for it in items:
            val = value_words(it)
            more = " · ".join(x for x in (it.get("detail") or "", val) if x)
            lines.append(f"    {name}/{it['id']:<22} {it['name'][:34]:<34} {more}")
    return "\n".join(head + lines) if lines else "\n".join(head + ["  nothing found"])


if __name__ == "__main__":         # run on its own (python3 hardware.py): a machine with no Bento yet
    import sys
    if "--json" in sys.argv:
        print(json.dumps(probe(), indent=1))
    else:
        print(text(platform.node() or "this machine", probe()))

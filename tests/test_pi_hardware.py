"""What a Zero has, down to each sensor (hardware.py, ties.ask_hardware, the link's zero_hardware,
Devices → Hardware). Asked for as "the complete hardware understanding of the Pi … discovered every
day … the full inventory is with the hub … everything mapped to the Pi's inventory name".

The tree and the tool outputs below are what a real Raspberry Pi 3 B+ on trixie showed
(2026-10-27): ten /dev/video nodes and no camera, an under-voltage, 28 header pins."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from agentos import hardware, inventory, teamlink, ties      # noqa: E402
from test_zero_mind import _on, hz                            # noqa: E402,F401

ROOT = Path(__file__).parent.parent

PINCTRL = "\n".join(
    [" 0: ip    -- | hi // ID_SDA/GPIO0 = input", " 1: ip    -- | hi // ID_SCL/GPIO1 = input"]
    + [f"{n:2d}: ip    -- | lo // GPIO{n} = input" for n in range(2, 17)]
    + [" 17: op    -- | hi // GPIO17 = output"]
    + [f"{n:2d}: ip    -- | lo // GPIO{n} = input" for n in range(18, 28)])
TOOLS = {
    "vcgencmd get_throttled": "throttled=0x50005\n",
    "vcgencmd measure_volts": "volt=1.2000V\n",
    "pinctrl get": PINCTRL,
    "rpicam-hello --list-cameras": "Available cameras\n-----------------\n"
                                   "0 : imx219 [3280x2464 10-bit RGGB] (/base/soc/i2c0mux/i2c@1/imx219@10)\n",
}


def _w(root: Path, rel: str, text: str = ""):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _pi(root: Path):
    """A Pi's /sys, /proc and /dev, laid out as the kernel lays them out."""
    _w(root, "proc/device-tree/model", "Raspberry Pi 3 Model B Plus Rev 1.3\0")
    _w(root, "proc/device-tree/serial-number", "000000007803781d\0")
    _w(root, "proc/meminfo", "MemTotal:  926764 kB\nMemAvailable:  392780 kB\n")
    _w(root, "etc/os-release", 'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\n')
    _w(root, "proc/loadavg", "0.29 0.27 0.37 1/378 7596\n")
    _w(root, "proc/uptime", "4300.5 8000.1\n")
    _w(root, "sys/class/thermal/thermal_zone0/type", "cpu-thermal")
    _w(root, "sys/class/thermal/thermal_zone0/temp", "54768")
    for n, name in ((10, "bcm2835-codec-decode"), (13, "bcm2835-isp-output0"), (14, "bcm2835-isp-capture0")):
        _w(root, f"sys/class/video4linux/video{n}/name", name)
        _w(root, f"dev/video{n}")
    _w(root, "dev/gpiochip0")
    _w(root, "dev/i2c-2")
    _w(root, "sys/bus/i2c/devices/i2c-2/name", "bcm2835 (i2c@7e805000)")
    for d, vid, pid, cls, man, prod in (("usb1", "1d6b", "0002", "09", "Linux", "DWC OTG"),
                                       ("1-1", "0424", "2514", "09", "", ""),
                                       ("1-1.1.1", "0424", "7800", "ff", "", ""),
                                       ("1-1.1.2", "0781", "558a", "00", "SanDisk", "Ultra")):
        for f, v in (("idVendor", vid), ("idProduct", pid), ("bDeviceClass", cls), ("manufacturer", man), ("product", prod)):
            if v:
                _w(root, f"sys/bus/usb/devices/{d}/{f}", v)
    _w(root, "proc/asound/cards", " 0 [vc4hdmi        ]: vc4-hdmi - vc4-hdmi\n                      vc4-hdmi\n"
                                  " 1 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones\n"
                                  "                      bcm2835 Headphones\n")
    _w(root, "proc/asound/pcm", "00-00: MAI PCM i2s-hifi-0 : MAI PCM i2s-hifi-0 : playback 1\n"
                                "01-00: bcm2835 Headphones : bcm2835 Headphones : playback 8\n")
    _w(root, "proc/bus/input/devices", 'I: Bus=0000\nN: Name="vc4-hdmi"\n\nN: Name="vc4-hdmi HDMI Jack"\n\n'
           'I: Bus=0003\nN: Name="HS6209 2.4G Wireless Receiver Keyboard"\nP: Phys=usb-3f980000.usb-1.3/input0\n\n'
           'I: Bus=0003\nN: Name="HS6209 2.4G Wireless Receiver Mouse"\nP: Phys=usb-3f980000.usb-1.3/input1\n')
    for n, st in (("eth0", "down"), ("wlan0", "up"), ("lo", "unknown")):
        _w(root, f"sys/class/net/{n}/operstate", st)
        _w(root, f"sys/class/net/{n}/address", "b8:27:eb:56:2d:48")
    (root / "sys/class/net/wlan0/wireless").mkdir()
    _w(root, "proc/net/wireless", "Inter-| sta-|\n face | tus |\n wlan0: 0000   47.  -63.  -256\n")
    _w(root, "sys/class/bluetooth/hci0/address", "b8:27:eb:00:00:01")


@pytest.fixture()
def pi(tmp_path, monkeypatch):
    root = tmp_path / "pi-root"
    _pi(root)
    monkeypatch.setattr(hardware, "ROOT", root)

    def run(argv, timeout=hardware.TOOL_TIMEOUT):
        return next((v for k, v in TOOLS.items() if " ".join(argv).startswith(k)), "")
    monkeypatch.setattr(hardware, "_run", run)
    return root


def test_a_pi_is_listed_down_to_each_thing_under_a_stable_id(pi):
    got = hardware.probe()
    b = got["board"]
    assert b["model"].startswith("Raspberry Pi 3") and b["pi"] and b["ram_mb"] == 905 and "trixie" in b["os"]
    ids = {i["id"]: i for i in got["items"]}
    assert ids["cpu.temp"]["value"] == 54.8 and ids["cpu.temp"]["unit"] == "°C"
    t = ids["power.throttle"]
    assert t["flags"]["now"] == ["under-voltage", "throttled"] and "since boot" in t["detail"]
    assert ids["power.core_volts"]["value"] == 1.2
    assert ids["camera.0"]["sensor"] == "imx219" and ids["camera.0"]["can"] == ["snapshot"]
    assert not [i for i in got["items"] if i["kind"] == "camera" and i["id"] != "camera.0"], \
        "the chip's codec and ISP video nodes are not cameras"
    pins = [i for i in got["items"] if i["kind"] == "gpio"]
    assert len(pins) == 28 and ids["gpio.17"]["detail"] == "output" and ids["gpio.17"]["value"] == 1
    assert ids["gpio.0"]["label"] == "ID_SDA"
    assert ids["i2c.2"]["detail"].startswith("bcm2835")
    assert "usb.1-1.1.2" in ids and ids["usb.1-1.1.2"]["name"] == "SanDisk Ultra"
    assert "usb.usb1" not in ids and "usb.1-1" not in ids, "hubs and root hubs are plumbing"
    assert ids["audio.out.1.0"]["name"] == "bcm2835 Headphones" and not any(k.startswith("audio.in") for k in ids)
    assert sorted(i["id"] for i in got["items"] if i["kind"] == "input") == \
        ["input.usb.1.3.input0", "input.usb.1.3.input1"], "named by the port, and the HDMI port is not an input"
    assert ids["net.wlan0"]["value"] == -63.0 and ids["net.wlan0"]["unit"] == "dBm" and "net.lo" not in ids
    assert "bluetooth.hci0" in ids and ids["system.memory_free"]["value"] == 383
    assert all(hardware._ID.fullmatch(i) for i in ids)
    text = hardware.text("raspberrypi", got)
    assert "raspberrypi/cpu.temp" in text and "raspberrypi/gpio.17" in text, "listed under its inventory name"


def test_the_quick_hash_moves_when_something_is_plugged_in_and_readings_do_not(pi):
    a, d = hardware.quick(), hardware.digest(hardware.probe())
    _w(pi, "sys/class/thermal/thermal_zone0/temp", "61000")
    assert hardware.quick() == a and hardware.digest(hardware.probe()) == d, "a reading is not a change"
    _w(pi, "sys/bus/usb/devices/1-1.3/idVendor", "046d")
    _w(pi, "sys/bus/usb/devices/1-1.3/idProduct", "0825")
    _w(pi, "sys/bus/usb/devices/1-1.3/product", "Webcam C270")
    _w(pi, "dev/video0")
    _w(pi, "sys/class/video4linux/video0/name", "Webcam C270")
    (pi / "sys/class/video4linux/video0/device").mkdir(parents=True)
    (pi / "drivers/uvcvideo").mkdir(parents=True)
    (pi / "sys/class/video4linux/video0/device/driver").symlink_to(pi / "drivers/uvcvideo")
    assert hardware.quick() != a
    got = hardware.probe()
    assert hardware.digest(got) != d
    ids = {i["id"] for i in got["items"]}
    assert "camera.usb.0" in ids and "usb.1-1.3" in ids, "a USB camera is a camera"


def test_what_arrives_is_read_field_by_field():
    dropped = []
    got = hardware.clean({"board": {"model": "Pi\x1b[31m", "ram_mb": "905"},
                          "items": [{"id": "cpu.temp", "kind": "temperature", "name": "CPU", "value": 50.1, "unit": "°C"},
                                    {"id": "Bad ID!", "kind": "temperature"},
                                    {"id": "x.y", "kind": "rocket"},
                                    {"id": "cpu.temp", "kind": "temperature"},
                                    {"id": "gpio.4", "kind": "gpio", "can": ["read", "launch"], "value": True},
                                    {"id": "power.throttle", "kind": "power", "flags": {"now": ["under-voltage", "lies"]}}],
                          "evil": 1}, dropped)
    assert [i["id"] for i in got["items"]] == ["cpu.temp", "gpio.4", "power.throttle"]
    assert len(dropped) == 3 and "x.y" in " ".join(dropped)
    assert "\x1b" not in got["board"]["model"] and got["board"]["ram_mb"] == 905 and "evil" not in got
    assert got["items"][1]["can"] == ["read"] and "value" not in got["items"][1]
    assert got["items"][2]["flags"]["now"] == ["under-voltage"]


def test_a_change_is_something_coming_or_going_or_the_power_turning(pi):
    old = hardware.clean(hardware.probe())
    assert hardware.diff(None, old)[0][0] == "hardware"
    new = hardware.clean(hardware.probe())
    for i in new["items"]:
        if i["kind"] in ("gpio", "system"):
            i["value"] = 0
    new["items"] = [i for i in new["items"] if i["id"] != "camera.0"]
    new["items"].append({"id": "w1.28-000005e2fdc3", "kind": "sensor", "name": "1-Wire thermometer", "can": ["read"]})
    tp = next(i for i in new["items"] if i["id"] == "power.throttle")
    tp["flags"] = {"now": [], "since_boot": ["under-voltage"]}
    ev = hardware.diff(old, new)
    kinds = sorted(e for e, _t in ev)
    assert kinds == ["found", "gone", "power"], ev
    assert any("fine again" in t for _e, t in ev)


def test_a_zero_tells_only_its_own_hub_and_the_hub_keeps_it_on_the_inventory_row(hz, pi):
    H, Z, loop = hz
    with teamlink.at(H["home"]):
        d = teamlink._load()
        d["links"][0]["url"] = f"127.0.0.1:{Z['lst'].port}"
        teamlink._save(d)
        lk = d["links"][0]

    async def zero_on_ask(lk_, req):
        with teamlink.at(Z["home"]):
            return hardware.answer(Z["cfg"], lk_)
    Z["lst"].on_ask = zero_on_ask
    with teamlink.at(Z["home"]):
        assert not hardware.answer(Z["cfg"], {"kind": "machine", "peer_host_fp": "someone"})["ok"]

    got = _on(H, loop, lambda: teamlink.call(lk, {"op": "hello"}, timeout=10))
    assert got.get("hw") == hardware.quick(), "the hello carries the hash, to its own hub"
    with teamlink.at(H["home"]):
        assert ties.hardware_due(lk) == "first look"
    got = _on(H, loop, lambda: ties.ask_hardware(lk))
    assert got["ok"] and len(got["hardware"]["items"]) > 40 and got["events"][0][0] == "hardware"
    with teamlink.at(H["home"]):
        r = ties.inventory_row(lk)
        assert r and r["hardware"]["board"]["serial"] == "000000007803781d"
        assert ties.hardware_due(lk) == "", "read just now, nothing plugged in"
        ties._HW[lk["id"]] = "something-else"
        assert ties.hardware_due(lk) == "something was plugged in or out"
        rows = inventory.load()["devices"]
        assert any(e.get("hardware") for e in rows.values()), "kept in inventory.json"
    assert not _on(H, loop, lambda: ties.ask_hardware({"kind": "machine", "peer_host_fp": "nobody"}))["ok"]


def test_the_minute_watch_reads_a_zero_when_it_is_due_and_not_otherwise(monkeypatch):
    from agentos import server as servermod
    from agentos import zero as zeromod
    # the modules the server reads now: another test may have reloaded them
    ties, teamlink = sys.modules["agentos.ties"], sys.modules["agentos.teamlink"]   # noqa: F811
    lk = {"id": "z9", "kind": "machine", "label": "pi", "url": "192.168.1.20:8622", "owner": ""}
    monkeypatch.setattr(teamlink, "_load", lambda: {"links": [lk], "invites": [], "requests": []})
    monkeypatch.setattr(zeromod, "ships_to", lambda x: True)

    async def probe(lks, force=False, wait=0):
        ties._PROBED["z9"] = (0, True, "")
        ties._VERSION["z9"] = "0.7.0"
    monkeypatch.setattr(ties, "probe", probe)
    asked = []

    async def tie_hw(lk_, why):
        asked.append(why)
        return {"ok": True}
    monkeypatch.setattr(servermod, "_tie_hardware", tie_hw)
    due = iter(["first look", "", "something was plugged in or out"])
    monkeypatch.setattr(ties, "hardware_due", lambda x: next(due))
    for d in (servermod._TIE_UP, servermod._TIE_MISS, ties._VERSION):
        d.pop("z9", None)
    servermod._TIE_REFRESH.discard("z9")

    async def call(lk_, req, **kw):
        return {"ok": True, "said": "nothing to refresh"}
    monkeypatch.setattr(teamlink, "call", call)
    loop = asyncio.new_event_loop()
    try:
        for _ in range(3):
            loop.run_until_complete(servermod._ties_check())
    finally:
        loop.close()
    assert asked == ["first look", "something was plugged in or out"]


def test_the_doors():
    tl = (ROOT / "agentos/teamlink.py").read_text()
    assert '"zero_hardware"' in tl and "hardware.quick()" in tl and "is_my_hub(self.cfg, lk)" in tl
    srv = (ROOT / "agentos/server.py").read_text()
    h = srv[srv.index("async def _zero_hardware_from_hub"):]
    h = h[:h.index("\n_HW_BUSY")]
    assert "hardware.answer" in h and "audit_team" in h and '.log("device"' in h, \
        "read only for its own hub, and written in the machine's diary and ledger"
    w = srv[srv.index("async def _ties_check"):]
    assert "hardware_due(lk)" in w[:w.index("\nasync def _ties_watch")]
    assert '@app.post("/api/network/hardware")' in srv
    js = (ROOT / "agentos/ui/src/js/24n-network.js").read_text()
    assert "function netHardwareHTML" in js and "data-net=\"hwcheck\"" in js
    src = (ROOT / "agentos/hardware.py").read_text()
    import re
    calls = re.findall(r'_run\(\[([^\]]*)\]', src)
    tools = {c.split(",")[0].strip(' "') for c in calls if c != "argv"} - {"argv[0]"}
    assert tools == {"rpicam-hello", "libcamera-hello", "vcgencmd", "pinctrl"}, tools
    assert all('"set"' not in c for c in calls if "pinctrl" in c), "pinctrl only reads"
    assert "hardware" in (ROOT / "agentos/__main__.py").read_text()

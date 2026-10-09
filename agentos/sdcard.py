"""A Raspberry Pi SD card that installs Bento on its first boot: the zero-touch road.

How a Pi configures itself when it first boots (docs/pi-first-boot.md has the whole story):
the card has a small FAT32 boot partition (mounted as `/boot/firmware` on the Pi, and the
partition your computer opens when you plug the card in). Raspberry Pi OS based on Debian 13
"trixie" reads three files from it on first boot with cloud-init: `meta-data`, `user-data`
(the user, SSH, hostname, and commands to run once) and `network-config` (Wi-Fi). Raspberry
Pi Imager 2 writes them from its customisation screen. Images based on Debian 12 "bookworm"
use the older `firstrun.sh` instead, which this module does not edit.

So this module adds Bento to what Imager wrote, and changes nothing else:

  * the leader's SSH public key on the card's user, so the leader can always reach the Pi;
  * `enable_ssh: true` (a Raspberry Pi OS cloud-init option), so it can;
  * one `runcmd`: wait for the network, then run the real installer as that user with the
    community's enrolment key. The Pi comes up waiting with that key, the leader hears it,
    and an automatic key sets it up as a member with an agent. Nobody types anything.
  * Wi-Fi in `network-config`, only when asked for (Imager usually wrote it already).

Merged, never replaced: Imager's user, password and locale stay exactly as written. The kit
is refused for a card that does not look like a Pi boot partition, and for a bookworm card,
in a sentence saying which road to take instead (the SSH install, remoteinstall.py).

The key travels on the card in clear (as `bento-enroll.txt` does): anyone holding the card
holds it. The docs say so, and a kit's key can be revoked in Settings like any other.
Kept free of HTTP; `bento pool sdcard PATH` writes it with the server down.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

LOG = "/var/log/bento-firstboot.log"
WIFI_RE = re.compile(r"[ -~]{1,32}")
COUNTRY_RE = re.compile(r"[A-Z]{2}")
HOST_RE = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")


class KitError(Exception):
    """A sentence for the person."""


def looks_like_boot(path: Path) -> str:
    """'' when `path` is a Raspberry Pi boot partition this kit can write, else why not."""
    if not path.is_dir():
        return f"{path} is not a folder (open the SD card's boot partition, called bootfs)"
    if not ((path / "config.txt").exists() or (path / "cmdline.txt").exists()):
        return f"{path} does not look like a Raspberry Pi boot partition (no config.txt)"
    if (path / "firstrun.sh").exists() and not (path / "user-data").exists():
        return ("this card is Raspberry Pi OS bookworm (it has firstrun.sh, not cloud-init). Use a "
                "trixie image, or let the leader install Bento over SSH once the Pi is on the network")
    return ""


def first_boot_command(url: str, user: str, key_text: str, extra: str = "") -> list:
    """The one command the card runs on first boot, as root: wait for the network, keep the
    user's services running without a login (linger), then run the installer AS that user
    with the enrolment key. Its output goes to LOG on the Pi."""
    inner = ("export XDG_RUNTIME_DIR=/run/user/$(id -u); "
             f"curl -fsSL {shlex.quote(url)} | {extra}sh -s -- --lite --enroll={shlex.quote(key_text)}")
    script = (f"for i in $(seq 1 60); do curl -fsI {shlex.quote(url)} >/dev/null 2>&1 && break; sleep 10; done; "
              f"loginctl enable-linger {shlex.quote(user)}; sleep 3; "
              f"runuser -l {shlex.quote(user)} -c {shlex.quote(inner)}")
    return ["sh", "-c", f"( {script} ) >>{LOG} 2>&1"]


def merge_user_data(existing: str, *, user: str, pubkey: str, command: list,
                    hostname: str = "") -> tuple[str, str]:
    """(new user-data text, the user it targets). Adds the leader's key to the card's user,
    `enable_ssh`, the hostname if given and the first-boot command; keeps everything else."""
    doc = {}
    if existing.strip():
        try:
            doc = yaml.safe_load(existing) or {}
        except yaml.YAMLError as e:
            raise KitError(f"the card's user-data is not valid YAML ({e.__class__.__name__}); "
                           f"write the card again with Raspberry Pi Imager") from e
        if not isinstance(doc, dict):
            raise KitError("the card's user-data is not a cloud-config document")
    users = doc.get("users") if isinstance(doc.get("users"), list) else []
    named = [u for u in users if isinstance(u, dict) and u.get("name")]
    target = None
    if user:
        target = next((u for u in named if u["name"] == user), None)
    elif named:
        target = named[0]
    if target is None:
        if not user:
            raise KitError("the card has no user yet. Set one in Raspberry Pi Imager (OS customisation), "
                           "or name one here")
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
            raise KitError("that is not a user name (lower-case letters, digits, - and _)")
        target = {"name": user, "groups": "users,adm,dialout,audio,netdev,video,plugdev,cdrom,games,"
                                          "input,gpio,spi,i2c,render,sudo",
                  "shell": "/bin/bash", "sudo": "ALL=(ALL) NOPASSWD:ALL", "lock_passwd": True}
        users.append(target)
    keys = target.get("ssh_authorized_keys") or []
    if pubkey and pubkey not in keys:
        keys.append(pubkey)
    if keys:
        target["ssh_authorized_keys"] = keys
    doc["users"] = users
    doc["enable_ssh"] = True
    if hostname:
        if not HOST_RE.fullmatch(hostname):
            raise KitError("a host name is lower-case letters, digits and hyphens")
        doc["hostname"] = hostname
    run = doc.get("runcmd") if isinstance(doc.get("runcmd"), list) else []
    run = [c for c in run if not (isinstance(c, list) and c[:2] == ["sh", "-c"] and LOG in str(c[-1]))]
    run.append(command)
    doc["runcmd"] = run
    return "#cloud-config\n" + yaml.safe_dump(doc, sort_keys=False, width=1000), target["name"]


def network_config(ssid: str, password: str, country: str, existing: str = "") -> str:
    """Wi-Fi for first boot, in the netplan v2 shape Raspberry Pi OS reads (NetworkManager)."""
    if not WIFI_RE.fullmatch(ssid or ""):
        raise KitError("a Wi-Fi name is 1 to 32 plain characters")
    if not (8 <= len(password or "") <= 63):
        raise KitError("a Wi-Fi password is 8 to 63 characters")
    country = (country or "").upper()
    if not COUNTRY_RE.fullmatch(country):
        raise KitError("the Wi-Fi country is two letters, like GB, IN or US")
    doc = {}
    if existing.strip():
        try:
            doc = yaml.safe_load(existing) or {}
        except yaml.YAMLError:
            doc = {}
    net = doc.get("network") if isinstance(doc.get("network"), dict) else {}
    net["version"] = 2
    wifis = net.get("wifis") if isinstance(net.get("wifis"), dict) else {}
    wifis["renderer"] = "NetworkManager"
    wl = wifis.get("wlan0") if isinstance(wifis.get("wlan0"), dict) else {}
    wl.update({"dhcp4": True, "regulatory-domain": country, "optional": True})
    aps = wl.get("access-points") if isinstance(wl.get("access-points"), dict) else {}
    aps[ssid] = {"password": password}
    wl["access-points"] = aps
    wifis["wlan0"] = wl
    net["wifis"] = wifis
    doc["network"] = net
    return yaml.safe_dump(doc, sort_keys=False, width=1000)


def write(path: str | Path, *, url: str, key_text: str, pubkey: str, user: str = "",
          hostname: str = "", wifi: dict | None = None, extra: str = "") -> dict:
    """Add Bento to the card's boot partition at `path`. Returns what was written."""
    p = Path(path)
    why = looks_like_boot(p)
    if why:
        raise KitError(why)
    ud = p / "user-data"
    existing = ud.read_text() if ud.exists() else ""
    # the user is decided before the command, because the command runs as that user
    probe_user = user
    if not probe_user and existing.strip():
        try:
            d = yaml.safe_load(existing) or {}
            probe_user = next((u["name"] for u in d.get("users") or [] if isinstance(u, dict) and u.get("name")), "")
        except Exception:
            probe_user = ""
    if not probe_user:
        raise KitError("the card has no user yet. Set one in Raspberry Pi Imager (OS customisation), "
                       "or name one here")
    cmd = first_boot_command(url, probe_user, key_text, extra)
    text, who = merge_user_data(existing, user=probe_user, pubkey=pubkey, command=cmd, hostname=hostname)
    ud.write_text(text)
    written = ["user-data"]
    if not (p / "meta-data").exists():
        (p / "meta-data").write_text("instance-id: bento-firstboot\n")
        written.append("meta-data")
    if wifi and wifi.get("ssid"):
        nc = p / "network-config"
        nc.write_text(network_config(wifi["ssid"], wifi.get("password", ""), wifi.get("country", ""),
                                     nc.read_text() if nc.exists() else ""))
        written.append("network-config")
    (p / "bento-enroll.txt").write_text(key_text + "\n")
    written.append("bento-enroll.txt")
    return {"written": written, "user": who, "log": LOG}

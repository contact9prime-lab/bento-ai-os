"""Devices on the local network that do NOT run Bento yet: found, recognised, offered.

Asked for as "discover the devices in the same network, or add a new device to the network
without Bento installed on it, and ask if you would like to install on it … the idea is
POAP: it connects to the network, DHCP gives it an IP, and Bento discovers it and asks".

A machine without Bento runs nothing of ours, so it cannot announce itself the way a waiting
Bento does (provision.py). What it DOES do is what every networked machine does, and that is
all this module reads:

  * ANNOUNCE ITS NAME. A Raspberry Pi running Raspberry Pi OS starts avahi on boot and says
    `raspberrypi.local is 192.168.1.40` to the mDNS group (224.0.0.251:5353) as soon as DHCP
    gave it an address. `MdnsEar` listens for that, passively: no packet is sent. It is the
    closest thing an ordinary program can do to watching DHCP, because DHCP's own port is a
    privileged one and its broadcasts are the router's business.
  * ANSWER ON A PORT. `scan()` knocks on TCP 22 (SSH) and Bento's own ports across this
    machine's own private networks, on request, reads the SSH banner (it names the OS) and the
    neighbour table (`/proc/net/arp`, which then holds each answerer's MAC address).
  * CARRY A MAKER IN ITS MAC. The first three bytes are registered to a maker; Raspberry Pi's
    are in `PI_OUIS`. A randomised (locally administered) address says nothing and is shown as
    private rather than guessed at.

What it will not do: scan anything but this machine's own private networks (RFC 1918 and
link-local, at most `MAX_HOSTS` addresses), scan on its own (a scan is a person's act, the
ear is passive), or log in anywhere. Installing is remoteinstall.py, behind a consent screen.

Kept free of HTTP: `bento pool devices` runs it with the server down.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
import struct
import time
from pathlib import Path

SSH_PORT = 22
BENTO_PORTS = (8321,)               # the desktop's default port
PROBE_TIMEOUT = 0.8
CONCURRENCY = 128
MAX_HOSTS = 1024                    # a /22: a home or an office, never the internet
MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353

# Registered to Raspberry Pi (the Foundation's first block, then Raspberry Pi Trading), from
# the IEEE register as listed by maclookup.app and netify.ai, checked 2026-10-09.
PI_OUIS = {"b8:27:eb": 2012, "dc:a6:32": 2019, "e4:5f:01": 2020, "28:cd:c1": 2021,
           "d8:3a:dd": 2022, "2c:cf:67": 2024}


# ---- this machine's networks ----------------------------------------------------------------

def _ifaddr(name: str, req: int) -> str:
    import fcntl
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        r = fcntl.ioctl(s.fileno(), req, struct.pack("256s", name[:15].encode()))
        return socket.inet_ntoa(r[20:24])
    finally:
        s.close()


def local_networks() -> list[ipaddress.IPv4Network]:
    """This machine's own private IPv4 networks, each capped at MAX_HOSTS (a bigger one is
    narrowed to the /24 this machine sits in). `AGENTOS_SCAN_NETWORKS` (comma-separated CIDRs)
    replaces the list, which is how a test points it at loopback and how a person names a
    network the interfaces do not show (a VPN)."""
    env = [x.strip() for x in os.environ.get("AGENTOS_SCAN_NETWORKS", "").split(",") if x.strip()]
    if env:
        return [ipaddress.ip_network(x, strict=False) for x in env]
    out: list = []
    try:
        names = [n for _, n in socket.if_nameindex()]
    except OSError:
        names = []
    for n in names:
        try:
            addr, mask = _ifaddr(n, 0x8915), _ifaddr(n, 0x891B)   # SIOCGIFADDR, SIOCGIFNETMASK
        except Exception:
            continue
        ip = ipaddress.ip_address(addr)
        if ip.is_loopback or not (ip.is_private or ip.is_link_local):
            continue
        net = ipaddress.ip_network(f"{addr}/{mask}", strict=False)
        if net.num_addresses > MAX_HOSTS:
            net = ipaddress.ip_network(f"{addr}/24", strict=False)
        if net not in out:
            out.append(net)
    return out


def allowed(ip: str) -> bool:
    """Only a private or link-local address is ever knocked on or offered an install."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if os.environ.get("AGENTOS_SCAN_NETWORKS") and a.is_loopback:
        return True                     # the tests' stand-in network
    return (a.is_private or a.is_link_local) and not a.is_loopback


# ---- who is who -------------------------------------------------------------------------------

def neighbours(text: str | None = None) -> dict[str, str]:
    """IP → MAC from the kernel's neighbour table. Linux only; elsewhere {}."""
    if text is None:
        try:
            text = Path("/proc/net/arp").read_text()
        except OSError:
            return {}
    out = {}
    for ln in text.splitlines()[1:]:
        f = ln.split()
        if len(f) >= 4 and re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", f[3].lower()) \
                and f[3] != "00:00:00:00:00:00":
            out[f[0]] = f[3].lower()
    return out


def maker(mac: str) -> str:
    """'Raspberry Pi', 'private address' for a randomised one, or ''."""
    mac = str(mac or "").lower()
    if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
        return ""
    if mac[:8] in PI_OUIS:
        return "Raspberry Pi"
    if int(mac[:2], 16) & 0x02:
        return "private address"       # locally administered: randomised by a phone or laptop
    return ""


def os_from_banner(banner: str) -> str:
    """'Debian 13 (trixie)' from 'SSH-2.0-OpenSSH_10.0p2 Debian-7', roughly. The banner is
    the other machine's words, so this only ever reads it, and only for a hint."""
    b = str(banner or "")
    m = re.search(r"(Debian|Raspbian|Ubuntu)", b)
    if not m:
        return ""
    who = m.group(1)
    if who == "Debian":
        # the package revision maps to a release: deb13 / 10.0p is trixie, deb12 / 9.2p bookworm
        if "deb13" in b or "OpenSSH_10" in b:
            return "Debian 13 (trixie)"
        if "deb12" in b or "OpenSSH_9.2" in b:
            return "Debian 12 (bookworm)"
        return "Debian"
    return who                          # Ubuntu's revision ("3ubuntu13") is not a release


def looks_like_pi(d: dict) -> bool:
    n = str(d.get("name") or "").lower()
    return d.get("maker") == "Raspberry Pi" or n.startswith("raspberrypi") or "raspbian" in str(
        d.get("banner") or "").lower()


# ---- knocking -------------------------------------------------------------------------------

async def _knock(ip: str, port: int, timeout: float, banner_too: bool = False) -> str | None:
    """'' when the port answered, its SSH banner when `banner_too`, None when it did not."""
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return None
    banner = ""
    try:
        if banner_too:
            banner = (await asyncio.wait_for(r.readline(), timeout)).decode(errors="replace").strip()[:120]
    except Exception:
        pass
    finally:
        w.close()
    return banner


async def _name(ip: str) -> str:
    try:
        n = await asyncio.wait_for(asyncio.to_thread(socket.gethostbyaddr, ip), 1.5)
        return n[0][:63]
    except Exception:
        return ""


def ports() -> tuple[int, ...]:
    """The ports knocked on. `AGENTOS_SCAN_PORTS` stands a test's ports in for 22 and 8321."""
    env = os.environ.get("AGENTOS_SCAN_PORTS", "")
    if env:
        return tuple(int(x) for x in env.split(",") if x.strip().isdigit())
    return (SSH_PORT,) + BENTO_PORTS


async def scan(networks: list | None = None, timeout: float = PROBE_TIMEOUT) -> list[dict]:
    """Knock on SSH and Bento's port across this machine's own networks. Returns every
    address that answered: its name, its maker, its SSH banner and an OS hint."""
    nets = networks if networks is not None else local_networks()
    mine = set()
    try:
        mine = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except Exception:
        pass
    targets = []
    for net in nets:
        hosts = list(net.hosts()) if net.num_addresses > 2 else list(net)
        for h in hosts[:MAX_HOSTS]:
            ip = str(h)
            if allowed(ip) and ip not in mine:
                targets.append(ip)
    targets = targets[:MAX_HOSTS]
    ps = ports()
    ssh_port = ps[0]
    sem = asyncio.Semaphore(CONCURRENCY)
    found: dict = {}

    async def one(ip):
        async with sem:
            got = await asyncio.gather(*[_knock(ip, p, timeout, p == ssh_port) for p in ps])
        open_ = [p for p, g in zip(ps, got) if g is not None]
        if open_:
            found[ip] = {"ip": ip, "ports": open_, "ssh": ssh_port in open_, "banner": got[0] or ""}

    await asyncio.gather(*[one(ip) for ip in targets])
    macs = neighbours()
    names = await asyncio.gather(*[_name(ip) for ip in found])
    out = []
    for (ip, d), n in zip(found.items(), names):
        mac = macs.get(ip, "")
        d.update(mac=mac, maker=maker(mac), name=n, os=os_from_banner(d["banner"]))
        d["pi"] = looks_like_pi(d)
        out.append(d)
    return sorted(out, key=lambda d: tuple(int(x) for x in d["ip"].split(".")))


# ---- the passive ear: mDNS announcements -------------------------------------------------------

def _dns_name(buf: bytes, off: int, depth: int = 0) -> tuple[str, int]:
    labels, jumped, end = [], False, off
    while True:
        if off >= len(buf) or depth > 20:
            raise ValueError("bad name")
        n = buf[off]
        if n == 0:
            off += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = ((n & 0x3F) << 8) | buf[off + 1]
            if not jumped:
                end = off + 2
            name, _ = _dns_name(buf, ptr, depth + 1)
            labels.append(name)
            jumped = True
            break
        labels.append(buf[off + 1:off + 1 + n].decode(errors="replace"))
        off += 1 + n
    return ".".join(x for x in labels if x), (end if jumped else off)


def parse_mdns(buf: bytes) -> list[tuple[str, str]]:
    """(name, IPv4) pairs from the A records of one mDNS message, answers and additionals.
    A malformed packet gives []; it is somebody else's bytes."""
    try:
        _id, flags, qd, an, ns, ar = struct.unpack("!6H", buf[:12])
        if not flags & 0x8000:
            return []                  # a question, not an answer
        off = 12
        for _ in range(qd):
            _, off = _dns_name(buf, off)
            off += 4
        out = []
        for _ in range(an + ns + ar):
            name, off = _dns_name(buf, off)
            rtype, _cls, _ttl, rdlen = struct.unpack("!HHIH", buf[off:off + 10])
            off += 10
            if rtype == 1 and rdlen == 4:
                out.append((name.lower().rstrip("."), socket.inet_ntoa(buf[off:off + 4])))
            off += rdlen
        return out
    except Exception:
        return []


class MdnsEar:
    """Listens on the mDNS group for machines saying their name. Sends nothing. A machine
    whose bind fails (another program owns 5353 without sharing it) just has no ear, and the
    scan button still works."""

    def __init__(self, on_seen):
        self.on_seen = on_seen          # (name, ip) for every A record heard
        self.tr = None

    async def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", int(os.environ.get("AGENTOS_MDNS_PORT") or MDNS_PORT)))
        mreq = struct.pack("4s4s", socket.inet_aton(MDNS_GROUP), socket.inet_aton("0.0.0.0"))
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        except OSError:
            pass                        # no multicast route (a container): unicast tests still work
        s.setblocking(False)
        loop = asyncio.get_running_loop()
        ear = self

        class P(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                if len(data) > 9000:
                    return
                for name, ip in parse_mdns(data):
                    if name.endswith(".local") and allowed(ip):
                        try:
                            ear.on_seen(name[:-6], ip)
                        except Exception:
                            pass

        self.tr, _ = await loop.create_datagram_endpoint(P, sock=s)
        return self

    async def stop(self):
        if self.tr:
            self.tr.close()
            self.tr = None


# ---- what was seen ----------------------------------------------------------------------------

def remember(seen: dict, d: dict) -> bool:
    """Fold a device into `seen` (keyed by MAC when known, else IP). True the first time a
    device is seen, which is when a Pi is worth a toast."""
    key = d.get("mac") or d.get("ip")
    if not key:
        return False
    if key not in seen and d.get("ip"):
        # heard by name first (no MAC yet), knocked on later (MAC known): one device, not two
        for k, e in list(seen.items()):
            if e.get("ip") == d["ip"] and not (d.get("mac") and e.get("mac")):
                if k != key and d.get("mac"):
                    seen[key] = seen.pop(k)
                else:
                    key = k
                break
    e = seen.get(key)
    new = e is None
    e = e or {"first": time.time(), "state": "new"}
    for k in ("ip", "mac", "maker", "name", "ssh", "banner", "os", "pi", "ports"):
        if d.get(k) not in (None, "", []):
            e[k] = d[k]
    e["last"] = time.time()
    seen[key] = e
    if len(seen) > 256:
        for k, _ in sorted(seen.items(), key=lambda kv: kv[1].get("last", 0))[:len(seen) - 256]:
            seen.pop(k, None)
    return new

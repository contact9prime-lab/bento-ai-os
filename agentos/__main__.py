"""Entry point: `agentos` serves the UI; `agentos ask "..."` runs a one-shot agent in the terminal."""

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import webbrowser


def _use_system_certs():
    # verify TLS against the OS trust store instead of certifi's bundled CAs
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def serve(host: str, port: int, open_browser: bool):
    import uvicorn
    from . import config as cfgmod
    from . import remote as remotemod
    cfg = remotemod.sanitize_remote(cfgmod.load_config())
    port = port or cfg.get("port", 8321)

    # Binding off-loopback is the one thing this program will not do on a flag
    # alone. AgentOS hands whoever loads it a real shell, so listening on the
    # network requires the passphrase that guards it — set it in
    # Settings → Remote access (or `agentos remote --passphrase ...`).
    if host == "127.0.0.1" and remotemod.enabled(cfg):
        host = remotemod.bind_host(cfg)          # the setting opts in; honour it
    if not remotemod.is_loopback(host) and not remotemod.enabled(cfg):
        print(f"Refusing to serve on {host}: remote access is off.\n"
              f"  AgentOS has no login until you give it one, and the agent has a real\n"
              f"  shell — an open port here is an open shell.\n"
              f"  Turn it on:  agentos serve   (then Settings → Remote access)\n"
              f"  or headless: agentos remote --on --passphrase '<something long>'")
        sys.exit(4)
    os.environ["AGENTOS_BOUND_HOST"] = host
    url = f"http://{host}:{port}"
    if not _port_free(host, port):
        # bail BEFORE the app's startup hook runs: a doomed instance must not spawn
        # MCP servers / scheduler / telegram or write to the DB it shares with the
        # instance that actually owns the port
        print(f"AgentOS is already running (or something else holds {host}:{port}).\n"
              f"  open it:            {url}\n"
              f"  or stop the owner:  systemctl --user stop agentos   (if installed as a service)\n"
              f"  or pick a port:     agentos serve --port <other>")
        sys.exit(3)
    print(f"""
  ┌─────────────────────────────────────┐
  │   ▲ AgentOS                         │
  │   your machine, with a brain        │
  │                                     │
  │   {url:<34}│
  └─────────────────────────────────────┘
""")
    if remotemod.enabled(cfg):
        print("  remote access is ON — this desktop is reachable from your network:")
        for a in remotemod.lan_addresses(port):
            print(f"    {a}")
        print("  sign in with your passphrase; local use is unchanged.\n")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run("agentos.server:app", host=host, port=port, log_level="warning")


def ask(prompt: str, model: str | None, full: bool):
    from . import config as cfgmod
    from .agent import Agent
    from .memory import Store
    from .tools import Toolbox

    cfg = cfgmod.load_config()
    cfgmod.ensure_dirs(cfg)
    if cfgmod.is_first_run():
        print("Tip: run `agentos setup` for first-time setup (model, autonomy, boot autostart).\n")
    if full:
        cfg["autonomy"] = "full"
    store = Store(cfgmod.DB_PATH)
    toolbox = Toolbox(cfg, store)

    async def emit(ev):
        if ev["type"] == "text_delta":
            sys.stdout.write(ev["text"])
            sys.stdout.flush()
        elif ev["type"] == "tool_start":
            args = json.dumps(ev["args"])
            print(f"\n\033[36m▸ {ev['name']} {args[:160]}\033[0m")
        elif ev["type"] == "tool_end":
            out = ev["output"].strip()
            if out:
                shown = "\n".join(out.splitlines()[:12])
                print(f"\033[90m{shown}\033[0m")
        elif ev["type"] == "error":
            print(f"\033[31merror: {ev['message']}\033[0m")

    async def approver(name, args, reason) -> bool:
        print(f"\n\033[33m⚠ approval needed: {name} {json.dumps(args)[:200]}\n  {reason}\033[0m")
        ans = input("  allow? [y/N] ").strip().lower()
        return ans in ("y", "yes")

    async def main_async():
        model_id = model or cfg.get("default_model", "")
        if not model_id:
            from . import providers
            models = await providers.available_models(cfg)
            if not models:
                print("No models available. Start Ollama or add an API key via the UI (`agentos`).")
                return
            model_id = models[0]["id"]
        agent = Agent(cfg, toolbox, model_id, emit, approver)
        await agent.run([{"role": "user", "content": prompt}])
        print()

    asyncio.run(main_async())


def doctor(fix: bool = False):
    """Environment sanity: the checks that catch every 'it hangs' class of incident.
    With fix=True, auto-remediate what is safe to fix and print sudo steps for the rest."""
    import json as _json
    import shutil
    import socket
    import sqlite3
    import subprocess
    import urllib.request
    from . import config as cfgmod

    ok = lambda m: print(f"  \033[32m✓\033[0m {m}")           # noqa: E731
    warn = lambda m: print(f"  \033[33m!\033[0m {m}")         # noqa: E731
    bad = lambda m: print(f"  \033[31m✗\033[0m {m}")          # noqa: E731
    fixed = lambda m: print(f"  \033[36m⚑ fixed:\033[0m {m}")  # noqa: E731
    todo = lambda m: print(f"  \033[35m→ do:\033[0m {m}")     # noqa: E731

    def run(argv):
        try:
            return subprocess.run(argv, capture_output=True, text=True, timeout=15)
        except Exception:
            return None

    cfg = cfgmod.load_config()
    port = cfg.get("port", 8321)
    print("AgentOS doctor" + ("  (--fix: auto-repair on)" if fix else "") + "\n")

    # 1. who owns the port?
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build/status", timeout=3) as r:
            _json.loads(r.read())
        ok(f"server responding on 127.0.0.1:{port}")
    except Exception:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                bad(f"port {port} is taken but does not answer like AgentOS — another app owns it")
            else:
                warn(f"no server on port {port} (start with: agentos serve)")

    # 2. duplicate instances (the crash-loop incident class)
    try:
        out = subprocess.run(["pgrep", "-fc", "agentos serve"], capture_output=True, text=True)
        n = int(out.stdout.strip() or 0)
        if n > 1:
            bad(f"{n} 'agentos serve' processes are running — they will fight over the port and the DB")
        elif n == 1:
            ok("exactly one server process")
    except Exception:
        pass
    r = run(["systemctl", "--user", "is-active", "agentos"])
    if r is not None:
        st = r.stdout.strip()
        if st == "activating":
            bad("systemd unit 'agentos' is crash-looping (activating)")
            if fix:
                # if something already answers the port, the unit is the loser of a
                # port war and should stand down; otherwise stopping is still safe
                run(["systemctl", "--user", "stop", "agentos"])
                after = run(["systemctl", "--user", "is-active", "agentos"])
                if after and after.stdout.strip() != "activating":
                    fixed("stopped the crash-looping unit (re-enable later with: "
                          "systemctl --user start agentos)")
                else:
                    todo("systemctl --user stop agentos   (couldn't stop it automatically)")
            else:
                todo("agentos doctor --fix   (or: systemctl --user stop agentos)")
        elif st == "active":
            ok("systemd user service active")
        else:
            warn(f"systemd user service: {st}")

    # 3. Ollama + VRAM pressure
    base = cfg["providers"]["ollama"]["base_url"]
    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=3) as r:
            loaded = _json.loads(r.read()).get("models", [])
        ok(f"ollama up at {base} ({len(loaded)} model(s) loaded)")
        for m in loaded:
            gb = m.get("size_vram", 0) / 1e9
            pinned = (str(m.get("expires_at", "")).startswith("2")
                      and int(str(m.get("expires_at", "0"))[:4] or 0) > 2100)
            (warn if pinned else ok)(
                f"  loaded: {m['name']} ({gb:.1f}GB VRAM)"
                + (" — pinned forever (keep_alive=-1)" if pinned else ""))
            if pinned and fix:
                try:
                    req = urllib.request.Request(
                        f"{base}/api/generate", method="POST",
                        data=_json.dumps({"model": m["name"], "keep_alive": 0}).encode(),
                        headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=10).read()
                    fixed(f"released {m['name']} from VRAM (keep_alive=0 for this run)")
                except Exception:
                    todo(f"ollama stop {m['name']}")
    except Exception:
        warn(f"ollama not reachable at {base} (local models unavailable)")
    # exposure check: an unauthenticated Ollama on 0.0.0.0 is reachable by the whole LAN
    r = run(["ss", "-tln"])
    if r is not None:
        for line in r.stdout.splitlines():
            if ":11434" in line and ("0.0.0.0:11434" in line or "*:11434" in line or "[::]:11434" in line):
                bad("ollama listens on ALL interfaces (OLLAMA_HOST=0.0.0.0) — the LAN can use it")
                # needs root to edit the service → always guidance, never auto-sudo
                todo("set OLLAMA_HOST=127.0.0.1: edit /etc/systemd/system/ollama.service.d/*.conf "
                     "(or `launchctl setenv` on macOS), then restart ollama")
                break

    # 4. DB
    try:
        db = sqlite3.connect(str(cfgmod.DB_PATH), timeout=3)
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        if mode != "wal" and fix:
            new = db.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            db.execute("PRAGMA busy_timeout=5000")
            if new == "wal":
                fixed("set db journal_mode=WAL")
                mode = new
        integ = db.execute("PRAGMA integrity_check").fetchone()[0]
        (ok if mode == "wal" else warn)(f"db journal_mode={mode}")
        (ok if integ == "ok" else bad)(f"db integrity: {integ}")
    except Exception as e:
        bad(f"db check failed: {e}")

    # 5. optional companions
    ok("git available" if shutil.which("git") else "")
    if not shutil.which("git"):
        warn("git not installed — the Ship pillar (git_* tools) needs it")
    from .tools import sandbox_mechanism
    mech = sandbox_mechanism()
    if mech:
        ok(f"sandbox available ({mech})")
    elif sys.platform == "linux":
        warn("bubblewrap missing — sandbox falls back to unjailed commands (install: apt install bubblewrap)")
    else:
        warn("no sandbox mechanism found — shell commands run unjailed")
    from . import trainforge as tfmod
    tf = tfmod.conf(cfg)
    if tf["path"]:
        ok(f"TrainForge found at {tf['path']} (Train pillar)")
    elif tf.get("repo") and "YOUR_ORG" not in tf["repo"]:
        warn("TrainForge not installed — the Train app will fetch it on first Start")
    else:
        warn("TrainForge not found — set trainforge.path or trainforge.repo to enable the Train pillar")

    from . import hermes as hermesmod
    hcli = hermesmod.cli_path()
    if hcli:
        ok(f"Hermes companion agent available ({'gateway running' if hermesmod.gateway_running() else 'installed'})")

    # 6. the desktop (AgentOS-as-the-DE)
    if sys.platform == "linux":
        from pathlib import Path as _P

        from . import compositor as compmod
        from . import runmode
        effective, detected = runmode.resolve(cfg)
        ok(f"desktop mode: {effective}"
           + (f" (pinned; detected {detected})" if effective != detected else "")
           + f" — session type {os.environ.get('XDG_SESSION_TYPE', 'unknown')}")

        wl_entry = _P("/usr/share/wayland-sessions/agentos.desktop")
        x_entry = _P("/usr/share/xsessions/agentos.desktop")
        if wl_entry.exists():
            ok("AgentOS Wayland session installed (pick it at the login screen)")
        elif x_entry.exists():
            warn("only the legacy X11 AgentOS session is installed — "
                 "`agentos install-session` adds the Wayland one")
        else:
            warn("AgentOS is not installed as a login session — `agentos install-session`")

        if shutil.which("sway"):
            if compmod.available():
                try:
                    n = len(compmod.Compositor().windows())
                    ok(f"compositor reachable on $SWAYSOCK ({n} managed windows)")
                except Exception as e:
                    bad(f"compositor socket present but not answering: {e}")
                _doctor_session_handover(compmod, effective, runmode, ok, warn, bad)
            elif effective == runmode.DE:
                bad("in DE mode but $SWAYSOCK is not set — window management is dead")
            else:
                ok("sway installed (compositor for the AgentOS session)")
        elif wl_entry.exists() or effective == runmode.DE:
            bad("sway is not installed but the AgentOS session expects it — apt install sway")
        else:
            warn("sway not installed — needed only for the AgentOS Wayland session")

        # How the desktop gets DRAWN, which decides whether it is a real desktop
        # surface or a window pretending to be one.
        from . import shellhost as _sh
        from . import desktop as desktopmod
        # A previous login tried the native surface and got nothing on screen, so
        # the session launcher parked it. Say so loudly: otherwise the machine
        # silently keeps using the fallback and nobody knows why.
        _lsfail = cfgmod.AGENTOS_HOME / "layer-shell-failed"
        if _lsfail.is_file():
            warn("the native desktop surface is DISABLED — it failed to render here")
            for _line in _lsfail.read_text().splitlines()[:2]:
                print(f"      {_line}")
            if fix:
                _lsfail.unlink()
                fixed("cleared the flag — the next login will try the native surface again")
            else:
                todo(f"agentos doctor --fix   (or: rm {_lsfail})   to try it again")
        _py, _wk = _sh.python_with_gi()
        if _py and not _lsfail.is_file():
            ok(f"native desktop surface available (WebKit2GTK {_wk} via {_py})")
            ok("  → app windows stack above the desktop natively; the menu bar and dock "
               "are reserved with the compositor")
        elif _py:
            pass                        # already reported as disabled above
        else:
            warn("no native desktop surface — the session will draw the desktop in a "
                 "Chromium window instead, which has to fake the stacking order")
            todo(_sh.install_hint())
        if desktopmod.find_browser():
            ok("Chromium-family browser found (the fallback renderer, and the Web app)")
        elif not _py:
            bad("nothing can draw the desktop: no WebKitGTK layer-shell stack and no "
                "chromium-family browser")
        else:
            warn("no chromium-family browser (only needed as the fallback renderer)")

        # The browser remote desktop: reachable from a phone with nothing on it.
        from . import remotedesktop as _rd
        _have = _rd.available()
        if _have["wayvnc"] and _have["novnc"]:
            ok("Remote Desktop ready (wayvnc + noVNC) — usable from a phone browser")
        elif _have["wayvnc"]:
            warn("wayvnc is installed but noVNC is not — remote control needs a VNC "
                 "client app until you add it (apt install novnc)")
        else:
            warn("Remote Desktop not installed (apt install wayvnc novnc) — optional")

        try:
            from . import session as _sess
            if _sess.SWAY_CONF.is_file() and _sess.config_is_stale():
                if fix:
                    _changed, _how = _sess.refresh_config()
                    fixed(f"compositor config was from an older AgentOS — {_how}")
                else:
                    bad("the installed compositor config is older than this AgentOS. "
                        "Window rules shipped since you installed the session are not "
                        "active — that is what 'no window controls' and 'apps always on "
                        "top' look like")
                    todo("agentos doctor --fix   (or `agentos install-session` again)")
            elif _sess.SWAY_CONF.is_file():
                ok("compositor config matches this version of AgentOS")
        except Exception:
            pass

        if effective == runmode.DE and os.environ.get("AGENTOS_SESSION") != "1":
            warn("server reports DE mode but wasn't started by the session launcher — "
                 "a stale server from another session may be holding the port")

        # NVIDIA + wlroots: modeset must be on for the session to light up.
        # (Some driver builds make this file root-only — unreadable is not a finding.)
        try:
            modeset = _P("/sys/module/nvidia_drm/parameters/modeset").read_text().strip()
        except OSError:
            modeset = ""
        if modeset and modeset not in ("Y", "1"):
            warn("NVIDIA without nvidia-drm.modeset=1 — the Wayland session may not start "
                 "on this GPU (add nvidia-drm.modeset=1 to the kernel cmdline, or let it "
                 "use the iGPU)")

        from .hostctl import audio as _au
        from .hostctl import bluetooth as _bt
        from .hostctl import brightness as _br
        from .hostctl import network as _net
        for label, avail in (("wifi control (NetworkManager)", _net.available()[:2]),
                             ("bluetooth (BlueZ)", _bt.available()[:2]),
                             ("audio devices (PipeWire)", _au.available()[:2]),
                             ("brightness", _br.available()[:2])):
            avail_ok, why = avail
            if avail_ok:
                ok(label)
            else:
                warn(f"{label}: {why}")
    print()
    if not fix:
        print("  \033[90mrun `agentos doctor --fix` to auto-repair the fixable items above\033[0m\n")



def _doctor_session_handover(compmod, effective, runmode, ok, warn, bad):
    """The three facts that decide whether launching an app actually works.

    Every one of these was broken at some point in a way no unit test could see,
    because they are properties of a LIVE compositor: the desktop has to be
    findable, it has to be able to step back, and a command has to survive sway's
    own parser on the way to the shell.
    """
    if effective != runmode.DE:
        return
    C = compmod.Compositor()
    port = compmod.shell_port()

    shell = ""
    try:
        shell = C.find_shell(port)
    except Exception as e:
        bad(f"could not look for the desktop window: {e}")
    if shell:
        ok(f"the desktop window is identifiable (con_id {shell}) — raise/lower can work")
    else:
        bad(f"the desktop window was NOT found on port {port}. Launching an app cannot "
            f"lower it, so the app will open behind a screen-filling window and look "
            f"like nothing happened")

    # can the desktop actually step back? do it and put it straight back.
    if shell:
        try:
            was = compmod.SHELL_RAISED[0]
            C.raise_shell(False)
            floating = next((w["floating"] for w in C.windows(include_shell=True)
                             if w["id"] == shell), None)
            if floating:
                warn("the desktop is still floating after being lowered — apps will be "
                     "painted underneath it")
            else:
                ok("the desktop steps back on demand (apps can come to the front)")
            if was:
                C.raise_shell(True)
        except Exception as e:
            bad(f"lowering the desktop failed: {e}")

    # does a command survive sway's parser? `,` and `;` are separators to it, and
    # real .desktop Exec lines are full of them.
    try:
        C.exec("sh -c 'exit 0'  # agentos doctor, ignore")
        ok("the compositor accepts launch commands verbatim (.desktop Exec lines are safe)")
    except Exception as e:
        bad(f"the compositor rejected a launch command: {e}")


def _apps_cli(args):
    """Native applications from a terminal.

    The same catalogue and the same consent ladder as the desktop's
    Applications -> Get apps. It exists because a headless Pi reached over SSH is
    a first-class way to run AgentOS, and "install this program" is the most
    ordinary thing anyone does with a machine.
    """
    from . import appstore
    b = appstore.backends()
    if not appstore.available():
        print("No package manager found (looked for flatpak, apt, dnf, pacman).")
        sys.exit(1)

    if args.action == "list" and not args.name:
        print("available here: " + ", ".join(k for k, v in b.items() if v and k != "needs_root"))
        print("\n  agentos apps search <query>")
        print("  agentos apps install <package> [--backend flatpak|apt|dnf|pacman]")
        print("  agentos apps remove  <package>")
        return

    if args.action in ("list", "search"):
        res = asyncio.run(appstore.search(args.name, 40))
        if res.get("message"):
            print(res["message"])
        for r in res["results"]:
            mark = "installed" if r["installed"] else ""
            print(f"  {r['name'][:34]:36} {r['backend']:8} {mark:9} {r['summary'][:60]}")
        if not res["results"]:
            print("  nothing matched")
        return

    if not args.name:
        print(f"which package? e.g. agentos apps {args.action} gimp")
        sys.exit(2)
    # Say what will run before running it. This is someone's machine.
    print(f"{args.action}: {args.name}"
          + (f" (via {args.backend})" if args.backend else ""))
    res = asyncio.run(appstore.act(args.action, args.name, args.backend))
    if res.get("command"):
        print(f"  $ {res['command']}")
    print(("✓ " if res.get("ok") else "✗ ") + (res.get("message") or ""))
    sys.exit(0 if res.get("ok") else 1)


def _remote_desktop_cli(args):
    """Turn the browser remote desktop on or off without a desktop to click in.

    This is the switch you want over SSH: enable it, then open the machine's
    AgentOS address on your phone and go to /remote-desktop. The VNC server it
    starts is bound to 127.0.0.1 — AgentOS relays it over the connection your
    passphrase already protects.
    """
    import urllib.error
    import urllib.request
    from . import config as cfgmod
    from . import remotedesktop as rd

    port = cfgmod.load_config().get("port", 8321)
    base = f"http://127.0.0.1:{port}"
    have = rd.available()

    def call(path, data=None):
        req = urllib.request.Request(base + path, method="POST" if data else "GET",
                                     data=json.dumps(data).encode() if data else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return {"error": json.loads(e.read() or b"{}").get("error", str(e))}
        except Exception as e:                                    # noqa: BLE001
            return {"error": f"{e} — is AgentOS running? (agentos serve)"}

    if args.on or args.off:
        if args.on and not (have["wayvnc"] and have["novnc"]):
            missing = [n for n in ("wayvnc", "novnc") if not have[n]]
            print(f"! {' and '.join(missing)} not installed — the packages that make this work.")
            print(f"    sudo apt install {' '.join(missing)}")
            sys.exit(1)
        res = call("/api/screen/control", {"action": "start" if args.on else "stop"})
        if res.get("error"):
            print(f"✗ {res['error']}")
            sys.exit(1)
        print("✓ remote desktop " + ("on" if args.on else "off"))

    st = call("/api/screen/control")
    if st.get("error"):
        print(f"  ({st['error']})")
        return
    print(f"  wayvnc installed : {st.get('installed')}")
    print(f"  noVNC client     : {st.get('novnc')}")
    print(f"  running          : {st.get('running')}")
    if st.get("running"):
        from . import remote as remotemod
        print("  open on your phone:")
        for a in (remotemod.lan_addresses(port) or [f"http://127.0.0.1:{port}"]):
            print(f"    {a.rstrip('/')}/remote-desktop")
        print("  (sign in with your AgentOS passphrase; the VNC port stays on 127.0.0.1)")


def _remote_cli(args):
    """`agentos remote` — the headless equivalent of Settings → Remote access,
    for machines you only ever reach over SSH (a Pi, a server)."""
    import getpass

    from . import config as cfgmod
    from . import remote as remotemod
    cfg = remotemod.sanitize_remote(cfgmod.load_config())
    r = cfg.setdefault("remote", {})

    pw = args.passphrase
    if args.on and not pw and not r.get("pass_hash"):
        pw = getpass.getpass("Set a remote-access passphrase: ")
        if pw != getpass.getpass("Repeat it: "):
            print("those did not match")
            sys.exit(1)
    if pw:
        problem = remotemod.passphrase_problem(pw)
        if problem:
            print(f"passphrase: {problem}")
            sys.exit(1)
        r["pass_hash"], r["pass_salt"] = remotemod.hash_passphrase(pw)
    if args.bind:
        r["bind"] = args.bind
    if args.on:
        if not r.get("pass_hash"):
            print("set a passphrase first: agentos remote --on --passphrase '<something long>'")
            sys.exit(1)
        r["enabled"] = True
    if args.off:
        r["enabled"] = False
    if args.on or args.off or pw or args.bind:
        remotemod.sanitize_remote(cfg)
        cfgmod.save_config(cfg)

    st = remotemod.status(cfg)
    print(f"remote access: {'ON' if st['enabled'] else 'off'}"
          f"{'' if st['configured'] else '  (no passphrase set)'}")
    print(f"  binds:   {remotemod.bind_host(cfg)}:{st['port']}")
    for a in st["addresses"]:
        print(f"  reach:   {a}")
    if st["enabled"]:
        print("  restart AgentOS for a bind change to take effect.")


def main():
    _use_system_certs()
    parser = argparse.ArgumentParser(prog="agentos", description="AgentOS — your machine, with a brain.")
    sub = parser.add_subparsers(dest="cmd")

    p_serve = sub.add_parser("serve", help="start the AgentOS server + UI (default)")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=0)
    p_serve.add_argument("--no-browser", action="store_true")

    p_ask = sub.add_parser("ask", help="one-shot agent run in the terminal")
    p_ask.add_argument("prompt", nargs="+")
    p_ask.add_argument("--model", default=None, help="e.g. ollama/qwen3.5:9b")
    p_ask.add_argument("--full", action="store_true", help="full autonomy (no approval prompts)")

    sub.add_parser("app", help="open AgentOS as a desktop app window")
    p_doctor = sub.add_parser("doctor", help="check the environment: port conflicts, duplicate instances, Ollama/VRAM, DB health")
    p_doctor.add_argument("--fix", action="store_true", help="auto-repair what's safe; print sudo steps for the rest")
    sub.add_parser("tui", help="terminal UI — the AgentOS agent in your terminal (great over SSH)")
    sub.add_parser("setup", help="first-time setup wizard (name, model, autonomy, autostart)")
    p_install = sub.add_parser("install", help="install app launcher + boot service + login autostart")
    p_install.add_argument("--no-service", action="store_true",
                           help="launcher only; skip the background boot service")
    p_install.add_argument("--no-login", action="store_true",
                           help="don't open AgentOS automatically at login")
    sub.add_parser("uninstall", help="remove launcher + boot service")
    p_auto = sub.add_parser("autostart", help="open AgentOS at login (on) or stop (--off)")
    p_auto.add_argument("--off", action="store_true", help="disable login autostart")
    p_sess = sub.add_parser("install-session",
                            help="add AgentOS as a login session (Linux only) — pick it at the login screen, "
                                 "or --autologin to boot straight into it")
    p_sess.add_argument("--wayland", action="store_true",
                        help="the sway-based Wayland session (default)")
    p_sess.add_argument("--x11", action="store_true",
                        help="the older X11 kiosk session instead")
    p_sess.add_argument("--autologin", action="store_true",
                        help="boot tty1 straight into AgentOS, no login screen (reversible; prints the escape hatch)")
    p_sess.add_argument("--force", action="store_true",
                        help="allow --autologin over SSH")
    p_sess.add_argument("--remove", action="store_true", help="remove the AgentOS session")
    p_remote = sub.add_parser("remote", help="show or change remote access (reach this desktop from your phone)")
    p_remote.add_argument("--on", action="store_true", help="enable remote access (needs a passphrase)")
    p_remote.add_argument("--off", action="store_true", help="disable it and go back to loopback only")
    p_remote.add_argument("--passphrase", default="", help="set the sign-in passphrase (prompted if omitted)")
    p_remote.add_argument("--bind", default="", help="interface to listen on once enabled (default 0.0.0.0)")

    # Every graphical capability needs a way in from a terminal too — a headless
    # Pi reached over SSH is a first-class way to run AgentOS, not an edge case.
    p_apps = sub.add_parser("apps", help="find, install and remove native applications")
    p_apps.add_argument("action", nargs="?", default="list",
                        choices=["list", "search", "install", "remove"])
    p_apps.add_argument("name", nargs="?", default="", help="query, or the package to act on")
    p_apps.add_argument("--backend", default="", help="flatpak, apt, dnf or pacman")

    p_rd = sub.add_parser("remote-desktop",
                          help="the browser remote desktop — use the real screen from a phone")
    p_rd.add_argument("--on", action="store_true", help="start it")
    p_rd.add_argument("--off", action="store_true", help="stop it")

    p_mode = sub.add_parser("session", help="show or pin the desktop run mode (auto | de | hosted | kiosk)")
    p_mode.add_argument("action", nargs="?", default="show", choices=["show", "mode", "run"])
    p_mode.add_argument("value", nargs="?", default="",
                        help="with `mode`: auto, de, hosted or kiosk")

    args = parser.parse_args()
    if args.cmd == "doctor":
        doctor(fix=getattr(args, "fix", False))
    elif args.cmd == "ask":
        ask(" ".join(args.prompt), args.model, args.full)
    elif args.cmd == "app":
        from . import desktop
        desktop.app_mode()
    elif args.cmd == "setup":
        from . import setup as setupmod
        setupmod.run_cli_wizard()
    elif args.cmd == "tui":
        from . import config as cfgmod
        if cfgmod.is_first_run():
            from . import setup as setupmod
            setupmod.run_cli_wizard()
        try:
            from . import tui_app          # full-screen Textual UI
            tui_app.run()
        except ImportError:
            import asyncio as _a            # fallback: simple REPL
            from . import clitui
            try:
                _a.run(clitui.run_tui())
            except KeyboardInterrupt:
                pass
    elif args.cmd == "install":
        from . import desktop
        desktop.install(autostart=not args.no_service, open_at_login=not args.no_login)
    elif args.cmd == "uninstall":
        from . import desktop
        desktop.uninstall()
    elif args.cmd == "autostart":
        from . import desktop
        desktop.enable_login_app(not args.off)
    elif args.cmd == "install-session":
        from . import session
        if args.remove:
            session.remove(autologin=args.autologin)
        else:
            session.install(wayland=not args.x11, autologin=args.autologin,
                            force=args.force)
    elif args.cmd == "remote":
        _remote_cli(args)
    elif args.cmd == "apps":
        _apps_cli(args)
    elif args.cmd == "remote-desktop":
        _remote_desktop_cli(args)
    elif args.cmd == "session":
        from . import config as cfgmod
        from . import runmode
        if args.action == "run":     # Exec target of the packaged session entry
            from . import session
            session.run_session()
            return
        cfg = cfgmod.load_config()
        if args.action == "mode" and args.value:
            if args.value not in runmode.CHOICES:
                print(f"mode must be one of: {', '.join(runmode.CHOICES)}")
                sys.exit(2)
            cfg.setdefault("desktop", {})["mode"] = args.value
            cfgmod.save_config(cfg)
            print(f"✓ desktop.mode = {args.value}  (takes effect on the next server start)")
        effective, detected = runmode.resolve(cfg)
        pin = cfg.get("desktop", {}).get("mode", "auto")
        print(f"mode: {effective}  (detected: {detected}, pinned: {pin})")
        print(f"  {runmode.describe(effective)}")
    else:
        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 0)
        no_browser = getattr(args, "no_browser", False)
        serve(host, port, not no_browser)


if __name__ == "__main__":
    main()

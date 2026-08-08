#!/usr/bin/env python3
"""The AgentOS desktop as a real Wayland surface — the session shell (SUI).

WHY THIS EXISTS
===============
Until now the AgentOS session drew its desktop in a Chromium *window*. A window
is a peer of every other window, so "the desktop is behind the apps" had to be
faked: the shell was pinned as the one tiled window, apps were all forced to
float above it, and summoning the desktop meant floating the shell to the size
of the screen and lowering it again afterwards. Every one of those is a trade —
and while the trade is in flight the stacking order is wrong, which is what
"it launches the app behind the desktop" and "it is always on top" both were.

Wayland already has the right answer, and it is not a trick: **wlr-layer-shell**.
A layer surface is not a window. It is placed on one of four layers, and the
BACKGROUND layer is *by definition* below every ordinary window. Put the desktop
there and native apps are above it in normal stacking order, permanently, with
nobody raising or lowering anything. The desktop stops being a window pretending
to be a desktop and simply is one.

Chromium cannot speak layer-shell. WebKitGTK can, through gtk-layer-shell, so
this host is a small GTK program that owns three surfaces:

    ┌──────────────────────────────────────────┐  ← strut, TOP layer, 30px
    │            menu bar band                 │    exclusive: apps cannot cover it
    ├──────────────────────────────────────────┤
    │                                          │
    │   DESKTOP: WebKitWebView on the          │  ← the AgentOS shell, BACKGROUND
    │   BACKGROUND layer, whole output         │    layer. Native windows are
    │   (wallpaper, icons, widgets, apps)      │    above this, always.
    │                                          │
    ├──────────────────────────────────────────┤
    │              dock band                   │  ← strut, TOP layer
    └──────────────────────────────────────────┘    exclusive: apps stop above it

The two struts are **empty and click-through**. They paint nothing; they exist
so the compositor reserves those bands, which is how a panel works in every
other desktop — a maximised app stops above the dock instead of swallowing it.
Because their input region is empty, a click in those bands falls straight
through to the desktop surface underneath, so the menu bar and dock the user
clicks are the real ones, drawn by the page.

The page can still ask to come forward (Ctrl+Space, a hot corner). That is now
one call — move the surface to the OVERLAY layer and take the keyboard — with no
window management involved at all, and no Chromium "press Esc to exit full
screen" toast, because nothing went full screen.

DEPENDENCIES, AND WHY THEY ARE ASKED FOR RATHER THAN SHIPPED
============================================================
GTK 3, gtk-layer-shell (MIT) and WebKitGTK are distribution packages. AgentOS
does not vendor or redistribute them; `agentos install-session` checks for them
and prints the one apt/dnf line that installs them. See docs/session-ui.md.

This module deliberately imports NOTHING from agentos. The server runs in its
own virtualenv, which usually cannot see the system PyGObject — so this file has
to be runnable by whichever system python does have it. `python_with_gi()` finds
that interpreter; the generated session script re-execs into it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

# The GTK/WebKit imports are deliberately inside main(): this module is also
# imported by the CLI and by the doctor on machines that do not have them, and
# `agentos doctor` telling you what is missing must not itself need the thing.

#: Interpreters that might carry PyGObject, best first. The venv python is tried
#: first only because when it *does* work (a distro-python install, or
#: --system-site-packages) it is the one already holding our config.
PYTHON_CANDIDATES = ("python3", "python3.12", "python3.11", "python3.13", "python3.10")

REQUIRED = (("Gtk", "3.0"), ("GtkLayerShell", "0.1"), ("WebKit2", "4.1"))
#: Older distributions ship WebKit2GTK 4.0 against libsoup2; same API for us.
WEBKIT_VERSIONS = ("4.1", "4.0")

PROBE = """
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
# PyGObject's cairo bridge is its own package (Debian: python3-gi-cairo) and is
# NOT pulled in by python3-gi or python3-cairo. The host needs it to give the
# strut surfaces an empty input region. Probing for it here is what makes the
# difference between "fall back to the Chromium renderer" and "the session host
# starts, dies on the first strut, and takes the compositor down with it".
gi.require_foreign("cairo")
ok = ""
for v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", v); ok = v; break
    except ValueError:
        continue
if not ok:
    raise SystemExit(1)
from gi.repository import Gtk, GtkLayerShell, WebKit2   # noqa: F401
print(ok)
"""


#: Memoised because the probe SPAWNS interpreters, and the answer is a property
#: of the machine's installed packages. /api/platform is called on every page
#: load and by every settings panel; probing five pythons each time would make
#: the desktop feel broken while it told you what it can do.
_PROBED: list = []


def python_with_gi(refresh: bool = False) -> tuple[str, str]:
    """(interpreter, webkit_version) able to run this host, or ('', '').

    Checked by actually importing, not by looking for files: a machine can have
    the GIR typelibs for one python and not another, and the only honest test of
    "can this interpreter draw the desktop" is asking it to load the libraries.
    """
    if _PROBED and not refresh:
        return _PROBED[0]
    found = ("", "")
    seen = set()
    for name in (sys.executable,) + PYTHON_CANDIDATES:
        exe = shutil.which(name) if not os.path.isabs(name or "") else name
        if not exe or exe in seen:
            continue
        seen.add(exe)
        try:
            r = subprocess.run([exe, "-c", PROBE], capture_output=True, text=True, timeout=8)
        except Exception:
            continue
        if r.returncode == 0 and r.stdout.strip():
            found = (exe, r.stdout.strip())
            break
    _PROBED[:] = [found]
    return found


def available(refresh: bool = False) -> bool:
    return bool(python_with_gi(refresh)[0])


#: What to tell the user to install, per package manager.
#:
#: This IS a second copy of what components.CATALOG["session-ui"] holds, and it
#: has to be: this module must stay importable by a bare system python that
#: cannot see the AgentOS package at all (see the module docstring and
#: tests/test_sui_remotedesktop.py, which enforces it). The duplication is
#: therefore deliberate — but duplication is how python3-gi-cairo came to be in
#: one list and not the other, which decided whether a user's desktop worked
#: depending on which message they happened to read. So
#: tests/test_components.py asserts the two agree, package for package.
INSTALL_HINTS = (
    # python3-gi-cairo is NOT redundant with python3-gi or python3-cairo: it is
    # the foreign-type bridge that lets PyGObject pass a cairo.Region into GDK.
    # Leaving it out is what made the desktop start and then die on its struts.
    ("apt", "sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 "
            "gir1.2-gtklayershell-0.1 gir1.2-webkit2-4.1"),
    ("dnf", "sudo dnf install python3-gobject python3-cairo gtk3 gtk-layer-shell "
            "webkit2gtk4.1"),
    ("pacman", "sudo pacman -S python-gobject python-cairo gtk3 gtk-layer-shell "
               "webkit2gtk-4.1"),
    ("zypper", "sudo zypper install python3-gobject python3-gobject-cairo python3-cairo "
               "gtk3 gtk-layer-shell typelib-1_0-WebKit2-4_1"),
)


def install_hint() -> str:
    for mgr, line in INSTALL_HINTS:
        if shutil.which(mgr):
            return line
    return INSTALL_HINTS[0][1]


# =============================================================================
# the host itself
# =============================================================================

BRIDGE_JS = r"""
/* Injected by the AgentOS session host, before the page runs.

   The page uses this to know it is the session UI rather than a browser tab,
   and to ask the compositor for the two things a web page cannot do for
   itself: come to the front, and reserve screen space for its own chrome. */
window.AGENTOS_SUI = {version: 1, host: 'layer-shell'};
document.documentElement.setAttribute('data-sui', '1');
window.suiCall = function (cmd, args) {
  try { window.webkit.messageHandlers.agentos.postMessage(
          JSON.stringify(Object.assign({cmd: cmd}, args || {}))); }
  catch (e) { /* not running in the session host */ }
};
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentos shell-host", description=__doc__)
    ap.add_argument("--url", default="", help="what to draw (default: the local server)")
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--boot", default="", help="splash file to show until the server answers")
    ap.add_argument("--top", type=int, default=30, help="menu-bar band to reserve, px")
    ap.add_argument("--bottom", type=int, default=0, help="dock band to reserve, px")
    ap.add_argument("--layer", default="background", choices=("background", "bottom"))
    ap.add_argument("--no-struts", action="store_true",
                    help="do not reserve space (apps may cover the dock)")
    ap.add_argument("--inspect", action="store_true", help="enable the web inspector")
    ap.add_argument("--give-up-after", type=float, default=40.0,
                    help="seconds to wait for the desktop to appear before failing "
                         "so the launcher can fall back (0 = wait forever)")
    args = ap.parse_args(argv)

    # Layer-shell exists ONLY on Wayland. If GDK picks X11 — and it will if
    # $DISPLAY is set and the Wayland connection is refused for any reason —
    # gtk_layer_init_for_window() calls g_error(), which aborts the process. The
    # session script exports DISPLAY for XWayland apps, so that is a live risk on
    # every machine. Ask for Wayland by name and fail with a sentence instead.
    os.environ.setdefault("GDK_BACKEND", "wayland")

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    wk = ""
    for v in WEBKIT_VERSIONS:
        try:
            gi.require_version("WebKit2", v)
            wk = v
            break
        except ValueError:
            continue
    if not wk:
        print("WebKit2GTK is not installed. Install it with:\n  " + install_hint(),
              file=sys.stderr)
        return 1
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, GtkLayerShell, WebKit2, GLib

    # Ask for the display explicitly. Without this the first widget built is a
    # WebView, and GTK aborts the whole process with "Can't create a
    # GtkStyleContext without a display connection" — a crash where the honest
    # answer is "there is no compositor to draw on".
    if not Gtk.init_check(None)[0]:
        print("no Wayland display to draw on ($WAYLAND_DISPLAY is "
              f"{os.environ.get('WAYLAND_DISPLAY') or 'unset'}). The session host "
              "must run inside the compositor.", file=sys.stderr)
        return 1

    url = args.url or f"http://127.0.0.1:{args.port}/"
    start = url
    if args.boot and os.path.exists(args.boot):
        start = "file://" + os.path.abspath(args.boot)

    state = {"raised": False, "top": args.top, "bottom": args.bottom,
             "painted": False, "exit": 0}

    # ---- the desktop surface ------------------------------------------------
    ctx = WebKit2.WebContext.get_default()
    try:
        # A desktop is not a browsing session; nothing here should be restored,
        # re-offered, or written to a profile that outlives the login.
        ctx.set_cache_model(WebKit2.CacheModel.DOCUMENT_BROWSER)
    except Exception:
        pass

    ucm = WebKit2.UserContentManager()
    ucm.add_script(WebKit2.UserScript.new(
        BRIDGE_JS, WebKit2.UserContentInjectedFrames.TOP_FRAME,
        WebKit2.UserScriptInjectionTime.START, None, None))
    ucm.register_script_message_handler("agentos")

    view = WebKit2.WebView.new_with_user_content_manager(ucm)
    s = view.get_settings()
    s.set_enable_developer_extras(bool(args.inspect))
    s.set_javascript_can_access_clipboard(True)
    s.set_enable_write_console_messages_to_stdout(True)
    for setter, val in (("set_enable_media_stream", True),      # voice input
                        ("set_enable_webgl", True),
                        ("set_enable_smooth_scrolling", True),
                        ("set_enable_back_forward_navigation_gestures", False)):
        if hasattr(s, setter):
            getattr(s, setter)(val)
    # The desktop must never show a browser's error page; we retry instead.
    view.connect("load-failed", lambda *_: True)

    # ---- proving the desktop actually appeared -------------------------------
    # This is the difference between a fallback that works and a black screen you
    # have to power-cycle. Importing the libraries proves nothing about whether
    # WebKit can draw on THIS machine's GPU: it can import perfectly and then
    # render nothing, and a BACKGROUND-layer surface that renders nothing has no
    # chrome to click and takes no keyboard, so there is no way back.
    #
    # So the host declares failure instead of sitting there. Two signals:
    #   · the page never finishes loading within --give-up-after
    #   · WebKit's web process dies (its own crash, not ours)
    # Either exits non-zero, and the session script falls back to Chromium.
    state["painted"] = False

    def on_load(_v, ev):
        if ev == WebKit2.LoadEvent.FINISHED and not state["painted"]:
            state["painted"] = True
            print("agentos shell-host: desktop is up", flush=True)

    view.connect("load-changed", on_load)

    def web_process_died(*_a):
        print("agentos shell-host: WebKit's web process died — the desktop cannot "
              "be drawn here", file=sys.stderr, flush=True)
        state["exit"] = 3
        Gtk.main_quit()
        return True

    for sig in ("web-process-terminated", "web-process-crashed"):
        try:
            view.connect(sig, web_process_died)
            break
        except TypeError:
            continue                       # older/newer WebKit spells it differently

    win = Gtk.Window()
    win.set_decorated(False)
    win.add(view)
    GtkLayerShell.init_for_window(win)
    GtkLayerShell.set_namespace(win, "agentos-desktop")
    LAYER = {"background": GtkLayerShell.Layer.BACKGROUND,
             "bottom": GtkLayerShell.Layer.BOTTOM}[args.layer]
    GtkLayerShell.set_layer(win, LAYER)
    for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                 GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
        GtkLayerShell.set_anchor(win, edge, True)
    # -1 means "ignore other surfaces' exclusive zones": the desktop spans the
    # whole output and our own struts sit on top of it, which is the point —
    # the wallpaper runs edge to edge and the dock band is part of the page.
    GtkLayerShell.set_exclusive_zone(win, -1)
    # ON_DEMAND, not EXCLUSIVE: clicking the desktop gives it the keyboard,
    # clicking an app gives it back. EXCLUSIVE would mean the desktop swallowed
    # every keystroke in the session, including the ones meant for a terminal.
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.ON_DEMAND)

    def raise_shell(on: bool):
        """Come to the front, or go back to being the desktop.

        This is the whole of what used to be raise_shell()'s float-resize-move-
        focus dance, and unlike that dance it cannot leave the stacking order in
        a wrong intermediate state."""
        state["raised"] = bool(on)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY if on else LAYER)
        GtkLayerShell.set_keyboard_mode(
            win, GtkLayerShell.KeyboardMode.EXCLUSIVE if on
            else GtkLayerShell.KeyboardMode.ON_DEMAND)

    # ---- struts: the bands no app may cover ---------------------------------
    struts: list[Gtk.Window] = []

    def make_strut(edge, size: int) -> Gtk.Window:
        """An empty, click-through surface whose only job is to reserve space.

        Paints nothing and takes no input — the compositor keeps ordinary
        windows out of the band, and the click lands on the desktop below,
        which is where the real dock is drawn."""
        w = Gtk.Window()
        w.set_decorated(False)
        w.set_app_paintable(True)
        vis = w.get_screen().get_rgba_visual()
        if vis:
            w.set_visual(vis)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, "agentos-strut")
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(w, edge, True)
        GtkLayerShell.set_anchor(w, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(w, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_exclusive_zone(w, max(0, int(size)))
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        w.set_size_request(-1, max(1, int(size)))
        w.show_all()
        # Empty input region => every click falls through to the desktop.
        #
        # This is the ONLY place the host needs cairo, and it needs it through
        # PyGObject's foreign-type bridge (Debian: python3-gi-cairo), which is a
        # SEPARATE package from python3-gi and python3-cairo. Without it the
        # call raises `KeyError: could not find foreign type Region` — and
        # because struts are built before the first frame, an unguarded call
        # killed the host, which took sway with it and left a black screen at
        # login. A band that swallows clicks is a small bug; no desktop at all
        # is not. So this degrades instead of raising.
        gw = w.get_window()
        if gw is not None:
            try:
                import cairo
                gw.input_shape_combine_region(cairo.Region(), 0, 0)
            except Exception as exc:                                # pragma: no cover
                print(f"agentos shell-host: strut is not click-through ({exc}); "
                      f"install the cairo bridge for PyGObject "
                      f"(apt: python3-gi-cairo) to fix", flush=True)
        return w

    def apply_struts():
        for w in struts:
            w.destroy()
        struts.clear()
        if args.no_struts:
            return
        if state["top"] > 0:
            struts.append(make_strut(GtkLayerShell.Edge.TOP, state["top"]))
        if state["bottom"] > 0:
            struts.append(make_strut(GtkLayerShell.Edge.BOTTOM, state["bottom"]))

    # ---- the page talks back ------------------------------------------------
    def on_message(_ucm, msg):
        try:
            val = msg.get_js_value() if hasattr(msg, "get_js_value") else msg
            data = json.loads(val.to_string())
        except Exception:
            return
        cmd = data.get("cmd")
        if cmd == "raise":
            raise_shell(True)
        elif cmd == "lower":
            raise_shell(False)
        elif cmd == "struts":
            # The page owns its own chrome heights — themes change them, and a
            # phone-shaped layout has none at all. It tells us; we reserve.
            state["top"] = max(0, int(data.get("top", state["top"])))
            state["bottom"] = max(0, int(data.get("bottom", state["bottom"])))
            apply_struts()
        elif cmd == "reload":
            view.load_uri(url)
        elif cmd == "quit":
            Gtk.main_quit()

    ucm.connect("script-message-received::agentos", on_message)

    # ---- keep the desktop on screen even if the server is slow -------------
    def watchdog():
        """Retry until the server answers.

        A desktop that has given up and is showing a load error is worse than a
        black screen: there is nothing to click to fix it. So the surface simply
        keeps trying, and the splash keeps saying so."""
        here = view.get_uri() or ""
        if here.startswith(url):
            return view.get_estimated_load_progress() < 1.0   # loaded → stop the timer
        if not view.is_loading():
            view.load_uri(url)
        return True

    def give_up():
        """Nothing has been drawn in --give-up-after seconds. Say so and fail.

        A slow server is not this: the splash and the retry loop cover that, and
        `painted` is set as soon as ANY page finishes loading, splash included.
        Reaching here means WebKit is not putting pixels on this screen at all."""
        if state["painted"]:
            return False
        print(f"agentos shell-host: nothing rendered in {args.give_up_after:.0f}s — "
              "giving up so the session can fall back to a Chromium window",
              file=sys.stderr, flush=True)
        state["exit"] = 3
        Gtk.main_quit()
        return False

    win.show_all()
    apply_struts()
    view.load_uri(start)
    GLib.timeout_add_seconds(2, watchdog)
    if args.give_up_after > 0:
        GLib.timeout_add(int(args.give_up_after * 1000), give_up)
    print(f"agentos shell-host: WebKit2 {wk} on the "
          f"{args.layer} layer, struts top={state['top']} bottom={state['bottom']}",
          flush=True)
    Gtk.main()
    return state["exit"]


if __name__ == "__main__":
    raise SystemExit(main())

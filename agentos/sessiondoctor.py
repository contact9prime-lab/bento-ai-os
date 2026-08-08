"""`agentos doctor --session` — why the desktop did or did not come up, on THIS machine.

Written because the answer was previously "look in a log and tell me what you
see", which is the wrong way round: the machine knows, and a person trying to log
in should not have to read a renderer's stderr to find out.

Every probe runs in its own subprocess with a timeout. That is the point rather
than tidiness: the failures being diagnosed here are aborts and segmentation
faults inside GTK and WebKit, and a probe that crashes the doctor cannot report
that it crashed. A dead subprocess is a result — signal number included.

Nothing here changes anything. It only looks.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess

TIMEOUT = 25.0


def _run_py(code: str, timeout: float = TIMEOUT, env: dict | None = None) -> tuple[int, str]:
    """Run a probe under an interpreter that has PyGObject, capturing everything.

    Returns (returncode, output). A negative returncode is a signal — that is how
    "GTK aborted" and "WebKit segfaulted" arrive, and both are answers.
    """
    from . import shellhost
    py, _ = shellhost.python_with_gi()
    if not py:
        return 127, "no interpreter with PyGObject + gtk-layer-shell + WebKitGTK"
    e = dict(os.environ)
    e.setdefault("GDK_BACKEND", "wayland")
    if env:
        e.update(env)
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           timeout=timeout, env=e)
    except subprocess.TimeoutExpired as t:
        out = (t.stdout or "") + (t.stderr or "")
        return 124, (out if isinstance(out, str) else out.decode(errors="replace")) \
                    + "\n(timed out — it hung rather than answering)"
    return r.returncode, (r.stdout + r.stderr).strip()


def _signal_name(rc: int) -> str:
    if rc >= 0:
        return ""
    try:
        return f" (killed by {signal.Signals(-rc).name})"
    except Exception:
        return f" (killed by signal {-rc})"


# =============================================================================
# probes
# =============================================================================

PROBE_GTK = """
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
ok, _ = Gtk.init_check(None)
if not ok:
    raise SystemExit('Gtk.init_check failed: no display connection')
d = Gdk.Display.get_default()
print('backend:', type(d).__name__)
"""

PROBE_LAYER = """
import gi
gi.require_version('Gtk', '3.0'); gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, GtkLayerShell, GLib
Gtk.init_check(None)
w = Gtk.Window(); w.set_decorated(False)
w.add(Gtk.Label(label='probe'))
GtkLayerShell.init_for_window(w)
GtkLayerShell.set_layer(w, GtkLayerShell.Layer.BACKGROUND)
for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
          GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
    GtkLayerShell.set_anchor(w, e, True)
w.show_all()
# One main-loop turn is enough: a compositor that refuses layer-shell errors here.
GLib.timeout_add(1200, Gtk.main_quit)
Gtk.main()
print('layer surface mapped')
"""

#: The important one. Imports prove nothing — this asks WebKit to actually load a
#: page and say it finished, which is what the session launcher waits for.
#:
#: It loads the REAL desktop when the server is up. A 20-byte page renders happily
#: on a stack that then dies on the actual shell, which is exactly the false pass
#: this probe existed to avoid: measured here, a trivial page passed while the
#: session was segfaulting. The synthetic fallback below therefore exercises the
#: same expensive things the shell does — compositing layers, a canvas, and a
#: backdrop-filter — rather than being a blank body.
PROBE_WEBKIT = """
import gi, sys
gi.require_version('Gtk', '3.0')
wk = ''
for v in ('4.1', '4.0'):
    try:
        gi.require_version('WebKit2', v); wk = v; break
    except ValueError:
        pass
if not wk:
    raise SystemExit('WebKit2GTK is not installed')
from gi.repository import Gtk, WebKit2, GLib
Gtk.init_check(None)
state = {'done': False, 'loaded': False}
v = WebKit2.WebView()
def on_load(_v, ev):
    # "Finished loading" is NOT "can draw". Measured: WebKit reports FINISHED,
    # having genuinely loaded and run the page, and segfaults a few seconds later
    # while compositing it — which is exactly the black screen this diagnoses. So
    # the probe keeps painting for a while and only then claims success.
    if ev == WebKit2.LoadEvent.FINISHED and not state['loaded']:
        state['loaded'] = True
        def survived():
            state['done'] = True
            print('webkit ' + wk + ': rendered and kept drawing')
            Gtk.main_quit()
            return False
        GLib.timeout_add(6000, survived)
v.connect('load-changed', on_load)
for sig in ('web-process-terminated', 'web-process-crashed'):
    try:
        v.connect(sig, lambda *a: (print('web process DIED', file=sys.stderr), Gtk.main_quit()))
        break
    except TypeError:
        pass
w = Gtk.Window(); w.set_default_size(320, 200); w.add(v); w.show_all()
URL = __PROBE_URL__
if URL:
    v.load_uri(URL)
else:
    # No server to point at: synthesise the load this desktop actually is —
    # translucent compositing, a canvas, and a lot of DOM.
    v.load_html('''<body style="margin:0;background:#0b0d10">
      <div style="position:fixed;inset:0;backdrop-filter:blur(24px) saturate(1.6);
                  background:rgba(20,24,32,.6)"></div>
      <canvas id=c width=800 height=600></canvas>
      <div id=d></div>
      <script>
        var x=document.getElementById('c').getContext('2d');
        for(var i=0;i<400;i++){x.fillStyle='hsl('+i+',60%,50%)';x.fillRect(i,i%300,40,40)}
        var h='';for(var j=0;j<4000;j++)h+='<span style="opacity:.5">x</span>';
        document.getElementById('d').innerHTML=h;
        // keep compositing busy: a still page can sit on a broken stack quietly
        var t=0;(function loop(){t++;x.fillStyle='hsl('+(t%360)+',70%,50%)';
          x.fillRect((t*7)%700,(t*11)%500,60,60);requestAnimationFrame(loop)})();
      </script></body>''', 'file:///')
def give_up():
    if not state['done']:
        print('loaded but did not survive painting' if state['loaded']
              else 'nothing rendered', file=sys.stderr)
        Gtk.main_quit()
    return False
GLib.timeout_add(20000, give_up)
Gtk.main()
raise SystemExit(0 if state['done'] else 4)
"""

#: Same, but as a LAYER surface — the combination the session actually uses, and
#: the one that can work in a window and still fail here.
PROBE_WEBKIT_LAYER = PROBE_WEBKIT.replace(
    "w = Gtk.Window(); w.set_default_size(320, 200); w.add(v); w.show_all()",
    """
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import GtkLayerShell
w = Gtk.Window(); w.set_decorated(False); w.add(v)
GtkLayerShell.init_for_window(w)
GtkLayerShell.set_layer(w, GtkLayerShell.Layer.BACKGROUND)
for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
          GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
    GtkLayerShell.set_anchor(w, e, True)
GtkLayerShell.set_exclusive_zone(w, -1)
w.show_all()
""")


def gpu_notes() -> list[str]:
    """What is drawing, in the words of the drivers themselves.

    WebKit failing to render is nearly always the GL/EGL stack underneath it, so
    the renderer strings are usually the actual answer.
    """
    notes: list[str] = []
    for exe, args, label in (("eglinfo", ["-B"], "EGL"),
                             ("glxinfo", ["-B"], "GLX"),
                             ("wlr-randr", [], "outputs")):
        if not shutil.which(exe):
            continue
        try:
            r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=12)
        except Exception:
            continue
        for line in (r.stdout or "").splitlines():
            low = line.lower()
            if any(k in low for k in ("renderer", "opengl version", "vendor", "device:")):
                notes.append(f"{label}: {line.strip()[:110]}")
    if os.path.isdir("/sys/module/nvidia"):
        notes.append("NVIDIA proprietary driver is loaded — wlroots needs "
                     "nvidia-drm.modeset=1, and WebKit often needs "
                     "WEBKIT_DISABLE_DMABUF_RENDERER=1 on it")
    cards = sorted(p for p in os.listdir("/dev/dri") if p.startswith(("card", "renderD"))) \
        if os.path.isdir("/dev/dri") else []
    have = ", ".join(cards) if cards else "EMPTY — no GPU device, software rendering only"
    notes.append(f"/dev/dri: {have}")
    return notes


def _webkit_probe(code: str, port: int) -> str:
    """Point the probe at the live desktop if there is one.

    Testing the real page is the difference between a probe that agrees with the
    session and one that reassures you while the session crashes."""
    url = ""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
            url = f"http://127.0.0.1:{port}/"
    except Exception:
        url = ""
    return code.replace("__PROBE_URL__", repr(url))


def report(ok, warn, bad, todo) -> None:
    """Run every probe and explain the result. Printers are passed in so this
    matches the rest of `agentos doctor`."""
    from . import shellhost

    print("\n  session renderer — what can actually draw on this machine\n")

    wl = os.environ.get("WAYLAND_DISPLAY")
    if not wl:
        warn("not inside a Wayland session, so these probes describe the shell you "
             "ran this from, not the AgentOS session")
        todo("run it from inside the AgentOS session, or over SSH with "
             "WAYLAND_DISPLAY and XDG_RUNTIME_DIR set")
    else:
        ok(f"Wayland display: {wl}")

    py, wk = shellhost.python_with_gi()
    if not py:
        bad("no interpreter has PyGObject + gtk-layer-shell + WebKitGTK")
        todo(shellhost.install_hint())
        return
    ok(f"interpreter: {py} (WebKit2GTK {wk})")

    rc, out = _run_py(PROBE_GTK)
    if rc == 0:
        ok(f"GTK opens a display — {out.splitlines()[-1] if out else 'ok'}")
    else:
        bad(f"GTK cannot open a display{_signal_name(rc)}: {out[-300:]}")
        return

    rc, out = _run_py(PROBE_LAYER)
    if rc == 0:
        ok("layer-shell works — the compositor accepts a desktop surface")
    else:
        bad(f"layer-shell FAILED{_signal_name(rc)}: {out[-300:]}")
        todo("this compositor may not implement wlr-layer-shell; the AgentOS "
             "session needs sway/wlroots")

    port = 8321
    try:
        from . import config as _cfg
        port = int(_cfg.load_config().get("port", 8321))
    except Exception:
        pass
    rc, out = _run_py(_webkit_probe(PROBE_WEBKIT, port), timeout=40)
    webkit_window_ok = rc == 0
    if webkit_window_ok:
        ok("WebKit renders in an ordinary window")
    else:
        bad(f"WebKit CANNOT render in an ordinary window{_signal_name(rc)}")
        for line in out.splitlines()[-6:]:
            if line.strip():
                print(f"      {line.strip()[:110]}")

    rc, out = _run_py(_webkit_probe(PROBE_WEBKIT_LAYER, port), timeout=40)
    if rc == 0:
        ok("WebKit renders on a layer surface — the session desktop will work")
    elif webkit_window_ok:
        bad(f"WebKit renders in a window but NOT on a layer surface{_signal_name(rc)}")
        todo("this is the combination the session uses; the native desktop will "
             "fall back to a Chromium window until it is fixed")
    else:
        warn("skipping: WebKit could not render in a window either")

    notes = gpu_notes()
    if notes:
        print("\n  what is doing the drawing:")
        for n in notes:
            print(f"      {n}")

    print("\n  verdict:")
    if rc == 0:
        print("      the native desktop surface should work here.")
    elif webkit_window_ok:
        print("      WebKit works, but not as a desktop surface. The session will use")
        print("      the Chromium fallback; window stacking is arranged rather than native.")
    else:
        print("      WebKit cannot draw on this machine at all. That is a driver/GL")
        print("      problem beneath AgentOS, not a setting in it. The session will use")
        print("      the Chromium fallback, which does not depend on WebKit.")

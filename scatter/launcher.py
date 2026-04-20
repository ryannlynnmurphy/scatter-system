#!/usr/bin/env python3
"""
scatter launcher — native app wrapper for the Scatter GUI.

Wraps the existing HTTP server in a chromeless GTK + WebKit2 window.
No URL bar, no tabs, no back button. A tool, not a website.

Navigation lock: the WebView refuses any URL that isn't localhost.
Links clicked inside a build preview cannot break out of the bubble.
This is enforcement by WebKit policy, not by convention.

Usage:
  python3 launcher.py              # launch native window (default)
  python3 launcher.py --server-only  # run just the HTTP server (dev mode)
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError


HERE = Path(__file__).resolve().parent
SERVER = HERE / "server.py"


def _free_port(start: int = 3333) -> int:
    """Find a free port starting at `start`. Sticks close so dev instincts still work."""
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    # Fallback to anonymous
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port: int, timeout: float = 20.0) -> bool:
    """Poll /health until it responds or timeout."""
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urlopen(Request(url), timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (URLError, ConnectionRefusedError, OSError):
            time.sleep(0.1)
    return False


def run_server_only() -> int:
    env = os.environ.copy()
    return subprocess.call([sys.executable, str(SERVER)], env=env)


def run_native() -> int:
    # Import GTK/WebKit only when actually launching native, so --server-only
    # works on headless machines without the display stack.
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

    port = _free_port(3333)
    env = os.environ.copy()
    env["SCATTER_STUDIO_PORT"] = str(port)

    server = subprocess.Popen(
        [sys.executable, str(SERVER)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not _wait_ready(port):
        server.terminate()
        print("scatter server did not become ready — check ollama", file=sys.stderr)
        return 1

    window = Gtk.Window(title="Scatter · Journal")

    # Size the window so the GNOME top bar (clock, Activities, system menu)
    # is always reachable. Mutter auto-maximizes tall windows on small
    # screens, so we clamp short enough that the top panel is guaranteed
    # to stay visible above us. Wayland ignores client-side positioning —
    # only the size is load-bearing.
    # Size to the monitor's workarea — the rectangle that excludes the
    # GNOME top bar and the Scatter bottom bar (both reserve struts).
    # A small inset keeps the window from feeling glued to the edges.
    display = Gdk.Display.get_default()
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    if monitor is not None:
        wa = monitor.get_workarea()
        w = max(900, wa.width - 32)
        h = max(600, wa.height - 24)
        window.set_default_size(w, h)
    else:
        window.set_default_size(1200, 720)
    window.set_position(Gtk.WindowPosition.CENTER)
    window.set_resizable(True)
    window.set_type_hint(Gdk.WindowTypeHint.NORMAL)
    window.set_decorated(True)

    # Escape closes the window — no titlebar controls to lean on.
    def _on_key(_w, event):
        if event.keyval == Gdk.KEY_Escape:
            _shutdown()
            return True
        return False
    window.connect("key-press-event", _on_key)

    # Climate hacker: dark window background so there is no white flash
    # at startup before the web UI paints.
    css = b"""
    window { background-color: #0a0a0a; }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    webview = WebKit2.WebView()
    settings = webview.get_settings()
    # Enable JS (the UI needs it), block features that leak
    settings.set_enable_javascript(True)
    settings.set_enable_developer_extras(False)
    settings.set_enable_page_cache(False)
    settings.set_enable_offline_web_application_cache(False)
    # Navigation lock — stay in the bubble.
    def _guard(wv, decision, decision_type):
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if uri.startswith((f"http://127.0.0.1:{port}", f"http://localhost:{port}")):
            return False  # allow
        if uri.startswith(("about:", "data:")):
            return False
        decision.ignore()
        return True
    webview.connect("decide-policy", _guard)

    webview.load_uri(f"http://127.0.0.1:{port}/")
    window.add(webview)

    def _shutdown(*_a):
        try:
            server.terminate()
            server.wait(timeout=3)
        except Exception:
            try:
                server.kill()
            except Exception:
                pass
        Gtk.main_quit()
        return False

    window.connect("destroy", _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _shutdown)

    window.show_all()
    # Mutter may auto-maximize a large window on a small screen. Force it
    # back to our requested size so the top panel stays reachable.
    window.unmaximize()
    Gtk.main()
    return 0


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    if "--server-only" in sys.argv:
        return run_server_only()
    return run_native()


if __name__ == "__main__":
    sys.exit(main())

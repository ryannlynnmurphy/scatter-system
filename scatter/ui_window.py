#!/usr/bin/env python3
"""
scatter/ui_window.py — open a chromeless GTK + WebKit2 window at a given URL.

Small, reusable. Used by scatter-wrap prototype launchers to host a Next.js
dev server inside a native Scatter-feeling window.

On window close: optionally kills a process group (the dev server that the
wrapping bash launcher spawned) so we don't leak stray `node` processes.

Usage:
  python3 ui_window.py --url http://localhost:3100/ --title "Scatter Draft"
  python3 ui_window.py --url ... --title ... --kill-pgid 12345
"""

from __future__ import annotations

import argparse
import os
import signal
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="scatter-ui-window")
    parser.add_argument("--url", required=True)
    parser.add_argument("--title", default="Scatter")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument(
        "--kill-pgid",
        type=int,
        default=0,
        help="On close, kill this process group (e.g. the dev server).",
    )
    args = parser.parse_args()

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

    window = Gtk.Window(title=args.title)
    window.set_default_size(args.width, args.height)
    window.set_position(Gtk.WindowPosition.CENTER)

    css = b"window { background-color: #0a0a0a; }"
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    webview = WebKit2.WebView()
    settings = webview.get_settings()
    settings.set_enable_javascript(True)
    settings.set_enable_developer_extras(False)

    # Navigation lock: stay at localhost targets or about:/data: only.
    # This keeps a prototype dev server honest — if its code accidentally
    # links to an external site, the wrapper won't let the user navigate
    # out of the bubble.
    def _guard(wv, decision, decision_type):
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if uri.startswith(("http://127.0.0.1", "http://localhost", "about:", "data:")):
            return False
        decision.ignore()
        return True
    webview.connect("decide-policy", _guard)

    webview.load_uri(args.url)
    window.add(webview)

    def _shutdown(*_a):
        if args.kill_pgid > 0:
            try:
                os.killpg(args.kill_pgid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        Gtk.main_quit()
        return False

    window.connect("destroy", _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _shutdown)

    window.show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())

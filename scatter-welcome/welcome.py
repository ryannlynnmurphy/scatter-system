#!/usr/bin/env python3
"""
scatter-welcome — first-boot introduction.

Cycles through the prototype-era manifesto READMEs verbatim. The
practitioner-designers introduce their own apps. This is the thesis-
grade pedagogy: no marketing voice, no developer voice — the voice of
the person who lived the craft the tool serves.

Each slide shows one prototype manifesto + a next button. On the
final slide ("Begin."), the window closes and config.welcomed=true
is written so the welcome does not repeat.

Run:   python3 welcome.py
       (or:  scatter welcome)
"""

from __future__ import annotations

import html
import json
import os
import re
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


PROTOTYPES_ROOT = Path.home() / "projects" / "hazel"

# Ordered. Order matters — it's the narrative arc.
SLIDES = [
    {
        "title": "Scatter Draft",
        "voice": "the playwright",
        "readme": PROTOTYPES_ROOT / "hzl-draft" / "README.md",
    },
    {
        "title": "Scatter Film",
        "voice": "the screenwriter",
        "readme": PROTOTYPES_ROOT / "hzl-film" / "README.md",
    },
    {
        "title": "Scatter Music",
        "voice": "the arranger",
        "readme": PROTOTYPES_ROOT / "hzl-music" / "README.md",
    },
    {
        "title": "Scatter Write",
        "voice": "the writer",
        "readme": PROTOTYPES_ROOT / "hzl-write" / "README.md",
    },
]


def _read_manifesto(path: Path) -> str:
    """Read the README and return only the prose above the first code block
    or the first top-level section break. Manifestos live in the opening."""
    if not path.is_file():
        return "_(manifesto not found — the prototype is not on this machine)_"
    text = path.read_text(encoding="utf-8", errors="replace")
    # Cut at the first '## ' after the body begins (keep the intro),
    # the first code fence, or 1400 chars — whichever comes first.
    cut = len(text)
    m = re.search(r"\n## ", text[1:])
    if m:
        cut = min(cut, m.start() + 1)
    m = re.search(r"```", text)
    if m:
        cut = min(cut, m.start())
    return text[:cut].strip()[:1800]


def _md_to_html(md: str) -> str:
    """Minimal markdown → HTML. Safe subset: heading 1 + paragraphs +
    bold + italic + blockquote + inline code. No images, no links,
    no lists. Keeps a manifesto a manifesto."""
    md = html.escape(md)
    # # heading
    md = re.sub(r"^# (.+)$", r'<h1>\1</h1>', md, flags=re.MULTILINE)
    # bold / italic / code
    md = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", md)
    md = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", md)
    md = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", md)
    # > blockquote
    md = re.sub(r"^&gt; (.+)$", r"<blockquote>\1</blockquote>", md, flags=re.MULTILINE)
    # paragraphs
    paras = [p.strip() for p in md.split("\n\n") if p.strip()]
    out = []
    for p in paras:
        if p.startswith(("<h1", "<blockquote")):
            out.append(p)
        else:
            out.append(f"<p>{p.replace(chr(10), '<br>')}</p>")
    return "\n".join(out)


def build_page() -> str:
    slides_html = []
    for i, s in enumerate(SLIDES):
        body_html = _md_to_html(_read_manifesto(s["readme"]))
        slides_html.append(f"""
        <section class="slide" data-index="{i}" {'' if i == 0 else 'hidden'}>
          <header class="slide-head">
            <div class="eyebrow">{html.escape(s['voice'])} explains —</div>
            <h2 class="slide-title">{html.escape(s['title'])}</h2>
          </header>
          <article class="manifesto">{body_html}</article>
        </section>
        """)
    # Final slide
    slides_html.append(f"""
    <section class="slide final" data-index="{len(SLIDES)}" hidden>
      <header class="slide-head">
        <div class="eyebrow">you</div>
        <h2 class="slide-title">Your turn.</h2>
      </header>
      <article class="manifesto">
        <p>You have heard the four voices: the playwright, the screenwriter, the arranger, the writer.</p>
        <p>Every tool in Scatter was built by someone who uses it. The person who designed the tool is the person who needed it.</p>
        <p>Scatter is yours. The machine is local. Nothing leaves unless you ask and watch.</p>
        <p><strong>Begin.</strong></p>
      </article>
    </section>
    """)

    style = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { height: 100%; background: #0a0a0a; color: #d8e4dc;
        font-family: 'JetBrains Mono','Ubuntu Mono','SF Mono',Menlo,monospace;
        overflow: hidden; }
    body { display: flex; align-items: center; justify-content: center; padding: 40px; }
    .deck { max-width: 640px; width: 100%; height: 100%; display: flex; flex-direction: column; }
    .top { flex: 0 0 auto; display: flex; justify-content: space-between; align-items: center;
        padding-bottom: 24px; border-bottom: 1px solid #1a1a1a; margin-bottom: 32px; }
    .mark { font-size: 0.7rem; letter-spacing: 0.1em; color: #6a7a72; text-transform: lowercase; }
    .dots { display: flex; gap: 6px; }
    .dots span { width: 6px; height: 6px; border-radius: 50%; background: #1f1f1f; }
    .dots span.on { background: #00ff88; box-shadow: 0 0 6px rgba(0,255,136,0.5); }
    .slides-wrap { flex: 1; overflow-y: auto; overflow-x: hidden; padding-right: 12px; }
    .slide { animation: fade 0.4s ease; }
    @keyframes fade { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    .eyebrow { color: #00ff88; font-size: 0.7rem; letter-spacing: 0.1em; text-transform: lowercase; margin-bottom: 10px; }
    .slide-title { font-size: 1.75rem; font-weight: 500; letter-spacing: 0.02em; margin-bottom: 28px; color: #ffffff; }
    .manifesto h1 { font-size: 1.5rem; margin-bottom: 16px; color: #ffffff; }
    .manifesto p { font-size: 0.92rem; line-height: 1.65; color: #c0c8c4; margin-bottom: 16px; }
    .manifesto p:last-child { margin-bottom: 0; }
    .manifesto em { color: #ffb800; font-style: normal; }
    .manifesto strong { color: #ffffff; }
    .manifesto blockquote { border-left: 2px solid rgba(0,255,136,0.35); padding-left: 16px;
        color: #ffb800; margin-bottom: 16px; font-style: normal; }
    .manifesto code { background: #111; padding: 2px 6px; border-radius: 4px;
        font-family: inherit; font-size: 0.85em; color: #00ff88; }
    .bottom { flex: 0 0 auto; display: flex; justify-content: space-between; align-items: center;
        padding-top: 24px; border-top: 1px solid #1a1a1a; margin-top: 32px; }
    button { background: transparent; color: #6a7a72; border: 1px solid #1f1f1f;
        padding: 10px 22px; border-radius: 999px; font-family: inherit; font-size: 0.78rem;
        letter-spacing: 0.08em; text-transform: lowercase; cursor: pointer; transition: all 0.15s; }
    button:hover { color: #00ff88; border-color: rgba(0,255,136,0.3); }
    button:disabled { opacity: 0.25; cursor: not-allowed; }
    .begin { background: rgba(0,255,136,0.08); color: #00ff88;
        border-color: rgba(0,255,136,0.3); padding: 12px 28px; font-size: 0.82rem; }
    .begin:hover { background: rgba(0,255,136,0.14); }
    /* scrollbar */
    .slides-wrap::-webkit-scrollbar { width: 4px; }
    .slides-wrap::-webkit-scrollbar-track { background: transparent; }
    .slides-wrap::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 2px; }
    """

    n = len(SLIDES) + 1  # plus final slide
    dots = "".join('<span></span>' for _ in range(n))

    js = f"""
    const total = {n};
    let idx = 0;
    const slides = document.querySelectorAll('.slide');
    const dots = document.querySelectorAll('.dots span');
    const back = document.getElementById('back');
    const next = document.getElementById('next');
    const begin = document.getElementById('begin');

    function render() {{
        slides.forEach((s, i) => s.hidden = i !== idx);
        dots.forEach((d, i) => d.classList.toggle('on', i === idx));
        back.disabled = idx === 0;
        if (idx === total - 1) {{
            next.hidden = true;
            begin.hidden = false;
        }} else {{
            next.hidden = false;
            begin.hidden = true;
        }}
    }}

    back.addEventListener('click', () => {{ if (idx > 0) {{ idx--; render(); }} }});
    next.addEventListener('click', () => {{ if (idx < total - 1) {{ idx++; render(); }} }});
    begin.addEventListener('click', () => {{
        fetch('scatter://welcomed', {{ method: 'POST' }}).catch(() => {{}});
        window.close();
    }});

    document.addEventListener('keydown', (e) => {{
        if (e.key === 'ArrowRight' || e.key === 'Enter') {{ if (idx < total - 1) {{ idx++; render(); }} else {{ begin.click(); }} }}
        if (e.key === 'ArrowLeft' || e.key === 'Backspace') {{ if (idx > 0) {{ idx--; render(); }} }}
        if (e.key === 'Escape') {{ window.close(); }}
    }});

    render();
    """

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>Welcome to Scatter</title>
<style>{style}</style>
</head><body>
<div class="deck">
  <div class="top">
    <span class="mark">scatter · welcome</span>
    <span class="dots">{dots}</span>
  </div>
  <div class="slides-wrap">
    {"".join(slides_html)}
  </div>
  <div class="bottom">
    <button id="back">back</button>
    <span style="flex:1"></span>
    <button id="next">next</button>
    <button id="begin" class="begin" hidden>begin</button>
  </div>
</div>
<script>{js}</script>
</body></html>
"""


def mark_welcomed() -> None:
    cfg = sc.config_read()
    cfg["welcomed"] = True
    cfg["welcomed_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
    sc.config_write(cfg)
    sc.journal_append("welcomed")


def needs_welcome() -> bool:
    return not sc.config_read().get("welcomed", False)


def run_welcome() -> int:
    """Open the welcome window. Mark config on close."""
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gtk, WebKit2, Gdk, GLib  # noqa: E402

    page = build_page()

    window = Gtk.Window(title="Welcome to Scatter")
    window.set_default_size(880, 640)
    window.set_position(Gtk.WindowPosition.CENTER)

    css = b"window { background-color: #0a0a0a; }"
    prov = Gtk.CssProvider()
    prov.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    webview = WebKit2.WebView()
    settings = webview.get_settings()
    settings.set_enable_javascript(True)
    settings.set_enable_developer_extras(False)

    # Intercept the fake scatter://welcomed URL from the JS Begin button.
    def _guard(wv, decision, decision_type):
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        uri = decision.get_navigation_action().get_request().get_uri()
        if uri.startswith("scatter://welcomed"):
            mark_welcomed()
            decision.ignore()
            _shutdown()
            return True
        if uri.startswith(("about:", "data:")):
            return False
        decision.ignore()
        return True
    webview.connect("decide-policy", _guard)

    # Base URI must be a valid scheme WebKit accepts. file:// is safest —
    # there are no relative URLs in our generated HTML to resolve anyway,
    # so the base is just for the frame identity.
    webview.load_html(page, "file:///home/ryannlynnmurphy/scatter-system/scatter-welcome/")
    window.add(webview)

    def _shutdown(*_a):
        # Also mark welcomed if the user closed via ESC or window X after at
        # least seeing slide 0. Conservative: only mark if they clicked begin.
        Gtk.main_quit()
        return False

    window.connect("destroy", _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, _shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, _shutdown)

    window.show_all()
    Gtk.main()
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--status" in argv:
        welcomed = sc.config_read().get("welcomed", False)
        print(f"welcomed: {welcomed}")
        return 0
    if "--reset" in argv:
        cfg = sc.config_read()
        cfg.pop("welcomed", None)
        cfg.pop("welcomed_at", None)
        sc.config_write(cfg)
        print("welcome reset — next `scatter welcome` run will show again")
        return 0
    if "--if-needed" in argv:
        if not needs_welcome():
            return 0
    return run_welcome()


if __name__ == "__main__":
    sys.exit(main())

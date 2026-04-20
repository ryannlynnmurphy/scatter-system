#!/usr/bin/env python3
"""
scatter/artifacts.py — typed build outputs.

Build mode used to ask qwen for "some HTML." The result was unpredictable —
sometimes a useful page, sometimes a near-empty white box. This module
replaces that with a small taxonomy of artifacts that the model fills in:

  note      — a short research note: title, summary, prose body, key points
  reference — a structured fact sheet: definition + sections + see-also
  lesson    — an adaptive learning unit: objective + exploration + question

Each subtype is a JSON contract. qwen returns JSON; the server renders it
into a consistent dark Scatter card. No more freeform HTML, no more
mystery output. The lesson shape mirrors hzl-academy so a future lesson
corpus can flow in without re-templating.

Stdlib only. Iframes are sandboxed by the caller; we still html-escape
all model output so a quirky generation can't break the template.
"""

from __future__ import annotations

import html
import json
import re
from typing import Callable


# ── Subtype prompts ───────────────────────────────────────────────────
# Each prompt is single-purpose: you are writing a {kind}; here are the
# fields; output JSON only. Temperature is intentionally low (set by caller).

NOTE_PROMPT = """You are writing a short research note for a thoughtful adult.

Output ONLY a JSON object — no prose before, no prose after, no markdown fences. Schema:
  {
    "title":      "<3-8 words, sentence case>",
    "summary":    "<one or two sentences capturing the gist>",
    "body":       "<2-4 short paragraphs in plain prose, separated by \\n\\n>",
    "key_points": ["<short string>", "<short string>", "<short string>"]
  }

Rules:
- No HTML. No markdown bold or italics. Just clean prose.
- Be precise, cite no sources you can't verify, and prefer concrete examples.
- Three to five key points. Each is a complete thought, not a fragment."""


REFERENCE_PROMPT = """You are writing a structured reference page for someone who needs the facts fast.

Output ONLY a JSON object — no prose before, no prose after, no markdown fences. Schema:
  {
    "topic":      "<the noun being defined, 1-4 words>",
    "definition": "<one sentence — what it is, plainly>",
    "sections":   [{"heading": "<2-4 words>", "content": "<one short paragraph>"}],
    "see_also":   ["<related topic>", "<related topic>"]
  }

Rules:
- No HTML, no markdown.
- Three to five sections. Each is one paragraph of prose, not a list.
- See-also is two to four related concepts. Just the noun, no explanation."""


LESSON_PROMPT = """You are designing one short adaptive lesson — the way a patient teacher would.

Output ONLY a JSON object — no prose before, no prose after, no markdown fences. Schema:
  {
    "topic":       "<2-5 words>",
    "objective":   "<one sentence: what the learner will understand>",
    "exploration": "<3-4 short paragraphs of prose that build the idea step by step, separated by \\n\\n>",
    "question":    "<one open-ended question that invites reflection, not a quiz>"
  }

Rules:
- No HTML, no markdown.
- The exploration should not lecture. Show one concrete example.
- The question is for the learner to sit with — never multiple choice."""


SUBTYPES = {
    "note":      {"prompt": NOTE_PROMPT,      "label": "note"},
    "reference": {"prompt": REFERENCE_PROMPT, "label": "reference"},
    "lesson":    {"prompt": LESSON_PROMPT,    "label": "lesson"},
}


# ── Rendering ─────────────────────────────────────────────────────────

_SHELL = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #0a0a0a; --panel: #111114; --border: #1f1f1f;
    --fg: #e5e5e5; --mute: #6a7a72; --accent: #00ff88; --amber: #ffb800;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ background: var(--bg); color: var(--fg); }}
  body {{
    font-family: "Inter", "Helvetica Neue", system-ui, sans-serif;
    padding: 32px 40px 40px;
    line-height: 1.6;
    font-size: 15px;
  }}
  .kicker {{
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: 10px;
  }}
  h1, h2 {{ font-family: "Inter", "Helvetica Neue", sans-serif; letter-spacing: -0.015em; }}
  h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 14px; }}
  h2 {{ font-size: 13px; font-weight: 600; color: var(--mute); text-transform: uppercase;
        letter-spacing: 0.08em; margin: 28px 0 8px; }}
  p {{ margin-bottom: 12px; color: #c8c8d0; }}
  .summary {{ font-size: 16px; color: var(--fg); margin-bottom: 24px; }}
  .definition {{ font-size: 16px; color: var(--fg); padding: 14px 16px; border-left: 2px solid var(--accent); margin: 18px 0 24px; }}
  .objective {{ font-size: 14px; color: var(--amber); margin: 10px 0 22px; }}
  ul {{ list-style: none; padding: 0; margin: 6px 0 0; }}
  li {{ position: relative; padding-left: 18px; color: #c8c8d0; margin-bottom: 8px; }}
  li::before {{ content: "›"; position: absolute; left: 0; color: var(--accent); }}
  .pill-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .pill {{
    font-family: "JetBrains Mono", monospace;
    font-size: 11px; letter-spacing: 0.04em;
    padding: 4px 10px; border: 1px solid var(--border); border-radius: 999px; color: var(--mute);
  }}
  .question {{
    font-size: 16px; color: var(--fg); padding: 18px 20px;
    border: 1px solid var(--border); background: var(--panel); margin-top: 24px;
  }}
  footer {{
    margin-top: 36px; padding-top: 14px; border-top: 1px solid var(--border);
    font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--mute);
    letter-spacing: 0.06em;
  }}
</style></head><body>
{body}
<footer>scatter · {subtype} · {model}</footer>
</body></html>"""


def _paragraphs(text: str) -> str:
    """Render escaped paragraphs from a multi-paragraph string."""
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in parts)


def _render_note(d: dict, model: str) -> str:
    title = (d.get("title") or "untitled note").strip()
    summary = (d.get("summary") or "").strip()
    body = _paragraphs(d.get("body") or "")
    points = d.get("key_points") or []
    points_html = ""
    if isinstance(points, list) and points:
        items = "\n".join(f"<li>{html.escape(str(p))}</li>" for p in points if p)
        points_html = f"<h2>key points</h2><ul>{items}</ul>"
    body_html = (
        f'<div class="kicker">note</div>'
        f"<h1>{html.escape(title)}</h1>"
        + (f'<p class="summary">{html.escape(summary)}</p>' if summary else "")
        + body
        + points_html
    )
    return _SHELL.format(title=html.escape(title), body=body_html, subtype="note", model=html.escape(model))


def _render_reference(d: dict, model: str) -> str:
    topic = (d.get("topic") or "untitled reference").strip()
    definition = (d.get("definition") or "").strip()
    sections = d.get("sections") or []
    see_also = d.get("see_also") or []
    sections_html = ""
    if isinstance(sections, list):
        for s in sections:
            if not isinstance(s, dict):
                continue
            heading = html.escape(str(s.get("heading", "")).strip())
            content = _paragraphs(str(s.get("content") or ""))
            if heading or content:
                sections_html += f"<h2>{heading}</h2>{content}"
    see_html = ""
    if isinstance(see_also, list) and see_also:
        pills = "".join(f'<span class="pill">{html.escape(str(t))}</span>' for t in see_also if t)
        see_html = f'<h2>see also</h2><div class="pill-row">{pills}</div>'
    body_html = (
        f'<div class="kicker">reference</div>'
        f"<h1>{html.escape(topic)}</h1>"
        + (f'<div class="definition">{html.escape(definition)}</div>' if definition else "")
        + sections_html
        + see_html
    )
    return _SHELL.format(title=html.escape(topic), body=body_html, subtype="reference", model=html.escape(model))


def _render_lesson(d: dict, model: str) -> str:
    topic = (d.get("topic") or "untitled lesson").strip()
    objective = (d.get("objective") or "").strip()
    exploration = _paragraphs(d.get("exploration") or "")
    question = (d.get("question") or "").strip()
    body_html = (
        f'<div class="kicker">lesson</div>'
        f"<h1>{html.escape(topic)}</h1>"
        + (f'<div class="objective">{html.escape(objective)}</div>' if objective else "")
        + exploration
        + (f'<div class="question">{html.escape(question)}</div>' if question else "")
    )
    return _SHELL.format(title=html.escape(topic), body=body_html, subtype="lesson", model=html.escape(model))


_RENDERERS = {"note": _render_note, "reference": _render_reference, "lesson": _render_lesson}


# ── JSON extraction ───────────────────────────────────────────────────

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of qwen's response. Tolerates fenced blocks
    and prose preambles. Raises ValueError if nothing parses."""
    if not text:
        raise ValueError("empty model output")
    candidates = []
    for m in _FENCE.finditer(text):
        candidates.append(m.group(1).strip())
    # Also try the largest brace-balanced span
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text.strip())
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            continue
    raise ValueError("model did not return parseable JSON")


# ── Public entry ──────────────────────────────────────────────────────

def generate(
    subtype: str,
    user_prompt: str,
    ollama_chat: Callable[[list, str], str],
    model: str,
) -> str:
    """Generate an artifact of `subtype` for `user_prompt`.

    `ollama_chat(messages, model)` is injected so this module never imports
    server.py — keeps the dependency arrow pointing inward.

    Returns a complete HTML document ready to drop into an iframe srcdoc.
    Raises RuntimeError on any model or parse failure (caller decides
    whether to surface as chat error or fallback)."""
    if subtype not in SUBTYPES:
        raise RuntimeError(f"unknown artifact subtype: {subtype}")
    cfg = SUBTYPES[subtype]
    messages = [
        {"role": "system", "content": cfg["prompt"]},
        {"role": "user", "content": user_prompt},
    ]
    response = ollama_chat(messages, model)
    try:
        data = _extract_json(response)
    except ValueError as e:
        raise RuntimeError(f"{subtype} generation: {e}") from e
    renderer = _RENDERERS[subtype]
    return renderer(data, model)

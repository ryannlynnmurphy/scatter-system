#!/usr/bin/env python3
"""
scatter/ai_local.py — local AI primitives.

Three verbs the craft apps want:
  transcribe  audio → text              (whisper.cpp or openai-whisper)
  caption     image → description       (ollama + vision model, e.g. llava)
  coverage    script + clips → gap report   (ollama + qwen2.5-coder)

These are *local* calls. They talk to localhost services (Ollama on
127.0.0.1:11434) or invoke local binaries (whisper). They do NOT go
through scatter/api.py because they do not leave the machine. Every
call is journaled and watts-logged via scatter_core.

Honest fallback strategy: if a required tool/model is missing, the
primitive raises RuntimeError with the exact install command. Nothing
is pulled or apt-installed automatically — that decision is the user's.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


OLLAMA_URL = os.environ.get("SCATTER_OLLAMA_URL", "http://127.0.0.1:11434")
BUILD_MODEL = os.environ.get("SCATTER_MODEL", "qwen2.5-coder:7b")
VISION_MODELS_PREFERRED = ("llava:7b", "llava:13b", "llava", "bakllava", "moondream")


# ---------- internals ----------

def _ollama_models() -> list[str]:
    try:
        with urlopen(Request(f"{OLLAMA_URL}/api/tags"), timeout=3) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except (URLError, json.JSONDecodeError, OSError):
        return []


def _ollama_generate(model: str, prompt: str, images: Optional[list[str]] = None,
                     temperature: float = 0.2, num_predict: int = 512) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    if images:
        payload["images"] = images
    req = Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read())
    duration = time.monotonic() - t0
    # Rough watts estimate. Real numbers come from task #30.
    joules = 35.0 * duration if "7b" in model or "13b" in model else 18.0 * duration
    sc.watts_log(source=f"model:{model}", joules=joules, duration_s=duration)
    return result.get("response", "")


def _pick_vision_model() -> Optional[str]:
    available = set(_ollama_models())
    for candidate in VISION_MODELS_PREFERRED:
        if candidate in available:
            return candidate
        # also try without tag
        base = candidate.split(":")[0]
        for m in available:
            if m.split(":")[0] == base:
                return m
    return None


# ---------- transcribe ----------

def transcribe(audio_path: str, language: Optional[str] = None) -> str:
    """Transcribe audio to text via whisper.cpp or openai-whisper.

    Raises RuntimeError with install instructions if neither is present."""
    src = Path(audio_path)
    if not src.is_file():
        raise FileNotFoundError(f"audio not found: {audio_path}")

    audit_id = sc.journal_append(
        "ai_local_start",
        verb="transcribe",
        source=str(src),
        language=language or "auto",
    )

    # whisper.cpp binary
    wc = shutil.which("whisper-cpp") or shutil.which("whisper")
    t0 = time.monotonic()
    try:
        if wc and wc.endswith("whisper-cpp"):
            cmd = [wc, "-f", str(src), "-otxt", "-of", f"/tmp/scatter-transcribe-{os.getpid()}"]
            if language:
                cmd.extend(["-l", language])
            subprocess.run(cmd, check=True, capture_output=True)
            out_path = Path(f"/tmp/scatter-transcribe-{os.getpid()}.txt")
            text = out_path.read_text() if out_path.exists() else ""
            out_path.unlink(missing_ok=True)
        elif wc:
            # openai-whisper CLI: `whisper file.wav --output_dir /tmp --output_format txt`
            out_dir = f"/tmp/scatter-transcribe-{os.getpid()}"
            Path(out_dir).mkdir(exist_ok=True)
            cmd = [wc, str(src), "--output_dir", out_dir, "--output_format", "txt"]
            if language:
                cmd.extend(["--language", language])
            subprocess.run(cmd, check=True, capture_output=True)
            # openai-whisper writes <stem>.txt in out_dir
            txt_file = Path(out_dir) / f"{src.stem}.txt"
            text = txt_file.read_text() if txt_file.exists() else ""
            shutil.rmtree(out_dir, ignore_errors=True)
        else:
            raise RuntimeError(
                "No whisper binary found. Install one of:\n"
                "  sudo apt install whisper-cpp          # fast, local, recommended\n"
                "  pipx install openai-whisper           # python, slower, more models\n"
                "Also needs ffmpeg: sudo apt install ffmpeg"
            )
        duration = time.monotonic() - t0
        sc.watts_log(source="whisper", joules=15.0 * duration, duration_s=duration)
        sc.journal_append(
            "ai_local_done",
            verb="transcribe",
            source=str(src),
            chars=len(text),
            duration_s=round(duration, 2),
        )
        return text.strip()
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace")[:300] if e.stderr else ""
        sc.journal_append("ai_local_fail", verb="transcribe", error=stderr)
        raise RuntimeError(f"whisper failed: {stderr}") from e


# ---------- caption ----------

def caption(image_path: str, prompt: str = "Describe this image in one concise sentence.") -> str:
    """Caption an image via Ollama + a pulled vision model.

    Raises RuntimeError if no vision model is available — with the
    exact `ollama pull` command to fix."""
    src = Path(image_path)
    if not src.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")

    model = _pick_vision_model()
    if not model:
        raise RuntimeError(
            "No vision model available. Pull one:\n"
            "  ollama pull llava:7b          # 4.7GB, fast\n"
            "  ollama pull llava:13b         # 8GB, better quality\n"
            "  ollama pull moondream         # ~1.7GB, tiny\n"
            "Scatter will auto-detect after the pull."
        )

    sc.journal_append("ai_local_start", verb="caption", source=str(src), model=model)
    b64 = base64.b64encode(src.read_bytes()).decode()
    response = _ollama_generate(model, prompt, images=[b64], num_predict=200)
    text = response.strip()
    sc.journal_append(
        "ai_local_done",
        verb="caption",
        source=str(src),
        model=model,
        chars=len(text),
    )
    return text


# ---------- coverage (script-aware gap analysis) ----------

COVERAGE_PROMPT = """You are a script supervisor. You have a shooting script and a list of filmed clips. Report which scenes have coverage and which have gaps.

SHOOTING SCRIPT:
{script}

FILMED CLIPS (filename and short note if provided):
{clips}

For each scene in the script, output one JSON object per line (one per scene):
{{"scene": <number>, "description": "<short>", "covered": <bool>, "missing_shots": ["close-up on X", "reaction of Y"], "suggestion": "<one sentence>"}}

Only output the JSON lines, one per scene, no markdown fences, no prose before or after."""


def coverage(script_path: str, clips: list[str]) -> list[dict]:
    """Script-aware coverage analysis.

    Takes a script file and a list of clip filenames/descriptors.
    Returns a list of scene-by-scene gap reports from qwen2.5-coder.
    """
    src = Path(script_path)
    if not src.is_file():
        raise FileNotFoundError(f"script not found: {script_path}")

    available = set(_ollama_models())
    if BUILD_MODEL not in available:
        raise RuntimeError(
            f"Build model {BUILD_MODEL} not pulled. Fix: ollama pull {BUILD_MODEL}"
        )

    script_text = src.read_text(encoding="utf-8", errors="replace")
    clips_text = "\n".join(f"- {c}" for c in clips) if clips else "(no clips provided)"

    sc.journal_append(
        "ai_local_start",
        verb="coverage",
        source=str(src),
        clips_n=len(clips),
        model=BUILD_MODEL,
    )

    prompt = COVERAGE_PROMPT.format(script=script_text[:8000], clips=clips_text)
    response = _ollama_generate(BUILD_MODEL, prompt, num_predict=1024, temperature=0.1)

    # Parse line-by-line JSON. Skip lines that don't parse.
    scenes = []
    for line in response.splitlines():
        line = line.strip().lstrip("```json").rstrip("```").strip()
        if not line or not line.startswith("{"):
            continue
        try:
            scenes.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    sc.journal_append(
        "ai_local_done",
        verb="coverage",
        source=str(src),
        scenes_reported=len(scenes),
    )
    return scenes


# ---------- CLI ----------

def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scatter-ai", description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="verb", required=True)

    p_t = sub.add_parser("transcribe", help="audio → text (whisper)")
    p_t.add_argument("audio", help="path to audio file")
    p_t.add_argument("--lang", default=None, help="language code (e.g. en)")

    p_c = sub.add_parser("caption", help="image → description (ollama vision)")
    p_c.add_argument("image", help="path to image file")
    p_c.add_argument("--prompt", default="Describe this image in one concise sentence.")

    p_cov = sub.add_parser("coverage", help="script + clips → gap report")
    p_cov.add_argument("script", help="path to script .txt/.fountain/.md")
    p_cov.add_argument("clips", nargs="*", help="clip filenames/descriptions")

    sub.add_parser("status", help="report which primitives are available")

    args = parser.parse_args(argv)

    try:
        if args.verb == "transcribe":
            print(transcribe(args.audio, language=args.lang))
        elif args.verb == "caption":
            print(caption(args.image, prompt=args.prompt))
        elif args.verb == "coverage":
            scenes = coverage(args.script, args.clips)
            print(json.dumps(scenes, indent=2))
        elif args.verb == "status":
            models = _ollama_models()
            vision = _pick_vision_model()
            whisper = shutil.which("whisper-cpp") or shutil.which("whisper")
            print(f"ollama daemon: {'up' if models else 'DOWN'}")
            print(f"  build model ({BUILD_MODEL}): {'yes' if BUILD_MODEL in models else 'NOT PULLED'}")
            print(f"  vision model: {vision or 'none pulled (caption unavailable)'}")
            print(f"whisper: {whisper or 'not installed (transcribe unavailable)'}")
            print(f"ffmpeg: {'yes' if shutil.which('ffmpeg') else 'not installed (whisper may fail)'}")
    except RuntimeError as e:
        print(f"scatter-ai: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"scatter-ai: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))

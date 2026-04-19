#!/usr/bin/env python3
"""
scatter/tts.py — text-to-speech primitives.

Two paths, one interface:
  speak_local(text)  → Piper, fully offline, watts-logged as "tts:piper"
  speak_cloud(text)  → ElevenLabs, visible cloud egress, logged as "tts:elevenlabs"

Both return raw WAV/MP3 bytes. Callers decide whether to stream, save, or
serve the audio. Stdlib only, matching scatter-system's zero-deps posture.

Network egress for ElevenLabs is *explicit*: the caller must pass
prefer_local=False AND the API key must be present. There is no silent
fallback from local to cloud — if Piper is missing, we raise with the
install command. The user chooses the path, every time.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scatter_core as sc  # noqa: E402


ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech"
ELEVEN_MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_turbo_v2_5")


# ---------- local (Piper) ----------

def speak_local(text: str) -> bytes:
    """Synthesize speech locally via Piper. Returns WAV bytes.

    Raises RuntimeError with install guidance if Piper or the voice model
    is missing."""
    piper = shutil.which("piper")
    if not piper:
        raise RuntimeError(
            "piper isn't installed. in a terminal: sudo apt install piper-tts"
        )
    voice_path = os.path.expanduser(
        os.environ.get("PIPER_VOICE_MODEL", "~/.scatter/voices/en_US-lessac-medium.onnx")
    )
    if not Path(voice_path).is_file():
        raise RuntimeError(
            f"piper voice model not found at {voice_path}. "
            "download one from https://github.com/rhasspy/piper/releases"
        )

    t0 = time.monotonic()
    proc = subprocess.run(
        [piper, "-m", voice_path, "--output_raw"],
        input=text.encode(),
        capture_output=True,
        check=False,
    )
    duration = time.monotonic() - t0
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace")[:300]
        sc.watts_log(source="tts:piper", joules=8.0 * duration, duration_s=duration)
        raise RuntimeError(f"piper failed: {err}")

    # piper --output_raw writes PCM s16le 22050Hz. Wrap in a WAV header.
    wav = _wrap_pcm_as_wav(proc.stdout, sample_rate=22050, channels=1, bits=16)

    # Rough: Piper uses ~8W on laptop CPU during synthesis. Real numbers
    # come from the watts_baseline task (measure with RAPL/upower).
    sc.watts_log(
        source="tts:piper",
        joules=8.0 * duration,
        duration_s=duration,
        tokens=len(text),
    )
    sc.journal_append("tts", path="local:piper", chars=len(text),
                      duration_s=round(duration, 3))
    return wav


# ---------- cloud (ElevenLabs) ----------

def speak_cloud(text: str, voice_id: Optional[str] = None) -> bytes:
    """Synthesize speech via ElevenLabs. Returns MP3 bytes.

    Raises RuntimeError if no API key is set."""
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set. add it to ~/scatter-system/scatter/.env"
        )
    vid = voice_id or os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    if not vid:
        raise RuntimeError(
            "ELEVENLABS_VOICE_ID not set. add it to ~/scatter-system/scatter/.env"
        )

    payload = json.dumps({
        "text": text,
        "model_id": ELEVEN_MODEL,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
    }).encode()
    req = Request(
        f"{ELEVEN_URL}/{vid}",
        data=payload,
        headers={
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )

    t0 = time.monotonic()
    try:
        with urlopen(req, timeout=30) as resp:
            audio = resp.read()
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode(errors="replace")[:300]
        except Exception:
            pass
        duration = time.monotonic() - t0
        sc.watts_log(source="tts:elevenlabs", joules=3.0 * duration,
                     duration_s=duration)
        if e.code == 401:
            raise RuntimeError("elevenlabs rejected the api key. check .env") from e
        if e.code == 429:
            raise RuntimeError("elevenlabs rate-limited. try again shortly") from e
        raise RuntimeError(f"elevenlabs HTTP {e.code}: {body}".strip()) from e
    except URLError as e:
        duration = time.monotonic() - t0
        sc.watts_log(source="tts:elevenlabs", joules=3.0 * duration,
                     duration_s=duration)
        raise RuntimeError(f"can't reach elevenlabs: {getattr(e, 'reason', e)}") from e

    duration = time.monotonic() - t0
    # Local watts are tiny (network + audio playback). Upstream datacenter
    # cost is opaque — that asymmetry is the honest caveat.
    sc.watts_log(
        source="tts:elevenlabs",
        joules=3.0 * duration,
        duration_s=duration,
        tokens=len(text),
    )
    sc.journal_append("tts", path="cloud:elevenlabs", chars=len(text),
                      voice_id=vid, duration_s=round(duration, 3))
    return audio


# ---------- helpers ----------

def _wrap_pcm_as_wav(pcm: bytes, sample_rate: int, channels: int, bits: int) -> bytes:
    """Build a WAV header around raw PCM. Avoids pulling in `wave` with a
    tempfile round-trip."""
    import struct
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    data_size = len(pcm)
    header = b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH",
                                     16, 1, channels, sample_rate,
                                     byte_rate, block_align, bits)
    header += b"data" + struct.pack("<I", data_size)
    return header + pcm

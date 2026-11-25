"""Natural local text-to-speech via Piper (offline, free). Falls back gracefully if not installed."""

from __future__ import annotations

import io
import threading
import wave
from pathlib import Path

VOICE_DIR = Path(r"F:\DDG_Video_Studio\models\piper")
VOICE_NAME = "en_GB-alan-medium"
_lock = threading.Lock()
_voice = None


def voice_files() -> tuple[Path, Path]:
    return VOICE_DIR / f"{VOICE_NAME}.onnx", VOICE_DIR / f"{VOICE_NAME}.onnx.json"


def is_ready() -> bool:
    m, c = voice_files()
    if not (m.exists() and c.exists()):
        return False
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return True


def synthesize_wav(text: str) -> bytes:
    global _voice
    from piper import PiperVoice

    text = " ".join((text or "").split())[:1500]
    if not text:
        raise ValueError("empty text")
    with _lock:
        if _voice is None:
            m, c = voice_files()
            _voice = PiperVoice.load(str(m), config_path=str(c))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            _voice.synthesize_wav(text, wf)
        return buf.getvalue()

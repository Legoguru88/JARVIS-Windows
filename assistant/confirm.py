import os
import threading

import numpy as np

_MODEL = None
_LOCK = threading.Lock()


def _transcribe(clip: np.ndarray) -> str:
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel

            size = os.environ.get("STT_MODEL", "tiny.en").strip() or "tiny.en"
            _MODEL = WhisperModel(size, device="cpu", compute_type="int8")
    audio = clip.astype(np.float32) / 32768.0
    segments, _ = _MODEL.transcribe(audio, language="en", vad_filter=True)
    return " ".join(s.text for s in segments).strip().lower()


def confirm_wakeup(clip: np.ndarray, phrase: str) -> bool:
    text = _transcribe(clip)
    print(f"confirm: heard -> {text!r}", flush=True)
    return phrase.lower() in text
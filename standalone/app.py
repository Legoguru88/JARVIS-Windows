"""
JARVIS.exe — fully self-contained Windows voice assistant.

Everything is bundled into this one file:
  - Wake word ("hey jarvis")          openwakeword (embedded model)
  - Confirmation speech-to-text       faster-whisper tiny.en (bundled model)
  - Briefing generation               llama-cpp-python + bundled Qwen GGUF
  - Speech output                     Windows SAPI (built into the OS)

Build it with build.ps1. Runs entirely offline; installs nothing on the PC.
"""

import os
import sys
import time
import traceback
import threading
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
EXE_DIR = Path(sys.executable).parent
CONFIG = EXE_DIR / ".env"
TASKS_FILE = EXE_DIR / "tasks.txt"
LOG_FILE = EXE_DIR / "jarvis.log"


def log_error(context: str, error: BaseException) -> None:
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {context}: {error}\n")
            fh.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
            fh.write("\n")
    except Exception:
        pass

# ---------------------------------------------------------------- config

DEFAULTS = {
    "WAKE_THRESHOLD": "0.35",
    "CONFIRM_WAKEUP": "1",
    "WAKEUP_PHRASE": "wake up",
    "STT_MODEL": "tiny.en",
    "WAKEUP_WINDOW": "3.0",
    "JARVIS_SPEED": "1.2",
    "JARVIS_VOLUME": "1.0",
    "OLLAMA_QUALITY": "0.7",
}

cfg = dict(DEFAULTS)
if CONFIG.exists():
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        cfg[k.strip()] = v.strip()

FLOAT = lambda key, default: float(cfg.get(key, str(default)).strip() or default)
WAKE_THRESHOLD = FLOAT("WAKE_THRESHOLD", 0.35)
CONFIRM_WAKEUP = str(cfg.get("CONFIRM_WAKEUP", "1")).strip() != "0"
WAKEUP_PHRASE = (cfg.get("WAKEUP_PHRASE", "wake up").strip() or "wake up").lower()
WAKEUP_WINDOW = FLOAT("WAKEUP_WINDOW", 3.0)
JARVIS_SPEED = FLOAT("JARVIS_SPEED", 1.2)

os.environ.setdefault("HF_HUB_OFFLINE", "1")

# ---------------------------------------------------------------- wake word

SAMPLE_RATE = 16000
CHUNK = 1280


def listen(on_wake, cooldown: float = 10.0) -> None:
    import sounddevice as sd
    from openwakeword.model import Model

    model = Model(wakeword_models=["hey jarvis"])
    key = "hey jarvis"
    last_hit = 0.0
    recording = {"active": False, "buffers": [], "started": 0.0}

    def callback(indata, frames, time_info, status):
        audio = np.squeeze(indata).copy()
        now = time.monotonic()
        if recording["active"]:
            recording["buffers"].append(audio)
            if now - recording["started"] >= WAKEUP_WINDOW:
                clip = np.concatenate(recording["buffers"])
                recording["active"] = False
                recording["buffers"] = []
                print("wake: captured confirmation clip", flush=True)
                on_wake(clip)
            return
        scores = model.predict(audio)
        score = float(scores.get(key, 0.0))
        if score > WAKE_THRESHOLD and now - last_hit > cooldown:
            last_hit = now
            print(f"wake: '{key}' detected (score={score:.2f})", flush=True)
            recording["active"] = True
            recording["started"] = now
            recording["buffers"] = [audio]

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK,
        callback=callback,
    ):
        print("wake: listening for 'hey jarvis'", flush=True)
        while True:
            sd.sleep(1000)


# ---------------------------------------------------------------- confirm (whisper)

_WHISPER = None
_WHISPER_LOCK = threading.Lock()


def _whisper_model():
    global _WHISPER
    with _WHISPER_LOCK:
        if _WHISPER is None:
            from faster_whisper import WhisperModel

            local = BASE / "models" / "whisper" / "tiny.en"
            _WHISPER = WhisperModel(str(local), device="cpu", compute_type="int8")
    return _WHISPER


def confirm_wakeup(clip: np.ndarray) -> bool:
    audio = clip.astype(np.float32) / 32768.0
    segments, _ = _whisper_model().transcribe(
        audio, language="en", vad_filter=True
    )
    text = " ".join(s.text for s in segments).strip().lower()
    print(f"confirm: heard -> {text!r}", flush=True)
    return WAKEUP_PHRASE in text


# ---------------------------------------------------------------- speech output

def sapi_speak(text: str) -> None:
    rate = int((JARVIS_SPEED - 1.0) * 5)
    safe = text.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name } | "
        "Where-Object { $_ -match 'Zira|David|Mark|Aria|Jenny' } | Select-Object -First 1; "
        "if ($v) { $s.SelectVoice($v) } "
        f"$s.Rate = {rate}; "
        f"$s.Speak('{safe}');"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=False,
        timeout=300,
    )


def notify(title: str, message: str) -> None:
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        r"$n.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info;"
        "$n.Visible = $true;"
        f"$n.BalloonTipTitle = '{title.replace(chr(39), chr(39) * 2)}';"
        f"$n.BalloonTipText = '{message.replace(chr(39), chr(39) * 2)}';"
        "$n.ShowBalloonTip(5000);"
        "Start-Sleep -Seconds 6;"
        "$n.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=False,
    )


def play_tone() -> None:
    try:
        import winsound
        winsound.Beep(920, 140)
    except Exception:
        pass


# ---------------------------------------------------------------- local LLM

_LLM_LOCK = threading.Lock()
_LLM = None


def _load_llm():
    global _LLM
    with _LLM_LOCK:
        if _LLM is None:
            try:
                from llama_cpp import Llama
            except Exception as error:
                log_error("import llama_cpp", error)
                raise
            gguf = BASE / "models" / "qwen" / "model.gguf"
            for layers in (-1, 0):  # try full GPU offload, else CPU
                try:
                    _LLM = Llama(
                        model_path=str(gguf),
                        n_ctx=4096,
                        n_gpu_layers=layers,
                        verbose=False,
                    )
                    break
                except Exception as error:
                    log_error(f"llama load (n_gpu_layers={layers})", error)
                    if layers == 0:
                        raise
                    print(f"GPU offload failed ({error}); using CPU", flush=True)
    return _LLM


def ollama_chat(prompt: str, temperature: float, max_tokens: int) -> str:
    llm = _load_llm()
    out = llm.create_chat_completion(
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return out["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------- briefing

_NUM_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    30: "thirty", 40: "forty", 50: "fifty",
}


def spoken_time() -> str:
    now = datetime.now()
    hour = now.hour % 12 or 12
    minute = now.minute
    hour_word = _NUM_WORDS.get(hour, str(hour))
    if minute == 0:
        clock = f"{hour_word} o'clock"
    else:
        tens, ones = divmod(minute, 10)
        if tens == 0:
            minute_word = _NUM_WORDS.get(ones, str(ones))
        elif ones == 0:
            minute_word = _NUM_WORDS.get(tens * 10, str(tens * 10))
        else:
            minute_word = (
                f"{_NUM_WORDS.get(tens * 10, str(tens * 10))} "
                f"{_NUM_WORDS.get(ones, str(ones))}"
            )
        clock = f"{hour_word} {minute_word}"
    period = (
        "in the morning" if now.hour < 12
        else ("in the afternoon" if now.hour < 18 else "in the evening")
    )
    return f"{clock} {period}"


def current_temperature() -> str | None:
    try:
        import urllib.request

        with urllib.request.urlopen("https://wttr.in/?format=%t", timeout=8) as resp:
            raw = resp.read().decode().strip()
        digits = "".join(ch for ch in raw if ch.isdigit() or ch in "+-")
        if not digits:
            return None
        return f"{int(digits)} degrees"
    except Exception:
        return None


def opener_line() -> str:
    parts = ["Hi Gabriel."]
    parts.append(f"The time is {spoken_time()}.")
    temp = current_temperature()
    if temp:
        parts.append(f"The temperature is {temp}.")
    return " ".join(parts)


def load_tasks() -> list[str]:
    for candidate in (TASKS_FILE, BASE / "tasks.txt"):
        if candidate.exists():
            return [
                line.strip()
                for line in candidate.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
    return []


def generate_briefing_text(tasks: list[str]) -> str:
    task_lines = "\n".join(f"- {t}" for t in tasks) if tasks else "No tasks listed for today."
    prompt = (
        "You are JARVIS, Tony Stark's highly capable personal AI assistant. "
        "Speak in polished, natural British English with a calm, refined and understated manner. "
        'Address the user as "sir" naturally, but never excessively. '
        "Your humour is subtle, dry and occasionally sardonic. "
        "Deliver a concise spoken morning briefing, under 100 words. "
        "Begin with a brief, courteous greeting, state the number of tasks for today, "
        "then summarise each task naturally, prioritising anything urgent. "
        "Conclude with a brief, understated remark in JARVIS's characteristic dry wit. "
        "Do not use markdown, bullet points, or headers — the response will be spoken aloud exactly as written.\n\n"
        f"Tasks:\n{task_lines}"
    )
    return ollama_chat(prompt, temperature=float(cfg.get("OLLAMA_QUALITY", "0.7")), max_tokens=200)


# ---------------------------------------------------------------- assistant

class Assistant:
    def __init__(self) -> None:
        self.busy = False

    def on_wake(self, clip) -> None:
        if self.busy:
            return
        if CONFIRM_WAKEUP and not confirm_wakeup(clip):
            print("confirm: phrase not recognized, standing by", flush=True)
            return
        self.trigger()

    def trigger(self) -> None:
        if self.busy:
            return
        self.busy = True
        try:
            notify("JARVIS", "At your service, sir.")
            play_tone()
            briefing = generate_briefing_text(load_tasks())
            sapi_speak(f"{opener_line()}. {briefing}")
        except Exception as error:
            print(f"error: {error}", flush=True)
            log_error("trigger", error)
            sapi_speak("I could not prepare the briefing, sir.")
        finally:
            self.busy = False


def main() -> None:
    assistant = Assistant()
    if "--once" in sys.argv:
        assistant.trigger()
        return
    print("JARVIS.exe ready. Say 'hey jarvis' then 'wake up'.", flush=True)
    listen(assistant.on_wake)


if __name__ == "__main__":
    main()
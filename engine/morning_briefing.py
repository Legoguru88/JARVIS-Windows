#!/usr/bin/env python3
"""
Morning Briefing
----------------
Reads your tasks from tasks.txt (or tasks.json), asks the local Ollama model
to turn them
into a short spoken briefing, converts that text to audio with ElevenLabs,
and plays it out loud.

Commands:
  python3 morning_briefing.py                # run the spoken briefing
  python3 morning_briefing.py --text-only    # print briefing text only
  python3 morning_briefing.py --speak        # speak output with JARVIS (any command)
  python3 morning_briefing.py add "Task"     # append a task
  python3 morning_briefing.py list           # show numbered tasks
  python3 morning_briefing.py done 5         # remove task by number
  python3 morning_briefing.py open           # open the tasks file
  python3 morning_briefing.py ask "Q?"       # open-ended Ollama answer
  python3 morning_briefing.py study "subj"   # open ~/Notes/<subj> + pomodoro
  python3 morning_briefing.py routine        # JARVIS reads today's briefing
  python3 morning_briefing.py scan "img"     # OCR image -> raw text
  python3 morning_briefing.py schedule "img" # OCR + filter to you -> schedule.json
  python3 morning_briefing.py tune           # cycle voice blend ratios to pick one
  python3 morning_briefing.py tune -t "..."  # tune with a custom sample phrase
  python3 morning_briefing.py say "..."      # JARVIS speaks any phrase aloud
  python3 morning_briefing.py mp3 -o intro.mp3 "..."  # save JARVIS line to an mp3 file
  python3 morning_briefing.py send           # send the briefing to your phone via Telegram

Setup:
  1. pip install -r requirements.txt
  2. Start Ollama and pull a model (the default is llama3.1:8b). Set environment
     variables (or put them in a .env file next to this script) as needed:
       OLLAMA_URL=...   (optional, defaults to http://localhost:11434/v1)
       OLLAMA_MODEL=... (optional, defaults to llama3.1:8b)
       ELEVENLABS_API_KEY=...
       ELEVENLABS_VOICE_ID=...   (optional, defaults to a stock voice)
  3. Run: python3 morning_briefing.py
"""

import os
import sys
import json
import time
import shutil
import random
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
TASKS_FILE = SCRIPT_DIR / "tasks.json"
SCHEDULES_DIR = SCRIPT_DIR / "schedules"
BRIEFING_TEXT_FILE = Path(tempfile.gettempdir()) / "jarvis_briefing.txt"

IS_WINDOWS = os.name == "nt"


def schedule_file() -> Path:
    """Schedule JSON for the current week, named by the week's Monday date."""
    return SCHEDULES_DIR / f"{week_monday()}.json"

_VENV_PY = SCRIPT_DIR / ".venv" / "Scripts" / "python.exe"
if (
    __name__ == "__main__"
    and _VENV_PY.exists()
    and Path(sys.prefix).resolve() != _VENV_PY.parent.parent.resolve()
):
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

# Load .env if present (simple, no extra dependency required)
def load_dotenv(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())

load_dotenv(SCRIPT_DIR / ".env")

ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # "Rachel" stock voice
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
JARVIS_VOICE = os.environ.get("JARVIS_VOICE", "Charon")
JARVIS_POCKET_VOICE = os.environ.get("JARVIS_POCKET_VOICE")
JARVIS_POCKET_URL = os.environ.get("JARVIS_POCKET_URL", "http://localhost:8000")
# > 1.0 = talk faster (1.2 = 20% faster), < 1.0 = slower. Pitch is preserved.
JARVIS_SPEED = float(os.environ.get("JARVIS_SPEED", "1.0").strip() or "1.0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")

TTS_MODEL_3_1 = "gemini-3.1-flash-tts-preview"
TTS_MODEL_2_5 = "gemini-2.5-flash-preview-tts"

SPEAK = False


def ollama_chat(prompt: str, temperature: float, max_tokens: int) -> str:
    """Ask the local Ollama model to answer, returning the text content."""
    import requests

    r = requests.post(
        f"{OLLAMA_URL}/chat/completions",
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def load_tasks() -> dict:
    txt_file = SCRIPT_DIR / "tasks.txt"
    if txt_file.exists():
        tasks = [
            line.strip()
            for line in txt_file.read_text().splitlines()
            if line.strip()
        ]
        return {"tasks": tasks, "notes": ""}
    if not TASKS_FILE.exists():
        sys.exit(f"Could not find {TASKS_FILE} or tasks.txt. Run 'add' to create tasks.txt.")
    return json.loads(TASKS_FILE.read_text())


def active_tasks_file() -> Path:
    txt_file = SCRIPT_DIR / "tasks.txt"
    if txt_file.exists() or not TASKS_FILE.exists():
        return txt_file
    return TASKS_FILE


def read_task_lines(file: Path) -> list[str]:
    if not file.exists():
        return []
    return [
        line.strip()
        for line in file.read_text().splitlines()
        if line.strip()
    ]


def add_task(task: str) -> None:
    file = active_tasks_file()
    tasks = read_task_lines(file)
    tasks.append(task)
    if file.suffix == ".json":
        file.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(file.read_text()) if file.exists() else {"tasks": [], "notes": ""}
        data["tasks"] = tasks
        file.write_text(json.dumps(data, indent=2) + "\n")
    else:
        file.write_text("\n".join(tasks) + "\n")


def remove_task(number: int) -> None:
    file = active_tasks_file()
    tasks = read_task_lines(file)
    if number < 1 or number > len(tasks):
        sys.exit(f"Task number {number} not found. Use 'list' to see tasks.")
    removed = tasks.pop(number - 1)
    if file.suffix == ".json":
        data = json.loads(file.read_text())
        data["tasks"] = tasks
        file.write_text(json.dumps(data, indent=2) + "\n")
    else:
        file.write_text("\n".join(tasks) + "\n")
    show(f"Removed: {removed}")


def open_tasks_file() -> None:
    if IS_WINDOWS:
        os.startfile(str(active_tasks_file()))
    else:
        subprocess.run(["open", str(active_tasks_file())], check=True)


def ocr_image(image_path: str) -> str:
    """Run OCR on an image and return its raw text. On Windows this uses
    pytesseract (install tesseract-ocr, or set TESSERACT_CMD in .env)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        sys.exit("OCR needs 'pip install pytesseract pillow' (plus tesseract-ocr).")
    cmd = os.environ.get("TESSERACT_CMD")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    elif shutil.which("tesseract"):
        pytesseract.pytesseract.tesseract_cmd = shutil.which("tesseract")
    else:
        sys.exit("tesseract not found on PATH. Install it or set TESSERACT_CMD in .env.")
    return pytesseract.image_to_string(Path(image_path)).strip()


def week_monday() -> str:
    today = datetime.now().date()
    return (today - timedelta(days=today.weekday())).isoformat()


def parse_schedule_to_file(raw_text: str, image_week: str) -> dict:
    """Ask Ollama to pull only Gabriel's entries from OCR'd timetable text."""
    prompt = (
        "Below is OCR text from a weekly school timetable. "
        "Extract ONLY the entries that belong to Gabriel (referred to as 'Gab' or 'Gabriel'): "
        "his dismissal, HBL, and his classes (STRIVE, Swift Accelerator, Pique Lab, "
        "LingoAce, Mr Jeremy, Ms Shuni, and so on). "
        "Exclude anything belonging to Elliott, shared family car rides, and pickup notes "
        "that seem to be for Elliott unless they clearly concern Gabriel. "
        "Group results by weekday using keys Mon, Tue, Wed, Thu, Fri, Sat, Sun. "
        "Return only JSON with no markdown, like: "
        '{"days": {"Mon": ["dismissal 2:30"], "Wed": ["dismissal 2:10", "5-6 Ms Shuni"]}}. '
        "Keep each item short. If OCR is garbled, preserve meaning where possible.\n\n"
        f"OCR text:\n{raw_text}"
    )

    content = ollama_chat(prompt, temperature=0.1, max_tokens=600)
    if content.startswith("```"):
        content = content.strip("`").removeprefix("json").strip()
    data = json.loads(content)

    payload = {"week_of": image_week, "days": data.get("days", {})}
    SCHEDULES_DIR.mkdir(exist_ok=True)
    schedule_file().write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def today_schedule() -> list[str]:
    """Return Gabriel's scheduled items for today, or [] if schedule is missing/stale."""
    if not schedule_file().exists():
        return []
    data = json.loads(schedule_file().read_text())
    if data.get("week_of") != week_monday():
        return []
    day_key = datetime.now().strftime("%a")
    return data.get("days", {}).get(day_key, [])


def synth_pocket(text: str, out_path: Path) -> Path | None:
    """Synthesize 'text' through a local Pocket TTS server using the user's own
    cloned voice (JARVIS_POCKET_VOICE). Returns the wav path, or None if the
    server or voice reference is unavailable."""
    voice = JARVIS_POCKET_VOICE
    if not voice or not Path(voice).exists():
        return None
    wav_path = out_path.with_suffix(".wav")
    try:
        import requests

        with open(voice, "rb") as vf:
            resp = requests.post(
                f"{JARVIS_POCKET_URL}/tts",
                files={"voice_wav": (Path(voice).name, vf, "audio/wav")},
                data={"text": text},
                timeout=120,
            )
        resp.raise_for_status()
        wav_path.write_bytes(resp.content)
        return wav_path
    except Exception as e:
        print(f"[TTS] Pocket TTS failed: {e}")
        return None


def synth_charon(text: str, out_path: Path) -> Path | None:
    """Synthesize 'text' with Gemini's JARVIS_VOICE (default Charon) to a wav
    file at the same location as out_path. Returns the wav path on success,
    or None if the API is unavailable or fails."""
    if not GEMINI_API_KEY:
        return None
    import wave
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    wav_path = out_path.with_suffix(".wav")
    last_err: Exception | None = None
    for model in (TTS_MODEL_3_1, TTS_MODEL_2_5):
        try:
            response = client.models.generate_content(
                model=model,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=JARVIS_VOICE,
                            )
                        )
                    ),
                ),
            )
            pcm = response.candidates[0].content.parts[0].inline_data.data
            with wave.open(str(wav_path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm)
            return wav_path
        except Exception as e:
            last_err = e
            continue
    print(f"[TTS] Gemini synth failed: {last_err}")
    return None


def sapi_speak(text: str, speed: float = 1.0) -> bool:
    """Speak with Windows' built-in SAPI voice via PowerShell. Returns True if
    a voice started speaking."""
    if os.name != "nt":
        return False
    rate = int((speed - 1.0) * 5)
    safe = text.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {rate}; "
        f"$s.Speak('{safe}');"
    )
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False, timeout=180)
        return True
    except Exception as e:
        print(f"[TTS] SAPI failed: {e}")
        return False


def ffplay_available() -> bool:
    return shutil.which("ffplay") is not None


def play_sound(path: str | Path, volume: str | None = None, wait: bool = True) -> bool:
    """Play an audio file without raising on failure, so broken system audio
    can't crash JARVIS. Uses ffplay if present, else winsound (wav) or the
    default Windows handler. Returns True if playback was started."""
    try:
        if ffplay_available():
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
            if volume is not None:
                cmd += ["-af", f"volume={volume}"]
            cmd.append(str(path))
            if wait:
                subprocess.run(cmd, check=True)
            else:
                subprocess.Popen(cmd)
            return True
        ext = Path(path).suffix.lower()
        if IS_WINDOWS and ext == ".wav":
            import winsound
            flags = winsound.SND_FILENAME | winsound.SND_NODEFAULT
            if not wait:
                flags |= winsound.SND_ASYNC
            winsound.PlaySound(str(path), flags)
            return True
        subprocess.Popen(["cmd", "/c", "start", "", str(path)])
        return True
    except Exception:
        return False


def play_audio_fast(path: Path, speed: float = 1.0) -> None:
    """Play an audio file, scaling its tempo to `speed` while keeping the
    original pitch. Falls back to plain playback if ffmpeg or the speed
    setting is unavailable."""
    if speed <= 0 or speed == 1.0:
        play_sound(str(path))
        return
    tmp = Path(tempfile.gettempdir()) / f"jarvis_fast_{os.getpid()}.wav"
    try:
        filter = f"atempo={speed:.3f}"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-af", filter, "-vn", str(tmp)],
            check=True, capture_output=True,
        )
        play_sound(str(tmp))
    except Exception:
        play_sound(str(path))
    finally:
        tmp.unlink(missing_ok=True)


def jarvis_say(text: str) -> None:
    """Speak 'text' as JARVIS — Pocket TTS (own voice) first, then Gemini
    (JARVIS_VOICE), falling back to the Windows SAPI voice."""
    out = Path(tempfile.gettempdir()) / "jarvis_line.mp3"
    wav = synth_pocket(text, out) or synth_charon(text, out)
    if wav is not None:
        play_audio_fast(wav, JARVIS_SPEED)
        return
    sapi_speak(text, JARVIS_SPEED)


def save_briefing_text(text: str) -> None:
    """Save the generated briefing text so it can be spoken on demand later."""
    BRIEFING_TEXT_FILE.write_text(text, encoding="utf-8")


def load_briefing_text() -> str | None:
    """Return the previously generated briefing text, or None if unavailable."""
    if not BRIEFING_TEXT_FILE.exists():
        return None
    return BRIEFING_TEXT_FILE.read_text(encoding="utf-8").strip() or None


_NUM_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    30: "thirty", 40: "forty", 50: "fifty",
}


def spoken_time() -> str:
    """Return the current time as spoken words, e.g. 'seven fifteen in the morning'."""
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
            minute_word = f"{_NUM_WORDS.get(tens * 10, str(tens * 10))} {_NUM_WORDS.get(ones, str(ones))}"
        clock = f"{hour_word} {minute_word}"
    period = "in the morning" if now.hour < 12 else ("in the afternoon" if now.hour < 18 else "in the evening")
    return f"{clock} {period}"


def current_temperature() -> str | None:
    """Return the current outside temperature in degrees, or None if unavailable."""
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
    """'Hi Gabriel. The time is ... The temperature is ...'"""
    parts = ["Hi Gabriel."]
    time_str = spoken_time()
    parts.append(f"The time is {time_str}.")
    temp = current_temperature()
    if temp:
        parts.append(f"The temperature is {temp}.")
    return " ".join(parts)


def jarvis_mp3(text: str, out_path: Path) -> Path:
    """Synthesize 'text' as JARVIS and save it to a wav next to out_path.
    Pocket TTS (own voice) first, then Gemini. Returns the wav path."""
    wav_path = synth_pocket(text, out_path) or synth_charon(text, out_path)
    if wav_path is None:
        raise RuntimeError(
            "TTS failed to synthesize. "
            f"Tried to save to {out_path.with_suffix('.wav')}."
        )
    return wav_path


def send_audio_to_telegram(path: Path, caption: str = "") -> None:
    """Send an audio file to a Telegram chat. Requires TELEGRAM_BOT_TOKEN and
    TELEGRAM_CHAT_ID in the environment (or .env)."""
    import requests

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "Missing Telegram credentials. Set TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID in .env"
        )

    url = f"https://api.telegram.org/bot{token}/sendAudio"
    with open(path, "rb") as f:
        resp = requests.post(
            url,
            files={"audio": f},
            data={"chat_id": chat_id, "caption": caption},
            timeout=60,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram send failed ({resp.status_code}): {resp.text}")
    print("Sent. Check your phone.")


def audio_duration_ms(path: Path) -> int:
    """Return the duration of an audio file in milliseconds via ffprobe."""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(float(proc.stdout.strip()) * 1000)


def build_briefing_audio(speech_path: Path, out_path: Path) -> Path:
    """Mix Startup -> (random music track under the briefing) -> Startup into
    out_path. The music is held at BRIEFING_THEME_VOLUME under the speech.
    Returns out_path, or speech_path unchanged if the music/startup files are
    missing."""
    startup = SCRIPT_DIR / "Startup.mp3"
    theme = random_track() if (SCRIPT_DIR / "Music").exists() else theme_path()
    if not (startup.exists() and theme.exists()):
        return speech_path

    startup_ms = audio_duration_ms(startup)
    speech_ms = audio_duration_ms(speech_path)
    theme_vol = os.environ.get("BRIEFING_THEME_VOLUME", "0.2")

    # theme input may be m4a; convert to wav for ffmpeg piping
    tmp_theme = Path(tempfile.gettempdir()) / "theme_briefing.wav"
    if theme.suffix.lower() == ".m4a":
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(theme), str(tmp_theme)],
            check=True, capture_output=True,
        )
    else:
        tmp_theme = theme

    cmd = [
        "ffmpeg", "-y",
        "-i", str(startup),
        "-i", str(tmp_theme),
        "-i", str(speech_path),
        "-filter_complex",
        (
            "[0:a]asplit=2[s1][s2];"
            f"[s1]adelay=0|0[st1];"
            f"[s2]adelay={startup_ms}|{startup_ms}[st2];"
            f"[1:a]volume={theme_vol},atrim=duration={speech_ms / 1000:.3f},"
            f"adelay={startup_ms}|{startup_ms}[music];"
            f"[2:a]adelay={startup_ms}|{startup_ms}[speech];"
            "[music][speech]amix=inputs=2:duration=longest:normalize=0[mix];"
            "[st1][mix][st2]concat=n=3:v=0:a=1[out]"
        ),
        "-map", "[out]",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, timeout=120)
    return out_path


def send_briefing_to_phone() -> None:
    """Generate today's briefing, synthesize it with the Gemini voice,
    mix in a random music track and startup sound, and send it to the phone."""
    data = load_tasks()
    track = random_track() if (SCRIPT_DIR / "Music").exists() else theme_path()
    print(f"Picked track: {track.name}")
    print("Generating briefing text with Ollama...")
    briefing_text = generate_briefing_text(data.get("tasks", []), data.get("notes", ""), today_schedule())
    print("Synthesizing with Gemini...")
    speech_path = jarvis_mp3(briefing_text, SCRIPT_DIR / "briefing_speech.mp3")
    print("Mixing startup, music, and briefing...")
    audio_path = build_briefing_audio(speech_path, SCRIPT_DIR / "briefing_send.mp3")
    print("Sending to Telegram...")
    send_audio_to_telegram(audio_path, caption="Morning briefing, sir.")
    speech_path.unlink(missing_ok=True)
    audio_path.unlink(missing_ok=True)
    print(briefing_text)


def tune_voice(ratios: list[float], sample_text: str) -> None:
    """Speak a sample with the configured Gemini voice (no ratio blending —
    JARVIS_VOICE in .env selects the voice, e.g. Charon, Kore, Puck)."""
    print(f"Voice: {JARVIS_VOICE} ({TTS_MODEL_3_1})")
    print("Speaking sample...")
    jarvis_say(sample_text)
    print("\nDone. Switch voices by editing JARVIS_VOICE in .env "
          "(options include Charon, Kore, Puck, Zephyr, Orus, Fenrir, Leda).")


def notify(title: str, message: str) -> None:
    if IS_WINDOWS:
        ps = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$n = New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon = [System.Drawing.SystemIcons]::Information;"
            "$n.Visible = $true;"
            f"$n.BalloonTipTitle = '{title.replace(chr(39), chr(39) * 2)}';"
            f"$n.BalloonTipText = '{message.replace(chr(39), chr(39) * 2)}';"
            "$n.ShowBalloonTip(5000);"
            "Start-Sleep -Seconds 6;"
            "$n.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False)
    else:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            check=False,
        )


def run_timer(minutes: int, label: str) -> None:
    total = minutes * 60
    for remaining in range(total, 0, -1):
        if remaining % 60 == 0:
            print(f"{label}: {remaining // 60} min remaining")
        time.sleep(1)


def chime() -> None:
    """Play a short system sound, safest available on the current OS."""
    if IS_WINDOWS:
        try:
            import winsound
            winsound.Beep(880, 180)
        except Exception:
            pass
    else:
        play_sound("/System/Library/Sounds/Glass.aiff")


def start_study_session(subject: str) -> None:
    subject_dir = Path.home() / "Notes" / subject
    subject_dir.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        os.startfile(str(subject_dir))
    else:
        subprocess.run(["open", str(subject_dir)], check=True)
    print(f"Opened {subject_dir}. Starting study session.")

    jarvis_say(f"Study session initialized. I have opened the {subject} notes for you. Good luck, sir.")
    cycle = 1
    try:
        while True:
            print(f"\n--- Cycle {cycle}: FOCUS 25 min ---")
            run_timer(25, "Focus")
            notify("Focus complete", f"Cycle {cycle} done. 5-minute break.")
            chime()
            jarvis_say("Twenty-five minutes have elapsed. You may take your five-minute reprieve.")

            print(f"--- Cycle {cycle}: BREAK 5 min ---")
            run_timer(5, "Break")
            notify("Break over", "Back to focus.")
            chime()
            jarvis_say("Your break has concluded. Shall we return to the work?")
            cycle += 1
    except KeyboardInterrupt:
        print("\nStudy session stopped.")


def show(text: str) -> None:
    print(text)
    if SPEAK:
        jarvis_say(text)


def generate_briefing_text(tasks: list[str], notes: str, schedule: list[str] | None = None) -> str:
    """Ask Ollama to turn the raw task list into a short spoken briefing."""
    task_lines = "\n".join(f"- {t}" for t in tasks) if tasks else "No tasks listed for today."
    schedule_lines = "\n".join(f"- {e}" for e in schedule) if schedule else "none"
    schedule_line = "Highlight the most time-sensitive of these briefly, alongside the tasks." if schedule else ""
    prompt = (
        "You are JARVIS, Tony Stark's highly capable personal AI assistant. "
"Speak in polished, natural British English with a calm, refined and understated manner. "
"You are exceptionally intelligent, observant and composed, with complete confidence in your abilities. "
"Be helpful and proactive without being intrusive. Address the user as \"sir\" naturally, but never excessively. "
"Your humour is subtle, dry and occasionally sardonic - never exaggerated or theatrical. "
"Speak as though you are a trusted assistant who already understands the user's routines and priorities. "
"Deliver a concise spoken morning briefing, under 100 words. Begin with a brief, courteous greeting. "
"State the number of tasks for today, then summarise each task naturally, prioritising anything urgent or time-sensitive. "
"Mention today's schedule in one or two concise clauses, including any notable conflicts or important events. "
"Conclude with a brief, understated remark in JARVIS's characteristic dry wit. "
"Never sound robotic, overly enthusiastic, verbose, or like a generic virtual assistant. "
"Do not use markdown, bullet points, or headers - the response will be spoken aloud exactly as written.\n\n"
f"Tasks:\n{task_lines}\n\n"
f"Today's schedule:\n{schedule_lines}\n"
f"Notes: {notes or 'none'}"

    )

    return ollama_chat(prompt, temperature=0.7, max_tokens=200)


def generate_answer(question: str) -> str:
    """Answer an open-ended question in plain, spoken-style prose."""
    prompt = (
        "You are J.A.R.V.I.S., a helpful everyday AI assistant. "
        "Answer plainly and conversationally, as if speaking aloud. "
        "Keep prose natural English and be friendly. "
        "Never ask the user follow-up questions - give a complete, direct answer "
        "using what you have, or state plainly if you need more information. "
        "Do not use markdown, bullet points, or headers - the reply will be read aloud.\n\n"
        f"User: {question}"
    )

    return ollama_chat(prompt, temperature=0.5, max_tokens=300)


def synthesize_speech(text: str) -> Path:
    """Call ElevenLabs TTS and save the resulting audio to a temp file."""
    import requests

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()

    out_path = Path(tempfile.gettempdir()) / "morning_briefing.mp3"
    out_path.write_bytes(resp.content)
    return out_path


def play_audio(path: Path):
    play_sound(str(path))


_theme_proc: subprocess.Popen | None = None


def theme_path() -> Path:
    for name in ("Briefing theme.mp3", "Briefing theme.m4a"):
        p = SCRIPT_DIR / name
        if p.exists():
            return p
    return SCRIPT_DIR / "Briefing theme.mp3"


def random_track() -> Path:
    """Pick a random music track from the Music/ folder, avoiding the track
    used last time (recorded in .last_track). Falls back to theme_path() if
    no tracks are found."""
    music_dir = SCRIPT_DIR / "Music"
    exts = {".mp3", ".m4a", ".wav", ".aiff", ".aif"}
    tracks = [
        p for p in music_dir.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    ]
    if not tracks:
        return theme_path()

    last_file = SCRIPT_DIR / ".last_track"
    last = last_file.read_text().strip() if last_file.exists() else ""
    candidates = [t for t in tracks if t.name != last] or tracks
    chosen = random.choice(candidates)
    last_file.write_text(chosen.name + "\n")
    return chosen


def play_theme() -> None:
    global _theme_proc
    theme = theme_path()
    if not theme.exists():
        return
    volume = os.environ.get("BRIEFING_THEME_VOLUME", "0.2")
    try:
        cmd = ["ffplay", "-nodisp", "-loglevel", "quiet", "-af", f"volume={volume}"]
        if IS_WINDOWS:
            cmd += ["-loop", "0"]
        cmd.append(str(theme))
        _theme_proc = subprocess.Popen(cmd)
    except Exception:
        _theme_proc = None


def stop_theme() -> None:
    global _theme_proc
    if _theme_proc is not None:
        _theme_proc.terminate()
        _theme_proc = None


def play_loading_sequence() -> None:
    """Play Startup -> theme music -> intro voice -> Startup again, timed so the
    morning briefing is ready to start right after. Leaves the theme playing."""
    startup = SCRIPT_DIR / "Startup.mp3"
    intro = next(
        (p for p in (SCRIPT_DIR / "intro.wav", SCRIPT_DIR / "intro.mp3") if p.exists()),
        None,
    )
    theme = theme_path()
    volume = os.environ.get("BRIEFING_THEME_VOLUME", "0.2")

    # 1. Startup plays
    if startup.exists():
        play_sound(str(startup))
    # 2. Music starts right after startup ends
    if theme.exists():
        play_theme()
    # 3. Intro voice starts 0.5s after music starts
    time.sleep(0.5)
    if intro is not None:
        play_sound(str(intro))
    # 4. Startup plays again 0.5s after the intro ends
    time.sleep(0.5)
    if startup.exists():
        play_sound(str(startup))


def generate_with_loading(tasks: list[str], notes: str, schedule: list[str] | None) -> str:
    """Generate the briefing text in a background thread while the loading
    sequence plays. Returns the text, with the theme left playing."""
    result: dict[str, str] = {}

    def _gen() -> None:
        result["text"] = generate_briefing_text(tasks, notes, schedule)

    thread = threading.Thread(target=_gen, daemon=True)
    thread.start()
    play_loading_sequence()
    thread.join()
    return result["text"]


def main():
    global SPEAK
    args = sys.argv[1:]
    text_only = "--text-only" in args
    SPEAK = "--speak" in args

    if args and args[0] == "add":
        task = " ".join(args[1:]).strip()
        if not task:
            sys.exit("Missing task. Usage: morning_briefing.py add \"Task name\"")
        add_task(task)
        show(f"Added: {task}")
        return

    if args and args[0] == "list":
        tasks = load_tasks().get("tasks", [])
        lines = "\n".join(f"{i}. {t}" for i, t in enumerate(tasks, 1))
        show(lines or "No tasks.")
        return

    if args and args[0] == "done":
        try:
            number = int(args[1])
        except (IndexError, ValueError):
            sys.exit("Missing task number. Usage: morning_briefing.py done 5")
        remove_task(number)
        return

    if args and args[0] == "open":
        open_tasks_file()
        show(f"Opened {active_tasks_file()}")
        return

    if args and args[0] == "ask":
        question = " ".join(args[1:]).strip()
        if not question:
            sys.exit("Missing question. Usage: morning_briefing.py ask \"your question?\"")
        show(generate_answer(question))
        return

    if args and args[0] == "study":
        subject = " ".join(args[1:]).strip()
        if not subject:
            sys.exit("Missing subject. Usage: morning_briefing.py study \"history\"")
        start_study_session(subject)
        return

    if args and args[0] == "routine":
        no_speak = "--no-speak" in args
        data = load_tasks()
        print("Generating briefing text with Ollama...")
        briefing_text = generate_with_loading(data.get("tasks", []), data.get("notes", ""), today_schedule())
        print(f"\nBriefing:\n{briefing_text}\n")
        opener = opener_line()
        if no_speak:
            save_briefing_text(f"{opener}. {briefing_text}" if opener else briefing_text)
            print("Briefing ready — click JARVIS to hear it.")
            return
        jarvis_say(f"{opener}. {briefing_text}" if opener else briefing_text)
        stop_theme()
        return

    if args and args[0] == "speak-briefing":
        briefing_text = load_briefing_text()
        if briefing_text:
            jarvis_say(briefing_text)
        return

    if args and args[0] == "scan":
        image = " ".join(args[1:]).strip()
        if not image:
            sys.exit("Missing image path. Usage: morning_briefing.py scan /path/to/image.jpg")
        show(ocr_image(image))
        return

    if args and args[0] == "schedule":
        image = " ".join(args[1:]).strip()
        if not image:
            sys.exit("Missing image path. Usage: morning_briefing.py schedule /path/to/image.jpg")
        raw = ocr_image(image)
        payload = parse_schedule_to_file(raw, week_monday())
        count = sum(len(items) for items in payload["days"].values())
        show(f"Schedule updated for the week of {payload['week_of']}. {count} entries for you.")
        return

    if args and args[0] == "tune":
        rest = args[1:]
        sample_text = "At your service, sir."
        ratios = [round(i * 0.1, 1) for i in range(11)]
        if rest and rest[0] in ("text", "-t") and len(rest) > 1:
            sample_text = " ".join(rest[2:]) or sample_text
        tune_voice(ratios, sample_text)
        return

    if args and args[0] == "say":
        text = " ".join(args[1:]).strip()
        if not text:
            sys.exit("Missing text. Usage: morning_briefing.py say \"Good morning, sir.\"")
        jarvis_say(text)
        return

    if args and args[0] == "mp3":
        rest = args[1:]
        out_path = SCRIPT_DIR / "intro.mp3"
        if rest and rest[0] == "-o":
            out_path = SCRIPT_DIR / rest[1]
            rest = rest[2:]
        text = " ".join(rest).strip()
        if not text:
            sys.exit("Missing text. Usage: morning_briefing.py mp3 [ -o intro.mp3 ] \"Good morning, sir.\"")
        saved = jarvis_mp3(text, out_path)
        print(f"Saved to {saved}")
        return

    if args and args[0] == "send":
        send_briefing_to_phone()
        return

    data = load_tasks()
    tasks = data.get("tasks", [])
    notes = data.get("notes", "")

    print("Generating briefing text with Ollama...")

    if text_only:
        briefing_text = generate_briefing_text(tasks, notes, today_schedule())
        print(briefing_text)
        return

    briefing_text = generate_with_loading(tasks, notes, today_schedule())
    print(f"\nBriefing:\n{briefing_text}\n")

    if SPEAK:
        jarvis_say(briefing_text)
        stop_theme()
        return

    if not ELEVENLABS_API_KEY:
        stop_theme()
        sys.exit("Missing ELEVENLABS_API_KEY. Set it as an environment variable or in a .env file.")
    if not os.environ.get("ENABLE_TTS"):
        stop_theme()
        print("TTS disabled - skipping speech synthesis. Set ENABLE_TTS=1 to enable.")
        return

    print("Synthesizing speech with ElevenLabs...")
    audio_path = synthesize_speech(briefing_text)

    print("Playing...")
    play_audio(audio_path)
    stop_theme()


if __name__ == "__main__":
    main()
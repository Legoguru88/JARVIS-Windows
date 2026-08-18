import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import urllib.parse
import urllib.request

IS_WINDOWS = os.name == "nt"

OPENTTS_URL = os.environ.get("OPENTTS_URL", "http://localhost:5500")
OPENTTS_VOICE = os.environ.get("OPENTTS_VOICE", "en_US-amy-medium")
VOLUME = os.environ.get("JARVIS_VOLUME", "1.0")


def ffplay_available() -> bool:
    return shutil.which("ffplay") is not None


def synth_opentts(text: str) -> Path | None:
    url = f"{OPENTTS_URL}/api/tts"
    params = urllib.parse.urlencode({"text": text, "voice": OPENTTS_VOICE})
    request = urllib.request.Request(
        f"{url}?{params}", headers={"Accept": "audio/wav"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()
            content_type = response.headers.get("Content-Type", "")
    except Exception as error:
        print(f"speak: OpenTTS {OPENTTS_URL} failed: {error}", flush=True)
        return None

    ext = "wav" if "wav" in content_type else "mp3"
    out = Path(tempfile.gettempdir()) / f"jarvis_speech.{ext}"
    out.write_bytes(data)
    return out


def play_audio(path: Path) -> None:
    speed = float(os.environ.get("JARVIS_SPEED", "1.0").strip() or 1.0)
    if speed != 1.0:
        afilter = f"atempo={speed:.3f},volume={VOLUME}"
    else:
        afilter = f"volume={VOLUME}"
    subprocess.run(
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-af", afilter, str(path)],
        check=False,
    )


def sapi_speak(text: str) -> bool:
    """Speak with the built-in Windows SAPI voice via PowerShell."""
    if not IS_WINDOWS:
        return False
    rate = -1
    safe = text.replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Rate = {rate}; "
        f"$s.Speak('{safe}');"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            check=False,
            timeout=180,
        )
        return True
    except Exception as error:
        print(f"speak: PowerShell SAPI failed: {error}", flush=True)
        return False


def jarvis_say(text: str) -> None:
    audio = synth_opentts(text)
    if audio is not None and ffplay_available():
        play_audio(audio)
        return
    if audio is not None:
        os.startfile(str(audio))
        return
    sapi_speak(text)


def play_tone() -> None:
    if IS_WINDOWS:
        try:
            import winsound
            winsound.Beep(920, 140)
            return
        except Exception:
            pass
    subprocess.run(
        [
            "ffplay",
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=920:duration=0.14",
            "-af",
            "volume=0.7",
        ],
        check=False,
    )


def notify(title: str, message: str) -> None:
    if not IS_WINDOWS:
        subprocess.run(
            ["notify-send", "--app-name=JARVIS", title, message], check=False
        )
        return
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
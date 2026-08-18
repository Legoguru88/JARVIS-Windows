import os
import subprocess
import sys
import tempfile
from pathlib import Path

from speak import jarvis_say, notify, play_tone
from wake import listen

SCRIPT_DIR = Path(__file__).resolve().parent
ENGINE_DIR = SCRIPT_DIR.parent / "engine"
PYTHON = ENGINE_DIR / ".venv" / "Scripts" / "python.exe"
ROUTINE = ENGINE_DIR / "morning_briefing.py"
BRIEFING_FILE = Path(tempfile.gettempdir()) / "jarvis_briefing.txt"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def run_briefing() -> str | None:
    result = subprocess.run(
        [str(PYTHON), str(ROUTINE), "routine", "--no-speak"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(result.stderr.strip(), flush=True)
    if BRIEFING_FILE.exists():
        content = BRIEFING_FILE.read_text(encoding="utf-8").strip()
        if content:
            return content
    for line in result.stdout.splitlines():
        if line.lstrip().startswith("Briefing:"):
            briefing = line.split(":", 1)[1].strip()
            if briefing:
                return briefing
    return None


class Assistant:
    def __init__(self) -> None:
        self.busy = False

    def on_wake(self, clip) -> None:
        if self.busy:
            return
        if os.environ.get("CONFIRM_WAKEUP", "1").strip() != "0":
            from confirm import confirm_wakeup

            phrase = os.environ.get("WAKEUP_PHRASE", "wake up").strip() or "wake up"
            if not confirm_wakeup(clip, phrase):
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
            briefing = run_briefing()
            if briefing:
                jarvis_say(briefing)
            else:
                jarvis_say("I could not prepare the briefing, sir.")
        finally:
            self.busy = False


def main() -> None:
    load_dotenv(ENGINE_DIR / ".env")
    assistant = Assistant()
    if "--once" in sys.argv:
        assistant.trigger()
        return
    threshold = float(os.environ.get("WAKE_THRESHOLD", "0.35").strip() or 0.35)
    window = float(os.environ.get("WAKEUP_WINDOW", "3.0").strip() or 3.0)
    listen(threshold, window, assistant.on_wake)


if __name__ == "__main__":
    main()
# JARVIS-Windows

Windows version of the JARVIS voice assistant. Same flow as the Ubuntu one —
"hey jarvis" -> "wake up" -> briefing -> spoken out loud — with Windows-native
replacements for the Linux tooling.

**Two ways to run it:**

1. **Self-contained single .exe** (`standalone/`) — one file
   containing everything: wake word, whisper, a bundled Qwen model, and
   speech. Requires only Python + an Nvidia GPU to build, and nothing at all
   on the machine that runs it. **Recommended.**
2. **Python install** (`setup.ps1`) — the classic venv install, needs Ollama
   installed separately.

| Ubuntu / macOS            | Windows                                  |
| ------------------------- | ---------------------------------------- |
| systemd (`setup.sh`)      | Task Scheduler (`setup.ps1 -AutoStart`)  |
| `.venv/bin/python3`       | `.venv\Scripts\python.exe`               |
| OpenTTS + `ffplay` / `espeak` | Windows **SAPI** fallback (built-in) + `ffplay` |
| `notify-send` / `osascript` | PowerShell `NotifyIcon` balloon toast   |
| `open` command            | `os.startfile`                           |
| Swift Vision OCR          | tesseract / pytesseract                  |
| `afconvert` / `say`       | `ffmpeg` / SAPI                          |

```
windows/
├── assistant/     wake-word, confirmation, TTS + playback (Windows)
├── engine/        briefing engine (morning_briefing.py, tasks, .env)
├── setup.ps1      installer (creates venv, optional Task Scheduler entry)
├── run-jarvis.bat launcher
└── README.md
```

## Prerequisites

- **Windows 10/11** with working mic + speakers
- **Python 3.10+** from python.org (tick "Add python.exe to PATH" and the py
  launcher during install)
- **Ollama** for Windows (`winget install ollama.ollama`), then pull a model:
  ```powershell
  ollama pull llama3.2:3b
  ```
- **(Optional but recommended)** FFmpeg for polished speed/volume playback:
  ```powershell
  winget install Gyan.FFmpeg
  ```
  Without ffmpeg, JARVIS still works — openwakeword/sounddevice/faster-whisper
  are pip packages, and speech falls back to the built-in SAPI voice.

## Install

```powershell
cd <this repo>
powershell -ExecutionPolicy Bypass -File setup.ps1        # just install
powershell -ExecutionPolicy Bypass -File setup.ps1 -AutoStart  # + start at logon
notepad engine\.env        # tweak OLLAMA_MODEL, GEMINI_API_KEY, etc.
```

`setup.ps1` creates `engine\.venv`, installs `engine/requirements.txt` +
`assistant/requirements.txt`, copies `.env.example` -> `.env` on first run, and
optionally registers a **Task Scheduler** task (`jarvis-wake`) that starts at
logon (Windows' equivalent of the systemd service). Whisper `tiny.en` (~40 MB)
downloads itself on the first "wake up".

## Run

```powershell
run-jarvis.bat                # foreground listener with live logs
run-jarvis.bat --once         # one briefing without saying anything
```

Say **"hey jarvis"** then **"wake up"** — you should hear today's briefing.

## Speech backends (in order of preference)

JARVIS speaks using the first working option:

1. **Pocket TTS** (`JARVIS_POCKET_VOICE` + `JARVIS_POCKET_URL`) — your own
   cloned voice hosted on a local server. Optional.
2. **Gemini TTS** (`GEMINI_API_KEY`, `JARVIS_VOICE` e.g. Charon) — high quality.
   Optional; needs `pip install google-genai`
   (`pip install -r requirements-optional.txt`).
3. **Windows SAPI** — the built-in fallback. No setup, always works.
   (If you'd rather use an OpenTTS server, set `OPENTTS_URL`/`OPENTTS_VOICE`
   in `.env` and `speak.py` will use it in place of SAPI.)

## Configuration (`engine\.env`)

| Variable            | Default                  | Purpose                             |
| ------------------- | ------------------------ | ----------------------------------- |
| `OLLAMA_MODEL`      | `llama3.2:3b`            | Briefing generation model           |
| `WAKE_THRESHOLD`    | `0.35`                   | Wake detection sensitivity          |
| `CONFIRM_WAKEUP`    | `1`                      | Set `0` to skip the confirm         |
| `WAKEUP_PHRASE`     | `wake up`                | Phrase needed to trigger            |
| `STT_MODEL`         | `tiny.en`                | Whisper size for confirmation       |
| `WAKEUP_WINDOW`     | `3.0`                    | Seconds of audio to capture         |
| `JARVIS_SPEED`      | `1.2`                    | Playback speed (pitch-preserved)    |
| `JARVIS_VOLUME`     | `1.0`                    | Playback volume                      |
| `GEMINI_API_KEY`    | *(unset)*                | High-quality Gemini TTS voice       |
| `OPENTTS_URL`       | *(unset)*                | Optional OpenTTS server             |

## Notes

- The `engine/tasks.txt` / `tasks.json` here are a working copy so the Windows
  briefing data is independent of the Ubuntu one (like the macOS copy).
- `morning_briefing.py` also runs standalone: `list`, `add`, `done`, `ask`,
  `study`, `say`, `mp3`, `send`, `scan`, `schedule` — all ported to Windows.
- The `scan`/`schedule` OCR commands need tesseract: install
  [UB-Mannheim tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and
  set `TESSERACT_CMD`, or just `pip install pytesseract pillow` if `tesseract`
  is already on PATH.

## Troubleshooting

| Symptom                          | Fix                                                            |
| -------------------------------- | -------------------------------------------------------------- |
| "hey jarvis" never triggers      | Check mic in Windows Settings -> System -> Sound; raise `WAKE_THRESHOLD` |
| Heard "hey jarvis", no response  | Check `WAKEUP_PHRASE=wake up`; whisper needs internet on first run |
| No voice                         | No GEMINI_API_KEY -> SAPI should still speak; if silent, test `powershell -c "(New-Object -ComObject SAPI.SpVoice).Speak('test')"` |
| Briefing slow / nothing          | Confirm the model exists: `ollama list`; `ollama pull llama3.2:3b` |
| Task won't auto-start            | `taskschd.msc` -> Task Scheduler Library -> `jarvis-wake` logon trigger |
| Volume too loud/quiet            | Tune `JARVIS_VOLUME` in `.env`                                  |

---

# Option 1 — Self-contained JARVIS folder

Build once on any Windows PC with Python + an Nvidia GPU (the RTX 5080
bundles in CUDA 12.8 support), then run that folder on any machine — no
Python, no Ollama, no ffmpeg, no internet, no installs.

```
standalone/
├── app.py        the whole assistant in one file
├── build.ps1     one-command build -> dist\JARVIS\ (folder)
└── tasks.txt     bundled briefing tasks
```

## Build (on the PC that will run it)

```powershell
cd standalone
powershell -ExecutionPolicy Bypass -File build.ps1         # GPU build (RTX 5080)
# or, for a machine without an Nvidia GPU:
powershell -ExecutionPolicy Bypass -File build.ps1 -Cpu
```

This is a big download once (~5 GB of model files) and takes a few minutes;
it produces **`dist\JARVIS\`** (~5.5-6 GB), a self-contained folder:

- **Wake word** — openwakeword embedded "hey jarvis" model
- **Confirmation STT** — faster-whisper `tiny.en`, bundled
- **Briefing brain** — Qwen2.5-7B Q4_K_M (GGUF, ~4.7 GB), bundled, run via
  llama-cpp-python (GPU offload when a CUDA build is available). Built with
  PyInstaller `--onedir`, which has no 4 GB archive limit, so the bigger 7B
  model fits. For a small/portable build, override the model with
  `-Model bartowski/Qwen2.5-3B-Instruct-GGUF -ModelFile Qwen2.5-3B-Instruct-Q4_K_M.gguf`.
- **Speech** — Windows SAPI, already part of the OS

That folder embeds the LLM, the STT model, the wake word model, and all
Python code. **Nothing else is placed on the PC.**

## Run

```powershell
dist\JARVIS\JARVIS.exe                # always-on listener
dist\JARVIS\JARVIS.exe --once         # one briefing immediately, for testing
```

First launch loads the model into RAM/VRAM (10-60 s), then it's always warm.
Say **"hey jarvis"** then **"wake up"**.

## Tuning without rebuilding

Put a file next to the exe to override packaged defaults:

- `tasks.txt` next to the exe — replaces the bundled tasks list
- `.env` next to the exe — settings (see `standalone/.env.example`):
  `WAKE_THRESHOLD`, `CONFIRM_WAKEUP`, `WAKEUP_PHRASE`, `WAKEUP_WINDOW`,
  `JARVIS_SPEED`, `OLLAMA_QUALITY`

## Portability

Copy the whole `dist\JARVIS\` folder wherever you like — it runs in place
from the folder, boots fast, and leaves nothing behind (unlike a onefile
exe, there's no temp-cache extraction on launch). Swap hardware freely:
would run on any Windows machine with enough RAM/VRAM, and the `-Cpu` flag
rebuilds a no-GPU variant.
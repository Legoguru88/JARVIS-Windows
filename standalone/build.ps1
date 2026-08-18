# JARVIS.exe build script -- produces a single self-contained executable.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1            # CUDA (RTX 5080)
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Cpu       # any GPU / CPU
#
# The output JARVIS.exe (~5-6 GB, model included) lives in dist\ and needs
# nothing else installed to run. Say "hey jarvis" then "wake up".

param(
    [switch]$Cpu,                # build the CPU version (no CUDA / Nvidia GPU needed)
    [string]$Model = "Qwen/Qwen2.5-7B-Instruct-GGUF",
    [string]$ModelFile = "qwen2.5-7b-instruct-q4_k_m.gguf"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Python = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Python) { throw "Python 3 not found. Install from python.org." }

if (-not (Test-Path .build\.venv)) {
    Write-Host "==> Creating build venv"
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .build\.venv } else { python -m venv .build\.venv }
    & .build\.venv\Scripts\python.exe -m pip install --upgrade pip
}

$py = ".build\.venv\Scripts\python.exe"

Write-Host "==> Installing Python build/runtime dependencies"
& $py -m pip install pyinstaller huggingface_hub
& $py -m pip install openwakeword sounddevice numpy faster-whisper

if ($Cpu) {
    Write-Host "==> Installing llama-cpp-python (CPU)"
    & $py -m pip install llama-cpp-python
} else {
    Write-Host "==> Installing llama-cpp-python (CUDA 12.8, Blackwell sm_120)"
    & $py -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu128
}

# ------------------------------------------------------------ bundle the models

$WarningPreference = "SilentlyContinue"
if (-not (Test-Path models\whisper\tiny.en\model.bin)) {
    Write-Host "==> Downloading whisper tiny.en (~75 MB)"
    & $py -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-tiny.en', local_dir='models/whisper/tiny.en')"
}
if (-not (Test-Path models\qwen\model.gguf)) {
    Write-Host "==> Downloading $ModelFile (~4.7 GB)"
    & $py -c "from huggingface_hub import hf_hub_download; hf_hub_download('$Model', '$ModelFile', local_dir='models/qwen')"
    if (-not (Test-Path models\qwen\model.gguf)) {
        Get-ChildItem models\qwen -Filter *.gguf | ForEach-Object { if ($_.Name -ne 'model.gguf') { Copy-Item $_.FullName 'models\qwen\model.gguf' } }
    }
}

# ------------------------------------------------------------ bundle tasks

# ------------------------------------------------------------ PyInstaller

Write-Host "==> Building JARVIS.exe (one file, self-contained)"
& $py -m PyInstaller `
    --noconfirm `
    --onefile `
    --name JARVIS `
    --add-data "models;models" `
    --add-data "tasks.txt;." `
    --collect-all openwakeword `
    --collect-all onnxruntime `
    --collect-all sounddevice `
    --collect-all faster_whisper `
    --collect-all llama_cpp `
    --distpath dist `
    --workpath .build\work `
    --specpath .build `
    app.py

if (-not (Test-Path dist\JARVIS.exe)) { throw "Build failed: dist\JARVIS.exe not produced." }
$size = [math]::Round((Get-Item dist\JARVIS.exe).Length / 1GB, 2)
Write-Host
Write-Host "SUCCESS: dist\JARVIS.exe ($size GB) -- copy it anywhere, it's the whole JARVIS."
Write-Host "  - Put a tasks.txt beside it to change the briefing, or a .env to tweak settings."
Write-Host "  - First run takes ~10-30s while the model loads into VRAM."
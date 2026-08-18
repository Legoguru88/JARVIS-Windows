# JARVIS.exe build script -- produces a single self-contained executable.
#
#   powershell -ExecutionPolicy Bypass -File build.ps1            # GPU (RTX)
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Cpu       # CPU only
#
# Default model is Qwen2.5-3B Q4_K_M (~1.9 GB) because PyInstaller onefile
# has a hard 4 GB per-file limit and CPU builds run better on a smaller
# model. Builds to dist\JARVIS.exe (~2-3 GB) needing nothing else installed.

param(
    [switch]$Cpu,                # build the CPU version (no Nvidia GPU needed)
    [string]$Model = "bartowski/Qwen2.5-3B-Instruct-GGUF",
    [string]$ModelFile = "Qwen2.5-3B-Instruct-Q4_K_M.gguf"
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
    Write-Host "==> Installing llama-cpp-python (CUDA, Blackwell sm_120)"
    # Prebuilt CUDA wheels exist for cu121/cu122/cu123/cu124 on Python 3.10-3.12.
    # cu128 is not published, so try cu124 (works with CUDA 12.8+ drivers), then
    # fall back to a CPU build so the build never dies on platform quirks.
    $cudaOk = $false
    @("https://abetlen.github.io/llama-cpp-python/whl/cu124",
      "https://abetlen.github.io/llama-cpp-python/whl/cu121") | ForEach-Object {
        if (-not $cudaOk) {
            Write-Host "   trying $_"
            & $py -m pip install llama-cpp-python --extra-index-url "$_" 2>$null
            if ($LASTEXITCODE -eq 0) { $cudaOk = $true }
        }
    }
    if (-not $cudaOk) {
        Write-Host "WARN: CUDA wheel unavailable for this Python - falling back to CPU llama-cpp."
        & $py -m pip install llama-cpp-python
        if ($LASTEXITCODE -ne 0) { throw "llama-cpp-python install failed" }
    }
}

# ------------------------------------------------------------ bundle the models

$WarningPreference = "SilentlyContinue"
function Invoke-HF {
    param([string]$Script)
    # Try the official endpoint, then fall back to a mirror for networks that
    # block huggingface.co.
    $env:HF_ENDPOINT = "https://huggingface.co"
    & $py -c $Script
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   primary endpoint failed, retrying via hf-mirror.com"
        $env:HF_ENDPOINT = "https://hf-mirror.com"
        & $py -c $Script
    }
}
function Get-Whisper {
    $need = "config.json", "model.bin", "tokenizer.json"
    $ok = $true
    foreach ($f in $need) { if (-not (Test-Path "models\whisper\tiny.en\$f")) { $ok = $false } }
    if ($ok) { return }
    Write-Host "==> Downloading whisper tiny.en (~75 MB)"
    Remove-Item models\whisper -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-HF "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-tiny.en', local_dir=r'models/whisper/tiny.en', max_workers=1)"
    if (-not (Test-Path models\whisper\tiny.en\model.bin)) {
        throw "Whisper download failed - check your internet connection and try again."
    }
}
function Get-Qwen {
    if (Test-Path models\qwen\model.gguf) { return }
    Write-Host "==> Downloading $ModelFile (~1.9 GB)"
    Remove-Item models\qwen -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-HF "from huggingface_hub import hf_hub_download; hf_hub_download('$Model', '$ModelFile', local_dir=r'models/qwen')"
    if (-not (Test-Path models\qwen\model.gguf)) {
        Get-ChildItem models\qwen -Filter *.gguf -ErrorAction SilentlyContinue |
            ForEach-Object { if ($_.Name -ne 'model.gguf') { Copy-Item $_.FullName 'models\qwen\model.gguf' } }
    }
    if (-not (Test-Path models\qwen\model.gguf)) {
        throw "Model download failed - check your internet connection and try again."
    }
}
Get-Whisper
Get-Qwen

# ------------------------------------------------------------ bundle tasks

# ------------------------------------------------------------ PyInstaller

Write-Host "==> Building JARVIS.exe (one file, self-contained)"
$ModelsAbs = Join-Path $Root "models"
$TasksAbs = Join-Path $Root "tasks.txt"
& $py -m PyInstaller `
    --noconfirm `
    --onefile `
    --name JARVIS `
    --add-data "$ModelsAbs;models" `
    --add-data "$TasksAbs;." `
    --collect-all openwakeword `
    --collect-all onnxruntime `
    --collect-all _sounddevice `
    --collect-all _sounddevice_data `
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
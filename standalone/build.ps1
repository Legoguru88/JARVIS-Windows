# JARVIS build script -- produces a self-contained folder (exe + _internal).
#
#   powershell -ExecutionPolicy Bypass -File build.ps1            # GPU (RTX)
#   powershell -ExecutionPolicy Bypass -File build.ps1 -Cpu       # CPU only
#
# Uses PyInstaller --onedir because onefile has a hard 4 GB archive limit;
# onedir ships files loose in _internal, so the bigger 7B model fits. Builds
# to dist\JARVIS\ (JARVIS.exe + _internal\) needing nothing else installed.
# For a smaller build, pass -Model/-ModelFile (e.g. the 3B Q4_K_M).

param(
    [switch]$Cpu,                # build the CPU version (no Nvidia GPU needed)
    [string]$Model = "bartowski/Qwen2.5-7B-Instruct-GGUF",
    [string]$ModelFile = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
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
    # model.gguf must match the model requested; a stale file from an earlier
    # build (or a different quantization) must not be reused silently.
    $stamp = Join-Path "models\qwen" "MODEL_TAG.txt"
    $want = "$Model`n$ModelFile"
    if ((Test-Path models\qwen\model.gguf) -and (Test-Path $stamp) -and
        ((Get-Content $stamp -Raw) -eq $want)) { return }
    Write-Host "==> Downloading $ModelFile"
    Remove-Item models\qwen -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-HF "from huggingface_hub import hf_hub_download; hf_hub_download('$Model', '$ModelFile', local_dir=r'models/qwen')"
    if (-not (Test-Path models\qwen\model.gguf)) {
        Get-ChildItem models\qwen -Filter *.gguf -ErrorAction SilentlyContinue |
            ForEach-Object { if ($_.Name -ne 'model.gguf') { Copy-Item $_.FullName 'models\qwen\model.gguf' } }
    }
    if (-not (Test-Path models\qwen\model.gguf)) {
        throw "Model download failed - check your internet connection and try again."
    }
    Set-Content -Path $stamp -Value $want
}
Get-Whisper
Get-Qwen

# ------------------------------------------------------------ bundle tasks

# ------------------------------------------------------------ PyInstaller

Write-Host "==> Building JARVIS (folder, self-contained)"
$ModelsAbs = Join-Path $Root "models"
$TasksAbs = Join-Path $Root "tasks.txt"
& $py -m PyInstaller `
    --noconfirm `
    --onedir `
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

if (-not (Test-Path dist\JARVIS\JARVIS.exe)) { throw "Build failed: dist\JARVIS\JARVIS.exe not produced." }
$folder = [math]::Round((Get-ChildItem dist\JARVIS -Recurse -File | Measure-Object Length -Sum).Sum / 1GB, 2)
$exe = [math]::Round((Get-Item dist\JARVIS\JARVIS.exe).Length / 1MB, 0)
Write-Host
Write-Host "SUCCESS: dist\JARVIS\ ($folder GB total) -- copy the whole folder anywhere, it's the whole JARVIS."
Write-Host "  - Run it as dist\JARVIS\JARVIS.exe (launcher is ${exe} MB; the rest lives in _internal\)."
Write-Host "  - Put a tasks.txt next to the exe to change the briefing, or a .env to tweak settings."
Write-Host "  - First run takes 10-60s while the model loads into RAM/VRAM."
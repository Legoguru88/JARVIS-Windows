# JARVIS-Windows installer
# Run:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Add -AutoStart to register a Task Scheduler entry that launches JARVIS at logon.

param(
    [switch]$AutoStart
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

$Python = Get-Command py, python -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $Python) {
    throw "Python 3 not found. Install it from python.org (tick 'Add python.exe to PATH' and the py launcher)."
}

if (-not (Test-Path engine\.venv)) {
    Write-Host "==> Creating engine\.venv"
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv engine\.venv
    } else {
        python -m venv engine\.venv
    }
    & engine\.venv\Scripts\python.exe -m pip install --upgrade pip
    Write-Host "==> Installing dependencies"
    & engine\.venv\Scripts\python.exe -m pip install -r engine\requirements.txt
    & engine\.venv\Scripts\python.exe -m pip install -r assistant\requirements.txt
}

if (-not (Test-Path engine\.env)) {
    Write-Host "==> engine\.env missing - creating from example"
    Copy-Item engine\.env.example engine\.env
    Write-Host "    Edit engine\.env to set your keys, then run setup again."
}

if ($AutoStart) {
    $TaskName = "jarvis-wake"
    $PythonExe = Join-Path $ProjectRoot "engine\.venv\Scripts\python.exe"
    $JarvisPy = Join-Path $ProjectRoot "assistant\jarvis.py"
    $WorkingDir = Join-Path $ProjectRoot "assistant"

    $Action = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument "`"$JarvisPy`"" `
        -WorkingDirectory $WorkingDir

    $Trigger = New-ScheduledTaskTrigger -AtLogOn

    $Settings = New-ScheduledTaskSettingsSet `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries

    try {
        Register-ScheduledTask `
            -TaskName $TaskName `
            -Action $Action `
            -Trigger $Trigger `
            -Settings $Settings `
            -Description "JARVIS wake-word listener (always-on)" `
            -Force | Out-Null
        Write-Host "==> Registered scheduled task '$TaskName' to start at logon."
    } catch {
        Write-Warning "Could not register the scheduled task: $($_.Exception.Message)"
        Write-Warning "JARVIS is installed; start it manually with run-jarvis.bat"
    }
}

Write-Host
Write-Host "Done. Configure: $ProjectRoot\engine\.env"
Write-Host "  - Ollama Windows:  winget install ollama.ollama  then:  ollama pull llama3.2:3b"
Write-Host "  - (Optional) playback needs ffmpeg on PATH:  winget install Gyan.FFmpeg"
Write-Host "  - TTS: set GEMINI_API_KEY in .env, or the built-in Windows SAPI voice is the fallback."
Write-Host "  - Run JARVIS:  run-jarvis.bat"
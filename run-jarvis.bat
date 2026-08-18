@echo off
rem Start JARVIS wake-word listener. Pass --once for a single briefing.
cd /d "%~dp0"
engine\.venv\Scripts\python.exe assistant\jarvis.py %*
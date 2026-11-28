@echo off
title DDG - Restart Bot Studio
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo Stopping everything: dashboard, crypto bot, video watcher and the AI engine (Ollama)...
"%PY%" -m studio.guardian stop
ping -n 3 127.0.0.1 >nul
echo.
echo Starting everything again (the AI engine first, with Qwen's folder on F:)...
"%PY%" -m studio.guardian start --browser
echo.
echo Health check (should show "version": "2026.11.28-overhaul"):
curl.exe -s http://127.0.0.1:8765/api/health
echo.
echo.
echo If anything looks wrong, the details are in the logs folder: watchdog.log, server.log, ollama.log, crypto.log
pause

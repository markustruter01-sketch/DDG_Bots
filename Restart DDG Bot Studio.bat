@echo off
title DDG - Restart Bot Studio
echo Stopping the old Bot Studio (whatever holds port 8765) and the old video watcher...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8765" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*studio.pipeline watch*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
ping -n 3 127.0.0.1 >nul
echo Starting the new Bot Studio...
wscript.exe "%~dp0scripts\silent_launch.vbs"
ping -n 8 127.0.0.1 >nul
echo.
echo Health check (should show "version": "2026.11.26-phase3"):
curl.exe -s http://127.0.0.1:8765/api/health
echo.
echo.
pause

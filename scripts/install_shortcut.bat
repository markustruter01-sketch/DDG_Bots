@echo off
setlocal
cd /d "C:\Users\User\Desktop\DDG\DDG_Local_Bot_Studio"
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe scripts\make_ico.py
) else (
    python scripts\make_ico.py
)
powershell -ExecutionPolicy Bypass -File "scripts\create_shortcut.ps1"
echo Done.
pause

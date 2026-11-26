@echo off
title DDG - Make Bot Studio always on
set "ROOT=%~dp0"
set "WATCH=%ROOT%scripts\ensure_running.vbs"
echo 1) Start the studio when you log in (Startup folder shortcut)...
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\DDG Bot Studio.lnk'); $s.TargetPath='wscript.exe'; $s.Arguments='\"%WATCH%\"'; $s.WorkingDirectory='%ROOT%'; $s.Save()"
echo 2) Check every 5 minutes and restart it if it has stopped (Task Scheduler)...
schtasks /Create /F /TN "DDG Bot Studio Watchdog" /SC MINUTE /MO 5 /TR "wscript.exe \"%WATCH%\""
echo.
echo Done. To turn this off again, run "Remove Always-On.bat".
pause

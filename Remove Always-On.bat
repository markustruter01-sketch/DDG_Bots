@echo off
title DDG - Turn off Bot Studio always-on
powershell -NoProfile -Command "Remove-Item -ErrorAction SilentlyContinue ([Environment]::GetFolderPath('Startup')+'\DDG Bot Studio.lnk')"
schtasks /Delete /F /TN "DDG Bot Studio Watchdog"
echo Always-on is off. The studio keeps running until you restart the PC or close it.
pause

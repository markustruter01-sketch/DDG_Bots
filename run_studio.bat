@echo off
rem Kill old stale background instances automatically
taskkill /F /FI "WINDOWTITLE eq DDG Night Glass Server*" >nul 2>&1
wscript.exe "%~dp0scripts\silent_launch.vbs"
exit

@echo off
title DDG Local Bot Studio - AI Model Installer
echo Starting DDG Local Bot Studio AI installer (models will save to F:\DDG_Video_Studio\models\ollama)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_local_env.ps1"
echo.
echo ============================================================================
echo Installer finished. Review any messages above, then press any key to close.
echo ============================================================================
pause

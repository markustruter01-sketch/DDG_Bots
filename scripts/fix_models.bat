@echo off
title DDG - Finish installing local AI models (leave this window open)
set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
set "OLLAMA_MODELS=F:\DDG_Video_Studio\models\ollama"
set "OLLAMA_HOST=127.0.0.1:11434"
set "LOG=%~dp0..\logs\model_fix.log"
echo DDG model fix started %date% %time% > "%LOG%"

"%OLLAMA%" list >nul 2>&1
if errorlevel 1 (
  echo Ollama was not running - starting it >> "%LOG%"
  start "DDG Local Ollama" /MIN "%OLLAMA%" serve
  ping -n 6 127.0.0.1 >nul
)

echo.
echo Step 1 of 3: finishing the download of qwen3:8b (the bots' brain)...
"%OLLAMA%" pull qwen3:8b
echo pull qwen3:8b exit=%errorlevel% >> "%LOG%"

echo.
echo Step 2 of 3: finishing the download of qwen3-vl:4b (the vision model)...
"%OLLAMA%" pull qwen3-vl:4b
echo pull qwen3-vl:4b exit=%errorlevel% >> "%LOG%"

echo ==== ollama list ==== >> "%LOG%"
"%OLLAMA%" list >> "%LOG%" 2>&1

echo.
echo Step 3 of 3: speed test, 3 runs...
for /L %%i in (1,1,3) do (
  echo ==== speed run %%i ==== >> "%LOG%"
  curl.exe -s http://127.0.0.1:11434/api/chat -H "Content-Type: application/json" -d @"%~dp0speed_test_request.json" >> "%LOG%" 2>&1
  echo. >> "%LOG%"
)
echo ==== ollama ps ==== >> "%LOG%"
"%OLLAMA%" ps >> "%LOG%" 2>&1
echo ==== gpu memory ==== >> "%LOG%"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv >> "%LOG%" 2>&1
echo ==== gpu apps ==== >> "%LOG%"
nvidia-smi --query-compute-apps=process_name,used_memory --format=csv >> "%LOG%" 2>&1
echo DONE %date% %time% >> "%LOG%"

echo.
echo All done. Tell Claude "done". You can close this window.
pause

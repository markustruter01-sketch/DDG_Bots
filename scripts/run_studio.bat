@echo off
setlocal
pushd "%~dp0.."
set STUDIO_ROOT=%CD%
popd
set OLLAMA_HOST=127.0.0.1:11434
set OLLAMA_KEEP_ALIVE=10m
set OLLAMA_MODELS=F:\DDG_Video_Studio\models\ollama
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    start "DDG Local Ollama (A$0)" /MIN "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
)
if exist "%STUDIO_ROOT%\.venv\Scripts\python.exe" (
    set PY="%STUDIO_ROOT%\.venv\Scripts\python.exe"
) else (
    set PY=python
)
start "DDG Night Glass Dashboard" /D "%STUDIO_ROOT%" %PY% dashboard\server.py
start "DDG Video Inbox Watcher" /D "%STUDIO_ROOT%" %PY% -m studio.pipeline watch
ping -n 3 127.0.0.1 >nul
start "" "http://127.0.0.1:8765"
echo DDG Local Bot Studio running at http://127.0.0.1:8765

# DDG Local Bot Studio - Free Local AI & Video Engine Setup (Windows / RTX 3070 Ti)
$ErrorActionPreference = "Stop"
$StudioRoot = Split-Path -Parent $PSScriptRoot
$FootageRoot = "F:\DDG_Video_Studio"

Write-Host "=== 1. Creating F:\DDG_Video_Studio drop folders ===" -ForegroundColor Cyan
@("01_Raw_Inbox\Vlog","01_Raw_Inbox\DeepDive","01_Raw_Inbox\Gaming","01_Raw_Inbox\Short",
  "02_Processing","03_Ready_For_Review","04_Approved_Exports","05_Archive") | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $FootageRoot $_) | Out-Null
}

Write-Host "=== 2. Setting localhost-only Ollama + F: drive model storage + instant VRAM unload ===" -ForegroundColor Cyan
$OllamaModelsDir = Join-Path $FootageRoot "models\ollama"
New-Item -ItemType Directory -Force -Path $OllamaModelsDir | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "127.0.0.1:11434", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "0", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $OllamaModelsDir, "User")
$env:OLLAMA_HOST = "127.0.0.1:11434"
$env:OLLAMA_KEEP_ALIVE = "0"
$env:OLLAMA_MODELS = $OllamaModelsDir

$OllamaExe = (Get-Command ollama -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
if (-not $OllamaExe) {
    $Candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $Candidate) { $OllamaExe = $Candidate }
}
if (-not $OllamaExe) {
    Write-Host "Installing Ollama via winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
    $Candidate = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $Candidate) { $OllamaExe = $Candidate } else { $OllamaExe = "ollama" }
}

Write-Host "=== 3. Pulling 8GB-VRAM optimal free Apache 2.0 models onto F:\DDG_Video_Studio\models\ollama ===" -ForegroundColor Cyan
& $OllamaExe pull qwen3:8b
& $OllamaExe pull qwen3-vl:4b

Write-Host "=== 4. Creating isolated Python .venv inside DDG_Local_Bot_Studio ===" -ForegroundColor Cyan
$VenvPath = Join-Path $StudioRoot ".venv"
if (-not (Test-Path $VenvPath)) {
    python -m venv $VenvPath
}
$Pip = Join-Path $VenvPath "Scripts\pip.exe"
& $Pip install --upgrade pip
& $Pip install pillow torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
& $Pip install whisperx auto-editor deepfilternet scenedetect opencv-python rapidocr-onnxruntime playwright yt-dlp moviepy

Write-Host "=== 5. Downloading free SIL OFL Geist & Geist Mono fonts ===" -ForegroundColor Cyan
$FontsDir = Join-Path $StudioRoot "assets\fonts"
New-Item -ItemType Directory -Force -Path $FontsDir | Out-Null
$ZipTmp = Join-Path $StudioRoot "logs\geist.zip"
try {
    Invoke-WebRequest -Uri "https://github.com/vercel/geist-font/releases/latest/download/geist-font.zip" -OutFile $ZipTmp
    Expand-Archive -Path $ZipTmp -DestinationPath (Join-Path $StudioRoot "logs\geist_extract") -Force
    Get-ChildItem (Join-Path $StudioRoot "logs\geist_extract") -Recurse -Filter "*.ttf" | Copy-Item -Destination $FontsDir -Force
    Remove-Item $ZipTmp -Force -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Could not auto-download Geist zip; Windows fallback fonts (Segoe UI / Consolas) remain active."
}

Write-Host "=== Done! Run scripts\run_studio.bat to start dashboard + watcher ===" -ForegroundColor Green

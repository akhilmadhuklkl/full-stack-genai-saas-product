$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$ollamaPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$uvPath = Join-Path $env:USERPROFILE ".local\bin\uv.exe"
$model = "llama3.2:3b"
$port = 8001

if (-not (Test-Path $ollamaPath)) {
    throw "Ollama was not found at $ollamaPath. Install Ollama, then run this script again."
}
if (-not (Test-Path $uvPath)) {
    throw "uv was not found at $uvPath. Install uv, then run this script again."
}

try {
    $null = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2
} catch {
    Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$models = & $ollamaPath list 2>$null
if (-not ($models -match [regex]::Escape($model))) {
    & $ollamaPath pull $model
}

Set-Location $projectRoot
Write-Host "Starting Forge Review at http://127.0.0.1:$port" -ForegroundColor Cyan
& $uvPath run --python 3.12 --with-editable ".[dev]" python -m uvicorn app.main:app --host 127.0.0.1 --port $port

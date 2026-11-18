$ErrorActionPreference = "Stop"

$baseUrl = if ($env:FORGE_BASE_URL) { $env:FORGE_BASE_URL } else { "http://127.0.0.1:8001" }
$health = Invoke-RestMethod -Uri "$baseUrl/health/details"
if ($health.status -notin @("ok", "degraded")) { throw "Unexpected application health status" }
if ($health.components.ollama.status -ne "ok") { throw "Ollama is not reachable" }

$version = Invoke-RestMethod -Uri "$baseUrl/api/v1/version"
if (-not $version.name) { throw "Version endpoint returned no application name" }

Write-Host "Application health: $($health.status)" -ForegroundColor Green
Write-Host "Ollama: $($health.components.ollama.status)" -ForegroundColor Green
Write-Host "Redis: $($health.components.redis.status)" -ForegroundColor Green
Write-Host "Version: $($version.version)" -ForegroundColor Green
Write-Host "Smoke test passed." -ForegroundColor Green

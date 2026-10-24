$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$taskDocker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $taskDocker -and (Test-Path 'C:\Program Files\Docker\Docker\resources\bin\docker.exe')) {
  $taskDocker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
}
if (-not $taskDocker) { throw 'Install and start Docker Desktop first.' }
if (Test-Path '.venv\Scripts\python.exe') {
  & '.\.venv\Scripts\python.exe' scripts/configure.py
} else {
  & $taskDocker run --rm -v "${PWD}:/app" -w /app python:3.11-slim python scripts/configure.py
}
if ($LASTEXITCODE -ne 0) { throw 'Secret configuration failed.' }
& $taskDocker compose build api
if ($LASTEXITCODE -ne 0) { throw 'Application image build failed.' }
& $taskDocker compose up --no-build -d --scale worker=3
if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed; inspect docker compose logs.' }
Write-Host 'Petition desk: http://127.0.0.1:8000. API key: .secrets/triage_key. Grafana: http://127.0.0.1:3000 (admin; password in .secrets/grafana_key).'

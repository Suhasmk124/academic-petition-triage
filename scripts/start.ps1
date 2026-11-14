param([switch]$Live, [switch]$Showcase)
$ErrorActionPreference = 'Stop'
if ($Live -and $Showcase) { throw 'Choose either -Live or -Showcase.' }
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
$taskCompose = @('compose')
if ($Live) {
  if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) { throw 'Live mode needs the local hosted settings in .env.' }
  $taskCompose += @('-p','academic-petition-private','-f','compose.yaml','-f','compose.private.yaml')
} elseif ($Showcase) {
  $taskCompose += @('-p','academic-petition-showcase','-f','compose.yaml','-f','compose.showcase.yaml')
}
& $taskDocker @taskCompose build api
if ($LASTEXITCODE -ne 0) { throw 'Application image build failed.' }
if ($Live) {
  & $taskDocker @taskCompose run --no-deps --rm worker python -c "from hosted_model import HostedSettings; HostedSettings.from_env(); print('Hosted configuration is ready.')"
  if ($LASTEXITCODE -ne 0) { throw 'Hosted configuration validation failed.' }
  & $taskDocker @taskCompose up --no-build -d --scale worker=1 worker jaeger
} else {
  & $taskDocker @taskCompose up --no-build -d --scale worker=3
}
if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed; inspect docker compose logs.' }
if ($Live) { Write-Host 'Private petition desk: http://127.0.0.1:8002. Workspace key: .secrets/private_triage_key.'; return }
if ($Showcase) {
  Write-Host 'Showcase: http://127.0.0.1:8003 | Grafana: http://127.0.0.1:3001 | Prometheus: http://127.0.0.1:9091 | Jaeger: http://127.0.0.1:16687'
  return
}
Write-Host 'Petition desk: http://127.0.0.1:8000. API key: .secrets/triage_key. Grafana: http://127.0.0.1:3000 (admin; password in .secrets/grafana_key).'

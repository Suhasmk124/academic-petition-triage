param(
  [ValidateRange(1, 100)][int]$Users = 10,
  [ValidateRange(5, 600)][int]$Seconds = 60
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$showcaseDocker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $showcaseDocker -and (Test-Path 'C:\Program Files\Docker\Docker\resources\bin\docker.exe')) {
  $showcaseDocker = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
}
if (-not $showcaseDocker) { throw 'Install and start Docker Desktop first.' }
$showcaseState = Invoke-RestMethod 'http://127.0.0.1:8003/health' -TimeoutSec 5
if (-not $showcaseState.role_demo -or $showcaseState.mode -ne 'stub') { throw 'Start the simulated showcase with scripts\start.ps1 -Showcase.' }
if ($showcaseState.active_workers -lt 1) { throw 'Wait for a showcase worker to connect.' }
$showcaseCompose = @('compose','-p','academic-petition-showcase','-f','compose.yaml','-f','compose.showcase.yaml')
& $showcaseDocker @showcaseCompose run --rm --no-deps load python -m locust -f load/locustfile.py --host http://api:8000 --headless --only-summary -u $Users -r 2 -t "${Seconds}s" --stop-timeout 35 --csv /app/evaluations/showcase
if ($LASTEXITCODE -ne 0) { throw "Showcase load test failed with exit code $LASTEXITCODE." }

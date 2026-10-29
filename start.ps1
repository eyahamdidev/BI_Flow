# BIFlow one-command start (Windows PowerShell).
#   .\start.ps1                 build + start everything, run the demo (1% Olist sample), open the dashboard
#   .\start.ps1 -Dataset bike_share     run another dataset (olist_sample | bike_share | olist)
#   .\start.ps1 -Full           download the full Olist data (Kaggle) and run it
#   .\start.ps1 -Stop           stop everything
#   .\start.ps1 -NoBrowser      do not open the browser at the end
param([string]$Dataset = "olist_sample", [switch]$Full, [switch]$Stop, [switch]$NoRun, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Stop) { docker compose --profile core down; exit 0 }

Write-Host "== BIFlow ==" -ForegroundColor Cyan
try { docker info *> $null } catch { }
if ($LASTEXITCODE -ne 0) { Write-Host "Docker is not running. Start Docker Desktop, then run this script again." -ForegroundColor Red; exit 1 }

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example."
    $key = ""
    try { $key = Read-Host "Optional: paste an LLM API key (Groq or any OpenAI-compatible), or press Enter to run without LLM" } catch { }
    if ($key) {
        $lines = (Get-Content .env) -replace '^LLM_API_KEY=.*', "LLM_API_KEY=$key"
        [IO.File]::WriteAllLines((Join-Path $PSScriptRoot ".env"), $lines)   # UTF-8 without BOM (Compose reads it)
    }
}

# Docker Desktop may route all container traffic (also image builds) through its own proxy: pass it on automatically.
$proxy = (docker info --format "{{.HTTPSProxy}}" 2>$null)
if ($proxy -and -not (Select-String -Path .env -Pattern '^HTTPS_PROXY=' -Quiet)) {
    if ($proxy -notmatch '^https?://') { $proxy = "http://$proxy" }
    Add-Content .env "`n# added by start.ps1: Docker reports an HTTP proxy`nHTTPS_PROXY=$proxy`nHTTP_PROXY=$proxy"
    Write-Host "Docker uses a proxy ($proxy): added to .env."
}

Write-Host "Building and starting the services (the first time takes several minutes)..."
for ($try = 1; $try -le 3; $try++) {   # flaky networks: finished downloads are cached, so a retry continues
    docker compose --profile core up -d --build
    if ($LASTEXITCODE -eq 0) { break }
    if ($try -eq 3) { Write-Host "Build failed 3 times (network?): run .\start.ps1 again later." -ForegroundColor Red; exit 1 }
    Write-Host "Build attempt $try failed, retrying..." -ForegroundColor Yellow
}

Write-Host -NoNewline "Waiting for the services"
$ports = 8000, 8101, 8102, 8103, 8104, 8105, 8106
for ($i = 0; $i -lt 90; $i++) {
    $up = ($ports | Where-Object { try { (Invoke-WebRequest "http://localhost:$_/v1/meta" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }).Count
    if ($up -eq $ports.Count) { break }
    Write-Host -NoNewline "."; Start-Sleep -Seconds 2
}
Write-Host " ready."

if ($Full) {
    $Dataset = "olist"
    docker compose run --rm --no-deps -v "${PWD}/scripts:/srv/scripts:ro" gateway python /srv/scripts/get_olist.py
}
if (-not $NoRun) {
    Write-Host "Running the pipeline on '$Dataset' (sample: 1-2 min, full Olist: ~4 min)..."
    docker compose exec gateway python -m app.cli run --dataset $Dataset
}
Write-Host ""
Write-Host "Dashboard: http://localhost:8501   (pick the run in the left sidebar)" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process "http://localhost:8501" }

# Start FinAlly in Docker (Windows PowerShell). Idempotent: safe to run repeatedly.
#
# Usage: .\scripts\start_windows.ps1 [-Build] [-NoOpen]
#   -Build   Force a rebuild of the Docker image
#   -NoOpen  Don't open the browser
param(
    [switch]$Build,
    [switch]$NoOpen
)

# Native-command exit codes are checked explicitly; "Stop" would turn docker stderr into terminating errors on PowerShell 5.1
$ErrorActionPreference = "Continue"

$Image = "finally"
$Container = "finally"
$Volume = "finally-data"
$Port = if ($env:PORT) { $env:PORT } else { "8000" }
$Url = "http://localhost:$Port"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker not found. Install Docker Desktop and make sure it is running."
    exit 1
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Error "The Docker daemon is not running. Start Docker Desktop and retry."
    exit 1
}

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example - add your OPENROUTER_API_KEY to enable AI chat."
    } else {
        New-Item -ItemType File ".env" | Out-Null
    }
}

docker image inspect $Image *> $null
if ($Build -or $LASTEXITCODE -ne 0) {
    Write-Host "Building Docker image '$Image'..."
    docker build -t $Image .
    if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed."; exit 1 }
}

# Replace any existing container (running or stopped); the volume is kept
docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Removing existing container '$Container'..."
    docker rm -f $Container | Out-Null
}

# Fail fast if another process already serves the port; otherwise the health check below could pass against it
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    Write-Error "Something is already listening on port $Port. Stop it or set `$env:PORT to another port."
    exit 1
}

Write-Host "Starting container '$Container'..."
docker run -d `
    --name $Container `
    -p "${Port}:8000" `
    -v "${Volume}:/app/db" `
    --env-file .env `
    --restart unless-stopped `
    $Image | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to start container."; exit 1 }

Write-Host -NoNewline "Waiting for FinAlly to become healthy"
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$Url/api/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    Write-Host -NoNewline "."
    Start-Sleep -Seconds 1
}
Write-Host ""

if (-not $healthy) {
    Write-Warning "FinAlly did not respond on $Url yet. Check logs with: docker logs $Container"
    exit 1
}

Write-Host "FinAlly is running at $Url"
if (-not $NoOpen) { Start-Process $Url }

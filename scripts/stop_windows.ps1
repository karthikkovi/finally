# Stop and remove the FinAlly container (Windows PowerShell). Idempotent.
# The `finally-data` volume is NOT removed, so portfolio data persists.
# Native-command exit codes are checked explicitly; "Stop" would turn docker stderr into terminating errors on PowerShell 5.1
$ErrorActionPreference = "Continue"

$Container = "finally"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "docker not found."
    exit 1
}

docker container inspect $Container *> $null
if ($LASTEXITCODE -eq 0) {
    docker rm -f $Container | Out-Null
    Write-Host "Stopped and removed container '$Container'. Data volume 'finally-data' is preserved."
} else {
    Write-Host "Container '$Container' is not running."
}

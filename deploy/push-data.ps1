# Copy your Lingo OS data from this laptop to your server (docs/DEPLOY.md, step 4).
#
#   .\deploy\push-data.ps1 -Server ubuntu@lingo            # the server's Tailscale name (or IP), with its user
#   .\deploy\push-data.ps1 -Server ubuntu@lingo -DataDir D:\lingo-data -RemoteDir /home/ubuntu/lingo-data
#
# It stops the app on the server, packs this laptop's data folder (database, dictionaries, library, models), copies
# it over with scp (built into Windows), unpacks it and starts the app again. Stop Lingo OS on this laptop first, so
# the database isn't being written while it's copied. Nothing on this laptop is changed or deleted.
param(
  [Parameter(Mandatory = $true)][string]$Server,
  [string]$DataDir = "",
  [string]$RemoteDir = "~/lingo-data"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if (-not $DataDir) {
  $DataDir = if ($env:LINGO_DATA_DIR) { $env:LINGO_DATA_DIR } else { Join-Path $root "data" }
}
if (-not (Test-Path (Join-Path $DataDir "lingo.db"))) { throw "No Lingo OS data in $DataDir (lingo.db not found)." }

$running = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($running) { throw "Lingo OS is still running on this laptop (port 8787). Stop it first, then run this again." }

$archive = Join-Path $env:TEMP "lingo-data.tar.gz"
Write-Host "Packing $DataDir (the backups and cache folders are left out)..."
tar -czf $archive -C $DataDir --exclude=backups --exclude=cache .
$size = [math]::Round((Get-Item $archive).Length / 1MB, 1)
Write-Host "Packed $size MB."

Write-Host "Stopping Lingo OS on the server..."
ssh $Server "sudo systemctl stop lingo.service; mkdir -p $RemoteDir"

Write-Host "Copying to ${Server}:$RemoteDir ..."
scp $archive "${Server}:/tmp/lingo-data.tar.gz"

Write-Host "Unpacking and starting it again..."
ssh $Server "set -e; cd $RemoteDir; if [ -f lingo.db ]; then mkdir -p ../lingo-data-before-push && cp -a . ../lingo-data-before-push/; fi; tar -xzf /tmp/lingo-data.tar.gz -C $RemoteDir; rm /tmp/lingo-data.tar.gz; sudo systemctl start lingo.service"

Remove-Item $archive
Write-Host "Done. Your data is on the server. If anything was there before, it's kept in ~/lingo-data-before-push."

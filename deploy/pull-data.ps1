# Copy your Lingo OS data from your server back to this laptop (docs/DEPLOY.md, "Switching back to the laptop").
#
#   .\deploy\pull-data.ps1 -Server ubuntu@lingo-os         # the server's Tailscale name (or IP), with its user
#   .\deploy\pull-data.ps1 -Server ubuntu@lingo-os -DataDir D:\lingo-data -RemoteDir /home/ubuntu/lingo-data
#
# The reverse of push-data.ps1. It stops the app on the server for a moment (so the database isn't written while it's
# packed), packs its data folder, starts the app again, copies the archive here and unpacks it into this laptop's data
# folder. What was in that folder before is moved aside to <data folder>-before-pull, never deleted. Stop Lingo OS on
# this laptop first. Afterwards set Settings → Where Lingo OS runs → On this laptop.
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
$running = Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
if ($running) { throw "Lingo OS is still running on this laptop (port 8787). Stop it first, then run this again." }

Write-Host "Packing the data on ${Server} (the app pauses for a moment)..."
ssh $Server "set -e; test -f $RemoteDir/lingo.db || { echo 'No Lingo OS data in $RemoteDir on the server.'; exit 1; }; sudo systemctl stop lingo.service; trap 'sudo systemctl start lingo.service' EXIT; tar -czf /tmp/lingo-data-pull.tar.gz -C $RemoteDir --exclude=backups --exclude=cache ."

$archive = Join-Path $env:TEMP "lingo-data-pull.tar.gz"
Write-Host "Copying it here..."
scp "${Server}:/tmp/lingo-data-pull.tar.gz" $archive
ssh $Server "rm -f /tmp/lingo-data-pull.tar.gz"
$size = [math]::Round((Get-Item $archive).Length / 1MB, 1)
Write-Host "Copied $size MB."

if (Test-Path (Join-Path $DataDir "lingo.db")) {
  $aside = "$DataDir-before-pull"
  if (Test-Path $aside) { $aside = "$aside-$(Get-Date -Format yyyyMMdd-HHmmss)" }
  Write-Host "Moving this laptop's old data aside to $aside ..."
  Move-Item $DataDir $aside
}
New-Item -ItemType Directory -Force $DataDir | Out-Null
tar -xzf $archive -C $DataDir
Remove-Item $archive
Write-Host "Done. The server's data is now in $DataDir."
Write-Host "Next: start Lingo OS here, set Settings -> Where Lingo OS runs -> On this laptop, and pair your phone again."

<#
.SYNOPSIS
  Registers (or removes) the two Lingo OS background tasks in Windows Task Scheduler.

.DESCRIPTION
  - "Lingo OS update-content": every day at 06:00, finds new videos and articles near your level.
  - "Lingo OS evolve-profile": every Sunday at 21:00, writes the weekly report and adjusts your picks.
  Both run as you, only when you are logged on, and work whether or not the app is open (the database allows it).
  Nothing is registered until you run this script yourself.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1
  powershell -ExecutionPolicy Bypass -File scripts\schedule-windows.ps1 -Remove
#>
param(
  [switch]$Remove,
  [string]$UpdateTime = "06:00",
  [string]$EvolveTime = "21:00"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$names = @("Lingo OS update-content", "Lingo OS evolve-profile")

if ($Remove) {
  foreach ($name in $names) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $name -Confirm:$false
      Write-Host "Removed: $name"
    }
  }
  return
}

$uv = (Get-Command uv -ErrorAction Stop).Source
$logs = Join-Path $root "data\logs"
New-Item -ItemType Directory -Force $logs | Out-Null

function New-LingoAction([string]$command, [string]$log) {
  $arguments = "-NoProfile -WindowStyle Hidden -Command `"& '$uv' run --project backend lingo $command *>> '$log'`""
  New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $root
}

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $names[0] -Force -Settings $settings `
  -Action (New-LingoAction "update-content" (Join-Path $logs "update-content.log")) `
  -Trigger (New-ScheduledTaskTrigger -Daily -At $UpdateTime) `
  -Description "Lingo OS: find new content near your level" | Out-Null
Write-Host "Registered: $($names[0]) (daily at $UpdateTime)"

Register-ScheduledTask -TaskName $names[1] -Force -Settings $settings `
  -Action (New-LingoAction "evolve-profile" (Join-Path $logs "evolve-profile.log")) `
  -Trigger (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At $EvolveTime) `
  -Description "Lingo OS: weekly report and recalibration" | Out-Null
Write-Host "Registered: $($names[1]) (Sundays at $EvolveTime)"
Write-Host "Logs go to $logs. Remove both with: scripts\schedule-windows.ps1 -Remove"

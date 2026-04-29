# register-schedule.ps1 - one-time helper: register daily.ps1 with Task Scheduler.
# Default: every day at 08:00 local time. Override with -At "07:30".
#
# Usage:   .\register-schedule.ps1
#          .\register-schedule.ps1 -At "06:30"
#          .\register-schedule.ps1 -Unregister

[CmdletBinding()]
param(
    [string]$At = "08:00",
    [switch]$Unregister,
    [string]$TaskName = "VB Rental Finder Daily"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$daily = Join-Path $root "daily.ps1"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Unregistered '$TaskName'."
    } else {
        Write-Host "No task named '$TaskName'."
    }
    return
}

if (-not (Test-Path $daily)) {
    throw "daily.ps1 not found at $daily"
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$daily`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $At

# Run only when user is logged in. No need for highest privileges - we just
# touch git, run python, and show a toast in the user's session.
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Run vb-rental-finder, commit out/ to git, push, toast summary." | Out-Null

Write-Host "Registered '$TaskName' to run daily at $At."
Write-Host "Run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Unregister: .\register-schedule.ps1 -Unregister"

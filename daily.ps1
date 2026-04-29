# daily.ps1 - run scrapers, commit new CSV/diff/run-JSON, push, toast.
# Designed to be invoked by Task Scheduler. Keeps a rolling log at out/daily.log.
#
# Manual invocation: .\daily.ps1                         (does everything)
#                    .\daily.ps1 -NoPush -NoToast        (dry-run locally)

[CmdletBinding()]
param(
    [switch]$NoPush,
    [switch]$NoToast,
    [switch]$NoPull
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$logDir = Join-Path $root "out"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "daily.log"

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Host $line
}

function Show-Toast($title, $body) {
    if ($NoToast) { return }
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        $xmlDoc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $escTitle = [System.Security.SecurityElement]::Escape($title)
        $escBody = [System.Security.SecurityElement]::Escape($body)
        $xmlDoc.LoadXml(@"
<toast><visual><binding template="ToastText02"><text id="1">$escTitle</text><text id="2">$escBody</text></binding></visual></toast>
"@)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xmlDoc
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("vb-rental-finder").Show($toast)
    } catch {
        Write-Log "toast failed: $_"
    }
}

Write-Log "=== daily run starting ==="

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Log "no .venv found - creating one"
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install --upgrade pip --quiet
    & (Join-Path $root ".venv\Scripts\pip.exe") install -r (Join-Path $root "requirements.txt") --quiet
    & $python -m playwright install chromium
}

if (-not $NoPull) {
    Write-Log "git pull --rebase --autostash"
    git pull --rebase --autostash 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Log "git pull failed (continuing)" }
}

Write-Log "running main.py"
& $python (Join-Path $root "main.py") --log-level INFO 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
$pyExit = $LASTEXITCODE
if ($pyExit -ne 0) {
    Write-Log "main.py exit $pyExit - aborting commit/push"
    Show-Toast "VB Rentals: run failed" "main.py exit $pyExit. See out/daily.log."
    exit $pyExit
}

$today = Get-Date -Format "yyyy-MM-dd"
$runJson = Join-Path $root "out\run_$today.json"
if (-not (Test-Path $runJson)) {
    Write-Log "no run JSON at $runJson - aborting"
    exit 1
}
$summary = Get-Content $runJson -Raw | ConvertFrom-Json
$total = $summary.total_unique
$new = $summary.diff.new
$gone = $summary.diff.gone
$perSource = ($summary.per_source.PSObject.Properties | ForEach-Object {
    "{0}={1}" -f $_.Name, $_.Value.kept
}) -join ", "

Write-Log "summary: total=$total new=$new gone=$gone ($perSource)"

git add out/ 2>&1 | Out-Null
$staged = git diff --cached --name-only
if (-not $staged) {
    Write-Log "nothing to commit"
    Show-Toast "VB Rentals: no changes" "$total listings, no new vs prior run."
    exit 0
}

$body = @"
Daily run $today

- $total unique listings ($perSource)
- $new new listings, $gone gone vs prior run
"@

git commit -m $body 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Log "git commit failed"
    Show-Toast "VB Rentals: commit failed" "See out/daily.log"
    exit 1
}
Write-Log "committed: $body"

if (-not $NoPush) {
    git push origin main 2>&1 | Tee-Object -FilePath $log -Append | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Log "git push failed"
        Show-Toast "VB Rentals: push failed" "See out/daily.log. Commit is local."
        exit 1
    }
    Write-Log "pushed"
}

$msg = "$new new, $gone gone - $total total"
Show-Toast "VB Rentals: $today" $msg
Write-Log "=== daily run complete ==="
exit 0

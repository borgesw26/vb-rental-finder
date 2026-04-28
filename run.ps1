# run.ps1 — set up and run the Virginia Beach rental aggregator on Windows.
# Usage:   .\run.ps1
# Options: -SkipInstall  (don't reinstall deps)
#          -Only realtor,craigslist  (run a subset of scrapers)
#          -LogLevel DEBUG

[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [string[]]$Only,
    [string]$LogLevel = "INFO",
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
$pip = Join-Path $venv "Scripts\pip.exe"

if (-not (Test-Path $python)) {
    Write-Host "[setup] Creating venv at .venv" -ForegroundColor Cyan
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create venv. Is Python 3.11+ on PATH?" }
}

if (-not $SkipInstall) {
    Write-Host "[setup] Installing requirements" -ForegroundColor Cyan
    & $python -m pip install --upgrade pip --quiet
    & $pip install -r requirements.txt --quiet
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
    Write-Host "[setup] Installing Playwright browser (chromium)" -ForegroundColor Cyan
    & $python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { Write-Warning "playwright install returned non-zero. Some scrapers may fail." }
}

$argList = @("main.py", "--log-level", $LogLevel)
if ($Only) {
    $argList += "--only"
    $argList += $Only
}

Write-Host "[run] python $($argList -join ' ')" -ForegroundColor Cyan
& $python @argList
$exitCode = $LASTEXITCODE

$reportPath = Join-Path $root "report.html"
if ((-not $NoOpen) -and (Test-Path $reportPath)) {
    Write-Host "[done] Opening report.html" -ForegroundColor Green
    Start-Process $reportPath
}

exit $exitCode

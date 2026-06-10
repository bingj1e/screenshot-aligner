$ErrorActionPreference = "Stop"

$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$PidFile = Join-Path $AppDir "screenshot-aligner.pid"

if (-not (Test-Path $PidFile)) {
    Write-Host "Screenshot Aligner is not running, or no PID file exists."
    exit 0
}

$PidValue = Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
$Process = if ($PidValue) { Get-Process -Id $PidValue -ErrorAction SilentlyContinue } else { $null }

if ($Process) {
    Stop-Process -Id $Process.Id -Force
    New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
    Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Stopped Screenshot Aligner background watcher with PID $($Process.Id)"
    Write-Host "Stopped Screenshot Aligner background watcher."
} else {
    Write-Host "Stored PID was not running."
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

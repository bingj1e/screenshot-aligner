$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$PidFile = Join-Path $AppDir "screenshot-aligner.pid"
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null

$ExistingPid = if (Test-Path $PidFile) { Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1 } else { $null }
if ($ExistingPid) {
    $ExistingProcess = Get-Process -Id $ExistingPid -ErrorAction SilentlyContinue
    if ($ExistingProcess) {
        Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Screenshot Aligner is already running with PID $ExistingPid"
        exit 0
    }
}

Set-Location $ProjectRoot
$Command = Get-Command screenshot-aligner -ErrorAction Stop

$Process = Start-Process `
    -FilePath $Command.Source `
    -ArgumentList @("watch", "--quiet", "--log-file", "`"$LogFile`"") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

Set-Content -Path $PidFile -Value $Process.Id
Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Started Screenshot Aligner background watcher with PID $($Process.Id)"

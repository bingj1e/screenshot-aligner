$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$PidFile = Join-Path $AppDir "screenshot-aligner-tray.pid"
$WatchPidFile = Join-Path $AppDir "screenshot-aligner.pid"
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
. (Join-Path $PSScriptRoot "process-utils.ps1")

$ExistingProcess = Get-ValidatedScreenshotAlignerProcess -PidFile $PidFile
if (-not $ExistingProcess) {
    $ExistingProcess = Get-ValidatedScreenshotAlignerProcess -PidFile $WatchPidFile
}
if ($ExistingProcess) {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Screenshot Aligner is already running with PID $($ExistingProcess.Id)"
    exit 0
}

Set-Location $ProjectRoot
$Command = Get-Command screenshot-aligner -ErrorAction Stop

$Process = Start-Process `
    -FilePath $Command.Source `
    -ArgumentList @("tray", "--quiet", "--log-file", "`"$LogFile`"") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Milliseconds 300
if ($Process.HasExited) {
    Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Tray process exited during startup, usually because another instance already owns the lock"
    exit 0
}

Set-Content -Path $PidFile -Value $Process.Id
Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Started Screenshot Aligner tray app with PID $($Process.Id)"

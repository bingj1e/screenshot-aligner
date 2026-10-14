$ErrorActionPreference = "Stop"

$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$WatchPidFile = Join-Path $AppDir "screenshot-aligner.pid"
$TrayPidFile = Join-Path $AppDir "screenshot-aligner-tray.pid"
. (Join-Path $PSScriptRoot "process-utils.ps1")

$Processes = @()
foreach ($PidFile in @($WatchPidFile, $TrayPidFile)) {
    $Process = Get-ValidatedScreenshotAlignerProcess -PidFile $PidFile
    if ($Process) {
        $Processes += $Process
    }
}
$Processes += Get-DiscoveredScreenshotAlignerProcesses
$Processes = @($Processes | Sort-Object Id -Unique)

if ($Processes.Count -gt 0) {
    New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
    foreach ($Process in $Processes) {
        Stop-Process -Id $Process.Id -Force
        Add-Content -Path $LogFile -Value "$(Get-Date -Format s) Stopped Screenshot Aligner process with PID $($Process.Id)"
    }
    Write-Host "Stopped Screenshot Aligner."
} else {
    Write-Host "Screenshot Aligner is not running."
}

Remove-Item -LiteralPath $WatchPidFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $TrayPidFile -Force -ErrorAction SilentlyContinue

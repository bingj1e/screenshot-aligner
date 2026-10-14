$ErrorActionPreference = "Stop"

$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$WatchPidFile = Join-Path $AppDir "screenshot-aligner.pid"
$TrayPidFile = Join-Path $AppDir "screenshot-aligner-tray.pid"
$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "Screenshot Aligner.lnk"
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
    Write-Host "Screenshot Aligner: running, PID(s) $($Processes.Id -join ', ')"
} else {
    Write-Host "Screenshot Aligner: not running"
}

if (Test-Path $ShortcutPath) {
    Write-Host "Startup shortcut: installed"
    Write-Host $ShortcutPath
} else {
    Write-Host "Startup shortcut: not installed"
}

if (Test-Path $LogFile) {
    Write-Host "Log file:"
    Write-Host $LogFile
    Write-Host "Recent log lines:"
    Get-Content $LogFile -Tail 8
} else {
    Write-Host "Log file: not created yet"
}

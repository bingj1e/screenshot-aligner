$ErrorActionPreference = "Stop"

$AppDir = Join-Path $env:LOCALAPPDATA "ScreenshotAligner"
$LogFile = Join-Path $AppDir "screenshot-aligner.log"
$PidFile = Join-Path $AppDir "screenshot-aligner.pid"
$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "Screenshot Aligner.lnk"

$PidValue = if (Test-Path $PidFile) { Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1 } else { $null }
$Process = if ($PidValue) { Get-Process -Id $PidValue -ErrorAction SilentlyContinue } else { $null }

if ($Process) {
    Write-Host "Background watcher: running, PID $($Process.Id)"
} else {
    Write-Host "Background watcher: not running"
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

$ErrorActionPreference = "Stop"

$StartupFolder = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $StartupFolder "Screenshot Aligner.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host "Removed startup shortcut:"
    Write-Host $ShortcutPath
} else {
    Write-Host "Startup shortcut was not installed."
}

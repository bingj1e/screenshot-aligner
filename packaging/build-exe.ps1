$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

python packaging\make_icon.py

pyinstaller --noconfirm --clean --onefile --noconsole `
    --name ScreenshotAligner `
    --icon assets\icon.ico `
    --hidden-import pystray._win32 `
    --hidden-import pynput.keyboard._win32 `
    --hidden-import pynput.mouse._win32 `
    packaging\launcher.py

Write-Host "Built dist\ScreenshotAligner.exe"

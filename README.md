# Screenshot Aligner

**Copy a screenshot. Paste a cleaner one.**

A small Windows app that trims extra space and balances screenshot margins automatically, so sharing screenshots takes less effort.

## Get started

1. Download `ScreenshotAligner.exe` from the [latest release](https://github.com/bingj1e/screenshot-aligner/releases/latest).
2. Double-click it. The app runs in your system tray.
3. Copy a screenshot, wait a moment, and paste the cleaned-up image.

Use the tray menu to pause, resume, process the current image, or quit.

## Good to know

- Works best with text screenshots on plain backgrounds.
- Processes images locally, without OCR or uploads.
- Watches clipboard images automatically; no extra hotkey is needed.
- To start it when you sign in, place a shortcut to the EXE in your Windows Startup folder.

## Run from source

Requires Windows 10/11, Python 3.12+, and Git.

```powershell
git clone https://github.com/bingj1e/screenshot-aligner.git
cd screenshot-aligner
python -m pip install .
screenshot-aligner tray
```

For other commands and options:

```powershell
screenshot-aligner --help
```

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

Pushing a `v*` tag runs the release workflow to build and publish the Windows EXE.

---

Created by [bingj1e](https://github.com/bingj1e). [MIT License](LICENSE).

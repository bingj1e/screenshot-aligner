# Screenshot Aligner

**Copy a screenshot. Paste a cleaner one.**

A small Windows app that trims extra space and balances screenshot margins automatically, so sharing screenshots takes less effort.

## Get started

1. Download `ScreenshotAligner.exe` from the [latest release](https://github.com/bingj1e/screenshot-aligner/releases/latest).
2. Double-click it. The app runs in your system tray.
   The EXE is not code-signed, so Windows SmartScreen may warn on first run: choose **More info → Run anyway**.
3. Copy a screenshot, wait a moment, and paste the cleaned-up image.

Use the tray menu to pause, resume, process the current image, or quit.

## What it changes

Each copied image is checked before anything is changed:

| You copy | What happens |
|---|---|
| A text screenshot (chat, article, code, settings page…) | Extra space is trimmed and the margins are balanced. If text touches the edge, a thin margin is added. |
| A chart, icon or other graphic on a plain background | Extra space is trimmed. Nothing is added around it. |
| A photo, or a screenshot taken inside a photo | Left exactly as it is. |

## Good to know

- Works best with text screenshots on plain backgrounds.
- Processes images locally, without OCR or uploads.
- Watches clipboard images automatically; no extra hotkey is needed.
- Every image copied to the clipboard is checked, not only screenshots. Some apps copy a picture together with text, for example a range of Excel cells; the processed image may replace that copy. Pause watching from the tray menu first when that matters.
- Transparent areas become white. Color profiles and DPI information are not kept.
- To start it when you sign in: press `Win+R`, type `shell:startup`, and put a shortcut to the EXE in the folder that opens.

## Something looks wrong?

- **A screenshot was cropped badly:** pause watching from the tray, take the screenshot again, and save it as a file. Attach it when you open an [issue](https://github.com/bingj1e/screenshot-aligner/issues). If you run from source, `screenshot-aligner debug-file shot.png` prints what kind of image it detected and why; please include that output too.
- **Nothing happens:** check the log at `%LOCALAPPDATA%\ScreenshotAligner\screenshot-aligner.log`. The tray menu also has **Open log file**.
- **Only one copy runs at a time.** Starting a second one exits quietly.

## Run from source

Requires Windows 10/11, Python 3.12+, and Git.

```powershell
git clone https://github.com/bingj1e/screenshot-aligner.git
cd screenshot-aligner
python -m pip install .
screenshot-aligner tray
```

The `scripts` folder has helpers for running it hidden in the background (`start-tray.cmd`, `status.cmd`, `stop-watch.cmd`) and at sign-in (`install-startup.cmd`, `uninstall-startup.cmd`).

For other commands and options:

```powershell
screenshot-aligner --help
```

## How it works

No OCR and no network: the app estimates the background color from the image edges, detects text by the shape of its strokes, and crops around the content it finds. See [docs/how-it-works.md](docs/how-it-works.md) for the details, the commands, and the settings.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

Pushing a `v*` tag runs the release workflow to build and publish the Windows EXE.

---

Created by [bingj1e](https://github.com/bingj1e). [MIT License](LICENSE).

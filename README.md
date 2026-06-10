# Screenshot Aligner

Screenshot Aligner is a small Windows helper that cleans up screenshot content from the clipboard. The default mode crops to the detected main content and adds balanced padding, so text screenshots are easier to read and share.

It runs fully local (no OCR, no network) and can live in the system tray so every screenshot you copy is cleaned up automatically.

## Install

From this folder:

```powershell
python -m pip install -e ".[dev]"
```

## Use

Start the hotkey listener:

```powershell
screenshot-aligner run
```

Then:

1. Take a screenshot with any tool that copies the image to the clipboard.
2. Press `Ctrl+Alt+X`.
3. Paste the result into WeChat, Word, a browser, or another app.

By default this uses `crop` mode: it keeps the detected main content and replaces uneven outer margins with balanced padding.

If you want the old behavior that preserves every original pixel and only extends the canvas, use:

```powershell
screenshot-aligner run --mode pad
```

## Run In The System Tray (Recommended)

The tray app watches the clipboard in the background and shows an icon in the notification area:

```powershell
screenshot-aligner tray
```

The tray menu lets you:

- pause and resume clipboard watching,
- process the current clipboard image on demand,
- open the log file (when started with `--log-file`),
- quit the app.

To start it hidden (no console window) with logging enabled:

```powershell
.\scripts\start-tray.cmd
```

To start the tray app automatically when Windows signs in:

```powershell
.\scripts\install-startup.cmd
```

Pass `-Mode watch` to `scripts\install-startup.ps1` if you prefer the headless watcher without a tray icon.

## Auto Process Screenshots

Use `watch` when you want Screenshot Aligner to run automatically after another screenshot tool copies an image to the clipboard:

```powershell
screenshot-aligner watch
```

This works well with QQ, Windows Snipping Tool, ShareX, browser screenshots, and other tools that copy the screenshot image to the clipboard.

Stop it with `Ctrl+C` in the terminal.

You can also start watch mode with the helper script:

```powershell
.\scripts\start-watch.ps1
```

To start the background watcher now without a visible terminal:

```powershell
.\scripts\start-watch.cmd
```

To check whether it is running:

```powershell
.\scripts\status.cmd
```

To stop the background watcher:

```powershell
.\scripts\stop-watch.cmd
```

To remove the Windows startup shortcut:

```powershell
.\scripts\uninstall-startup.cmd
```

Background logs are written here:

```text
%LOCALAPPDATA%\ScreenshotAligner\screenshot-aligner.log
```

## Debug With Files

Use this command when you want to test the alignment algorithm without touching the clipboard:

```powershell
screenshot-aligner process-file input.png output.png
```

Use this command when you want to process the current clipboard image once without relying on the global hotkey:

```powershell
screenshot-aligner once
```

Use this command to inspect why a screenshot was cropped or padded in a specific way:

```powershell
screenshot-aligner debug-file input.png
```

## How The Alignment Works

- The background color is estimated from the dominant color among edge pixels, so mixed borders (for example a split light/dark frame) resolve to a real color instead of a blended gray.
- Foreground pixels are everything that differs from the background beyond a threshold, dilated a little so thin text strokes connect.
- Tiny isolated specks (a leftover cursor pixel, compression dust) are ignored when computing the content box, so they no longer stretch the crop.
- Padding adapts to content size: small snippets get a comfortable `24` px margin, large screenshots get proportionally more (6% of the longer content side, capped at `128` px).
- If the detected foreground covers almost the entire image, the background estimate is considered unreliable and the image is left unchanged instead of producing a distorted result.

## Defaults

- Hotkey: `Ctrl+Alt+X`
- Mode: `crop`
- Padding: adaptive, `24`-`128` px (6% of the longer content side)
- Background fill: dominant edge color
- Foreground detection threshold: `24`
- Foreground dilation: `3` px
- Specks smaller than `80` px² (after dilation) are ignored

## Run Tests

```powershell
pytest
```

## Notes

This tool does not use OCR. It detects visual foreground pixels against the estimated background, which is usually enough for text screenshots and keeps the tool fast and local. Light gray UI text, separators, and quote bars are still treated as content if they are visually different from the background.

## License

MIT. See [LICENSE](LICENSE).

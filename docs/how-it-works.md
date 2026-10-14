# How Screenshot Aligner works

Screenshot Aligner runs entirely on your machine. It uses no OCR and no network: it looks at pixel colors and shapes, decides what kind of image it has, and then crops (or pads) around the content.

## Processing steps

1. **Input limits.** Images above 100 million pixels are left unchanged. Images above 6 million pixels (for example a 4K screenshot) are analyzed at a reduced size; the crop is mapped back and applied to the full-resolution image.
2. **Color.** The image is converted to RGB. Transparent areas are composited onto white.
3. **Background color.** If the four corners agree on one color, that is the background. Otherwise the most common color along the image edges is used. If no color covers at least 12% of the edge, the image is treated as a photo or texture and left unchanged.
4. **Content box.** Pixels that differ from the background by more than a threshold are content. They are dilated slightly so thin strokes connect. Tiny specks (a stray cursor pixel, compression dust) and thin page border lines along the edges are ignored. If there is no content, or content covers almost the whole image (so the background estimate is unreliable), the image is left unchanged. Subtle containers around the text, such as chat bubbles or quote blocks, are added to the box when they overlap the text and stay close to it.
5. **Content kind** (see below): text, graphic, or picture. Pictures stop here, unchanged.
6. **Crop or pad** around the content box (see below).

## Content kinds

The kind decides how much the app is allowed to change.

| Kind | Recognized by | Crop mode | Pad mode |
|---|---|---|---|
| Text | Rows of glyph-sized strokes make up at least half of all strokes | Cropped, margins balanced, edge gutter allowed | Padded |
| Graphic | No text, but a pixel-flat background that is visible on all four sides | Cropped inside the original frame only | Unchanged |
| Picture | Anything else | Unchanged | Unchanged |

**Text** is found from local contrast, not from the page background: a morphological black-hat (dark text on a light background) or top-hat (light text on a dark background) picks out strokes thinner than about 15 px. That works inside chat bubbles and on tinted panels too. Stroke pieces are grouped into lines by overlap, so dots, accents, punctuation and the separate strokes of a CJK character stay in their line. A line needs at least four pieces and must be clearly wider than it is tall. Photo texture rarely forms such rows.

**Graphic** relies on the fact that a UI canvas is one exact RGB value from pixel to pixel; JPEG compression keeps flat areas flat as well. Sky, snow, sea or shadow in a photo carries sensor noise and gradients. At least 95% of the background pixels on the border must be within ±2 of the background color, the background must be confident (corners or at least 75% of the edge agree), and no content may touch any side. A screenshot taken inside a photo always touches the sides.

Why graphics are never extended: the only place the app invents pixels is the edge gutter for text. A graphic is cropped strictly inside the original frame, so if a photo is ever misclassified as a graphic (an overexposed sky or crushed blacks are also pixel-flat), the worst outcome is a tighter crop, not a fake border around a photo.

## Crop mode (default)

- **Margin size** scales with the content: 6% of the longer side of the content box, clamped to 24–128 px.
- **Balancing** reuses real pixels. On each axis the narrower existing margin is kept (up to the target size) and the wider side is cropped to match. Crop mode normally only removes pixels, so gradients and textured page backgrounds stay intact.
- **Edge gutter (text only).** When text touches an image edge, that axis gets a 16 px margin on both sides (24 px divided by the golden ratio, rounded to a 4 px grid). This is the one case where crop mode makes the image larger, by at most 32 px per axis. The new pixels use the corner color.

## Pad mode

`--mode pad` keeps every original pixel and only extends the canvas so the content is centered with equal margins on each axis. Because it always adds pixels, it only applies to text; graphics and pictures are left unchanged.

## Clipboard safety

- A result is written back only if the clipboard still holds the image that was read. The check runs while the Windows clipboard is locked, so anything you copy during processing is never overwritten.
- After a write-back, the watcher remembers the exact clipboard version it wrote, so its own result is not processed again and your next copy is still picked up.
- At most one image is processed at a time. Hotkey processing runs off the keyboard hook thread.
- Logging problems (unwritable folder, failed rotation) never stop processing. The log rotates at about 5 MB.

## Commands

| Command | What it does |
|---|---|
| `screenshot-aligner tray` | Watches the clipboard from a tray icon with pause/resume, process now, open log, and quit. This is what the EXE runs when double-clicked. |
| `screenshot-aligner watch` | Same watcher without a tray icon; stop with `Ctrl+C`. |
| `screenshot-aligner run` | Processes the clipboard only when you press `Ctrl+Alt+X`. |
| `screenshot-aligner once` | Processes the current clipboard image once. |
| `screenshot-aligner process-file in.png out.png` | Processes an image file. |
| `screenshot-aligner debug-file in.png` | Prints the detected content kind with its measurements, the content box, the margins, and the output size. |

All of them accept `--mode crop|pad`. `run`, `once`, `watch` and `tray` also accept `--quiet` and `--log-file PATH`. Only one clipboard-watching instance runs at a time.

The EXE accepts the same commands, but it is built without a console window, so output from `debug-file` is not visible there. Use an install from source for debugging.

### Background helper scripts

The scripts in `scripts/` run the installed `screenshot-aligner` command (from a source install) hidden in the background and log to `%LOCALAPPDATA%\ScreenshotAligner\screenshot-aligner.log`.

| Script | Purpose |
|---|---|
| `start-tray.cmd` / `start-watch.cmd` | Start the tray app or the headless watcher without a console window |
| `status.cmd` | Show whether a tray app, watcher, or EXE is running |
| `stop-watch.cmd` | Stop processes started by these scripts |
| `install-startup.cmd` | Start the tray app at sign-in. For the headless watcher: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-startup.ps1 -Mode watch` |
| `uninstall-startup.cmd` | Remove the sign-in shortcut |

## Settings

The command line exposes only the mode. Everything else is a field of `AlignmentConfig` (`src/screenshot_aligner/config.py`) for use from Python, for example:

```python
from PIL import Image
from screenshot_aligner import AlignmentConfig, align_image

result = align_image(Image.open("shot.png"), AlignmentConfig(min_padding=32))
print(result.changed, result.note)
if result.content is not None:  # None when an earlier check already stopped
    print(result.content.kind)
result.image.save("aligned.png")
```

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `crop` | `crop` or `pad` |
| `min_padding` / `max_padding` / `padding_ratio` | 24 / 128 / 0.06 | Target margin: 6% of the content's longer side, clamped |
| `edge_safety_padding` | 16 | Edge gutter for text touching the frame |
| `mask_threshold` | 24 | Color distance from the background that counts as content |
| `dilate_px` | 3 | Dilation that connects thin strokes |
| `min_component_area` | 80 | Smaller (dilated) specks are ignored |
| `content_gate` | `True` | Turn the text/graphic/picture check off to process every image geometrically |
| `text_min_coverage` | 0.5 | Share of strokes that must sit in text lines |
| `graphic_min_background_flatness` | 0.95 | Share of border background pixels that must be exactly flat |
| `max_analysis_pixels` | 6,000,000 | Larger images are analyzed downscaled |
| `max_input_pixels` / `max_output_pixels` | 100,000,000 | Hard limits; above them the image is left unchanged |
| `watch_interval_seconds` / `watch_debounce_seconds` | 0.25 / 0.45 | Clipboard polling interval and the wait after a change |

## Known limitations

- Detection is heuristic. Very large headline text (glyphs taller than about 60 px at analysis size) does not count as text; a screenshot of only such a headline is handled as a graphic, or left unchanged if it touches the edges. Sparse tables with only a few characters per cell can also end up as graphics: they are still cropped, just without the edge gutter.
- Every clipboard image is a candidate, including pictures that apps copy alongside text or table data. The processed image may replace that copy.
- Transparency is flattened onto white; color profiles and DPI metadata are not preserved.

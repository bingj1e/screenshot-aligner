# Reliability review — 2026-09-16

Reviewed the current working tree, preserving pre-existing uncommitted changes.

## Fixed findings

1. **High: clipboard overwrite race.** A copy made during image analysis could be overwritten by the older screenshot. The writer now compares the original clipboard sequence while holding the Windows clipboard lock, before emptying it.
2. **High: watcher silently skips new copies.** Sampling the latest sequence after processing could acknowledge somebody else's new copy. Processing now returns its exact consumed/written sequence, and both watch modes retain that value. A busy processing lock does not acknowledge a pending copy.
3. **High: expensive work in the keyboard hook callback.** Alignment and clipboard retries previously ran synchronously in the pynput callback. Work is now dispatched to a worker after acquiring a nonblocking processing lock, preventing both hook blocking and an unbounded queue of requests.
4. **Medium: resource guards applied too late.** Oversized images were copied/converted before the input guard; expanded canvases had no output guard; very thin analysis images could exceed their pixel budget. Limits now apply before these allocations.
5. **Medium: logging errors escape the recovery path.** An unwritable log or failed rotation could raise again while reporting a processing failure and terminate background work. Logging I/O failures are now contained.
6. **Medium: tray debounce ignores pause/quit.** A pending debounce could proceed after pause or quit. Both states are now checked before processing, and watcher shutdown is in a finally block. An operation already processing is allowed to finish during shutdown.
7. **Medium: inconsistent transparency handling.** Clipboard reads discarded alpha, and palette/grayscale-alpha images were not composited consistently. Alpha is retained until alignment and flattened onto white.

## Validation and limits

- Baseline: 31 tests passed before this review's changes.
- Added deterministic regression cases for concurrent clipboard changes, version accounting, log failures, resource caps, extreme aspect ratios, invalid input, and transparency.
- Final suite: **52 passed**; Python compilation and `git diff --check` passed (Git only reported line-ending conversion warnings).
- Windows mutex tests use the real OS. Clipboard race tests use a simulated OS clipboard to control the timing without replacing the user's clipboard.
- The actual Windows clipboard API also rejected an intentionally stale sequence before modifying the clipboard.
- Built `dist/hardened/ScreenshotAligner.exe` separately, retaining the existing EXE. The new executable processed both crop and pad fixtures successfully, with output pixels identical to the source implementation. Fixtures/results are in `build/hardening-smoke/`.
- Crop detection is heuristic: subtle content, punctuation, and unusual layouts can still be misidentified. Passing these tests does not establish that arbitrary screenshots can be cropped without losing content.
- No claim of real QQ/WeChat hotkey-and-paste acceptance. Existing releases and already-running processes do not acquire these fixes automatically.

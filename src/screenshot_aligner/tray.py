"""System tray mode: a resident background app with a small menu.

Runs the clipboard watcher in a worker thread and shows a tray icon with
pause/resume, process-now, open-log, and quit actions.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw

from .clipboard import ClipboardError, get_clipboard_sequence_number
from .config import AlignmentConfig

APP_NAME = "Screenshot Aligner"


def run_tray(config: AlignmentConfig, output, log_file: Path | None = None) -> int:
    try:
        import pystray
    except ImportError as exc:
        output.error(
            f"Could not import pystray: {exc}. Install it with: pip install pystray"
        )
        return 1

    single_instance_mutex = _acquire_single_instance_lock()
    if single_instance_mutex is None:
        output.info("Screenshot Aligner is already running; this instance will exit.")
        return 0

    from .cli import process_clipboard_once

    watching = threading.Event()
    watching.set()
    stop = threading.Event()

    def watch_loop() -> None:
        try:
            last_sequence = get_clipboard_sequence_number()
        except ClipboardError as exc:
            output.error(f"Could not watch clipboard: {exc}")
            return
        while not stop.wait(config.watch_interval_seconds):
            if not watching.is_set():
                continue
            try:
                current_sequence = get_clipboard_sequence_number()
                if current_sequence == last_sequence:
                    continue
                stop.wait(config.watch_debounce_seconds)
                process_clipboard_once(config, output)
                last_sequence = get_clipboard_sequence_number()
            except ClipboardError as exc:
                output.error(f"Clipboard error: {exc}")

    def on_toggle(icon, item) -> None:
        if watching.is_set():
            watching.clear()
            output.info("Paused clipboard watching.")
        else:
            watching.set()
            output.info("Resumed clipboard watching.")

    def on_process_now(icon, item) -> None:
        process_clipboard_once(config, output)

    def on_open_log(icon, item) -> None:
        if log_file is not None and log_file.exists():
            os.startfile(log_file)  # noqa: S606 - local file chosen by the user

    def on_quit(icon, item) -> None:
        stop.set()
        icon.stop()

    menu_items = [
        pystray.MenuItem(
            "Watch clipboard",
            on_toggle,
            checked=lambda item: watching.is_set(),
        ),
        pystray.MenuItem("Process clipboard now", on_process_now),
    ]
    if log_file is not None:
        menu_items.append(pystray.MenuItem("Open log file", on_open_log))
    menu_items.append(pystray.Menu.SEPARATOR)
    menu_items.append(pystray.MenuItem("Quit", on_quit))

    icon = pystray.Icon(
        name="screenshot-aligner",
        title=APP_NAME,
        icon=build_icon_image(),
        menu=pystray.Menu(*menu_items),
    )

    worker = threading.Thread(target=watch_loop, name="clipboard-watch", daemon=True)
    worker.start()
    output.info(f"{APP_NAME} is running in the system tray.")

    icon.run()
    stop.set()
    output.info("Stopped.")
    return 0


def _acquire_single_instance_lock():
    """Hold a session-wide mutex so double-clicking the exe twice is harmless.

    Returns the mutex handle to keep alive for the process lifetime, or None
    when another instance already owns it. On non-Windows platforms the lock
    is skipped (returns a placeholder truthy object).
    """
    if sys.platform != "win32":
        return object()

    import win32api
    import win32event
    import winerror

    handle = win32event.CreateMutex(None, False, "Local\\ScreenshotAlignerTray")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return None
    return handle


def build_icon_image(size: int = 64) -> Image.Image:
    """Draw the app icon: a tidy screenshot card on a blue gradient tile.

    Drawn at 256 px and downscaled, so edges stay smooth at small sizes.
    """
    base = 256
    image = Image.new("RGBA", (base, base), (0, 0, 0, 0))

    # Rounded-square tile filled with a vertical indigo-to-sky gradient.
    gradient = Image.new("RGBA", (base, base))
    gradient_draw = ImageDraw.Draw(gradient)
    top_color = (79, 70, 229)
    bottom_color = (14, 165, 233)
    for y in range(base):
        t = y / (base - 1)
        color = tuple(
            round(top_color[i] + (bottom_color[i] - top_color[i]) * t)
            for i in range(3)
        )
        gradient_draw.line([(0, y), (base, y)], fill=color + (255,))
    tile_mask = Image.new("L", (base, base), 0)
    ImageDraw.Draw(tile_mask).rounded_rectangle(
        (8, 8, base - 9, base - 9), radius=58, fill=255
    )
    image.paste(gradient, (0, 0), tile_mask)

    draw = ImageDraw.Draw(image)

    # Crop marks hugging the card corners: the "alignment" idea.
    mark = 26
    stroke = 12
    for cx, cy, dx, dy in (
        (52, 56, 1, 1),
        (204, 56, -1, 1),
        (52, 200, 1, -1),
        (204, 200, -1, -1),
    ):
        draw.line([(cx, cy), (cx + dx * mark, cy)], fill=(255, 255, 255, 230), width=stroke)
        draw.line([(cx, cy), (cx, cy + dy * mark)], fill=(255, 255, 255, 230), width=stroke)

    # White screenshot card with a soft drop shadow.
    card = (76, 84, 180, 172)
    draw.rounded_rectangle(
        (card[0] + 7, card[1] + 9, card[2] + 7, card[3] + 9),
        radius=18,
        fill=(15, 23, 90, 80),
    )
    draw.rounded_rectangle(card, radius=18, fill=(255, 255, 255, 255))

    # Text lines on the card: one heading and two body lines.
    line_left = card[0] + 16
    line_right = card[2] - 16
    full = line_right - line_left
    for y0, frac, color in (
        (card[1] + 18, 0.62, (51, 65, 85, 255)),
        (card[1] + 42, 1.0, (148, 163, 184, 255)),
        (card[1] + 62, 0.78, (148, 163, 184, 255)),
    ):
        draw.rounded_rectangle(
            (line_left, y0, line_left + full * frac, y0 + 11),
            radius=5,
            fill=color,
        )

    if size != base:
        image = image.resize((size, size), Image.LANCZOS)
    return image

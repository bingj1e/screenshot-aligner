"""System tray mode: a resident background app with a small menu.

Runs the clipboard watcher in a worker thread and shows a tray icon with
pause/resume, process-now, open-log, and quit actions.
"""

from __future__ import annotations

import os
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


def build_icon_image(size: int = 64) -> Image.Image:
    """Draw the tray icon: a centered content block inside a framed canvas."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 16
    draw.rounded_rectangle(
        (margin, margin, size - margin - 1, size - margin - 1),
        radius=size // 8,
        fill=(36, 99, 235, 255),
    )
    inner = size * 5 // 16
    draw.rectangle(
        (inner, inner, size - inner - 1, size - inner - 1),
        fill=(255, 255, 255, 255),
    )
    return image

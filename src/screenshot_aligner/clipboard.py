from __future__ import annotations

import io
import sys
import time
from contextlib import contextmanager

from PIL import Image, ImageGrab


class ClipboardError(RuntimeError):
    pass


def read_clipboard_image() -> Image.Image:
    data = ImageGrab.grabclipboard()
    if isinstance(data, Image.Image):
        return data.convert("RGB")
    raise ClipboardError("Clipboard does not contain an image.")


def write_clipboard_image(image: Image.Image) -> None:
    if sys.platform != "win32":
        raise ClipboardError("Writing images to the clipboard is only supported on Windows.")

    import win32clipboard

    rgb_image = image.convert("RGB")
    with io.BytesIO() as buffer:
        rgb_image.save(buffer, "BMP")
        dib = buffer.getvalue()[14:]

    with _open_clipboard(win32clipboard):
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)


def get_clipboard_sequence_number() -> int:
    if sys.platform != "win32":
        raise ClipboardError("Clipboard watching is only supported on Windows.")

    import win32clipboard

    return int(win32clipboard.GetClipboardSequenceNumber())


@contextmanager
def _open_clipboard(win32clipboard):
    last_error: Exception | None = None
    for _ in range(5):
        try:
            win32clipboard.OpenClipboard()
            break
        except Exception as exc:  # pywin32 raises different concrete errors by version.
            last_error = exc
            time.sleep(0.05)
    else:
        raise ClipboardError(f"Could not open clipboard: {last_error}")

    try:
        yield
    finally:
        win32clipboard.CloseClipboard()

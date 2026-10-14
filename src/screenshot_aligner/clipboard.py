from __future__ import annotations

import io
import sys
import time
from contextlib import contextmanager

from PIL import Image, ImageGrab


class ClipboardError(RuntimeError):
    pass


def read_clipboard_image() -> Image.Image:
    last_error: Exception | None = None
    for _ in range(5):
        try:
            data = ImageGrab.grabclipboard()
        except Exception as exc:
            last_error = exc
            time.sleep(0.05)
            continue

        if isinstance(data, Image.Image):
            # Preserve alpha until align_image composites it onto white.
            return data
        raise ClipboardError("Clipboard does not contain an image.")

    raise ClipboardError(f"Could not read clipboard: {last_error}")


def write_clipboard_image(
    image: Image.Image, *, expected_sequence: int | None = None
) -> int:
    if sys.platform != "win32":
        raise ClipboardError("Writing images to the clipboard is only supported on Windows.")

    import win32clipboard

    rgb_image = image.convert("RGB")
    with io.BytesIO() as buffer:
        rgb_image.save(buffer, "BMP")
        dib = buffer.getvalue()[14:]

    with _open_clipboard(win32clipboard):
        # Check while holding the OS clipboard lock, not before OpenClipboard:
        # another application may have copied something during image analysis.
        if (
            expected_sequence is not None
            and win32clipboard.GetClipboardSequenceNumber() != expected_sequence
        ):
            raise ClipboardError("Clipboard changed during processing; result discarded.")
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
        return int(win32clipboard.GetClipboardSequenceNumber())


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

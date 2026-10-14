from __future__ import annotations

from PIL import Image

from screenshot_aligner import clipboard


def test_clipboard_read_retries_temporary_errors(monkeypatch) -> None:
    attempts = 0
    expected = Image.new("RGB", (20, 10), "white")

    def grabclipboard():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("clipboard is temporarily busy")
        return expected

    monkeypatch.setattr(clipboard.ImageGrab, "grabclipboard", grabclipboard)
    monkeypatch.setattr(clipboard.time, "sleep", lambda _: None)

    result = clipboard.read_clipboard_image()

    assert attempts == 3
    assert result.size == expected.size

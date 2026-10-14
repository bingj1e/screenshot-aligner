from __future__ import annotations

import sys
import uuid

import pytest

from screenshot_aligner import cli
from screenshot_aligner.runtime import acquire_single_instance_lock


class RecordingOutput:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def info(self, message: str) -> None:
        self.messages.append(message)

    def error(self, message: str) -> None:
        self.messages.append(message)


def test_processing_lock_is_released_after_unexpected_error(monkeypatch) -> None:
    calls = 0
    output = RecordingOutput()

    def fail(config, target_output) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(cli, "process_clipboard_once", fail)

    cli.process_clipboard_safely(cli.AlignmentConfig(), output)
    cli.process_clipboard_safely(cli.AlignmentConfig(), output)

    assert calls == 2
    assert all("Already processing" not in message for message in output.messages)


def test_output_rotates_large_log(tmp_path) -> None:
    log_file = tmp_path / "screenshot-aligner.log"
    output = cli.Output(quiet=True, log_file=log_file)
    output._max_log_bytes = 20

    output.info("first message that crosses the limit")
    output.info("second message")

    assert log_file.exists()
    assert log_file.with_suffix(".log.1").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")
def test_single_instance_mutex_rejects_second_owner() -> None:
    import win32api

    name = f"Local\\ScreenshotAlignerTest-{uuid.uuid4()}"
    first = acquire_single_instance_lock(name)
    try:
        second = acquire_single_instance_lock(name)
        assert first is not None
        assert second is None
    finally:
        if first is not None:
            win32api.CloseHandle(first)

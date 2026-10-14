from types import SimpleNamespace
import sys

import pytest
from PIL import Image, ImageDraw

from screenshot_aligner import align_image, AlignmentConfig
from screenshot_aligner import cli, clipboard
from screenshot_aligner.align import make_analysis_image


def test_write_checks_version_under_os_lock(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        CF_DIB=8,
        OpenClipboard=lambda: calls.append("open"),
        CloseClipboard=lambda: calls.append("close"),
        GetClipboardSequenceNumber=lambda: 42,
        EmptyClipboard=lambda: calls.append("empty"),
        SetClipboardData=lambda *args: calls.append("write"),
    )
    monkeypatch.setitem(sys.modules, "win32clipboard", fake)
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    with pytest.raises(clipboard.ClipboardError, match="changed"):
        clipboard.write_clipboard_image(Image.new("RGB", (2, 2)), expected_sequence=41)
    assert calls == ["open", "close"]


def test_write_returns_own_version_before_releasing_os_lock(monkeypatch):
    state = {"version": 42, "open": False}

    def open_clipboard():
        state["open"] = True

    def close_clipboard():
        state.update(open=False, version=44)  # another app immediately copies

    def write(*args):
        state["version"] = 43

    def sequence():
        assert state["open"]
        return state["version"]

    fake = SimpleNamespace(CF_DIB=8, OpenClipboard=open_clipboard,
        CloseClipboard=close_clipboard, GetClipboardSequenceNumber=sequence,
        EmptyClipboard=lambda: None, SetClipboardData=write)
    monkeypatch.setitem(sys.modules, "win32clipboard", fake)
    monkeypatch.setattr(clipboard.sys, "platform", "win32")
    assert clipboard.write_clipboard_image(
        Image.new("RGB", (2, 2)), expected_sequence=42
    ) == 43
    assert state["version"] == 44


def test_copy_during_read_does_not_process_stale_image(monkeypatch):
    versions = iter([10, 11])
    monkeypatch.setattr(cli, "get_clipboard_sequence_number", lambda: next(versions))
    monkeypatch.setattr(cli, "read_clipboard_image", lambda: Image.new("RGB", (10, 10)))
    monkeypatch.setattr(cli, "align_image", lambda *args: pytest.fail("stale image processed"))
    assert cli.process_clipboard_once(AlignmentConfig(), cli.Output(quiet=True)) == 10


def test_copy_during_analysis_passes_original_version_to_writer(monkeypatch):
    state = {"version": 10}
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((60, 30, 100, 60), fill="black")
    monkeypatch.setattr(cli, "get_clipboard_sequence_number", lambda: state["version"])
    monkeypatch.setattr(cli, "read_clipboard_image", lambda: image)

    def analyze(*args):
        state["version"] = 11
        return align_image(*args)

    def write(image, *, expected_sequence):
        assert expected_sequence == 10
        assert state["version"] == 11
        raise clipboard.ClipboardError("changed")

    monkeypatch.setattr(cli, "align_image", analyze)
    monkeypatch.setattr(cli, "write_clipboard_image", write)
    assert cli.process_clipboard_once(AlignmentConfig(), cli.Output(quiet=True)) == 10


def test_watcher_does_not_swallow_copy_after_processing(monkeypatch):
    versions = iter([1, 2, 4])
    processed = iter([3, 5])
    calls = []
    sleeps = 0

    def sleep(_):
        nonlocal sleeps
        sleeps += 1
        if sleeps == 5:
            raise KeyboardInterrupt

    def process(*args):
        calls.append(True)
        return next(processed)

    monkeypatch.setattr(cli, "acquire_single_instance_lock", lambda: object())
    monkeypatch.setattr(cli, "get_clipboard_sequence_number", lambda: next(versions))
    monkeypatch.setattr(cli.time, "sleep", sleep)
    monkeypatch.setattr(cli, "process_clipboard_safely", process)
    assert cli.watch_clipboard(AlignmentConfig(), cli.Output(quiet=True)) == 0
    assert len(calls) == 2


def test_hotkey_callback_returns_while_processing_is_blocked(monkeypatch):
    import threading
    from screenshot_aligner.runtime import PROCESSING_LOCK

    entered = threading.Event()
    finish = threading.Event()
    finished = threading.Event()
    calls = []

    def process(*args):
        calls.append(threading.get_ident())
        entered.set()
        try:
            assert finish.wait(3)
        finally:
            finished.set()

    class Listener:
        def __init__(self, callbacks):
            self.callback = next(iter(callbacks.values()))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def join(self):
            try:
                self.callback()
                assert entered.wait(1)
                assert not finished.is_set()
                self.callback()  # ignored while first operation owns the lock
                assert len(calls) == 1
                assert calls[0] != threading.get_ident()
            finally:
                finish.set()
                assert finished.wait(2)
                # Wait for the worker's finally block to release the lock.
                assert PROCESSING_LOCK.acquire(timeout=2)
                PROCESSING_LOCK.release()

    monkeypatch.setitem(sys.modules, "pynput", SimpleNamespace(
        keyboard=SimpleNamespace(GlobalHotKeys=Listener)))
    monkeypatch.setattr(cli, "acquire_single_instance_lock", lambda: object())
    monkeypatch.setattr(cli, "process_clipboard_once", process)
    assert cli.run_listener(AlignmentConfig(), cli.Output(quiet=True)) == 0


def test_unwritable_log_does_not_break_processing_lock(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    output = cli.Output(quiet=True, log_file=blocker / "log")
    monkeypatch.setattr(cli, "process_clipboard_once", lambda *args: 9)
    output.error("test")
    assert cli.process_clipboard_safely(AlignmentConfig(), output) == 9
    assert cli.process_clipboard_safely(AlignmentConfig(), output) == 9


def test_oversize_image_is_not_copied_or_converted(monkeypatch):
    image = Image.new("RGBA", (20, 20))
    monkeypatch.setattr(image, "convert", lambda *a: pytest.fail("converted oversize image"))
    monkeypatch.setattr(image, "copy", lambda: pytest.fail("copied oversize image"))
    result = align_image(image, AlignmentConfig(max_input_pixels=10))
    assert result.image is image
    assert not result.changed


@pytest.mark.parametrize("mode", ["crop", "pad"])
def test_output_canvas_limit(mode):
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((60, 30, 100, 60), fill="black")
    result = align_image(
        image, AlignmentConfig(mode=mode, max_output_pixels=100, content_gate=False)
    )
    assert not result.changed
    assert "output pixel limit" in result.note
    assert result.image.tobytes() == image.tobytes()


@pytest.mark.parametrize("size", [(10000, 1), (1, 10000), (101, 99)])
def test_analysis_budget_handles_extreme_aspect_ratios(size):
    analysis, _, _ = make_analysis_image(
        Image.new("RGB", size), AlignmentConfig(max_analysis_pixels=100)
    )
    assert analysis.width * analysis.height <= 100


@pytest.mark.parametrize("mode", ["RGBA", "LA", "P"])
def test_transparent_background_is_composited_to_white(mode):
    image = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    if mode == "P":
        image = image.convert("P")
        image.info["transparency"] = 0
    else:
        image = image.convert(mode)
    result = align_image(image)
    assert result.image.getpixel((0, 0)) == (255, 255, 255)


def test_empty_image_has_clear_error():
    with pytest.raises(ValueError, match="dimensions"):
        align_image(Image.new("RGB", (0, 10)))


@pytest.mark.parametrize("kwargs", [{"mode": "invalid"}, {"max_analysis_pixels": 0},
    {"min_padding": -1}, {"max_output_pixels": 0}])
def test_invalid_config_fails_early(kwargs):
    with pytest.raises(ValueError):
        AlignmentConfig(**kwargs)

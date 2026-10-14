from __future__ import annotations

import argparse
from datetime import datetime
import sys
import threading
import time
from pathlib import Path

from PIL import Image

from .align import align_image
from .clipboard import (
    ClipboardError,
    get_clipboard_sequence_number,
    read_clipboard_image,
    write_clipboard_image,
)
from .config import HOTKEY, HOTKEY_LABEL, AlignmentConfig, AlignmentMode
from .runtime import (
    acquire_processing_lock,
    acquire_single_instance_lock,
    release_processing_lock,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AlignmentConfig(mode=args.mode) if hasattr(args, "mode") else AlignmentConfig()
    output = Output(quiet=getattr(args, "quiet", False), log_file=getattr(args, "log_file", None))

    if args.command == "run":
        return run_listener(config, output)
    if args.command == "once":
        instance_lock = acquire_single_instance_lock()
        if instance_lock is None:
            output.info(
                "Screenshot Aligner is already running; use the tray menu to process now."
            )
            return 0
        process_clipboard_safely(config, output)
        return 0
    if args.command == "watch":
        return watch_clipboard(config, output)
    if args.command == "tray":
        from .tray import run_tray

        return run_tray(config, output, log_file=getattr(args, "log_file", None))
    if args.command == "process-file":
        return process_file(args.input, args.output, config, output)
    if args.command == "debug-file":
        return debug_file(args.input, config, output)

    parser.print_help()
    return 2


def add_mode_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=["crop", "pad"],
        default="crop",
        help="crop keeps only the detected main content; pad preserves the original image and extends canvas.",
    )


def add_background_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress terminal output. Useful for hidden background startup.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Append status and errors to this log file.",
    )


def typed_mode(value: str) -> AlignmentMode:
    if value not in {"crop", "pad"}:
        raise argparse.ArgumentTypeError("mode must be crop or pad")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="screenshot-aligner",
        description="Clean up screenshot content by cropping or padding around the main foreground.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help=f"Listen for {HOTKEY_LABEL} and process the clipboard image.",
    )
    add_mode_argument(run_parser)
    add_background_arguments(run_parser)

    once_parser = subparsers.add_parser(
        "once",
        help="Process the current clipboard image once without listening for a hotkey.",
    )
    add_mode_argument(once_parser)
    add_background_arguments(once_parser)

    watch_parser = subparsers.add_parser(
        "watch",
        help="Automatically process new clipboard images after any screenshot tool copies one.",
    )
    add_mode_argument(watch_parser)
    add_background_arguments(watch_parser)

    tray_parser = subparsers.add_parser(
        "tray",
        help="Run the clipboard watcher as a system tray app with pause/resume and quit.",
    )
    add_mode_argument(tray_parser)
    add_background_arguments(tray_parser)

    file_parser = subparsers.add_parser(
        "process-file",
        help="Process an image file and save the aligned output.",
    )
    add_mode_argument(file_parser)
    file_parser.add_argument("input", type=Path)
    file_parser.add_argument("output", type=Path)

    debug_parser = subparsers.add_parser(
        "debug-file",
        help="Print foreground bounds and gap measurements for an image file.",
    )
    add_mode_argument(debug_parser)
    debug_parser.add_argument("input", type=Path)

    return parser


def process_file(
    input_path: Path, output_path: Path, config: AlignmentConfig, output: "Output"
) -> int:
    try:
        with Image.open(input_path) as source:
            image = source.copy()
    except OSError as exc:
        output.error(f"Could not open input image: {exc}")
        return 1

    result = align_image(image, config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.image.save(output_path)

    print_result("Processed image", result, config, output)
    return 0


def debug_file(input_path: Path, config: AlignmentConfig, output: "Output") -> int:
    try:
        with Image.open(input_path) as source:
            image = source.copy()
    except OSError as exc:
        output.error(f"Could not open input image: {exc}")
        return 1

    result = align_image(image, config)
    print_result("Debug image", result, config, output)
    if result.content is not None:
        content = result.content
        output.info(
            f"Content: {content.kind} (text segments={content.text_lines}, "
            f"text coverage={content.text_coverage:.2f}, "
            f"background flatness={content.background_flatness:.2f}, "
            f"background confidence={content.background_confidence:.2f}, "
            f"edges touched={content.edges_touched})"
        )
    if result.bbox is not None:
        width, height = image.size
        output.info(
            "Original gaps: "
            f"left={result.bbox.left}, right={width - result.bbox.right - 1}, "
            f"top={result.bbox.top}, bottom={height - result.bbox.bottom - 1}"
        )
        output.info(
            "Foreground bbox: "
            f"left={result.bbox.left}, top={result.bbox.top}, "
            f"right={result.bbox.right}, bottom={result.bbox.bottom}, "
            f"width={result.bbox.width}, height={result.bbox.height}"
        )
    output.info(f"Output size: {result.image.width}x{result.image.height}")
    return 0


def run_listener(config: AlignmentConfig, output: "Output") -> int:
    try:
        from pynput import keyboard
    except ImportError as exc:
        output.error(f"Could not import pynput: {exc}")
        return 1

    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        output.info("Screenshot Aligner is already running; this instance will exit.")
        return 0

    output.info(f"Screenshot Aligner is running. Press {HOTKEY_LABEL} to process the clipboard.")
    output.info("Press Ctrl+C in this terminal to stop.")

    def on_activate() -> None:
        # pynput invokes callbacks on the Windows input hook thread. Never
        # perform OpenCV work there: a slow callback can disable the hook.
        if not acquire_processing_lock():
            return
        worker = threading.Thread(
            target=_process_with_lock, args=(config, output), daemon=True
        )
        try:
            worker.start()
        except Exception:
            release_processing_lock()
            raise

    with keyboard.GlobalHotKeys({HOTKEY: on_activate}) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            output.info("Stopped.")
            return 0
    return 0


def watch_clipboard(config: AlignmentConfig, output: "Output") -> int:
    instance_lock = acquire_single_instance_lock()
    if instance_lock is None:
        output.info("Screenshot Aligner is already running; this instance will exit.")
        return 0

    try:
        last_sequence = get_clipboard_sequence_number()
    except ClipboardError as exc:
        output.error(f"Could not watch clipboard: {exc}")
        return 1

    output.info("Watching clipboard for new screenshot images.")
    output.info("Press Ctrl+C in this terminal to stop.")

    try:
        while True:
            time.sleep(config.watch_interval_seconds)
            try:
                current_sequence = get_clipboard_sequence_number()
                if current_sequence == last_sequence:
                    continue

                time.sleep(config.watch_debounce_seconds)
                processed = process_clipboard_safely(config, output)
                if processed is not None:
                    last_sequence = processed
            except Exception as exc:
                output.error(
                    f"Watcher recovered from an error: {type(exc).__name__}: {exc}"
                )
    except KeyboardInterrupt:
        output.info("Stopped.")
        return 0


def process_clipboard_once(config: AlignmentConfig, output: "Output") -> int:
    sequence = get_clipboard_sequence_number()
    try:
        image = read_clipboard_image()
    except ClipboardError as exc:
        output.info(f"Skipped: {exc}")
        return sequence

    if get_clipboard_sequence_number() != sequence:
        output.info("Clipboard changed while reading; result discarded.")
        return sequence

    result = align_image(image, config)

    if not result.foreground_found:
        output.info("No foreground detected; clipboard image left unchanged.")
        return sequence

    if not result.changed:
        output.info(result.note or "Clipboard image already appears centered.")
        return sequence

    try:
        written_sequence = write_clipboard_image(result.image, expected_sequence=sequence)
    except ClipboardError as exc:
        output.error(f"Could not write clipboard image: {exc}")
        return sequence

    print_result("Processed clipboard image", result, config, output)
    return written_sequence


def process_clipboard_safely(config: AlignmentConfig, output: "Output") -> int | None:
    if not acquire_processing_lock():
        output.info("Already processing a screenshot; ignoring repeated request.")
        return

    return _process_with_lock(config, output)


def _process_with_lock(config: AlignmentConfig, output: "Output") -> int | None:
    try:
        return process_clipboard_once(config, output)
    except Exception as exc:
        output.error(
            f"Screenshot processing failed: {type(exc).__name__}: {exc}"
        )
    finally:
        release_processing_lock()


def print_result(label: str, result, config: AlignmentConfig, output: "Output") -> None:
    if not result.foreground_found:
        output.info(f"{label}: no foreground detected.")
    elif result.changed:
        if config.mode == "crop":
            pad_x = (result.image.width - result.bbox.width) // 2
            pad_y = (result.image.height - result.bbox.height) // 2
            padding = f"{pad_x}px" if pad_x == pad_y else f"{pad_x}x{pad_y}px"
            output.info(
                f"{label}: cropped to main content with "
                f"{padding} padding, output={result.image.width}x{result.image.height}"
            )
            return
        output.info(
            f"{label}: padded to centered content, "
            f"added left={result.added_left}, right={result.added_right}, "
            f"top={result.added_top}, bottom={result.added_bottom}, "
            f"output={result.image.width}x{result.image.height}"
        )
    elif result.note:
        output.info(f"{label}: {result.note}")
    else:
        output.info(f"{label}: already appears aligned.")


class Output:
    def __init__(self, quiet: bool = False, log_file: Path | None = None) -> None:
        self.quiet = quiet
        self.log_file = log_file
        self._lock = threading.Lock()
        self._max_log_bytes = 5_000_000

    def info(self, message: str) -> None:
        self._write(message, error=False)

    def error(self, message: str) -> None:
        self._write(message, error=True)

    def _write(self, message: str, error: bool) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
        if not self.quiet:
            stream = sys.stderr if error else sys.stdout
            if stream is not None:
                try:
                    print(message, file=stream)
                except (OSError, ValueError):
                    pass
        if self.log_file is not None:
            try:
                with self._lock:
                    self.log_file.parent.mkdir(parents=True, exist_ok=True)
                    if (
                        self.log_file.exists()
                        and self.log_file.stat().st_size >= self._max_log_bytes
                    ):
                        rotated = self.log_file.with_suffix(self.log_file.suffix + ".1")
                        rotated.unlink(missing_ok=True)
                        self.log_file.replace(rotated)
                    with self.log_file.open("a", encoding="utf-8") as file:
                        file.write(line + "\n")
            except OSError:
                # Logging failures must not kill the watcher or prevent the
                # processing lock from being released in an exception handler.
                pass


if __name__ == "__main__":
    raise SystemExit(main())

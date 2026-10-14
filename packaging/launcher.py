"""PyInstaller entry point.

Double-clicking the exe starts tray mode with logging enabled; running it
from a terminal with arguments behaves exactly like the screenshot-aligner
command.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from screenshot_aligner.cli import main


def default_args() -> list[str]:
    app_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ScreenshotAligner"
    return ["tray", "--quiet", "--log-file", str(app_dir / "screenshot-aligner.log")]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or default_args()))

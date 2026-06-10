from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


HOTKEY = "<ctrl>+<alt>+x"
HOTKEY_LABEL = "Ctrl+Alt+X"
DEFAULT_MODE = "crop"
AlignmentMode = Literal["crop", "pad"]


@dataclass(frozen=True)
class AlignmentConfig:
    mode: AlignmentMode = DEFAULT_MODE
    min_padding: int = 24
    max_padding: int = 128
    padding_ratio: float = 0.06
    mask_threshold: int = 24
    dilate_px: int = 3
    edge_sample_px: int = 8
    min_component_area: int = 80
    max_foreground_ratio: float = 0.95
    watch_interval_seconds: float = 0.25
    watch_debounce_seconds: float = 0.45

    def padding_for(self, content_width: int, content_height: int) -> int:
        """Padding that scales with content size, clamped to a sane range."""
        scaled = round(max(content_width, content_height) * self.padding_ratio)
        return max(self.min_padding, min(self.max_padding, scaled))

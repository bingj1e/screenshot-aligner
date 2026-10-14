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
    # 24 / golden ratio ~= 15, aligned to the 4px design grid.
    edge_safety_padding: int = 16
    mask_threshold: int = 24
    container_threshold: int = 8
    container_reach_ratio: float = 0.5
    dilate_px: int = 3
    edge_sample_px: int = 8
    min_component_area: int = 80
    max_foreground_ratio: float = 0.95
    max_container_ratio: float = 0.995
    min_background_bucket_ratio: float = 0.12
    min_corner_background_ratio: float = 0.75
    max_corner_background_spread: float = 12.0
    max_analysis_pixels: int = 6_000_000
    max_input_pixels: int = 100_000_000
    max_output_pixels: int = 100_000_000
    border_touch_px: int = 4
    border_line_max_thickness: int = 12
    border_line_min_span_ratio: float = 0.6
    border_frame_max_density: float = 0.08
    border_frame_max_interior_ratio: float = 0.05
    watch_interval_seconds: float = 0.25
    watch_debounce_seconds: float = 0.45
    # Content gate: classify the screenshot as text, graphic or picture before
    # touching it. Text is aligned as usual, graphics on a clean canvas are
    # only cropped (never given an invented border), pictures are left alone.
    content_gate: bool = True
    text_stroke_kernel_px: int = 15
    text_stroke_threshold: int = 40
    text_min_glyph_height: int = 5
    text_max_glyph_height: int = 60
    text_min_glyphs_per_line: int = 4
    text_min_lines: int = 1
    text_min_coverage: float = 0.5
    background_flat_tolerance: int = 2
    graphic_min_background_flatness: float = 0.95
    graphic_min_background_confidence: float = 0.75

    def __post_init__(self) -> None:
        if self.mode not in ("crop", "pad"):
            raise ValueError(f"Unsupported alignment mode: {self.mode}")
        for name in ("max_analysis_pixels", "max_input_pixels", "max_output_pixels"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        if not 0 <= self.min_padding <= self.max_padding:
            raise ValueError("padding must satisfy 0 <= min_padding <= max_padding")
        if self.edge_safety_padding < 0 or self.padding_ratio < 0:
            raise ValueError("padding must be nonnegative")

    def padding_for(self, content_width: int, content_height: int) -> int:
        """Padding that scales with content size, clamped to a sane range."""
        scaled = round(max(content_width, content_height) * self.padding_ratio)
        return max(self.min_padding, min(self.max_padding, scaled))

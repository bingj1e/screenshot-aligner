from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .config import AlignmentConfig


@dataclass(frozen=True)
class BoundingBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1


@dataclass(frozen=True)
class AlignmentResult:
    image: Image.Image
    changed: bool
    foreground_found: bool
    bbox: BoundingBox | None
    background_color: tuple[int, int, int]
    added_left: int = 0
    added_top: int = 0
    added_right: int = 0
    added_bottom: int = 0
    note: str | None = None


def align_image(
    image: Image.Image, config: AlignmentConfig | None = None
) -> AlignmentResult:
    """Return a new image with foreground made easier to read."""
    cfg = config or AlignmentConfig()
    rgb_image = _to_rgb(image)
    arr = np.asarray(rgb_image, dtype=np.uint8)
    background_color = estimate_background_color(arr, cfg.edge_sample_px)
    mask = build_foreground_mask(arr, background_color, cfg)
    bbox = bbox_from_mask(mask, cfg)

    if bbox is None:
        return AlignmentResult(
            image=rgb_image.copy(),
            changed=False,
            foreground_found=False,
            bbox=None,
            background_color=background_color,
        )

    foreground_ratio = float(np.count_nonzero(mask)) / mask.size
    if foreground_ratio > cfg.max_foreground_ratio:
        return AlignmentResult(
            image=rgb_image.copy(),
            changed=False,
            foreground_found=True,
            bbox=bbox,
            background_color=background_color,
            note=(
                "Foreground covers almost the whole image; background estimate "
                "is unreliable, so the image was left unchanged."
            ),
        )

    if cfg.mode == "crop":
        return _crop_to_foreground(rgb_image, bbox, background_color, cfg)
    if cfg.mode == "pad":
        return _pad_to_center(rgb_image, bbox, background_color, cfg)
    raise ValueError(f"Unsupported alignment mode: {cfg.mode}")


def _crop_to_foreground(
    rgb_image: Image.Image,
    bbox: BoundingBox,
    background_color: tuple[int, int, int],
    cfg: AlignmentConfig,
) -> AlignmentResult:
    padding = cfg.padding_for(bbox.width, bbox.height)
    crop = rgb_image.crop((bbox.left, bbox.top, bbox.right + 1, bbox.bottom + 1))
    output = Image.new(
        "RGB",
        (bbox.width + padding * 2, bbox.height + padding * 2),
        background_color,
    )
    output.paste(crop, (padding, padding))

    changed = output.size != rgb_image.size or output.tobytes() != rgb_image.tobytes()
    return AlignmentResult(
        image=output,
        changed=changed,
        foreground_found=True,
        bbox=bbox,
        background_color=background_color,
        added_left=padding - bbox.left,
        added_top=padding - bbox.top,
        added_right=padding - (rgb_image.width - bbox.right - 1),
        added_bottom=padding - (rgb_image.height - bbox.bottom - 1),
    )


def _pad_to_center(
    rgb_image: Image.Image,
    bbox: BoundingBox,
    background_color: tuple[int, int, int],
    cfg: AlignmentConfig,
) -> AlignmentResult:
    width, height = rgb_image.size
    left_gap = bbox.left
    right_gap = width - bbox.right - 1
    top_gap = bbox.top
    bottom_gap = height - bbox.bottom - 1

    padding = cfg.padding_for(bbox.width, bbox.height)
    target_x_gap = max(left_gap, right_gap, padding)
    target_y_gap = max(top_gap, bottom_gap, padding)

    add_left = target_x_gap - left_gap
    add_right = target_x_gap - right_gap
    add_top = target_y_gap - top_gap
    add_bottom = target_y_gap - bottom_gap

    if add_left == add_right == add_top == add_bottom == 0:
        return AlignmentResult(
            image=rgb_image.copy(),
            changed=False,
            foreground_found=True,
            bbox=bbox,
            background_color=background_color,
        )

    new_width = width + add_left + add_right
    new_height = height + add_top + add_bottom
    output = Image.new("RGB", (new_width, new_height), background_color)
    output.paste(rgb_image, (add_left, add_top))

    return AlignmentResult(
        image=output,
        changed=True,
        foreground_found=True,
        bbox=bbox,
        background_color=background_color,
        added_left=add_left,
        added_top=add_top,
        added_right=add_right,
        added_bottom=add_bottom,
    )


def estimate_background_color(
    arr: np.ndarray, edge_sample_px: int = 8
) -> tuple[int, int, int]:
    """Estimate background color from the dominant color among edge pixels.

    A plain median blends mixed edges (for example a half dark, half light
    border) into a color that exists nowhere in the image. Instead, quantize
    the edge pixels into coarse color buckets, pick the most common bucket,
    and return the median of only the pixels inside it.
    """
    height, width, _ = arr.shape
    sample = max(1, min(edge_sample_px, height, width))

    edge_pixels = np.concatenate(
        [
            arr[:sample, :, :].reshape(-1, 3),
            arr[-sample:, :, :].reshape(-1, 3),
            arr[:, :sample, :].reshape(-1, 3),
            arr[:, -sample:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    quantized = edge_pixels // 32
    buckets, counts = np.unique(quantized, axis=0, return_counts=True)
    dominant = buckets[int(np.argmax(counts))]
    in_bucket = np.all(quantized == dominant, axis=1)
    median = np.median(edge_pixels[in_bucket], axis=0)
    return tuple(int(round(channel)) for channel in median)


def build_foreground_mask(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    config: AlignmentConfig | None = None,
) -> np.ndarray:
    cfg = config or AlignmentConfig()
    bg = np.array(background_color, dtype=np.int32)
    diff = arr.astype(np.int32) - bg
    distance = np.sqrt(np.sum(diff * diff, axis=2))
    mask = (distance > cfg.mask_threshold).astype(np.uint8) * 255

    if cfg.dilate_px > 0:
        kernel_size = cfg.dilate_px * 2 + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_size, kernel_size)
        )
        mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def bbox_from_mask(
    mask: np.ndarray, config: AlignmentConfig | None = None
) -> BoundingBox | None:
    """Bounding box of the main content, ignoring tiny isolated specks.

    Stray artifacts such as a leftover cursor pixel would otherwise stretch
    the box far beyond the real content. Components smaller than
    ``min_component_area`` are dropped unless they are all there is.
    """
    cfg = config or AlignmentConfig()
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return None

    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = areas >= cfg.min_component_area
    if not keep.any():
        keep = areas == areas.max()

    kept = stats[1:][keep]
    left = int(kept[:, cv2.CC_STAT_LEFT].min())
    top = int(kept[:, cv2.CC_STAT_TOP].min())
    right = int((kept[:, cv2.CC_STAT_LEFT] + kept[:, cv2.CC_STAT_WIDTH]).max()) - 1
    bottom = int((kept[:, cv2.CC_STAT_TOP] + kept[:, cv2.CC_STAT_HEIGHT]).max()) - 1
    return BoundingBox(left=left, top=top, right=right, bottom=bottom)


def find_foreground_bbox(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    config: AlignmentConfig | None = None,
) -> BoundingBox | None:
    cfg = config or AlignmentConfig()
    mask = build_foreground_mask(arr, background_color, cfg)
    return bbox_from_mask(mask, cfg)


def _to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image.copy()
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")

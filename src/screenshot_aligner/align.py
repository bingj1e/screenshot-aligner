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
    distance = background_distance(arr, background_color)
    mask = mask_from_distance(distance, cfg.mask_threshold, cfg)
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

    bbox = include_related_soft_regions(distance, bbox, cfg)

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
    base = cfg.padding_for(bbox.width, bbox.height)
    left_gap = bbox.left
    right_gap = rgb_image.width - bbox.right - 1
    top_gap = bbox.top
    bottom_gap = rgb_image.height - bbox.bottom - 1

    # Cap the padding at the average margin the screenshot already had on each
    # axis. Crop mode should only tighten and rebalance, never inflate: an
    # already tightly-cropped image (small side gaps) must not gain new borders
    # just because the adaptive padding is larger than the gap that was there.
    pad_x = max(0, min(base, (left_gap + right_gap) // 2))
    pad_y = max(0, min(base, (top_gap + bottom_gap) // 2))

    crop = rgb_image.crop((bbox.left, bbox.top, bbox.right + 1, bbox.bottom + 1))
    output = Image.new(
        "RGB",
        (bbox.width + pad_x * 2, bbox.height + pad_y * 2),
        background_color,
    )
    output.paste(crop, (pad_x, pad_y))

    changed = output.size != rgb_image.size or output.tobytes() != rgb_image.tobytes()
    return AlignmentResult(
        image=output,
        changed=changed,
        foreground_found=True,
        bbox=bbox,
        background_color=background_color,
        added_left=pad_x - left_gap,
        added_top=pad_y - top_gap,
        added_right=pad_x - right_gap,
        added_bottom=pad_y - bottom_gap,
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


def background_distance(
    arr: np.ndarray, background_color: tuple[int, int, int]
) -> np.ndarray:
    """Per-pixel Euclidean color distance from the estimated background."""
    bg = np.array(background_color, dtype=np.int32)
    diff = arr.astype(np.int32) - bg
    return np.sqrt(np.sum(diff * diff, axis=2))


def mask_from_distance(
    distance: np.ndarray, threshold: int, config: AlignmentConfig | None = None
) -> np.ndarray:
    cfg = config or AlignmentConfig()
    mask = (distance > threshold).astype(np.uint8) * 255

    if cfg.dilate_px > 0:
        kernel_size = cfg.dilate_px * 2 + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_size, kernel_size)
        )
        mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def build_foreground_mask(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    config: AlignmentConfig | None = None,
    threshold: int | None = None,
) -> np.ndarray:
    cfg = config or AlignmentConfig()
    mask_threshold = cfg.mask_threshold if threshold is None else threshold
    return mask_from_distance(
        background_distance(arr, background_color), mask_threshold, cfg
    )


def include_related_soft_regions(
    distance: np.ndarray,
    bbox: BoundingBox,
    config: AlignmentConfig | None = None,
) -> BoundingBox:
    """Expand content bounds to include subtle containers around detected text.

    Chat bubbles and quote blocks are often only slightly different from the
    page background, so the strong text mask misses their edges. A softer mask
    finds those regions, but a component is only included when it intersects
    the already-detected text bounds AND stays within reach of them. The reach
    limit rejects page furniture that merely grazes the content (a full-width
    separator band) and noise blobs that span the whole frame, both of which
    would otherwise drag the crop out to the page edges.
    """
    cfg = config or AlignmentConfig()
    if cfg.container_threshold >= cfg.mask_threshold:
        return bbox

    soft_mask = mask_from_distance(distance, cfg.container_threshold, cfg)
    if float(np.count_nonzero(soft_mask)) / soft_mask.size > cfg.max_foreground_ratio:
        # The soft threshold lights up nearly everything (noisy or textured
        # background); component analysis would be meaningless here.
        return bbox

    count, _, stats, _ = cv2.connectedComponentsWithStats(soft_mask, connectivity=8)
    if count <= 1:
        return bbox

    reach_x = max(2 * cfg.min_padding, round(bbox.width * cfg.container_reach_ratio))
    reach_y = max(2 * cfg.min_padding, round(bbox.height * cfg.container_reach_ratio))

    left = bbox.left
    top = bbox.top
    right = bbox.right
    bottom = bbox.bottom

    for component in stats[1:]:
        area = int(component[cv2.CC_STAT_AREA])
        if area < cfg.min_component_area:
            continue

        comp_left = int(component[cv2.CC_STAT_LEFT])
        comp_top = int(component[cv2.CC_STAT_TOP])
        comp_right = comp_left + int(component[cv2.CC_STAT_WIDTH]) - 1
        comp_bottom = comp_top + int(component[cv2.CC_STAT_HEIGHT]) - 1

        if not boxes_intersect(bbox, comp_left, comp_top, comp_right, comp_bottom):
            continue

        if (
            comp_left < bbox.left - reach_x
            or comp_right > bbox.right + reach_x
            or comp_top < bbox.top - reach_y
            or comp_bottom > bbox.bottom + reach_y
        ):
            continue

        left = min(left, comp_left)
        top = min(top, comp_top)
        right = max(right, comp_right)
        bottom = max(bottom, comp_bottom)

    return BoundingBox(left=left, top=top, right=right, bottom=bottom)


def boxes_intersect(
    bbox: BoundingBox, left: int, top: int, right: int, bottom: int
) -> bool:
    return not (
        right < bbox.left
        or left > bbox.right
        or bottom < bbox.top
        or top > bbox.bottom
    )


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

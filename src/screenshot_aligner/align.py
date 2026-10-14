from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Literal

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


ContentKind = Literal["text", "graphic", "picture"]


@dataclass(frozen=True)
class ContentClass:
    """Why the content gate decided what it decided (shown by debug-file)."""

    kind: ContentKind
    text_lines: int
    text_coverage: float
    background_flatness: float
    background_confidence: float
    edges_touched: int


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
    content: ContentClass | None = None


def align_image(
    image: Image.Image, config: AlignmentConfig | None = None
) -> AlignmentResult:
    """Return a new image with foreground made easier to read."""
    cfg = config or AlignmentConfig()
    if image.width < 1 or image.height < 1:
        raise ValueError("Image dimensions must be positive")
    input_pixels = image.width * image.height
    if input_pixels > cfg.max_input_pixels:
        return AlignmentResult(
            image=image,
            changed=False,
            foreground_found=True,
            bbox=None,
            background_color=(255, 255, 255),
            note=(
                f"Image has {input_pixels:,} pixels, above the safe limit of "
                f"{cfg.max_input_pixels:,}; it was left unchanged."
            ),
        )

    rgb_image = _to_rgb(image)
    analysis_image, scale_x, scale_y = make_analysis_image(rgb_image, cfg)
    arr = np.asarray(analysis_image, dtype=np.uint8)
    background_color, background_confidence = estimate_background(
        arr,
        cfg.edge_sample_px,
        cfg.min_corner_background_ratio,
        cfg.max_corner_background_spread,
    )
    if background_confidence < cfg.min_background_bucket_ratio:
        return AlignmentResult(
            image=rgb_image.copy(),
            changed=False,
            foreground_found=True,
            bbox=None,
            background_color=background_color,
            note=(
                "Image edges do not have a stable background color; this looks "
                "more like a photo or textured image, so it was left unchanged."
            ),
        )

    distance = background_distance(arr, background_color)
    mask = mask_from_distance(distance, cfg.mask_threshold, cfg)
    bbox = bbox_from_mask(mask, cfg)
    contact_mask = mask_from_distance(
        distance, cfg.mask_threshold, cfg, dilate_px=0
    )
    contact_bbox = bbox_from_mask(contact_mask, cfg)

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

    content: ContentClass | None = None
    if cfg.content_gate:
        content = classify_content(
            arr, background_color, background_confidence, distance, cfg
        )

    strong_bbox = bbox
    contact_bbox = contact_bbox or strong_bbox
    bbox = include_related_soft_regions(distance, bbox, cfg)
    bbox = map_bbox_to_original(
        bbox, scale_x, scale_y, rgb_image.width, rgb_image.height
    )
    contact_bbox = map_bbox_to_original(
        contact_bbox,
        scale_x,
        scale_y,
        rgb_image.width,
        rgb_image.height,
    )

    if content is not None and content.kind == "picture":
        return AlignmentResult(
            image=rgb_image.copy(),
            changed=False,
            foreground_found=True,
            bbox=bbox,
            background_color=background_color,
            note=(
                "No text detected and the background is not a clean canvas; "
                "this looks like a photo or picture, so it was left unchanged."
            ),
            content=content,
        )

    if cfg.mode == "crop":
        # Only text earns the edge safety gutter, which invents new canvas
        # pixels. A graphic is cropped strictly inside the original frame, so
        # a misclassified photo can at worst be cropped, never framed.
        allow_extension = content is None or content.kind == "text"
        result = _crop_to_foreground(
            rgb_image,
            bbox,
            contact_bbox,
            background_color,
            cfg,
            allow_canvas_extension=allow_extension,
        )
        return replace(result, content=content)
    if cfg.mode == "pad":
        if content is not None and content.kind == "graphic":
            # Pad mode only ever extends the canvas, which graphics never get.
            return AlignmentResult(
                image=rgb_image.copy(),
                changed=False,
                foreground_found=True,
                bbox=bbox,
                background_color=background_color,
                note=(
                    "Graphic content without text; pad mode would extend the "
                    "canvas, so it was left unchanged."
                ),
                content=content,
            )
        result = _pad_to_center(rgb_image, bbox, background_color, cfg)
        return replace(result, content=content)
    raise ValueError(f"Unsupported alignment mode: {cfg.mode}")


def classify_content(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    background_confidence: float,
    distance: np.ndarray,
    config: AlignmentConfig | None = None,
) -> ContentClass:
    """Decide whether a screenshot is text, a graphic on a canvas, or a picture.

    * text: rows of glyph-sized strokes make up most of the stroke pixels.
    * graphic: no text, but the background is a pixel-flat canvas that is
      visible on every side (charts, icons, logos on a plain page).
    * picture: everything else, including a screenshot taken inside a photo.
    """
    cfg = config or AlignmentConfig()
    text_lines, text_coverage = detect_text_lines(arr, background_color, cfg)
    flatness = background_flatness(arr, background_color, distance, cfg)
    edges = edges_touched(distance, cfg)

    if text_lines >= cfg.text_min_lines and text_coverage >= cfg.text_min_coverage:
        kind: ContentKind = "text"
    elif (
        flatness >= cfg.graphic_min_background_flatness
        and background_confidence >= cfg.graphic_min_background_confidence
        and edges == 0
    ):
        kind = "graphic"
    else:
        kind = "picture"

    return ContentClass(
        kind=kind,
        text_lines=text_lines,
        text_coverage=text_coverage,
        background_flatness=flatness,
        background_confidence=background_confidence,
        edges_touched=edges,
    )


def detect_text_lines(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    config: AlignmentConfig | None = None,
) -> tuple[int, float]:
    """Count text lines and the share of stroke pixels that belong to them.

    Strokes are found with a morphological black-hat (dark ink on a light
    background) or top-hat (light ink on a dark background). That measures
    local contrast, so text inside a chat bubble or on a tinted panel is found
    even though the bubble itself differs from the page background. Only one
    polarity is used: the other one would also light up the gaps between
    letters and merge whole paragraphs into one blob.
    """
    cfg = config or AlignmentConfig()
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    size = cfg.text_stroke_kernel_px
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    r, g, b = background_color
    light_background = 0.299 * r + 0.587 * g + 0.114 * b >= 128
    op = cv2.MORPH_BLACKHAT if light_background else cv2.MORPH_TOPHAT
    strokes = (cv2.morphologyEx(gray, op, kernel) > cfg.text_stroke_threshold)
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        strokes.astype(np.uint8), connectivity=8
    )
    if count <= 1:
        return 0, 0.0

    total_area = int(stats[1:, cv2.CC_STAT_AREA].sum())
    pieces = stats[1:]
    xs = pieces[:, cv2.CC_STAT_LEFT]
    ys = pieces[:, cv2.CC_STAT_TOP]
    ws = pieces[:, cv2.CC_STAT_WIDTH]
    hs = pieces[:, cv2.CC_STAT_HEIGHT]
    areas = pieces[:, cv2.CC_STAT_AREA]
    glyph_sized = (
        (hs >= cfg.text_min_glyph_height)
        & (hs <= cfg.text_max_glyph_height)
        & (ws <= 3 * hs)
        & (areas >= 6)
    )
    if not glyph_sized.any():
        return 0, 0.0
    xs, ys, ws, hs, areas = (v[glyph_sized] for v in (xs, ys, ws, hs, areas))

    # Link the pieces of one text line by overlap rather than by comparing
    # vertical centres: each piece's box is widened by half its height on both
    # sides and painted onto a canvas. A dot, accent or short CJK stroke sits
    # inside its glyph's vertical span, so it joins the line even though its
    # centre is far off the line centre (which used to split big text into
    # fragments). Separate lines stay apart because of the line spacing.
    height, width = strokes.shape
    canvas = np.zeros((height, width), dtype=np.uint8)
    reach = np.maximum(1, hs // 2)
    for x, y, w, h, r in zip(xs, ys, ws, hs, reach):
        cv2.rectangle(
            canvas,
            (int(max(0, x - r)), int(y)),
            (int(min(width - 1, x + w - 1 + r)), int(y + h - 1)),
            1,
            thickness=-1,
        )
    _, labels, group_stats, _ = cv2.connectedComponentsWithStats(canvas, connectivity=4)
    group_of = labels[ys + hs // 2, xs + ws // 2]

    # A text line segment: enough pieces, a flat row-shaped group (not a
    # sprawling blob of photo texture) that is clearly wider than tall.
    lines = 0
    text_area = 0
    for group in np.unique(group_of):
        members = group_of == group
        if int(members.sum()) < cfg.text_min_glyphs_per_line:
            continue
        group_width = int(group_stats[group, cv2.CC_STAT_WIDTH])
        group_height = int(group_stats[group, cv2.CC_STAT_HEIGHT])
        glyph_height = float(np.percentile(hs[members], 75))
        if group_height <= 2.5 * glyph_height and group_width >= 3 * group_height:
            lines += 1
            text_area += int(areas[members].sum())

    return lines, (text_area / total_area if total_area else 0.0)


def background_flatness(
    arr: np.ndarray,
    background_color: tuple[int, int, int],
    distance: np.ndarray,
    config: AlignmentConfig | None = None,
) -> float:
    """Share of background pixels on the image border that are exactly flat.

    A UI canvas is the same RGB value pixel for pixel (JPEG keeps flat areas
    flat too); sky, snow or shadow in a photo carries sensor noise and
    gradients. Only border pixels already classified as background count, so
    content touching the border does not lower the score.
    """
    cfg = config or AlignmentConfig()
    height, width = distance.shape
    sample = max(1, min(cfg.edge_sample_px, height, width))
    border = np.zeros((height, width), dtype=bool)
    border[:sample] = True
    border[-sample:] = True
    border[:, :sample] = True
    border[:, -sample:] = True
    background = border & (distance <= cfg.mask_threshold)
    if not background.any():
        return 0.0
    deviation = np.abs(
        arr[background].astype(np.int16) - np.array(background_color, dtype=np.int16)
    ).max(axis=1)
    return float(np.mean(deviation <= cfg.background_flat_tolerance))


def edges_touched(
    distance: np.ndarray, config: AlignmentConfig | None = None, band: int = 2
) -> int:
    """How many image sides strong foreground reaches (ignoring frame lines)."""
    cfg = config or AlignmentConfig()
    mask = mask_from_distance(distance, cfg.mask_threshold, cfg, dilate_px=0)
    mask = remove_border_line_components(mask, cfg)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return 0
    # Drop single-pixel dust so a stray compression speck is not "content".
    dust = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] < 4)
    solid = mask.astype(bool) & ~np.isin(labels, dust)
    return int(
        sum(
            [
                solid[:, :band].any(),
                solid[:, -band:].any(),
                solid[:band].any(),
                solid[-band:].any(),
            ]
        )
    )


def _crop_to_foreground(
    rgb_image: Image.Image,
    bbox: BoundingBox,
    contact_bbox: BoundingBox,
    background_color: tuple[int, int, int],
    cfg: AlignmentConfig,
    allow_canvas_extension: bool = True,
) -> AlignmentResult:
    base = cfg.padding_for(bbox.width, bbox.height)
    left_gap = bbox.left
    right_gap = rgb_image.width - bbox.right - 1
    top_gap = bbox.top
    bottom_gap = rgb_image.height - bbox.bottom - 1

    # Reuse real pixels from the narrower side on each axis, then crop the
    # wider side to match. This guarantees that crop mode only removes pixels;
    # it never invents a flat border that can look wrong on gradients.
    pad_x = max(0, min(base, left_gap, right_gap))
    pad_y = max(0, min(base, top_gap, bottom_gap))

    contact_left_gap = contact_bbox.left
    contact_right_gap = rgb_image.width - contact_bbox.right - 1
    contact_top_gap = contact_bbox.top
    contact_bottom_gap = rgb_image.height - contact_bbox.bottom - 1
    safety = min(base, cfg.edge_safety_padding)
    safety_x = (
        allow_canvas_extension
        and min(contact_left_gap, contact_right_gap) <= safety
    )
    safety_y = (
        allow_canvas_extension
        and min(contact_top_gap, contact_bottom_gap) <= safety
    )

    if safety_x:
        target_left = min(bbox.left, contact_bbox.left - safety)
        target_right = max(bbox.right + 1, contact_bbox.right + safety + 1)
    else:
        target_left = bbox.left - pad_x
        target_right = bbox.right + pad_x + 1

    if safety_y:
        target_top = min(bbox.top, contact_bbox.top - safety)
        target_bottom = max(bbox.bottom + 1, contact_bbox.bottom + safety + 1)
    else:
        target_top = bbox.top - pad_y
        target_bottom = bbox.bottom + pad_y + 1
    source_left = max(0, target_left)
    source_top = max(0, target_top)
    source_right = min(rgb_image.width, target_right)
    source_bottom = min(rgb_image.height, target_bottom)

    canvas_color = outer_corner_color(rgb_image, background_color)
    if (target_right - target_left) * (target_bottom - target_top) > cfg.max_output_pixels:
        return _output_limit_result(rgb_image, bbox, background_color)
    output = Image.new(
        "RGB",
        (target_right - target_left, target_bottom - target_top),
        canvas_color,
    )
    source = rgb_image.crop(
        (source_left, source_top, source_right, source_bottom)
    )
    output.paste(source, (source_left - target_left, source_top - target_top))

    reported_bbox = BoundingBox(
        left=contact_bbox.left if safety_x else bbox.left,
        top=contact_bbox.top if safety_y else bbox.top,
        right=contact_bbox.right if safety_x else bbox.right,
        bottom=contact_bbox.bottom if safety_y else bbox.bottom,
    )
    changed = output.size != rgb_image.size or output.tobytes() != rgb_image.tobytes()
    return AlignmentResult(
        image=output,
        changed=changed,
        foreground_found=True,
        bbox=reported_bbox,
        background_color=background_color,
        added_left=-target_left,
        added_top=-target_top,
        added_right=target_right - rgb_image.width,
        added_bottom=target_bottom - rgb_image.height,
    )


def outer_corner_color(
    image: Image.Image,
    fallback: tuple[int, int, int],
    max_spread: float = 12.0,
) -> tuple[int, int, int]:
    """Use the exposed outer corners when they agree on a canvas color."""
    width, height = image.size
    corners = np.array(
        [
            image.getpixel((0, 0)),
            image.getpixel((width - 1, 0)),
            image.getpixel((0, height - 1)),
            image.getpixel((width - 1, height - 1)),
        ],
        dtype=np.float32,
    )
    median = np.median(corners, axis=0)
    if float(np.linalg.norm(corners - median, axis=1).max()) > max_spread:
        return fallback
    return tuple(int(round(channel)) for channel in median)


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
    if new_width * new_height > cfg.max_output_pixels:
        return _output_limit_result(rgb_image, bbox, background_color)
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


def _output_limit_result(image, bbox, background_color) -> AlignmentResult:
    return AlignmentResult(
        image=image, changed=False, foreground_found=True, bbox=bbox,
        background_color=background_color,
        note="Aligned canvas exceeds the safe output pixel limit; image left unchanged.",
    )


def make_analysis_image(
    image: Image.Image, config: AlignmentConfig
) -> tuple[Image.Image, float, float]:
    pixels = image.width * image.height
    if pixels <= config.max_analysis_pixels:
        return image, 1.0, 1.0

    scale = math.sqrt(config.max_analysis_pixels / pixels)
    analysis_width = max(1, min(config.max_analysis_pixels, math.floor(image.width * scale)))
    analysis_height = max(1, min(
        config.max_analysis_pixels // analysis_width, math.floor(image.height * scale)
    ))
    analysis = image.resize(
        (analysis_width, analysis_height), Image.Resampling.BILINEAR
    )
    return analysis, image.width / analysis_width, image.height / analysis_height


def map_bbox_to_original(
    bbox: BoundingBox,
    scale_x: float,
    scale_y: float,
    original_width: int,
    original_height: int,
) -> BoundingBox:
    if scale_x == 1.0 and scale_y == 1.0:
        return bbox

    left = max(0, math.floor(bbox.left * scale_x))
    top = max(0, math.floor(bbox.top * scale_y))
    right = min(
        original_width - 1, math.ceil((bbox.right + 1) * scale_x) - 1
    )
    bottom = min(
        original_height - 1, math.ceil((bbox.bottom + 1) * scale_y) - 1
    )
    return BoundingBox(left=left, top=top, right=right, bottom=bottom)


def estimate_background_color(
    arr: np.ndarray, edge_sample_px: int = 8
) -> tuple[int, int, int]:
    """Estimate background color from the dominant color among edge pixels.

    A plain median blends mixed edges (for example a half dark, half light
    border) into a color that exists nowhere in the image. Instead, quantize
    the edge pixels into coarse color buckets, pick the most common bucket,
    and return the median of only the pixels inside it.
    """
    color, _ = estimate_background(arr, edge_sample_px)
    return color


def estimate_background(
    arr: np.ndarray,
    edge_sample_px: int = 8,
    min_corner_ratio: float = 0.75,
    max_corner_spread: float = 12.0,
) -> tuple[tuple[int, int, int], float]:
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

    # A large rounded card can occupy nearly every edge pixel while the four
    # corners still expose the true page background. Prefer those corners when
    # they form one stable color family; mixed corners (split layouts, photos)
    # fall back to the dominant full-edge estimate below.
    corner_pixels = np.concatenate(
        [
            arr[:sample, :sample, :].reshape(-1, 3),
            arr[:sample, -sample:, :].reshape(-1, 3),
            arr[-sample:, :sample, :].reshape(-1, 3),
            arr[-sample:, -sample:, :].reshape(-1, 3),
        ],
        axis=0,
    )
    corner_quantized = corner_pixels // 32
    corner_buckets, corner_counts = np.unique(
        corner_quantized, axis=0, return_counts=True
    )
    corner_index = int(np.argmax(corner_counts))
    corner_dominant = corner_buckets[corner_index]
    corner_in_bucket = np.all(corner_quantized == corner_dominant, axis=1)
    corner_confidence = float(corner_counts[corner_index]) / len(corner_pixels)
    corner_values = corner_pixels[corner_in_bucket]
    corner_median = np.median(corner_values, axis=0)
    corner_distance = np.linalg.norm(
        corner_values.astype(np.float32) - corner_median.astype(np.float32),
        axis=1,
    )
    corner_spread = float(np.percentile(corner_distance, 95))
    if (
        corner_confidence >= min_corner_ratio
        and corner_spread <= max_corner_spread
    ):
        color = tuple(int(round(channel)) for channel in corner_median)
        return color, corner_confidence

    quantized = edge_pixels // 32
    buckets, counts = np.unique(quantized, axis=0, return_counts=True)
    dominant = buckets[int(np.argmax(counts))]
    in_bucket = np.all(quantized == dominant, axis=1)
    median = np.median(edge_pixels[in_bucket], axis=0)
    color = tuple(int(round(channel)) for channel in median)
    confidence = float(counts.max()) / len(edge_pixels)
    return color, confidence


def background_distance(
    arr: np.ndarray, background_color: tuple[int, int, int]
) -> np.ndarray:
    """Per-pixel Euclidean color distance from the estimated background."""
    bg = np.array(background_color, dtype=np.float32)
    diff = arr.astype(np.float32) - bg
    squared = np.sum(diff * diff, axis=2, dtype=np.float32)
    return np.sqrt(squared, out=squared)


def mask_from_distance(
    distance: np.ndarray,
    threshold: int,
    config: AlignmentConfig | None = None,
    dilate_px: int | None = None,
) -> np.ndarray:
    cfg = config or AlignmentConfig()
    mask = (distance > threshold).astype(np.uint8) * 255

    dilation = cfg.dilate_px if dilate_px is None else dilate_px
    if dilation > 0:
        kernel_size = dilation * 2 + 1
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
    if float(np.count_nonzero(soft_mask)) / soft_mask.size > cfg.max_container_ratio:
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

        # A low-contrast gradient around a card can form one soft component
        # that reaches the image frame and intersects the real card border.
        # Including it would turn a correct card/content box back into the
        # whole screenshot. A related bubble or quote container may sit near
        # an edge, but it should not extend an existing content box all the way
        # through that edge.
        guard = cfg.border_touch_px
        frame_sides_reached = sum(
            [
                comp_left <= guard and comp_left < bbox.left,
                comp_top <= guard and comp_top < bbox.top,
                (
                    comp_right >= distance.shape[1] - guard - 1
                    and comp_right > bbox.right
                ),
                (
                    comp_bottom >= distance.shape[0] - guard - 1
                    and comp_bottom > bbox.bottom
                ),
            ]
        )
        if frame_sides_reached >= 3:
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
    mask = remove_border_line_components(mask, cfg)
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


def remove_border_line_components(
    mask: np.ndarray, config: AlignmentConfig | None = None
) -> np.ndarray:
    """Drop thin screenshot/page border lines connected to the image edge."""
    cfg = config or AlignmentConfig()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return mask

    height, width = mask.shape
    output = mask.copy()

    for label, component in enumerate(stats[1:], start=1):
        left = int(component[cv2.CC_STAT_LEFT])
        top = int(component[cv2.CC_STAT_TOP])
        comp_width = int(component[cv2.CC_STAT_WIDTH])
        comp_height = int(component[cv2.CC_STAT_HEIGHT])
        area = int(component[cv2.CC_STAT_AREA])
        right = left + comp_width - 1
        bottom = top + comp_height - 1

        touches_edge = (
            left <= cfg.border_touch_px
            or top <= cfg.border_touch_px
            or right >= width - cfg.border_touch_px - 1
            or bottom >= height - cfg.border_touch_px - 1
        )
        if not touches_edge:
            continue

        horizontal_border = (
            comp_height <= cfg.border_line_max_thickness
            and comp_width >= width * cfg.border_line_min_span_ratio
            and (top <= cfg.border_touch_px or bottom >= height - cfg.border_touch_px - 1)
        )
        vertical_border = (
            comp_width <= cfg.border_line_max_thickness
            and comp_height >= height * cfg.border_line_min_span_ratio
            and (left <= cfg.border_touch_px or right >= width - cfg.border_touch_px - 1)
        )
        inset = min(
            cfg.border_line_max_thickness * 2,
            max(0, comp_width // 4),
            max(0, comp_height // 4),
        )
        if inset > 0:
            interior = labels[
                top + inset : bottom - inset + 1,
                left + inset : right - inset + 1,
            ]
            interior_ratio = float(np.count_nonzero(interior == label)) / area
        else:
            interior_ratio = 0.0
        frame_border = (
            comp_width >= width * cfg.border_line_min_span_ratio
            and comp_height >= height * cfg.border_line_min_span_ratio
            and left <= cfg.border_touch_px
            and top <= cfg.border_touch_px
            and right >= width - cfg.border_touch_px - 1
            and bottom >= height - cfg.border_touch_px - 1
            and area / (comp_width * comp_height) <= cfg.border_frame_max_density
            and interior_ratio <= cfg.border_frame_max_interior_ratio
        )

        if horizontal_border or vertical_border or frame_border:
            output[labels == label] = 0

    return output


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
    if "A" in image.getbands() or "transparency" in image.info:
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.getchannel("A"))
        return background
    return image.convert("RGB")

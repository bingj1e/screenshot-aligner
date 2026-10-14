from __future__ import annotations

from PIL import Image, ImageDraw

from screenshot_aligner import AlignmentConfig, align_image
from screenshot_aligner.align import (
    background_distance,
    estimate_background_color,
    find_foreground_bbox,
)


# These tests exercise the crop/pad geometry with rectangles standing in for
# text, so they bypass the text/graphic/picture content gate (which would
# rightly classify a black rectangle as a graphic). The gate has its own tests
# in test_content_gate.py.
PAD_CONFIG = AlignmentConfig(
    mode="pad", min_padding=24, mask_threshold=24, dilate_px=3, content_gate=False
)
CROP_CONFIG = AlignmentConfig(
    mode="crop", min_padding=24, mask_threshold=24, dilate_px=3, content_gate=False
)


def test_pad_mode_left_biased_content_gets_equal_horizontal_padding() -> None:
    image = Image.new("RGB", (220, 120), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 45, 80, 75), fill="black")

    result = align_image(image, PAD_CONFIG)
    bbox = _bbox_for(result.image)

    assert result.changed
    assert bbox is not None
    assert bbox.left == result.image.width - bbox.right - 1


def test_pad_mode_top_biased_content_gets_equal_vertical_padding() -> None:
    image = Image.new("RGB", (160, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((55, 15, 105, 45), fill="black")

    result = align_image(image, PAD_CONFIG)
    bbox = _bbox_for(result.image)

    assert result.changed
    assert bbox is not None
    assert bbox.top == result.image.height - bbox.bottom - 1


def test_crop_mode_keeps_main_content_with_symmetric_padding() -> None:
    image = Image.new("RGB", (260, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 45, 150, 78), fill="black")

    result = align_image(image, CROP_CONFIG)
    bbox = _bbox_for(result.image)

    assert result.changed
    assert result.image.size == (81 + 48 + 6, 34 + 48 + 6)
    assert bbox is not None
    assert bbox.left == 24
    assert result.image.width - bbox.right - 1 == 24
    assert bbox.top == 24
    assert result.image.height - bbox.bottom - 1 == 24


def test_dark_background_uses_edge_color_for_new_canvas() -> None:
    background = (30, 34, 42)
    image = Image.new("RGB", (180, 100), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 35, 72, 62), fill=(230, 235, 240))

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.background_color == background
    assert result.image.getpixel((0, 0)) == background
    assert result.image.getpixel((result.image.width - 1, 0)) == background


def test_solid_image_returns_unchanged_copy() -> None:
    image = Image.new("RGB", (100, 80), (245, 245, 245))

    result = align_image(image, CROP_CONFIG)

    assert not result.changed
    assert not result.foreground_found
    assert result.image.size == image.size


def test_pad_mode_already_centered_image_does_not_change_size() -> None:
    image = Image.new("RGB", (148, 108), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 30, 97, 77), fill="black")

    result = align_image(image, PAD_CONFIG)

    assert result.foreground_found
    assert not result.changed
    assert result.image.size == image.size


def test_padding_scales_with_content_size() -> None:
    small = AlignmentConfig(mode="crop")
    assert small.padding_for(100, 60) == small.min_padding

    large = AlignmentConfig(mode="crop")
    assert large.padding_for(1500, 800) == 90

    huge = AlignmentConfig(mode="crop")
    assert huge.padding_for(4000, 2400) == huge.max_padding


def test_crop_mode_uses_adaptive_padding_for_large_content() -> None:
    image = Image.new("RGB", (1400, 800), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 100, 1149, 649), fill="black")

    result = align_image(image, CROP_CONFIG)

    # Dilated bbox is 1056x556 wide, so padding = round(1056 * 0.06) = 63.
    assert result.changed
    assert result.image.size == (1056 + 63 * 2, 556 + 63 * 2)


def test_crop_mode_includes_subtle_chat_bubble_around_text() -> None:
    image = Image.new("RGB", (420, 180), "white")
    draw = ImageDraw.Draw(image)
    bubble = (48, 26, 330, 84)
    draw.rounded_rectangle(bubble, radius=14, fill=(245, 245, 245))
    draw.rectangle((78, 44, 250, 55), fill="black")
    draw.rectangle((78, 62, 180, 73), fill="black")

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.bbox is not None
    assert result.bbox.left <= bubble[0]
    assert result.bbox.top <= bubble[1]
    assert result.bbox.right >= bubble[2]
    assert result.bbox.bottom >= bubble[3]


def test_grazing_full_width_band_is_not_included() -> None:
    image = Image.new("RGB", (800, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((350, 150, 450, 200), fill="black")  # the text
    # Subtle full-width separator band just below the text. It grazes the
    # dilated text bounds but is page furniture, not a related container.
    draw.rectangle((0, 205, 799, 215), fill=(246, 246, 246))

    result = align_image(image, CROP_CONFIG)

    assert result.bbox is not None
    assert result.bbox.left >= 300
    assert result.bbox.right <= 500


def test_noisy_background_does_not_expand_to_full_frame() -> None:
    import numpy as np

    rng = np.random.default_rng(7)
    arr = np.full((400, 800, 3), 245, dtype=np.int16)
    arr += rng.integers(-5, 6, size=arr.shape, dtype=np.int16)
    image = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((300, 150, 500, 250), fill="black")

    result = align_image(image, CROP_CONFIG)

    assert result.bbox is not None
    assert result.bbox.width <= 300
    assert result.bbox.height <= 200


def test_crop_mode_normalizes_tight_content_to_safety_gutter() -> None:
    # Content already fills most of the frame, leaving only small side gaps
    # (like an app screenshot the user cropped tightly themselves).
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 40, 300, 150), fill="black")

    result = align_image(image, CROP_CONFIG)

    assert result.bbox is not None
    assert result.image.width == result.bbox.width + 32
    assert result.image.width <= image.width + 32


def test_crop_mode_preserves_real_gradient_margin_pixels() -> None:
    import numpy as np

    width, height = 500, 180
    x = np.arange(width, dtype=np.uint8)
    arr = np.empty((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = 245 + (x % 5)
    arr[:, :, 1] = 242 + (x % 4)
    arr[:, :, 2] = 238 + (x % 3)
    image = Image.fromarray(arr, mode="RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 60, 300, 100), fill="black")

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.bbox is not None
    assert result.image.width < image.width
    # Crop mode uses source pixels directly instead of repainting a flat edge.
    assert len(set(result.image.crop((0, 0, result.image.width, 1)).getdata())) > 1


def test_soft_gradient_touching_frame_does_not_swallow_card_bbox() -> None:
    import numpy as np

    width, height = 800, 260
    arr = np.full((height, width, 3), (253, 251, 249), dtype=np.uint8)
    # Low-contrast outer variation is above the soft threshold but below the
    # strong foreground threshold, matching a tinted Windows settings page.
    arr[:, :20] = (246, 242, 238)
    arr[:, 720:] = (246, 242, 238)
    image = Image.fromarray(arr, mode="RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 0, 719, 259), outline=(232, 226, 220), width=2)
    draw.rectangle((55, 70, 310, 90), fill=(20, 20, 20))

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.bbox is not None
    assert result.bbox.left <= 20
    assert result.bbox.right >= 719
    assert result.bbox.left > 0
    assert result.bbox.right < width - 1
    assert result.image.width < image.width


def test_rounded_bubble_touching_top_and_bottom_uses_corner_background() -> None:
    image = Image.new("RGB", (881, 155), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((16, -8, 866, 162), radius=28, fill=(243, 243, 244))
    draw.rectangle((35, 20, 845, 39), fill=(25, 25, 25))
    draw.rectangle((35, 55, 700, 74), fill=(25, 25, 25))
    draw.rectangle((35, 90, 760, 109), fill=(25, 25, 25))
    draw.rectangle((35, 125, 500, 136), fill=(25, 25, 25))

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.background_color == (255, 255, 255)
    assert result.bbox is not None
    assert result.bbox.left < 16
    assert result.bbox.right > 866
    # The source bubble had 16px left and 14px right whitespace. Crop mode
    # removes only the two excess pixels from the left side.
    assert result.image.width == 879
    # The soft bubble reaches the top and bottom, but the strong text does not.
    # Edge safety therefore must not add unnecessary vertical gutters.
    assert result.image.height == 155


def test_full_width_table_lines_receive_horizontal_safety_gutter_only() -> None:
    image = Image.new("RGB", (500, 300), "white")
    draw = ImageDraw.Draw(image)
    for y in (70, 130, 190, 250):
        draw.line((0, y, 499, y), fill=(180, 180, 180), width=2)
    draw.rectangle((5, 25, 180, 44), fill=(20, 20, 20))
    draw.rectangle((5, 90, 220, 109), fill=(20, 20, 20))

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.bbox is not None
    assert result.image.width == result.bbox.width + 32
    assert result.image.height <= image.height


def test_crop_mode_adds_safety_gutter_when_content_touches_edges() -> None:
    image = Image.new("RGB", (260, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 259, 159), fill="white")
    draw.rectangle((2, 2, 257, 157), fill="black")  # gaps smaller than min_padding

    result = align_image(image, CROP_CONFIG)

    assert result.image.size == (292, 192)
    assert result.image.getpixel((0, 0)) == (255, 255, 255)


def test_thin_border_lines_are_ignored_when_computing_content_box() -> None:
    image = Image.new("RGB", (500, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 499, 259), outline=(210, 210, 210), width=2)
    draw.rectangle((95, 35, 420, 55), fill="black")
    draw.rectangle((95, 85, 360, 105), fill="black")
    draw.rectangle((95, 135, 390, 155), fill="black")

    result = align_image(image, CROP_CONFIG)

    assert result.bbox is not None
    assert result.bbox.left > 40
    assert result.bbox.right < 460
    assert result.bbox.top > 20
    assert result.bbox.bottom < 180


def test_edge_connected_table_grid_is_not_removed_as_a_frame() -> None:
    image = Image.new("RGB", (500, 260), "white")
    draw = ImageDraw.Draw(image)
    line_color = (190, 190, 190)
    draw.rectangle((0, 0, 499, 259), outline=line_color, width=2)
    draw.line((0, 86, 499, 86), fill=line_color, width=2)
    draw.line((0, 173, 499, 173), fill=line_color, width=2)
    draw.line((166, 0, 166, 259), fill=line_color, width=2)
    draw.line((333, 0, 333, 259), fill=line_color, width=2)

    result = align_image(image, CROP_CONFIG)

    assert result.bbox is not None
    assert result.bbox.left == 0
    assert result.bbox.top == 0
    assert result.bbox.right == 499
    assert result.bbox.bottom == 259


def test_large_image_uses_scaled_analysis_and_maps_bbox_back() -> None:
    config = AlignmentConfig(
        mode="crop",
        max_analysis_pixels=60_000,
        max_input_pixels=2_000_000,
        content_gate=False,
    )
    image = Image.new("RGB", (1200, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 120, 950, 430), fill="black")

    result = align_image(image, config)

    assert result.changed
    assert result.bbox is not None
    assert abs(result.bbox.left - 180) <= 20
    assert abs(result.bbox.top - 120) <= 20
    assert abs(result.bbox.right - 950) <= 20
    assert abs(result.bbox.bottom - 430) <= 20


def test_image_above_hard_pixel_limit_is_left_unchanged() -> None:
    config = AlignmentConfig(mode="crop", max_input_pixels=10_000)
    image = Image.new("RGB", (200, 100), "white")

    result = align_image(image, config)

    assert not result.changed
    assert result.note is not None
    assert "safe limit" in result.note


def test_photo_like_colorful_edges_are_left_unchanged() -> None:
    import numpy as np

    rng = np.random.default_rng(21)
    image = Image.fromarray(
        rng.integers(0, 256, size=(240, 360, 3), dtype=np.uint8), mode="RGB"
    )

    result = align_image(image, CROP_CONFIG)

    assert not result.changed
    assert result.note is not None
    assert "stable background" in result.note


def test_background_distance_uses_float32() -> None:
    import numpy as np

    arr = np.zeros((20, 30, 3), dtype=np.uint8)
    distance = background_distance(arr, (255, 255, 255))

    assert distance.dtype == np.float32


def test_isolated_speck_is_ignored_when_cropping() -> None:
    image = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 80, 250, 120), fill="black")
    image.putpixel((395, 4), (0, 0, 0))  # stray dark pixel near a corner

    result = align_image(image, CROP_CONFIG)

    assert result.changed
    assert result.bbox is not None
    assert result.bbox.left >= 140
    assert result.bbox.right <= 260
    assert result.bbox.top >= 70


def test_speck_only_image_still_detects_foreground() -> None:
    image = Image.new("RGB", (200, 100), "white")
    image.putpixel((100, 50), (0, 0, 0))

    result = align_image(image, CROP_CONFIG)

    assert result.foreground_found
    assert result.bbox is not None


def test_split_background_picks_dominant_color_not_blend() -> None:
    import numpy as np

    image = Image.new("RGB", (300, 100), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 99, 99), fill=(20, 20, 20))  # dark third of the frame

    color = estimate_background_color(np.asarray(image))

    # A plain median over mixed edges would blend toward gray;
    # the dominant-bucket estimate must return one of the real colors.
    assert color == (250, 250, 250)


def test_foreground_covering_whole_image_is_left_unchanged() -> None:
    image = Image.new("RGB", (200, 150))
    for y in range(150):
        for x in range(200):
            image.putpixel((x, y), ((x * 7 + y * 13) % 256, (x * 3) % 256, (y * 5) % 256))

    result = align_image(image, CROP_CONFIG)

    assert not result.changed
    assert result.note is not None


def _bbox_for(image: Image.Image):
    return find_foreground_bbox(
        arr=__import__("numpy").asarray(image.convert("RGB")),
        background_color=(255, 255, 255)
        if image.getpixel((0, 0)) == (255, 255, 255)
        else image.getpixel((0, 0)),
        config=CROP_CONFIG,
    )

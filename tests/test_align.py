from __future__ import annotations

from PIL import Image, ImageDraw

from screenshot_aligner import AlignmentConfig, align_image
from screenshot_aligner.align import estimate_background_color, find_foreground_bbox


PAD_CONFIG = AlignmentConfig(mode="pad", min_padding=24, mask_threshold=24, dilate_px=3)
CROP_CONFIG = AlignmentConfig(mode="crop", min_padding=24, mask_threshold=24, dilate_px=3)


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


def test_crop_mode_does_not_add_borders_to_already_tight_content() -> None:
    # Content already fills most of the frame, leaving only small side gaps
    # (like an app screenshot the user cropped tightly themselves).
    image = Image.new("RGB", (320, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 40, 300, 150), fill="black")

    result = align_image(image, CROP_CONFIG)

    # Crop must not inflate the frame: no new borders wider than the original.
    assert result.image.width <= image.width


def test_crop_mode_does_not_inflate_when_content_touches_edges() -> None:
    image = Image.new("RGB", (260, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 259, 159), fill="white")
    draw.rectangle((2, 2, 257, 157), fill="black")  # gaps smaller than min_padding

    result = align_image(image, CROP_CONFIG)

    assert result.image.width <= image.width
    assert result.image.height <= image.height


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

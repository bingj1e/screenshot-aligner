"""Text / graphic / picture content gate.

Pictures (including screenshots taken inside a photo) must come back
byte-for-byte unchanged, graphics may only be cropped inside the original
frame, and text keeps the full crop behaviour.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from screenshot_aligner import AlignmentConfig, align_image

LINES = [
    "The quick brown fox jumps over the lazy dog.",
    "Screenshot Aligner crops to the main content",
    "and adds balanced padding around it, 1234567890.",
]


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)  # bundled TrueType, Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


def _paragraph(size=(560, 200), bg="white", fg="black", origin=(30, 30), font_size=16):
    image = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(image)
    font = _font(font_size)
    for i, line in enumerate(LINES):
        draw.text((origin[0], origin[1] + i * font_size * 1.6), line, fill=fg, font=font)
    return image


def _jpeg(image: Image.Image, quality: int = 85) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def _with_noise(image: Image.Image, sigma: float, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = np.asarray(image, dtype=np.float32)
    arr = arr + rng.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _sky_and_mountains() -> Image.Image:
    width, height = 900, 600
    arr = np.zeros((height, width, 3), dtype=np.float32)
    for y in range(height):
        arr[y] = (110 + y * 0.05, 160 + y * 0.05, 225)
    image = Image.fromarray(arr.astype(np.uint8))
    ImageDraw.Draw(image).polygon(
        [(0, 380), (200, 300), (420, 370), (650, 280), (900, 360), (900, 600), (0, 600)],
        fill=(60, 95, 45),
    )
    return _jpeg(_with_noise(image.filter(ImageFilter.GaussianBlur(2)), 3, seed=1))


def _sea_horizon() -> Image.Image:
    image = Image.new("RGB", (900, 600), (190, 195, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 300, 900, 600), fill=(80, 100, 120))
    draw.polygon([(400, 300), (480, 300), (470, 315), (410, 315)], fill=(30, 30, 30))
    return _jpeg(_with_noise(image.filter(ImageFilter.GaussianBlur(1)), 3, seed=2))


def _snow_and_skier() -> Image.Image:
    image = Image.new("RGB", (900, 600), (240, 243, 248))
    draw = ImageDraw.Draw(image)
    draw.rectangle((420, 250, 470, 380), fill=(200, 40, 40))
    draw.ellipse((425, 210, 465, 250), fill=(230, 190, 160))
    return _jpeg(_with_noise(image, 3, seed=3))


def _night_and_moon() -> Image.Image:
    rng = np.random.default_rng(4)
    image = Image.new("RGB", (900, 600), (8, 10, 18))
    draw = ImageDraw.Draw(image)
    draw.ellipse((560, 120, 700, 260), fill=(235, 230, 210))
    for _ in range(60):
        draw.point((int(rng.integers(0, 900)), int(rng.integers(0, 600))), fill=(200, 200, 210))
    return _jpeg(_with_noise(image, 2, seed=5))


def _bar_chart(left_margin: int = 40) -> Image.Image:
    image = Image.new("RGB", (500, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.line((left_margin, 260, 470, 260), fill=(120, 120, 120))
    draw.line((left_margin, 30, left_margin, 260), fill=(120, 120, 120))
    for i, height in enumerate([120, 200, 90, 170, 60]):
        x = left_margin + 30 + i * 80
        draw.rectangle((x, 260 - height, x + 50, 260), fill=(66, 133, 244))
    return image


@pytest.mark.parametrize(
    "image",
    [
        pytest.param(_paragraph(), id="light"),
        pytest.param(_paragraph(bg=(30, 31, 34), fg=(220, 220, 220)), id="dark-mode"),
        pytest.param(_jpeg(_paragraph(), 70), id="jpeg"),
    ],
)
def test_text_screenshot_is_classified_as_text_and_cropped(image):
    result = align_image(image)

    assert result.content is not None
    assert result.content.kind == "text"
    assert result.changed
    assert result.image.width < image.width
    assert result.image.height < image.height


@pytest.mark.parametrize("font_size", [36, 44])
def test_large_dense_text_is_text(font_size):
    # Regression: dots, accents and punctuation sit far from the line centre in
    # big text; grouping by centre split every line into fragments and the
    # screenshot was misclassified as a graphic.
    image = Image.new("RGB", (1800, 1100), "white")
    draw = ImageDraw.Draw(image)
    font = _font(font_size)
    for i in range(int(900 / (font_size * 1.4))):
        draw.text(
            (60, 60 + i * font_size * 1.4),
            "Typography, judging, quizzical jigs; pyjama i-j dots!",
            fill="black",
            font=font,
        )

    result = align_image(image)

    assert result.content is not None
    assert result.content.kind == "text"


def test_text_inside_chat_bubbles_is_text():
    image = Image.new("RGB", (520, 260), (237, 237, 237))
    draw = ImageDraw.Draw(image)
    font = _font(16)
    draw.rounded_rectangle((20, 20, 330, 70), 8, fill="white")
    draw.text((34, 36), "Are we still on for dinner tonight?", fill="black", font=font)
    draw.rounded_rectangle((180, 90, 500, 140), 8, fill=(149, 236, 105))
    draw.text((194, 106), "Yes, see you at seven downstairs", fill="black", font=font)

    result = align_image(image)

    assert result.content is not None
    assert result.content.kind == "text"


def test_text_touching_the_edge_may_still_get_the_safety_gutter():
    image = _paragraph(font_size=28, size=(900, 200)).crop((30, 30, 700, 160))

    result = align_image(image)

    assert result.content is not None
    assert result.content.kind == "text"
    # Text is the only kind allowed to extend the canvas.
    assert max(result.added_left, result.added_top, result.added_right, result.added_bottom) > 0


@pytest.mark.parametrize("left_margin", [40, 8])
def test_graphic_is_cropped_strictly_inside_the_original_frame(left_margin):
    image = _bar_chart(left_margin)

    result = align_image(image)

    assert result.content is not None
    assert result.content.kind == "graphic"
    assert result.changed
    # Never extended: every output pixel is an original pixel.
    assert max(result.added_left, result.added_top, result.added_right, result.added_bottom) <= 0
    box = (
        -result.added_left,
        -result.added_top,
        image.width + result.added_right,
        image.height + result.added_bottom,
    )
    assert result.image.tobytes() == image.crop(box).tobytes()


def test_graphic_is_left_unchanged_in_pad_mode():
    image = _bar_chart()

    result = align_image(image, AlignmentConfig(mode="pad"))

    assert result.content is not None
    assert result.content.kind == "graphic"
    assert not result.changed
    assert result.image.tobytes() == image.tobytes()


@pytest.mark.parametrize(
    "factory",
    [_sky_and_mountains, _sea_horizon, _snow_and_skier, _night_and_moon],
    ids=["sky-mountains", "sea-horizon", "snow-skier", "night-moon"],
)
@pytest.mark.parametrize("mode", ["crop", "pad"])
def test_screenshot_inside_a_photo_is_left_unchanged(factory, mode):
    image = factory()

    result = align_image(image, AlignmentConfig(mode=mode))

    assert result.content is not None
    assert result.content.kind == "picture"
    assert not result.changed
    assert result.image.tobytes() == image.tobytes()


def test_without_the_gate_a_photo_gets_damaged():
    # Documents why the gate exists: the geometric engine alone treats the sea
    # as background and crops it away.
    image = _sea_horizon()

    result = align_image(image, AlignmentConfig(content_gate=False))

    assert result.changed
    assert result.content is None

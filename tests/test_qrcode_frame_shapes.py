"""Tests for the outline that shapes the finished QR image."""

import math

import pytest
from PIL import Image

from qrcode_manager.frame_shapes import (
    DEFAULT_FRAME_SHAPE,
    FRAME_SHAPES,
    QUIET_MODULES,
    apply_frame,
    decoration_matrix,
    frame_shape_choices,
    frame_width,
    inscribed_ratio,
    is_framed,
    regular_polygon,
    star_polygon,
)
from qrcode_manager.qr_image import build_qr_image, build_qr_png

WHITE = (255, 255, 255)
OUTLINED = [key for key in FRAME_SHAPES if FRAME_SHAPES[key][1] is not None]


def _square(side, color=(0, 0, 0)):
    """A stand-in for a rendered QR code."""
    return Image.new("RGB", (side, side), color)


def _corner_is_transparent(image):
    return image.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("sides", [3, 4, 6])
def test_regular_polygon_corners_are_equidistant_from_the_center(sides):
    for corner in regular_polygon(sides):
        assert math.dist(corner, (0.5, 0.5)) == pytest.approx(0.5)


def test_regular_polygon_starts_at_the_top():
    """Starting at the top is what makes four sides a diamond."""
    assert regular_polygon(4)[0] == pytest.approx((0.5, 0.0))


def test_star_polygon_alternates_outer_and_inner_radius():
    corners = star_polygon(points=5, inner_ratio=0.5)
    assert len(corners) == 10
    assert [math.dist(c, (0.5, 0.5)) for c in corners[0::2]] == pytest.approx([0.5] * 5)
    assert [math.dist(c, (0.5, 0.5)) for c in corners[1::2]] == pytest.approx(
        [0.25] * 5
    )


def test_none_is_the_default_and_leaves_the_image_alone():
    """Codes saved before outlines existed must render unchanged."""
    original = _square(100)
    assert apply_frame(original, DEFAULT_FRAME_SHAPE, WHITE) is original


def test_unknown_shape_falls_back_to_leaving_the_image_alone():
    original = _square(100)
    assert apply_frame(original, "trapezoid", WHITE) is original


def test_circle_ratio_matches_the_geometry():
    """A square inscribed in a circle has side diameter / sqrt(2)."""
    assert inscribed_ratio("circle") == pytest.approx(1 / math.sqrt(2), abs=0.01)


def test_diamond_ratio_matches_the_geometry():
    """The largest centered square in a diamond is half its width."""
    assert inscribed_ratio("diamond") == pytest.approx(0.5, abs=0.01)


@pytest.mark.parametrize("frame_shape", OUTLINED)
def test_every_outline_leaves_room_for_the_code(frame_shape):
    ratio = inscribed_ratio(frame_shape)
    assert 0 < ratio <= 1


def test_a_star_leaves_less_room_than_a_circle():
    assert inscribed_ratio("star") < inscribed_ratio("circle")


@pytest.mark.parametrize("frame_shape", OUTLINED)
def test_outline_keeps_the_whole_code(frame_shape):
    """Nothing may be cropped off a QR code, so the canvas has to grow."""
    code = _square(200)
    framed = apply_frame(code, frame_shape, WHITE)
    assert framed.width >= code.width
    assert framed.width == framed.height


def test_is_framed():
    assert not is_framed("none")
    assert not is_framed("trapezoid")
    assert is_framed("circle")


@pytest.mark.parametrize("frame_shape", OUTLINED)
@pytest.mark.parametrize("code_width", [29, 30])
def test_frame_width_fits_the_code_and_keeps_it_centered(frame_shape, code_width):
    """Same parity as the code, so it sits exactly on the shape's grid."""
    width = frame_width(frame_shape, code_width)
    assert width * inscribed_ratio(frame_shape) >= code_width
    assert (width - code_width) % 2 == 0


def test_decoration_leaves_the_code_square_empty():
    matrix = decoration_matrix("circle", 41, 29, 10, seed="x")
    assert all(not matrix[row][col] for row in range(6, 35) for col in range(6, 35))
    assert any(any(row) for row in matrix)


def test_decoration_stays_inside_the_shape():
    """The corners of a circle's bounding square are outside the circle."""
    matrix = decoration_matrix("circle", 41, 29, 10, seed="x")
    assert not matrix[0][0]
    assert not matrix[40][40]


def test_decoration_is_repeatable_for_the_same_seed():
    """The preview must not flicker, and the saved image must match it."""
    assert decoration_matrix("star", 61, 29, 10, seed="a") == decoration_matrix(
        "star", 61, 29, 10, seed="a"
    )
    assert decoration_matrix("star", 61, 29, 10, seed="a") != decoration_matrix(
        "star", 61, 29, 10, seed="b"
    )


def test_apply_frame_uses_the_decoration_image():
    decoration = Image.new("RGB", (300, 300), (12, 34, 56))
    framed = apply_frame(_square(100), "circle", WHITE, decoration)
    assert framed.size == (300, 300)
    assert framed.getpixel((150, 20))[:3] == (12, 34, 56)


@pytest.mark.parametrize("frame_shape", OUTLINED)
def test_outline_is_transparent_outside_and_filled_inside(frame_shape):
    """The transparency is what makes the PNG read as that shape."""
    framed = apply_frame(_square(120), frame_shape, WHITE)
    assert framed.mode == "RGBA"
    assert _corner_is_transparent(framed)
    middle = framed.width // 2
    assert framed.getpixel((middle, middle))[3] == 255


def test_outline_is_filled_with_the_code_background_color():
    """The fill continues the quiet zone, so it has to be the back color."""
    framed = apply_frame(_square(120), "circle", (12, 34, 56))
    # Just inside the left edge of the circle, on the vertical midline.
    middle = framed.height // 2
    edge = framed.getpixel((framed.width // 12, middle))
    assert edge[:3] == (12, 34, 56)


@pytest.mark.parametrize("frame_shape", OUTLINED)
def test_the_code_lands_centered_and_intact(frame_shape):
    """A recognisable code pasted in must come back out byte-identical."""
    code = _square(160, color=(200, 30, 90))
    framed = apply_frame(code, frame_shape, WHITE)
    offset = (framed.width - code.width) // 2
    inset = framed.crop((offset, offset, offset + code.width, offset + code.width))
    assert inset.convert("RGB").tobytes() == code.tobytes()


def test_choices_cover_every_registered_shape():
    assert [key for key, _ in frame_shape_choices()] == list(FRAME_SHAPES)


@pytest.mark.parametrize("frame_shape", sorted(FRAME_SHAPES))
def test_build_qr_image_applies_the_outline(frame_shape):
    plain = build_qr_image("https://example.com")
    shaped = build_qr_image("https://example.com", frame_shape=frame_shape)
    if FRAME_SHAPES[frame_shape][1] is None:
        assert shaped.size == plain.size
    else:
        assert _corner_is_transparent(shaped)


def test_framed_code_uses_a_thinner_quiet_zone():
    """The 4-module border shrinks to `QUIET_MODULES`, so the code fills
    more of the shape."""
    plain = build_qr_image("https://example.com")
    framed = build_qr_image("https://example.com", frame_shape="circle")
    modules = plain.width // 10 - 8
    assert framed.width == 10 * frame_width("circle", modules + 2 * QUIET_MODULES)


def test_framed_code_is_decorated_in_the_fill_color():
    """Outside the code square, the shape holds random fill-colored
    modules, not just plain background."""
    framed = build_qr_image(
        "https://example.com", fill_color="#ff0000", frame_shape="circle"
    ).convert("RGBA")
    band = framed.crop((framed.width // 2 - 30, 10, framed.width // 2 + 30, 40))
    assert (255, 0, 0, 255) in {color for _, color in band.getcolors()}


def test_framed_code_with_logo_and_neighbor_aware_drawer():
    logo = Image.new("RGBA", (50, 50), (0, 255, 0, 255))
    framed = build_qr_image(
        "https://example.com", module_style="rounded", logo=logo, frame_shape="hexagon"
    ).convert("RGB")
    assert framed.getpixel((framed.width // 2, framed.height // 2)) == (0, 255, 0)


def test_build_qr_png_keeps_the_transparency():
    """Saving must not flatten the outline onto an opaque square."""
    buffer = build_qr_png("https://example.com", frame_shape="star")
    assert buffer.read(8) == b"\x89PNG\r\n\x1a\n"
    buffer.seek(0)
    assert _corner_is_transparent(Image.open(buffer).convert("RGBA"))

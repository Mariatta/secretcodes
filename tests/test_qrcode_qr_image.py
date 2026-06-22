"""Tests for the storage-agnostic QR image builder."""

from unittest.mock import patch

import pytest
import qrcode as qrcode_lib
from PIL import Image

from qrcode_manager.qr_image import (
    COLOR_MASKS,
    MODULE_DRAWERS,
    build_qr_image,
    build_qr_png,
    color_mask_choices,
    module_style_choices,
)


def test_default_colors_black_on_white():
    img = build_qr_image("https://example.com").get_image().convert("RGB")
    colors = {color for _, color in img.getcolors()}
    assert colors == {(0, 0, 0), (255, 255, 255)}


def test_custom_colors_applied():
    img = (
        build_qr_image("https://example.com", "#112233", "#ffeedd")
        .get_image()
        .convert("RGB")
    )
    colors = {color for _, color in img.getcolors()}
    assert (17, 34, 51) in colors
    assert (255, 238, 221) in colors


def test_logo_is_embedded_in_center():
    logo = Image.new("RGBA", (50, 50), (255, 0, 0, 255))
    img = build_qr_image("https://example.com", logo=logo).get_image().convert("RGB")
    center = img.getpixel((img.width // 2, img.height // 2))
    assert center == (255, 0, 0)


def test_logo_bumps_error_correction():
    logo = Image.new("RGBA", (10, 10), (0, 255, 0, 255))
    with patch(
        "qrcode_manager.qr_image.qrcode.QRCode", wraps=qrcode_lib.QRCode
    ) as spy:
        build_qr_image("https://example.com")
        build_qr_image("https://example.com", logo=logo)
    plain_call, logo_call = spy.call_args_list
    assert plain_call.kwargs["error_correction"] == qrcode_lib.constants.ERROR_CORRECT_M
    assert logo_call.kwargs["error_correction"] == qrcode_lib.constants.ERROR_CORRECT_H


def test_build_qr_png_returns_rewound_png_buffer():
    buffer = build_qr_png("https://example.com")
    assert buffer.tell() == 0
    assert buffer.read(8) == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("module_style", sorted(MODULE_DRAWERS))
@pytest.mark.parametrize("color_mask_style", sorted(COLOR_MASKS))
def test_every_style_combination_builds_png(module_style, color_mask_style):
    """Every drawer x mask combination must produce a valid PNG."""
    buffer = build_qr_png(
        "https://example.com",
        fill_color="#1133aa",
        back_color="#ffffff",
        gradient_color="#aa3311",
        module_style=module_style,
        color_mask_style=color_mask_style,
    )
    assert buffer.read(8) == b"\x89PNG\r\n\x1a\n"


def test_unknown_module_style_falls_back_to_square():
    """An unknown/empty style key must not raise — it uses the default."""
    img = build_qr_image(
        "https://example.com", module_style="bogus", color_mask_style=""
    )
    assert img.get_image().convert("RGB").getpixel((0, 0))


def test_gradient_mask_blends_fill_into_gradient_color():
    img = (
        build_qr_image(
            "https://example.com",
            fill_color="#ff0000",
            back_color="#ffffff",
            gradient_color="#0000ff",
            color_mask_style="horizontal_gradient",
        )
        .get_image()
        .convert("RGB")
    )
    colors = {color for _, color in img.getcolors(maxcolors=100000)}
    reds = [c for c in colors if c[0] > 150 and c[2] < 80]
    blues = [c for c in colors if c[2] > 150 and c[0] < 80]
    assert reds and blues


def test_solid_mask_ignores_gradient_color():
    """With the solid style, the gradient color must not appear."""
    img = (
        build_qr_image(
            "https://example.com",
            fill_color="#ff0000",
            back_color="#ffffff",
            gradient_color="#0000ff",
            color_mask_style="solid",
        )
        .get_image()
        .convert("RGB")
    )
    colors = {color for _, color in img.getcolors()}
    assert (0, 0, 255) not in colors


def test_choices_cover_every_registered_style():
    assert [k for k, _ in module_style_choices()] == list(MODULE_DRAWERS)
    assert [k for k, _ in color_mask_choices()] == list(COLOR_MASKS)

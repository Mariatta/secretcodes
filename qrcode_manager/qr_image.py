"""Build QR code images, optionally styled with custom colors, module
shapes, color masks, and a logo.

This module is storage-agnostic: it only turns data into PIL images /
PNG bytes. Uploading the result lives in `s3_wrapper`, and the live
preview view serves these bytes straight from memory.

The `MODULE_DRAWERS` and `COLOR_MASKS` registries are the single source
of truth for the available styles: forms build their dropdown choices
from the keys here, and `build_qr_image` resolves a key back to the
qrcode library class. Adding a style is a one-line change here.
"""

import io

import qrcode
from PIL import ImageColor
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import (
    HorizontalGradiantColorMask,
    RadialGradiantColorMask,
    SolidFillColorMask,
    SquareGradiantColorMask,
    VerticalGradiantColorMask,
)
from qrcode.image.styles.moduledrawers.pil import (
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    HorizontalBarsDrawer,
    RoundedModuleDrawer,
    SquareModuleDrawer,
    VerticalBarsDrawer,
)

DEFAULT_FILL_COLOR = "#000000"
DEFAULT_BACK_COLOR = "#ffffff"
DEFAULT_GRADIENT_COLOR = "#0000ff"

DEFAULT_MODULE_STYLE = "square"
DEFAULT_COLOR_MASK_STYLE = "solid"

# key -> (human label, drawer class). The default `square` reproduces the
# plain qrcode look, so existing rows render identically.
MODULE_DRAWERS = {
    "square": ("Square", SquareModuleDrawer),
    "gapped": ("Gapped square", GappedSquareModuleDrawer),
    "circle": ("Circle", CircleModuleDrawer),
    "rounded": ("Rounded", RoundedModuleDrawer),
    "horizontal_bars": ("Horizontal bars", HorizontalBarsDrawer),
    "vertical_bars": ("Vertical bars", VerticalBarsDrawer),
}


def _solid_mask(fill, back, gradient):
    return SolidFillColorMask(back_color=back, front_color=fill)


def _radial_mask(fill, back, gradient):
    return RadialGradiantColorMask(
        back_color=back, center_color=fill, edge_color=gradient
    )


def _square_mask(fill, back, gradient):
    return SquareGradiantColorMask(
        back_color=back, center_color=fill, edge_color=gradient
    )


def _horizontal_mask(fill, back, gradient):
    return HorizontalGradiantColorMask(
        back_color=back, left_color=fill, right_color=gradient
    )


def _vertical_mask(fill, back, gradient):
    return VerticalGradiantColorMask(
        back_color=back, top_color=fill, bottom_color=gradient
    )


# key -> (human label, builder taking RGB tuples (fill, back, gradient)).
# The gradient masks blend `fill_color` into `gradient_color`; `solid`
# ignores the gradient color entirely.
COLOR_MASKS = {
    "solid": ("Solid", _solid_mask),
    "radial_gradient": ("Radial gradient", _radial_mask),
    "square_gradient": ("Square gradient", _square_mask),
    "horizontal_gradient": ("Horizontal gradient", _horizontal_mask),
    "vertical_gradient": ("Vertical gradient", _vertical_mask),
}

# Masks that actually use the second color, so the UI can show/hide the
# gradient color picker.
GRADIENT_COLOR_MASKS = frozenset(COLOR_MASKS) - {"solid"}


def module_style_choices():
    """`(key, label)` pairs for a form ChoiceField."""
    return [(key, label) for key, (label, _) in MODULE_DRAWERS.items()]


def color_mask_choices():
    """`(key, label)` pairs for a form ChoiceField."""
    return [(key, label) for key, (label, _) in COLOR_MASKS.items()]


def build_qr_image(
    data,
    fill_color=None,
    back_color=None,
    gradient_color=None,
    module_style=None,
    color_mask_style=None,
    logo=None,
):
    """Return a PIL image of the QR code for `data`.

    `fill_color`/`back_color`/`gradient_color` are CSS-style hex strings;
    `module_style`/`color_mask_style` are keys into `MODULE_DRAWERS` /
    `COLOR_MASKS` (unknown or empty keys fall back to the defaults).
    `logo` is an optional PIL image embedded in the center; with a logo
    we bump error correction to H so the code still scans with ~30% of it
    covered.
    """
    fill = ImageColor.getrgb(fill_color or DEFAULT_FILL_COLOR)
    back = ImageColor.getrgb(back_color or DEFAULT_BACK_COLOR)
    gradient = ImageColor.getrgb(gradient_color or DEFAULT_GRADIENT_COLOR)

    _, drawer_class = MODULE_DRAWERS.get(
        module_style, MODULE_DRAWERS[DEFAULT_MODULE_STYLE]
    )
    _, mask_builder = COLOR_MASKS.get(
        color_mask_style, COLOR_MASKS[DEFAULT_COLOR_MASK_STYLE]
    )

    error_correction = (
        qrcode.constants.ERROR_CORRECT_H if logo else qrcode.constants.ERROR_CORRECT_M
    )
    qr = qrcode.QRCode(error_correction=error_correction)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=drawer_class(),
        color_mask=mask_builder(fill, back, gradient),
        embedded_image=logo,
    )


def build_qr_png(
    data,
    fill_color=None,
    back_color=None,
    gradient_color=None,
    module_style=None,
    color_mask_style=None,
    logo=None,
):
    """Return the styled QR code as a PNG `io.BytesIO`, rewound."""
    buffer = io.BytesIO()
    img = build_qr_image(
        data,
        fill_color=fill_color,
        back_color=back_color,
        gradient_color=gradient_color,
        module_style=module_style,
        color_mask_style=color_mask_style,
        logo=logo,
    )
    img.save(buffer)
    buffer.seek(0)
    return buffer

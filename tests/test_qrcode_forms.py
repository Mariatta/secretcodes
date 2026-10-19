from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from qrcode_manager.forms import (
    LOGO_RASTER_WIDTH,
    RESERVED_SLUGS,
    QRCodePreviewForm,
    QRCodeStylePreviewForm,
    QRCodeWithSlugPreviewForm,
)

SVG_LOGO = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    b'<rect width="10" height="10" fill="red"/></svg>'
)


def test_preview_form_valid():
    form = QRCodePreviewForm(data={"url": "https://example.com", "description": "ok"})
    assert form.is_valid()


def test_preview_form_missing_description():
    form = QRCodePreviewForm(data={"url": "https://example.com"})
    assert not form.is_valid()
    assert "description" in form.errors


def test_slug_form_valid():
    form = QRCodeWithSlugPreviewForm(
        data={"url": "https://example.com", "description": "ok", "slug": "abc"}
    )
    assert form.is_valid()


def test_slug_form_rejects_spaces():
    form = QRCodeWithSlugPreviewForm(
        data={"url": "https://example.com", "description": "ok", "slug": "has space"}
    )
    assert not form.is_valid()
    assert "slug" in form.errors


@pytest.mark.parametrize("reserved", sorted(RESERVED_SLUGS))
def test_slug_form_rejects_reserved_word(reserved):
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": reserved,
        }
    )
    assert not form.is_valid()
    assert "slug" in form.errors
    assert "reserved" in str(form.errors["slug"]).lower()


def test_slug_form_rejects_reserved_word_case_insensitive():
    form = QRCodeWithSlugPreviewForm(
        data={"url": "https://example.com", "description": "ok", "slug": "Admin"}
    )
    assert not form.is_valid()
    assert "slug" in form.errors


def test_slug_form_valid_with_colors():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "fill_color": "#112233",
            "back_color": "#FFEEDD",
        }
    )
    assert form.is_valid()


@pytest.mark.parametrize("bad_color", ["112233", "#12", "red", "#11223", "#gggggg"])
def test_slug_form_rejects_malformed_color(bad_color):
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "fill_color": bad_color,
        }
    )
    assert not form.is_valid()
    assert "fill_color" in form.errors


def test_slug_form_colors_optional():
    """Posts without styling stay valid and fall back to model defaults."""
    form = QRCodeWithSlugPreviewForm(
        data={"url": "https://example.com", "description": "ok", "slug": "abc"}
    )
    assert form.is_valid()


def test_style_preview_form_requires_url():
    form = QRCodeStylePreviewForm(data={"slug": "abc"})
    assert not form.is_valid()
    assert "url" in form.errors


def test_style_preview_form_slug_not_validated():
    """A half-typed or reserved slug must not blank the live preview."""
    form = QRCodeStylePreviewForm(data={"url": "https://example.com", "slug": "admin"})
    assert form.is_valid()


def test_slug_form_valid_with_styles():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "module_style": "rounded",
            "color_mask_style": "radial_gradient",
            "fill_color": "#112233",
            "gradient_color": "#445566",
        }
    )
    assert form.is_valid()


def test_slug_form_rejects_unknown_module_style():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "module_style": "triangle",
        }
    )
    assert not form.is_valid()
    assert "module_style" in form.errors


def test_slug_form_rejects_unknown_color_mask():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "color_mask_style": "plaid",
        }
    )
    assert not form.is_valid()
    assert "color_mask_style" in form.errors


def test_slug_form_accepts_frame_shape():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "frame_shape": "hexagon",
        }
    )
    assert form.is_valid()
    assert form.cleaned_data["frame_shape"] == "hexagon"


def test_slug_form_rejects_unknown_frame_shape():
    form = QRCodeWithSlugPreviewForm(
        data={
            "url": "https://example.com",
            "description": "ok",
            "slug": "abc",
            "frame_shape": "trapezoid",
        }
    )
    assert not form.is_valid()
    assert "frame_shape" in form.errors


def test_style_preview_form_accepts_styles():
    form = QRCodeStylePreviewForm(
        data={
            "url": "https://example.com",
            "module_style": "horizontal_bars",
            "color_mask_style": "vertical_gradient",
        }
    )
    assert form.is_valid()


def test_color_field_reads_paired_text_input():
    """The browser posts swatch (..._0) + hex text (..._1); the text box
    wins."""
    form = QRCodeStylePreviewForm(
        data={
            "url": "https://example.com",
            "fill_color_0": "#000000",
            "fill_color_1": "#a1b2c3",
        }
    )
    assert form.is_valid()
    assert form.cleaned_data["fill_color"] == "#a1b2c3"


def test_color_field_falls_back_to_swatch_when_text_blank():
    form = QRCodeStylePreviewForm(
        data={
            "url": "https://example.com",
            "fill_color_0": "#a1b2c3",
            "fill_color_1": "",
        }
    )
    assert form.is_valid()
    assert form.cleaned_data["fill_color"] == "#a1b2c3"


def test_color_field_rejects_malformed_typed_hex():
    form = QRCodeStylePreviewForm(
        data={
            "url": "https://example.com",
            "fill_color_0": "#000000",
            "fill_color_1": "deadbeef",
        }
    )
    assert not form.is_valid()
    assert "fill_color" in form.errors


def _preview_with_logo(upload):
    return QRCodeStylePreviewForm(
        data={"url": "https://example.com"}, files={"logo": upload}
    )


def test_svg_logo_is_rasterized_to_png():
    form = _preview_with_logo(
        SimpleUploadedFile("brand.svg", SVG_LOGO, content_type="image/svg+xml")
    )
    assert form.is_valid(), form.errors
    logo = form.cleaned_data["logo"]
    assert logo.name == "brand.png"
    assert logo.image.format == "PNG"
    assert logo.image.width == LOGO_RASTER_WIDTH


def test_svg_logo_is_recognised_by_content_type_alone():
    form = _preview_with_logo(
        SimpleUploadedFile("brand", SVG_LOGO, content_type="image/svg+xml")
    )
    assert form.is_valid(), form.errors


def test_malformed_svg_logo_is_rejected():
    form = _preview_with_logo(
        SimpleUploadedFile("brand.svg", b"<svg", content_type="image/svg+xml")
    )
    assert not form.is_valid()
    assert form.errors.as_data()["logo"][0].code == "invalid_image"


def test_svg_logo_cannot_make_the_server_fetch_anything():
    """An uploaded SVG pointing at a URL or a local file must not be
    followed: cairosvg's safe mode swaps it for an empty image."""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" '
        b'xmlns:xlink="http://www.w3.org/1999/xlink" width="10" height="10">'
        b'<image xlink:href="http://169.254.169.254/latest" width="5" height="5"/>'
        b'<image xlink:href="file:///etc/passwd" width="5" height="5"/></svg>'
    )
    # cairosvg's parser holds its own reference to `fetch`, so both have to
    # be patched to see every fetch it might make.
    with (
        mock.patch("cairosvg.url.fetch", return_value=b"") as url_fetch,
        mock.patch("cairosvg.parser.fetch", return_value=b"") as parser_fetch,
    ):
        form = _preview_with_logo(
            SimpleUploadedFile("brand.svg", svg, content_type="image/svg+xml")
        )
        assert form.is_valid(), form.errors
    url_fetch.assert_not_called()
    parser_fetch.assert_not_called()

from pathlib import Path

import cairosvg
from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

from .frame_shapes import DEFAULT_FRAME_SHAPE, frame_shape_choices
from .qr_image import (
    DEFAULT_BACK_COLOR,
    DEFAULT_COLOR_MASK_STYLE,
    DEFAULT_FILL_COLOR,
    DEFAULT_GRADIENT_COLOR,
    DEFAULT_MODULE_STYLE,
    color_mask_choices,
    module_style_choices,
)

# Top-level URL prefixes that must not be shadowed by a QR slug. Kept explicit
# so that adding a new sibling app requires a conscious update here.
RESERVED_SLUGS = frozenset(
    {
        "accounts",
        "admin",
        "agents",
        "availability",
        "mcp",
        "media",
        "privacy",
        "qr",
        "qrcode_generator",
        "qrcode_preview",
        "qrcode_slug_generator",
        "static",
        "terms",
    }
)


def validate_slug_not_reserved(value):
    if value.lower() in RESERVED_SLUGS:
        raise ValidationError(
            _("'%(value)s' is a reserved URL — pick a different slug."),
            code="reserved_slug",
            params={"value": value},
        )


hex_color_validator = RegexValidator(
    r"^#[0-9a-fA-F]{6}$",
    _("Enter a color in #rrggbb format."),
    code="invalid_color",
)


class ColorPickerInput(forms.MultiWidget):
    """A native color swatch paired with a text box, so a hex code can be
    typed or pasted instead of only clicked. The two inputs are kept in
    sync client-side; the submitted value collapses back to a single hex
    string (see `value_from_datadict`), so the field stays a plain
    CharField validated by `hex_color_validator`."""

    def __init__(self, attrs=None):
        widgets = (
            forms.TextInput(
                attrs={
                    "type": "color",
                    "class": "form-control form-control-color sc-color-swatch",
                    "tabindex": "-1",
                    "aria-hidden": "true",
                }
            ),
            forms.TextInput(
                attrs={
                    "type": "text",
                    "class": "form-control sc-color-hex",
                    "maxlength": "7",
                    "placeholder": "#rrggbb",
                    "spellcheck": "false",
                    "autocomplete": "off",
                }
            ),
        )
        super().__init__(widgets, attrs)

    def decompress(self, value):
        """Feed the same hex string to both the swatch and the text box."""
        return [value, value]

    def value_from_datadict(self, data, files, name):
        swatch, text = super().value_from_datadict(data, files, name)
        # The text box is canonical (it's what the user typed); fall back
        # to the swatch if it's somehow empty (e.g. JS disabled), then to a
        # bare `<name>` key so non-JS / programmatic callers can still post
        # a single hex value.
        value = text or swatch or data.get(name, "")
        return (value or "").strip()


def _color_field(label, initial):
    """A hex color picker field. Optional so that posts without styling
    (e.g. API-ish callers and pre-customization bookmarks) stay valid;
    consumers fall back to the model defaults when empty."""
    return forms.CharField(
        label=label,
        initial=initial,
        required=False,
        validators=[hex_color_validator],
        widget=ColorPickerInput,
    )


def _style_field(label, choices, initial):
    """A dropdown of named styles (module shape / color mask). Optional so
    that styling-free posts stay valid and fall back to model defaults;
    the choice list comes from the `qr_image` registries."""
    return forms.ChoiceField(
        label=label,
        choices=choices,
        initial=initial,
        required=False,
    )


class QRCodePreviewForm(forms.Form):

    url = forms.URLField(label="URL", assume_scheme="https")
    description = forms.CharField(label="Description", max_length=30, required=True)


# Width, in pixels, an SVG logo is rasterized to. The logo covers about a
# quarter of a code a few hundred pixels wide, so this leaves headroom
# without letting a tiny SVG ask for a huge bitmap.
LOGO_RASTER_WIDTH = 512


def _is_svg(upload):
    return (
        upload.name.lower().endswith(".svg")
        or getattr(upload, "content_type", "") == "image/svg+xml"
    )


class LogoField(forms.ImageField):
    """An image upload that also takes SVG logos.

    Pillow can't open SVG, so an SVG upload is rasterized to PNG first and
    then validated like any other image. cairosvg's default safe mode is
    kept on purpose: no XML entities and no external files or URLs, so an
    uploaded SVG can't make the server read or fetch anything.
    """

    def to_python(self, data):
        if data and _is_svg(data):
            data = self._rasterize(data)
        return super().to_python(data)

    def _rasterize(self, upload):
        try:
            png = cairosvg.svg2png(
                bytestring=upload.read(), output_width=LOGO_RASTER_WIDTH
            )
        except Exception as exc:
            raise ValidationError(
                self.error_messages["invalid_image"], code="invalid_image"
            ) from exc
        return SimpleUploadedFile(Path(upload.name).stem + ".png", png, "image/png")


class QRCodeWithSlugPreviewForm(forms.Form):

    url = forms.URLField(label="URL", assume_scheme="https")
    description = forms.CharField(label="Description", max_length=30, required=True)
    slug = forms.CharField(
        label="Slug",
        max_length=30,
        required=True,
        validators=[
            RegexValidator(
                r"^[^\s]+$",  # Regex: matches one or more characters that are NOT whitespace
                _("This field cannot contain spaces."),
                code="no_spaces_allowed",
            ),
            validate_slug_not_reserved,
        ],
    )
    frame_shape = _style_field(
        "Image shape", frame_shape_choices(), DEFAULT_FRAME_SHAPE
    )
    module_style = _style_field(
        "Module shape", module_style_choices(), DEFAULT_MODULE_STYLE
    )
    color_mask_style = _style_field(
        "Color style", color_mask_choices(), DEFAULT_COLOR_MASK_STYLE
    )
    fill_color = _color_field("Fill color", DEFAULT_FILL_COLOR)
    gradient_color = _color_field("Gradient color", DEFAULT_GRADIENT_COLOR)
    back_color = _color_field("Background color", DEFAULT_BACK_COLOR)
    logo = LogoField(label="Logo (optional)", required=False)


class QRCodeStylePreviewForm(forms.Form):
    """Inputs for the throwaway live-preview image.

    The slug is unvalidated here on purpose: a half-typed slug only
    changes the encoded text of a preview that is never persisted, so
    rejecting it would just blank the preview while typing.
    """

    url = forms.URLField(label="URL", assume_scheme="https")
    slug = forms.CharField(label="Slug", max_length=30, required=False)
    frame_shape = _style_field(
        "Image shape", frame_shape_choices(), DEFAULT_FRAME_SHAPE
    )
    module_style = _style_field(
        "Module shape", module_style_choices(), DEFAULT_MODULE_STYLE
    )
    color_mask_style = _style_field(
        "Color style", color_mask_choices(), DEFAULT_COLOR_MASK_STYLE
    )
    fill_color = _color_field("Fill color", DEFAULT_FILL_COLOR)
    gradient_color = _color_field("Gradient color", DEFAULT_GRADIENT_COLOR)
    back_color = _color_field("Background color", DEFAULT_BACK_COLOR)
    logo = LogoField(label="Logo", required=False)

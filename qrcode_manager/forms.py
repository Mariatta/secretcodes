from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

# Top-level URL prefixes that must not be shadowed by a QR slug. Kept explicit
# so that adding a new sibling app requires a conscious update here.
RESERVED_SLUGS = frozenset(
    {
        "accounts",
        "admin",
        "availability",
        "media",
        "qr",
        "qrcode_generator",
        "qrcode_slug_generator",
        "static",
    }
)


def validate_slug_not_reserved(value):
    if value.lower() in RESERVED_SLUGS:
        raise ValidationError(
            _("'%(value)s' is a reserved URL — pick a different slug."),
            code="reserved_slug",
            params={"value": value},
        )


class QRCodePreviewForm(forms.Form):

    url = forms.URLField(label="URL")
    description = forms.CharField(label="Description", max_length=30, required=True)


class QRCodeWithSlugPreviewForm(forms.Form):

    url = forms.URLField(label="URL")
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

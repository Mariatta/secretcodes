from django import forms
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _


class QRCodePreviewForm(forms.Form):

    url = forms.URLField(label="URL")
    description = forms.CharField(label="Description", max_length=30, required=False)


class QRCodeWithSlugPreviewForm(forms.Form):

    url = forms.URLField(label="URL")
    description = forms.CharField(label="Description", max_length=30, required=False)
    slug = forms.CharField(
        label="Slug",
        max_length=30,
        required=True,
        validators=[
            RegexValidator(
                r"^[^\s]+$",  # Regex: matches one or more characters that are NOT whitespace
                _("This field cannot contain spaces."),
                code="no_spaces_allowed",
            )
        ],
    )

"""Tests for the ``{% icon %}`` template tag.

The tag replaces the runtime Font Awesome Kit script with inline SVG so
no third-party request fires when the respondent page (or any other
page) loads. These tests cover every branch in ``icons.py`` plus a
smoke test against the full bundled icon set.
"""

import pytest
from django.template import Context, Template, TemplateSyntaxError

from secretcodes.templatetags.icons import ICONS


def _render(template_source):
    return Template("{% load icons %}" + template_source).render(Context())


def test_icon_default_is_decorative_aria_hidden():
    """Bare ``{% icon "lock" %}`` renders as a decorative svg."""
    out = _render('{% icon "lock" %}')
    assert out.startswith("<svg")
    assert 'aria-hidden="true"' in out
    assert 'class="sc-icon"' in out
    assert 'role="img"' not in out
    assert "fa-" not in out


def test_icon_accepts_extra_class():
    """``class="me-1"`` is appended after the baseline ``sc-icon``."""
    out = _render('{% icon "lock" class="me-1" %}')
    assert 'class="sc-icon me-1"' in out


def test_icon_with_label_becomes_role_image():
    """A ``label`` flips the icon from decorative to a labelled image."""
    out = _render('{% icon "pen-to-square" label="Edit survey" %}')
    assert 'role="img"' in out
    assert 'aria-label="Edit survey"' in out
    assert 'aria-hidden="true"' not in out


def test_icon_unknown_name_raises():
    """A typo'd icon name fails loudly at render time."""
    with pytest.raises(TemplateSyntaxError, match="Unknown icon"):
        _render('{% icon "nope" %}')


@pytest.mark.parametrize("name", sorted(ICONS))
def test_every_bundled_icon_renders_without_error(name):
    """Smoke-test every entry in ``ICONS`` so a malformed path/viewBox
    is caught at test-time rather than discovered in the browser.
    """
    out = _render('{% icon "' + name + '" %}')
    viewbox, path = ICONS[name]
    assert f'viewBox="{viewbox}"' in out
    assert f'd="{path}"' in out

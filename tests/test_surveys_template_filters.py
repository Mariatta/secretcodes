"""Tests for the ``safe_markdown`` template filter.

Covers the rendering paths the respond.html integration tests don't
naturally exercise — empty input, link rendering, and protocol filtering.
"""

import pytest

from surveys.templatetags.survey_extras import safe_markdown


def test_safe_markdown_empty_returns_empty_string():
    assert safe_markdown("") == ""
    assert safe_markdown(None) == ""


def test_safe_markdown_renders_inline_formatting():
    out = safe_markdown("This is **bold** and *italic*.")
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out


def test_safe_markdown_preserves_safe_links():
    out = safe_markdown("[Click](https://example.com)")
    assert '<a href="https://example.com">Click</a>' in out


def test_safe_markdown_strips_javascript_links():
    """``javascript:`` href would let an owner XSS respondents — strip it."""
    out = safe_markdown("[Bad](javascript:alert(1))")
    assert "javascript:" not in out


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>",
        '<img src=x onerror="alert(1)">',
        "<iframe src='evil'></iframe>",
    ],
)
def test_safe_markdown_strips_unsafe_html(raw):
    out = safe_markdown(raw)
    assert "<script" not in out
    assert "<iframe" not in out
    assert "onerror" not in out

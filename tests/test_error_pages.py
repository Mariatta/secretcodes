"""Render checks for the branded 4xx/5xx error templates.

Django's default error-page mechanism only kicks in when DEBUG=False,
so each test temporarily disables debug to exercise the real handler.
"""

import pytest
from django.test import override_settings


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
@pytest.mark.django_db
def test_404_page_uses_branded_template(client):
    response = client.get("/this-path-does-not-exist-anywhere/")
    assert response.status_code == 404
    assert b"Lost" in response.content
    assert b"404" in response.content


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
@pytest.mark.django_db
def test_403_template_renders():
    """Render 403.html directly via the template engine."""
    from django.template.loader import render_to_string

    body = render_to_string("403.html")
    assert "Restricted" in body
    assert "403" in body


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
@pytest.mark.django_db
def test_500_template_renders():
    from django.template.loader import render_to_string

    body = render_to_string("500.html")
    assert "Static" in body
    assert "500" in body


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
@pytest.mark.django_db
def test_400_template_renders():
    from django.template.loader import render_to_string

    body = render_to_string("400.html")
    assert "Bad" in body
    assert "400" in body

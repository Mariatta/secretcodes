from qrcode_manager.forms import QRCodePreviewForm, QRCodeWithSlugPreviewForm


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

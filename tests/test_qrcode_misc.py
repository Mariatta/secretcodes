from django.apps import apps
from django.contrib import admin

from qrcode_manager import urls as qrcode_urls
from qrcode_manager.apps import QrcodeManagerConfig
from qrcode_manager.models import QRCode


def test_app_config_name():
    assert QrcodeManagerConfig.name == "qrcode_manager"
    assert apps.get_app_config("qrcode_manager").name == "qrcode_manager"


def test_admin_registered():
    assert admin.site.is_registered(QRCode)


def test_urls_module_has_app_name():
    assert qrcode_urls.app_name == "qrcode_manager"
    assert isinstance(qrcode_urls.urlpatterns, list)

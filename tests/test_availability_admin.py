from django.apps import apps
from django.contrib import admin

from availability.apps import AvailabilityConfig
from availability.models import AvailabilityProfile, GoogleAccount, TrackedCalendar


def test_app_config_name():
    assert AvailabilityConfig.name == "availability"
    assert apps.get_app_config("availability").name == "availability"


def test_all_models_registered():
    assert admin.site.is_registered(GoogleAccount)
    assert admin.site.is_registered(TrackedCalendar)
    assert admin.site.is_registered(AvailabilityProfile)

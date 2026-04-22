from django.contrib import admin

from .models import AvailabilityProfile, GoogleAccount, TrackedCalendar

admin.site.register(GoogleAccount)
admin.site.register(TrackedCalendar)
admin.site.register(AvailabilityProfile)

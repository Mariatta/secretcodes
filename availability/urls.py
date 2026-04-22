from django.urls import path

from . import views

app_name = "availability"

urlpatterns = [
    path("", views.week_grid, name="week_grid"),
    path("slots.json", views.slots_json, name="slots_json"),
    path("check/", views.check, name="check"),
    path("admin/", views.admin_page, name="admin"),
    path("oauth/start/", views.oauth_start, name="oauth_start"),
    path("oauth/callback/", views.oauth_callback, name="oauth_callback"),
]

from django.urls import path

from . import views

app_name = "availability"

urlpatterns = [
    path("", views.week_grid, name="week_grid"),
    path("slots.json", views.slots_json, name="slots_json"),
    path("check/", views.check, name="check"),
]

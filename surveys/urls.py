from django.urls import path

from . import views

app_name = "surveys"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new/", views.create, name="new"),
    path("import/", views.import_view, name="import"),
    path("<slug:slug>/edit/", views.edit, name="edit"),
    path("<slug:slug>/invite/", views.invite_create, name="invite_create"),
    path("<slug:slug>/team/", views.team, name="team"),
    path("<slug:slug>/delete/", views.delete_survey, name="delete"),
    path("<slug:slug>/results/", views.results, name="results"),
    path("<slug:slug>/export.csv", views.export_csv, name="export_csv"),
    path(
        "<slug:slug>/action-items.md",
        views.export_action_items,
        name="export_action_items",
    ),
    path("<slug:slug>/triage/", views.triage, name="triage"),
    path("<slug:slug>/actions/", views.actions, name="actions"),
    path(
        "<slug:slug>/themes/<int:theme_id>/resolve/",
        views.theme_resolve,
        name="theme_resolve",
    ),
    path(
        "<slug:slug>/themes/<int:theme_id>/",
        views.theme_detail,
        name="theme_detail",
    ),
    path(
        "<slug:slug>/themes/<int:theme_id>/star/<int:response_id>/",
        views.theme_star,
        name="theme_star",
    ),
    path(
        "<slug:slug>/themes/<int:theme_id>/untag/<int:response_id>/",
        views.theme_untag,
        name="theme_untag",
    ),
    path(
        "<slug:slug>/themes/<int:theme_id>/merge/",
        views.theme_merge,
        name="theme_merge",
    ),
    path("<slug:slug>/done/", views.done, name="done"),
    path("i/<str:key>/", views.accept_invite, name="accept_invite"),
    path("<slug:slug>/", views.respond, name="respond"),
]

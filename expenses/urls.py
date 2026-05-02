from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("events/<int:event_id>/", views.event_overview, name="event_overview"),
    path("events/<int:event_id>/ledger/", views.event_ledger, name="event_ledger"),
    path(
        "events/<int:event_id>/expenses/new/",
        views.expense_create,
        name="expense_create",
    ),
    path(
        "events/<int:event_id>/expenses/<int:expense_id>/edit/",
        views.expense_edit,
        name="expense_edit",
    ),
    path(
        "events/<int:event_id>/expenses/<int:expense_id>/delete/",
        views.expense_delete,
        name="expense_delete",
    ),
    path(
        "events/<int:event_id>/expenses/<int:expense_id>/receipt/",
        views.receipt_download,
        name="receipt_download",
    ),
    path(
        "events/<int:event_id>/settle/<int:debtor_id>/<int:creditor_id>/",
        views.settle_up,
        name="settle_up",
    ),
    path(
        "events/<int:event_id>/export.csv",
        views.event_export_csv,
        name="event_export_csv",
    ),
    path(
        "events/<int:event_id>/invite/",
        views.invite_create,
        name="invite_create",
    ),
    path("accept/<str:key>/", views.accept_invite, name="accept_invite"),
]
